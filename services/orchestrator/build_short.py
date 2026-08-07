"""Cut a vertical Short from a game's existing beat script.

    python services/orchestrator/build_short.py \
        --script outputs/videos/G/G.json [--full-url https://youtu.be/...]

The long-form pipeline already answers the hard question — which moment of a
game is worth 45 seconds — as a byproduct of analysis: beats carry quality
tags, evals, exact durations and word-level move cues. This selects the best
moment, its setup and its refutation, re-voices them, and renders the 9:16
composition.

AUDIO IS THE DESIGN CONSTRAINT. Every voice defect this channel has shipped —
seams heard as a new announcer, off-voice stretches, clipped splices — lives
at or across take boundaries. A Short is short enough to fit in ONE take
(the word budget guarantees it), so those defects cannot occur by
construction. This file enforces that: if the selection cannot fit one take,
it is trimmed until it does, and if synthesis still comes back with more than
one take or any unresolved defect, the build refuses to render.

Narration text is reused verbatim from the long-form script (already written,
already audited); only the hook and the sign-off are new, and they are
templates — no model call, so no API failure mode either.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
AUDIO_DIR = OUT / "audio_short"
RENDERER = ROOT / "apps" / "renderer"
PUB_AUDIO = RENDERER / "public" / "audio_short"
SHORTS_DIR = OUT / "shorts"

sys.path.insert(0, str(ROOT / "services" / "orchestrator"))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FPS = 30

# One take is the whole audio guarantee, so the budget wears a belt and
# braces: TTS merges takes up to SYNTH_WORD_BUDGET (320) words, and the
# selection trims to well under it. ~150 words at the narrator's ~170 wpm is
# ~53 seconds — under the sub-60s bar the Shorts feed treats most kindly.
MAX_WORDS = 150
MAX_SECONDS = 60.0
MIN_SECONDS = 15.0

TAG_PRIORITY = ("brilliant", "blunder", "great", "mistake")

HOOKS: Dict[str, str] = {
    "brilliant": "The move nobody saw coming.",
    "great": "One move to hold everything together.",
    "blunder": "One move threw the game away.",
    "mistake": "The moment it started to slip.",
}


def _words(text: Optional[str]) -> int:
    return len((text or "").split())


TAG_SCORE = {"brilliant": 5, "blunder": 4, "great": 3, "mistake": 2}
# The refutation is the payoff of the format — setup, disaster, and what
# should have happened. A blunder with its branch attached makes a stronger
# Short than a lone tagged move, however shiny: the first cut of this
# selector picked a bare "great" and produced nineteen thin seconds.
REFUTATION_BONUS = 3


def _has_refutation(beats: List[Dict[str, Any]], i: int) -> bool:
    j = i + 1
    return j < len(beats) and beats[j].get("kind") == "variation" \
        and bool(beats[j].get("branch"))


def pick_hero(beats: List[Dict[str, Any]]) -> Optional[int]:
    """Index of the beat worth a Short.

    Tag quality plus a large bonus for a refutation that follows. Played
    brilliancies never carry a branch (deliberately, since the variation
    policy change), so they compete on their own drama; errors compete with
    their punishment attached. Ties break toward the stronger tag, then the
    earlier moment.
    """
    moves = [i for i, b in enumerate(beats) if b.get("kind") == "move"]
    scored: List[Tuple[float, int, int]] = []
    for i in moves:
        b = beats[i]
        tag = b.get("tag")
        if b.get("branch") or tag not in TAG_SCORE:
            continue
        score = TAG_SCORE[tag] + (REFUTATION_BONUS if _has_refutation(beats, i) else 0)
        pri = TAG_PRIORITY.index(tag)
        scored.append((score, -pri, -i))
    if not scored:
        # No brilliancy, no blunder, nothing great and nothing punished:
        # this game has no 45 seconds worth a stranger's attention. Silence
        # beats filler — and this also refuses degenerate scripts outright
        # (a template-prose build almost became a Short through the old
        # eval-swing fallback here).
        return None
    score, neg_pri, neg_i = max(scored)
    return -neg_i


def select_window(beats: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """The hero move, one beat of setup, and the refutation that follows.

    Trimming order when over budget: setup first, then trailing variation
    beats — the refutation is the payoff, but a refutation cut mid-thought is
    worse than none, so variations drop from the end as whole beats.
    """
    hero = pick_hero(beats)
    if hero is None:
        return None

    setup: Optional[Dict[str, Any]] = None
    for j in range(hero - 1, -1, -1):
        b = beats[j]
        if b.get("kind") in ("move", "hold") and not b.get("branch"):
            setup = b
            break

    tail: List[Dict[str, Any]] = []
    j = hero + 1
    while j < len(beats) and beats[j].get("kind") == "variation" and beats[j].get("branch"):
        tail.append(beats[j])
        j += 1
    if j < len(beats) and beats[j].get("kind") == "resume":
        tail.append(beats[j])

    window = ([setup] if setup else []) + [beats[hero]] + tail

    def total() -> int:
        return sum(_words(b.get("text")) for b in window)

    if total() > MAX_WORDS and setup is not None and len(window) > 1:
        window = window[1:]  # drop setup before touching the refutation
    while total() > MAX_WORDS and len(window) > 2:
        window.pop()  # trailing variation/resume beats, whole beats at a time
    if total() > MAX_WORDS:
        # A single enormous hero beat: not Short material.
        return None
    return window


def build_short_script(script: Dict[str, Any], full_url: Optional[str]) -> Optional[Dict[str, Any]]:
    beats = script.get("beats") or []
    meta = dict(script.get("meta") or {})
    window = select_window(beats)
    if not window:
        return None

    hero = next((b for b in window if b.get("kind") == "move" and b.get("tag")), None)
    tag = (hero or {}).get("tag") or "great"
    hook_text = HOOKS.get(tag, HOOKS["great"])

    white = meta.get("whiteFull") or meta.get("white") or "White"
    black = meta.get("blackFull") or meta.get("black") or "Black"

    first = window[0]
    out_beats: List[Dict[str, Any]] = []
    out_beats.append({
        "id": "s0001", "kind": "intro",
        "text": f"{white} against {black}. {hook_text}",
        "prevFen": first.get("prevFen"), "fen": first.get("prevFen") or first.get("fen"),
        "move": None, "branch": False, "label": None,
        "highlights": [], "arrows": [], "checkSquare": None,
        "evalCp": first.get("evalCp"), "tag": None, "ply": None,
        "moveCueWords": [], "durationMs": 0, "moveAtMs": 0, "audioFile": None,
        "para": 0,
    })
    for n, b in enumerate(window, start=2):
        nb = dict(b)
        nb["id"] = f"s{n:04d}"
        nb["para"] = 0  # ONE paragraph -> one take -> no seams
        nb.pop("thinkPauseMs", None)  # a Short has no time to pause
        nb.pop("mentions", None)  # timed against the long-form audio; stale here
        out_beats.append(nb)
    out_beats.append({
        "id": f"s{len(window) + 2:04d}", "kind": "outro",
        "text": "The full game is on the channel.",
        "prevFen": window[-1].get("fen"), "fen": window[-1].get("fen"),
        "move": None, "branch": False, "label": None,
        "highlights": [], "arrows": [], "checkSquare": None,
        "evalCp": window[-1].get("evalCp"), "tag": None, "ply": None,
        "moveCueWords": [], "durationMs": 0, "moveAtMs": 0, "audioFile": None,
        "para": 0,
    })

    meta["shortHook"] = hook_text
    meta["shortOf"] = meta.get("llmTitle")
    if full_url:
        meta["fullVideoUrl"] = full_url
    return {"meta": meta, "beats": out_beats}


def synthesize_short(short: Dict[str, Any], backend: str) -> Dict[str, Any]:
    """One take, or refuse.

    All the long-form voice machinery runs (priming, re-rolls, rescue, the
    unresolved-defect marker); the single-paragraph layout simply gives it
    nothing to stitch.
    """
    from tts import synthesize

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for f in AUDIO_DIR.glob("*"):
        if f.is_file():
            f.unlink()

    lines = [{"id": b["id"], "text": b["text"], "para": b.get("para")}
             for b in short["beats"] if b.get("text")]
    total_words = sum(_words(l["text"]) for l in lines)
    if total_words > 320:
        raise SystemExit(f"[short] selection is {total_words} words — cannot be one take")

    print(f"[short] synthesizing {len(lines)} beats, {total_words} words, one take…")
    manifest = synthesize(lines, AUDIO_DIR, backend=backend)
    return manifest


def enforce_audio_contract(short: Dict[str, Any], manifest: Dict[str, Any]) -> None:
    """Hard gates. Every one of these was a shipped defect in long-form."""
    clips = manifest.get("clips") or {}
    problems: List[str] = []

    if manifest.get("backend") not in ("ttsapi", "qwen", "elevenlabs"):
        problems.append(f"voice came from '{manifest.get('backend')}', not the channel voice")

    # One take: exactly one clip is a take head; the rest are slices of it.
    heads = [cid for cid, c in clips.items() if not c.get("chain")]
    if len(heads) != 1:
        problems.append(f"{len(heads)} takes — a Short must be ONE (no seams by construction)")

    spoken = [b for b in short["beats"] if b.get("text")]
    for b in spoken:
        c = clips.get(b["id"])
        if not c or not (AUDIO_DIR / (c.get("file") or "")).exists():
            problems.append(f"{b['id']} has no audio")
        elif not c.get("words"):
            problems.append(f"{b['id']} has no word alignment")

    marker = AUDIO_DIR / "unresolved_seams.json"
    if marker.exists():
        try:
            unresolved = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unresolved = ["unreadable marker"]
        if unresolved:
            problems.append(f"synthesis reported unresolved defects: {unresolved}")

    total_s = sum(int(clips.get(b["id"], {}).get("durationMs") or 0)
                  for b in spoken) / 1000
    if total_s > MAX_SECONDS:
        problems.append(f"audio runs {total_s:.1f}s — over the {MAX_SECONDS:.0f}s Short bar")
    if total_s < MIN_SECONDS:
        problems.append(f"audio runs {total_s:.1f}s — too short to be a real clip")

    if problems:
        for p in problems:
            print(f"[short] AUDIO CONTRACT FAILED: {p}")
        raise SystemExit(4)
    print(f"[short] audio contract holds: one take, {total_s:.1f}s, all beats aligned")


def render_short(short: Dict[str, Any], out_path: Path) -> None:
    import tempfile

    npm = shutil.which("npm") or shutil.which("npm.cmd")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not (npm and npx):
        raise SystemExit("[short] npm/npx not found")
    if not (RENDERER / "node_modules").exists():
        subprocess.check_call([npm, "install", "--no-audit", "--no-fund"], cwd=str(RENDERER))

    PUB_AUDIO.mkdir(parents=True, exist_ok=True)
    for f in PUB_AUDIO.glob("*"):
        if f.is_file():
            f.unlink()
    for f in AUDIO_DIR.glob("*.wav"):
        shutil.copy2(f, PUB_AUDIO / f.name)
    for f in AUDIO_DIR.glob("*.mp3"):
        shutil.copy2(f, PUB_AUDIO / f.name)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="shortprops-"))
    props = tmp / "props.json"
    props.write_text(json.dumps({"script": short}, ensure_ascii=False), encoding="utf-8")
    total_ms = sum(b.get("durationMs") or 0 for b in short["beats"])
    print(f"[short] rendering {total_ms / 1000:.1f}s vertical…")
    try:
        subprocess.check_call(
            [npx, "remotion", "render", "src/index.tsx", "ChessShort",
             str(out_path.resolve()), "--codec=h264", "--crf=18", "--overwrite",
             f"--props={props.resolve()}"],
            cwd=str(RENDERER),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verify_rendered(short: Dict[str, Any], mp4: Path) -> None:
    """The rendered file must match the script it claims to be."""
    from tts import _ffmpeg

    ff = _ffmpeg()
    probe = (ff or "ffmpeg").replace("ffmpeg.exe", "ffprobe.exe")
    out = subprocess.run(
        [probe, "-v", "error",
         "-show_entries", "format=duration:stream=codec_type,width,height",
         "-of", "json", str(mp4)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    dur = float(data["format"]["duration"])
    want = sum(b.get("durationMs") or 0 for b in short["beats"]) / 1000
    streams = {s.get("codec_type") for s in data.get("streams", [])}
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})

    problems = []
    if "audio" not in streams:
        problems.append("no audio stream in the render")
    if abs(dur - want) > 1.5:
        problems.append(f"container is {dur:.1f}s but the script says {want:.1f}s")
    if (video.get("width"), video.get("height")) != (1080, 1920):
        problems.append(f"frame is {video.get('width')}x{video.get('height')}, not 1080x1920")
    if problems:
        for p in problems:
            print(f"[short] RENDER CHECK FAILED: {p}")
        raise SystemExit(4)
    print(f"[short] render verified: {dur:.1f}s, 1080x1920, audio present")


def main() -> int:
    # Same .env the long-form build reads — without it TTS_VOICE is unset,
    # the service rejects the request, and synthesis quietly hands back SAPI.
    # (The audio contract caught exactly that on this file's first real run.)
    from build_video import _load_dotenv
    _load_dotenv()

    ap = argparse.ArgumentParser(description="Cut a vertical Short from a beat script")
    ap.add_argument("--script", required=True, help="Long-form script.json (library copy)")
    ap.add_argument("--full-url", default=None, help="URL of the full-game video")
    ap.add_argument("--tts", default=os.getenv("TTS_BACKEND", "ttsapi"))
    ap.add_argument("--out", default=None, help="Output mp4 (default: outputs/shorts/<stem>.mp4)")
    args = ap.parse_args()

    src = Path(args.script)
    script = json.loads(src.read_text(encoding="utf-8"))
    short = build_short_script(script, args.full_url)
    if short is None:
        print("[short] no moment in this game clears the bar — no Short. "
              "Silence beats filler.")
        return 3

    words = sum(_words(b.get("text")) for b in short["beats"])
    print(f"[short] {len(short['beats'])} beats, {words} words "
          f"(hook: {short['meta']['shortHook']!r})")

    # Same redraw ladder the daily pipeline uses: synthesis is a lottery even
    # for a single take (a hook can come back read like an announcement while
    # the narration stays calm), and a fresh seed is a genuinely fresh draw.
    from build_video import resolve_timing
    base_seed = os.getenv("TTS_SEED", "42").strip() or "42"
    draws = 3
    manifest = None
    for attempt in range(1, draws + 1):
        if base_seed != "-1" and attempt > 1:
            os.environ["TTS_SEED"] = str(int(base_seed) + 10_000 * (attempt - 1))
            print(f"[short] voice draw {attempt}/{draws} on a fresh seed…")
        manifest = synthesize_short(short, args.tts)
        resolve_timing(short, manifest)
        try:
            enforce_audio_contract(short, manifest)
            break
        except SystemExit:
            if attempt == draws:
                print(f"[short] {draws} voice draws all failed the contract; "
                      "no Short from this game today")
                raise

    stem = src.stem + "-short"
    out_mp4 = Path(args.out) if args.out else SHORTS_DIR / stem / f"{stem}.mp4"
    render_short(short, out_mp4)
    verify_rendered(short, out_mp4)

    (out_mp4.parent / f"{stem}.json").write_text(
        json.dumps(short, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[short] done -> {out_mp4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
