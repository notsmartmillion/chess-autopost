"""Build a narrated chess video end to end.

    python services/orchestrator/build_video.py --pgn outputs/pgns/daily/game.pgn

Four passes:

1. **facts**    Stockfish walks the game once and emits a rich fact sheet
                (evals, best lines, move quality, pins, hanging pieces, long
                diagonals, pawn structure).
2. **director** Facts become a *beat script*: narration text plus the board
                directives that belong with it. Variations are branch beats, so
                showing "what was better" and returning to the game is trivial.
3. **voice**    Qwen3-TTS on your GPU, ElevenLabs, or local SAPI synthesizes
                each beat and returns word-level timings, so a piece starts
                moving exactly when its square is spoken.
4. **render**   Remotion renders the beats; the composition length is derived
                from the measured audio.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
AUDIO_DIR = OUT / "audio"
PUB = ROOT / "apps" / "renderer" / "public"
PUB_AUDIO = PUB / "audio"

sys.path.insert(0, str(ROOT / "services" / "orchestrator"))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FPS = 30

# Padding after each spoken line so beats do not butt up against each other.
BEAT_TAIL_MS = 260
MIN_BEAT_MS = 900
# Keep the piece animation from starting so late it cannot finish in the beat.
MOVE_ANIM_MS = 420
# An attack line is only worth drawing if the viewer has time to follow it.
# On a quick move the narration has already moved on before the eye reaches the
# far end, so the arrow reads as a flicker rather than as a point being made.
MIN_ARROW_DWELL_MS = 1500
# Backends that produce the channel's actual voice. Anything else is a
# fallback: usable to prove the pipeline runs, never usable on the channel.
VOICE_BACKENDS = {"ttsapi", "qwen", "elevenlabs"}


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def ensure_dirs() -> None:
    for path in (OUT, AUDIO_DIR, PUB, PUB_AUDIO):
        path.mkdir(parents=True, exist_ok=True)


def _clear_dir(path: Path, pattern: str = "*") -> None:
    if not path.exists():
        return
    for item in path.glob(pattern):
        if item.is_file():
            try:
                item.unlink()
            except OSError:
                pass


# "the knight on d3", "her rook back on f1" — a piece named on a square.
_MENTION_RE = re.compile(
    r"\b(king|queen|rook|bishop|knight|pawn)s?\s+"
    r"(?:(?:sitting|standing|back|still|over|waiting|stuck)\s+)?"
    r"(?:on|at)\s+([a-h][1-8])\b",
    re.IGNORECASE,
)

_PIECE_BY_NAME = {
    "king": 6, "queen": 5, "rook": 4, "bishop": 3, "knight": 2, "pawn": 1,
}


def _time_of_token(words: List[Dict[str, Any]], token: str, approx_idx: int) -> Optional[float]:
    """Spoken time of the token occurrence nearest to a position in the text."""
    best = None
    best_dist = None
    for i, w in enumerate(words):
        if w.get("w") == token:
            dist = abs(i - approx_idx)
            if best_dist is None or dist < best_dist:
                best, best_dist = w, dist
    return float(best["s"]) if best else None


def _mention_highlights(beat: Dict[str, Any], clip: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Squares to light up as the narrator names the piece standing on them.

    Only *verified* mentions fire: the text must name a piece AND a square, and
    the position on screen at the moment the words are spoken must actually
    have that piece on that square. A hallucinated or transcribed-wrong square
    simply never lights up — silence is the failure mode, not a wrong flash.
    """
    import chess

    text = beat.get("text") or ""
    words = clip.get("words") or []
    if not text or not words:
        return []

    move = beat.get("move") or {}
    skip = {move.get("from"), move.get("to")}
    move_at = int(beat.get("moveAtMs") or 0)
    already = {h.get("square") for h in (beat.get("highlights") or [])}

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for m in _MENTION_RE.finditer(text):
        piece_name = m.group(1).lower()
        square = m.group(2).lower()
        if square in skip or square in seen or square in already:
            continue
        approx_idx = len(text[: m.start(2)].split())
        spoken = _time_of_token(words, square, approx_idx)
        if spoken is None:
            continue
        at_ms = int(spoken * 1000)
        # The board shows prevFen until the move lands, fen after — verify
        # against whichever position is on screen when the words are heard.
        fen = beat.get("fen") if (not move or at_ms >= move_at) else beat.get("prevFen")
        try:
            piece = chess.Board(fen).piece_at(chess.parse_square(square))
        except Exception:
            continue
        if piece is None or piece.piece_type != _PIECE_BY_NAME[piece_name]:
            continue
        seen.add(square)
        out.append({"square": square, "atMs": at_ms})
        if len(out) >= 3:
            break
    return out


