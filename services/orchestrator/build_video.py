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


def resolve_timing(script: Dict[str, Any], manifest: Dict[str, Any]) -> None:
    """Attach measured durations and move-animation cues to each beat."""
    from tts import word_time

    clips = manifest.get("clips", {}) or {}
    for beat in script.get("beats", []):
        clip = clips.get(beat["id"])
        if clip:
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


def render(renderer_dir: Path, total_ms: int) -> None:
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
        channel_name=os.getenv("CHANNEL_NAME", "Quiet Chess"),
        use_llm=not args.no_llm,
        seed=args.seed,
    )
    beats = script.get("beats", [])
    variations = sum(1 for b in beats if b["kind"] == "variation")
    print(
        f"[script] {len(beats)} beats "
        f"({variations} variation beats, narration={script['meta'].get('narration')})"
    )

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

    save_script(script, OUT / "script.json")

    # --- 3) voice -------------------------------------------------------
    _clear_dir(AUDIO_DIR, "*.wav")
    _clear_dir(AUDIO_DIR, "*.mp3")
    lines = [{"id": b["id"], "text": b["text"]} for b in beats if b.get("text")]
    print(f"[voice] synthesizing {len(lines)} lines (backend={args.tts})…")
    manifest = synthesize(lines, AUDIO_DIR, backend=args.tts)
    print(f"[voice] backend={manifest['backend']} ext={manifest['ext']}")

    resolve_timing(script, manifest)
    save_script(script, OUT / "script.json")

    total_ms = sum(b["durationMs"] for b in beats)
    print(f"[timing] total {total_ms / 1000:.1f}s across {len(beats)} beats")

    # --- 4) render ------------------------------------------------------
    sync_to_public(script, manifest)
    if args.no_render:
        print("[ok] assets written; skipping render (--no-render)")
        return 0

    render(ROOT / "apps" / "renderer", total_ms)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)