# An invitation the narration makes ("pause here and ask yourself…") that the
# video then refuses to honour: the answer used to arrive in the next breath.
_PAUSE_CUE = re.compile(
    r"pause (?:here|the video|for a moment|with me)|try to find|"
    r"see if you can (?:find|spot)|ask yourself",
    re.IGNORECASE,
)


def _named_video_copy(script: Dict[str, Any]) -> Optional[Path]:
    """Copy the finished render to its own folder under outputs/videos/.

        outputs/videos/Geller-v-Keres-1953/
            Geller-v-Keres-1953.mp4
            Geller-v-Keres-1953.png
            Geller-v-Keres-1953.srt

    One folder per game, because uploading means picking up three files that
    belong together and a flat directory interleaves them across every video
    ever made. The files keep the descriptive stem rather than becoming
    video/thumbnail/captions: a file dragged out of its folder should still
    say what it is.

    Best effort: a naming problem must never fail a finished build.
    """
    try:
        meta = script.get("meta") or {}

        def surname(raw: Optional[str]) -> str:
            name = (raw or "").strip()
            if not name or set(name) <= {"?", "."}:
                return "Unknown"
            part = name.split(",")[0].strip() if "," in name else name.split()[-1]
            return re.sub(r"[^A-Za-z0-9]", "", part) or "Unknown"

        year = ""
        m = re.match(r"(\d{4})", (meta.get("date") or "").strip())
        if m:
            year = m.group(1)
        stem = f"{surname(meta.get('white'))}-v-{surname(meta.get('black'))}"
        stem += f"-{year}" if year else ""

        src = ROOT / "apps" / "renderer" / "out" / "video.mp4"
        if not src.exists():
            return None
        lib = OUT / "videos"
        # Same pairing twice (a re-render, or a rematch whose year is unknown):
        # keep both in numbered folders — the point of this copy is that
        # nothing overwrites.
        folder = lib / stem
        n = 2
        while folder.exists():
            folder = lib / f"{stem}-{n}"
            n += 1
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{folder.name}.mp4"
        shutil.copy2(src, dest)
        thumb = ROOT / "apps" / "renderer" / "out" / "thumbnail.png"
        if thumb.exists():
            shutil.copy2(thumb, dest.with_suffix(".png"))
        return dest
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] library copy failed ({exc})")
        return None


def apply_think_pauses(
    script: Dict[str, Any], manifest: Dict[str, Any], pause_ms: int = 5000, limit: int = 3
) -> int:
    """Give a "pause and find it" moment an actual pause.

    Inserts silence into the beat's clip right after the sentence that issues
    the challenge, so the viewer gets thinking time on the frozen position
    before the reveal. The padding is a whole number of video frames, so every
    later clip stays on the frame grid, and word timings after the insertion
    shift with the audio so cues stay honest.
    """
    import wave

    from tts import _norm_word

    clips = manifest.get("clips") or {}
    applied = 0
    for beat in script.get("beats", []):
        if applied >= limit:
            break
        text = beat.get("text") or ""
        cue = _PAUSE_CUE.search(text)
        clip = clips.get(beat["id"])
        if not cue or not clip:
            continue
        path = AUDIO_DIR / clip["file"]
        words = clip.get("words") or []
        if not path.exists() or not words:
            continue

        # The pause belongs at the end of the sentence that asks for it.
        tokens = text.split()
        cue_tok = len(text[: cue.start()].split())
        end_tok = next(
            (j for j in range(cue_tok, len(tokens))
             if tokens[j].rstrip('"”\')').endswith((".", "!", "?"))),
            len(tokens) - 1,
        )
        idx = sum(1 for t in tokens[: end_tok + 1] if _norm_word(t)) - 1
        if not (0 <= idx < len(words)):
            continue
        insert_t = float(words[idx]["e"]) + 0.15

        with wave.open(str(path), "rb") as fh:
            params = fh.getparams()
            sr = fh.getframerate()
            data = fh.readframes(fh.getnframes())
        width = params.sampwidth * params.nchannels
        pad_frames = round(pause_ms * FPS / 1000)
        pad = b"\x00" * (int(sr / FPS) * pad_frames * width)
        cut = min(len(data), int(round(insert_t * sr)) * width)
        with wave.open(str(path), "wb") as fh:
            fh.setparams(params)
            fh.writeframes(data[:cut] + pad + data[cut:])

        clip["durationMs"] = int(clip["durationMs"]) + pause_ms
        shift = pause_ms / 1000.0
        for w in words:
            if w["s"] >= insert_t:
                w["s"] = round(w["s"] + shift, 3)
                w["e"] = round(w["e"] + shift, 3)
        beat["thinkPauseMs"] = pause_ms
        applied += 1
        print(f"[timing] think-pause: +{pause_ms}ms in {beat['id']} after the challenge")
    return applied


def resolve_timing(script: Dict[str, Any], manifest: Dict[str, Any]) -> None:
    """Attach measured durations and move-animation cues to each beat."""
    from tts import word_time

    clips = manifest.get("clips", {}) or {}
    for beat in script.get("beats", []):
        clip = clips.get(beat["id"])
        if clip and clip.get("chain"):
            # Mid-paragraph beat: its clip is a frame-exact slice of one
            # continuous take, and the next beat's clip is the very next
            # sample. Padding or a minimum here would tear the sentence apart.
            beat["audioFile"] = clip["file"]
            beat["durationMs"] = int(clip["durationMs"])
        elif clip:
            beat["audioFile"] = clip["file"]
            beat["durationMs"] = max(MIN_BEAT_MS, int(clip["durationMs"]) + BEAT_TAIL_MS)
        else:
            beat["audioFile"] = None
            beat["durationMs"] = max(MIN_BEAT_MS, len(beat.get("text", "")) * 55)

        if not beat.get("move"):
            beat["moveAtMs"] = 0
            continue

        cue_seconds: Optional[float] = None
        if clip:
            cue_seconds = word_time(clip, *(beat.get("moveCueWords") or []))

        if cue_seconds is None:
            # No usable cue: move a little into the line so the viewer hears the
            # start of the sentence before the piece travels.
            move_at = int(beat["durationMs"] * 0.22)
        else:
            move_at = int(cue_seconds * 1000)

        # Always leave room for the animation to complete inside the beat.
        beat["moveAtMs"] = max(0, min(move_at, beat["durationMs"] - MOVE_ANIM_MS))

    # Second pass, after every moveAtMs is settled: light up squares the
    # narrator talks about ("the knight on d3 is pinned"), timed to the words.
    for beat in script.get("beats", []):
        clip = clips.get(beat["id"])
        beat["mentions"] = _mention_highlights(beat, clip) if clip else []

    # Third pass: drop attack lines the viewer would never have time to read.
    # Arrows come up with the move and live to the end of the beat, so on a
    # fast line they flash on and off inside a second. The director cannot know
    # this — it writes the geometry before a word has been spoken — so the
    # decision belongs here, where the real durations are finally known.
    flashed = 0
    for beat in script.get("beats", []):
        if not beat.get("arrows"):
            continue
        dwell = int(beat["durationMs"]) - int(beat.get("moveAtMs") or 0)
        if dwell < MIN_ARROW_DWELL_MS:
            flashed += len(beat["arrows"])
            beat["arrows"] = []
    if flashed:
        print(f"[timing] dropped {flashed} arrow(s) with under "
              f"{MIN_ARROW_DWELL_MS}ms on screen")


def sync_to_public(script: Dict[str, Any], manifest: Dict[str, Any]) -> None:
    _clear_dir(PUB_AUDIO)
    PUB_AUDIO.mkdir(parents=True, exist_ok=True)

    for clip in (manifest.get("clips") or {}).values():
        src = AUDIO_DIR / clip["file"]
        if src.exists():
            shutil.copy2(src, PUB_AUDIO / src.name)

    (PUB / "script.json").write_text(
        json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Remove artifacts from the previous (scene-based) pipeline so a stale file
    # can never be picked up by the renderer.
    for stale in ("timeline.json", "audio_durations.json"):
        stale_path = PUB / stale
        if stale_path.exists():
            stale_path.unlink()
    print(f"[ok] synced script.json + {len(manifest.get('clips') or {})} clips to renderer/public")


def render(renderer_dir: Path, total_ms: int, script: Dict[str, Any]) -> None:
    npm = shutil.which("npm") or shutil.which("npm.cmd") or shutil.which("npm.exe")
    if not npm:
        raise FileNotFoundError("npm not found in PATH. Install Node.js first.")

    if not (renderer_dir / "node_modules").exists():
        print("[render] installing renderer dependencies (first run)…")
        has_lock = (renderer_dir / "package-lock.json").exists()
        subprocess.check_call([npm, "ci" if has_lock else "install"], cwd=str(renderer_dir))

    pieces_dir = renderer_dir / "public" / "pieces" / "merida"
    if not pieces_dir.exists() or not any(pieces_dir.glob("*.svg")):
        print("[assets] fetching Merida chess piece SVGs…")
        subprocess.check_call([npm, "run", "fetch-pieces"], cwd=str(renderer_dir))

    # Thumbnail first: it is quick, and a failure here should not cost us the
    # whole video render.
    try:
        subprocess.check_call([npm, "run", "render:thumb"], cwd=str(renderer_dir))
        print("[ok] thumbnail -> apps/renderer/out/thumbnail.png")
    except subprocess.CalledProcessError as exc:
        print(f"[warn] thumbnail render failed ({exc.returncode}); continuing without one")

    minutes = total_ms / 60000.0
    print(f"[render] rendering ~{minutes:.1f} minutes of video…")
    subprocess.check_call([npm, "run", "render"], cwd=str(renderer_dir))
    print("[ok] render complete -> apps/renderer/out/video.mp4")

    # Keep a per-game copy so the next build cannot overwrite this one.
    # video.mp4 stays in place as the canonical path the uploader and the
    # daily flow read; the named file is the human-facing library.
    named = _named_video_copy(script)
    if named:
        print(f"[ok] library copy -> {named.relative_to(ROOT)}")
        # Captions travel with the video: YouTube's own transcription has
        # never heard this audio and mangles square names into words.
        try:
            subprocess.check_call(
                [sys.executable, str(Path(__file__).parent / "make_captions.py"),
                 "--out", str(named.with_suffix(".srt"))]
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] captions not written ({exc})")
        # The listing text, beside the video it belongs to. The uploader
        # generates this itself when posting through the API — this file is
        # for the manual path, so the title and description can be copied
        # without hunting for where they came from.
        try:
            subprocess.check_call(
                [sys.executable, str(Path(__file__).parent / "write_listing.py"),
                 "--out", str(named.with_suffix(".txt"))]
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] listing not written ({exc})")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build a narrated chess video")
    ap.add_argument("--pgn", required=True, help="Path to the PGN to narrate")
    ap.add_argument(
        "--tts",
        choices=["auto", "ttsapi", "qwen", "elevenlabs", "local", "silent"],
        default=os.getenv("TTS_BACKEND", "auto"),
        help="Voice backend (auto: ttsapi if TTS_VOICE set, else qwen if VOICE_REF_AUDIO set, "
             "else elevenlabs if keyed, else local)",
    )
    ap.add_argument("--depth", type=int, default=None, help="Stockfish depth override")
    ap.add_argument("--multipv", type=int, default=None, help="Stockfish MultiPV override")
    ap.add_argument("--max-plies", type=int, default=None, help="Analyse only the first N plies")
    ap.add_argument("--no-llm", action="store_true", help="Skip LLM narration polish")
    ap.add_argument("--no-render", action="store_true", help="Stop after writing assets")
    ap.add_argument("--seed", type=int, default=None, help="Deterministic phrasing seed")
    ap.add_argument("--reuse-narration", action="store_true",
                    help="Reuse the previous build's narration text and listing "
                         "metadata, so only non-narration changes show in the "
                         "output — the A/B switch")
    ap.add_argument("--allow-fallback-voice", action="store_true",
                    help="Render even if the voice service was unreachable and "
                         "the audio came from the SAPI fallback")
    return ap.parse_args()


def main() -> int:
    _load_dotenv()
    args = parse_args()
    ensure_dirs()

    from chessbot_analyzer.facts import extract_facts, save_facts
    from chessbot_analyzer.director import build_script, save_script
    from tts import synthesize

    pgn_path = Path(args.pgn)
    if not pgn_path.is_absolute():
        pgn_path = ROOT / pgn_path
    if not pgn_path.exists():
        print(f"[error] PGN not found: {pgn_path}")
        return 2
    pgn_text = pgn_path.read_text(encoding="utf-8", errors="ignore")
    print(f"[ingest] {pgn_path.name}")

    # --- 1) facts -------------------------------------------------------
    print("[facts] analysing game with Stockfish…")
    facts = extract_facts(
        pgn_text,
        depth=args.depth,
        multipv=args.multipv,
        max_plies=args.max_plies,
    )
    save_facts(facts, OUT / "facts.json")
    key_moments = facts.get("keyMoments") or []
    print(
        f"[facts] {len(facts.get('plies', []))} plies analysed, "
        f"{len(key_moments)} key moments"
    )

    # --- 2) director ----------------------------------------------------
    script = build_script(
        facts,
        channel_name=os.getenv("CHANNEL_NAME", "Nocturne Chess"),
        use_llm=not args.no_llm and not args.reuse_narration,
        seed=args.seed,
    )

    # The narration model writes fresh text every run, so two builds of the
    # same game are never the same video — which makes A/B-ing a voice or
    # render change impossible. --reuse-narration copies the previous build's
    # words (and listing metadata) onto this build's beats, so the only thing
    # that changes is what the change changed.
    if args.reuse_narration:
        prior_path = OUT / "script.json"
        try:
            prior = json.loads(prior_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"[script] ERROR: --reuse-narration needs a previous "
                  f"{prior_path.name} ({exc})")
            return 2
        texts = {b["id"]: b.get("text") for b in prior.get("beats", [])}
        matched = [b for b in script["beats"] if texts.get(b["id"])]
        # The beat list is derived from the facts, so a mismatch means the
        # analysis changed under us and the old words describe another video.
        if len(matched) < len(script["beats"]) * 0.9:
            print(f"[script] ERROR: only {len(matched)}/{len(script['beats'])} "
                  "beats match the previous script — the analysis has changed; "
                  "rerun without --reuse-narration")
            return 2
        for b in script["beats"]:
            if texts.get(b["id"]):
                b["text"] = texts[b["id"]]
        for key in ("llmTitle", "llmHook", "llmThumb", "quote", "narration"):
            if prior.get("meta", {}).get(key) is not None:
                script["meta"][key] = prior["meta"][key]
        print(f"[script] reusing narration from previous build "
              f"({len(matched)} beats, title: {script['meta'].get('llmTitle')!r})")
    beats = script.get("beats", [])
    variations = sum(1 for b in beats if b["kind"] == "variation")
    print(
        f"[script] {len(beats)} beats "
        f"({variations} variation beats, narration={script['meta'].get('narration')})"
    )

    # Cache portraits for the two players before looking for them on disk.
    # Best effort by design: a missing face renders the silhouette, and no
    # network hiccup is allowed to cost a day's video.
    try:
        import portraits_fetch

        portraits_fetch.ensure(script["meta"].get("white"), script["meta"].get("black"))
        credits = portraits_fetch.credits_for(
            script["meta"].get("white") or "", script["meta"].get("black") or ""
        )
        if credits:
            script["meta"]["portraitCredits"] = [
                {"player": c.get("player"), "licence": c.get("licence"),
                 "author": c.get("author"), "url": c.get("descriptionUrl")}
                for c in credits
            ]
    except Exception as exc:  # noqa: BLE001
        print(f"[portraits] skipped ({exc})")

    # Portraits are optional; wire them up when a matching file exists.
    for side, key in (("white", "whitePortrait"), ("black", "blackPortrait")):
        name = (script["meta"].get(side) or "").split(",")[0].strip().lower()
        if not name:
            continue
        for ext in ("jpg", "jpeg", "png", "webp"):
            candidate = PUB / "portraits" / f"{name}.{ext}"
            if candidate.exists():
                script["meta"][key] = candidate.name
                break

    # The quote's author often is not one of today's players — Nimzowitsch has
    # no game in the pool but plenty to say — so their portrait may simply not
    # be cached. The card lays out fine without one; a broken image does not.
    quote = script["meta"].get("quote") or {}
    if quote.get("portrait") and not (PUB / "portraits" / quote["portrait"]).exists():
        quote["portrait"] = None

    save_script(script, OUT / "script.json")

    # --- 3) voice -------------------------------------------------------
    _clear_dir(AUDIO_DIR, "*.wav")
    _clear_dir(AUDIO_DIR, "*.mp3")
    lines = [
        {"id": b["id"], "text": b["text"], "para": b.get("para")}
        for b in beats
        if b.get("text")
    ]
    print(f"[voice] synthesizing {len(lines)} lines (backend={args.tts})…")
    manifest = synthesize(lines, AUDIO_DIR, backend=args.tts)
    print(f"[voice] backend={manifest['backend']} ext={manifest['ext']}")

    # The voice layer degrades rather than dying, which is right for an
    # unattended daily run — flow.py keeps the render and holds the upload.
    # Interactively it is the wrong trade: six minutes of rendering produce a
    # video nobody can judge, in the channel's wrong voice. Stop here instead,
    # and say what to restart.
    if (
        not args.allow_fallback_voice
        and manifest["backend"] not in VOICE_BACKENDS
        and (args.tts in VOICE_BACKENDS
             or (args.tts == "auto" and os.getenv("TTS_VOICE", "").strip()))
    ):
        print(f"\n[voice] ERROR: asked for '{args.tts}' but the audio came from "
              f"'{manifest['backend']}'.")
        print(f"[voice] the voice service at {os.getenv('TTS_API_URL', '?')} "
              "did not answer. Start it and run this again,")
        print("[voice] or pass --allow-fallback-voice to render anyway.")
        return 3

    if apply_think_pauses(script, manifest):
        (OUT / "audio_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    resolve_timing(script, manifest)
    save_script(script, OUT / "script.json")

    total_ms = sum(b["durationMs"] for b in beats)
    print(f"[timing] total {total_ms / 1000:.1f}s across {len(beats)} beats")

    # --- 4) render ------------------------------------------------------
    sync_to_public(script, manifest)
    if args.no_render:
        print("[ok] assets written; skipping render (--no-render)")
        return 0

    render(ROOT / "apps" / "renderer", total_ms, script)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
