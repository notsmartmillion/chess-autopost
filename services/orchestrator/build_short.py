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
import zlib
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
# selection trims to well under it. Target is AROUND A MINUTE — measured
# ~163 wpm on real takes, so ~165 words lands near 60s. Sub-40s Shorts are
# hard to monetize, so the window pulls in extra lead-up beats to fill the
# minute with build-up rather than padding. Shorts classify by aspect ratio
# up to three minutes, so slightly over 60s costs nothing.
MAX_WORDS = 165
MAX_SETUP_BEATS = 4
MAX_SECONDS = 75.0
MIN_SECONDS = 15.0

# What earns a Short. Not a quality tag — the SWING. A "mistake" that turns
# -2.4 into -4.1 is a losing player losing harder, and cutting it as "the
# moment it started to slip" put a false headline over a true eval bar. Two
# things reliably make a stranger stop scrolling:
#
#   * a brilliancy — a sound sacrifice, rarer still in a streak, and
#   * a reversal — a player who was clearly winning and threw it away.
#
# Everything else is a fine long-form moment and no Short at all.
REVERSAL_BEFORE_CP = 250   # "sure of victory": +2.5 for the mover
REVERSAL_AFTER_CP = 50     # ...and after the move, nothing left of it

TAG_PRIORITY = ("brilliant", "blunder", "great", "mistake")  # hook wording only

# Hooks are drawn from what actually happened, not from the tag. Three of
# the first four Shorts opened with the identical line, because every
# brilliancy got one fixed string — on a feed where the hook IS the video,
# that reads as a template.
#
# A "brilliant" move is, by the classifier's own definition, the only move
# AND a sacrifice, so naming the piece offered is always true. The piece
# comes from the SAN: an uppercase letter names it, anything else is a pawn.
PIECE_HOOKS: Dict[str, Tuple[str, ...]] = {
    "Q": (
        "He gave his queen away.",
        "The queen, offered for nothing.",
        "Who gives up a queen here?",
    ),
    "R": (
        "He left a rook hanging on purpose.",
        "A rook, offered and meant.",
        "The rook was never the point.",
    ),
    "B": (
        "The bishop was there to be taken.",
        "He threw a bishop into it.",
        "A bishop, and no way to refuse.",
    ),
    "N": (
        "The knight walked in unprotected.",
        "He put a knight where it could not stand.",
        "A knight, offered to everything.",
    ),
    "P": (
        "One pawn nobody was allowed to take.",
        "A pawn, thrown forward and left there.",
        "It starts with a pawn.",
    ),
}
GENERIC_HOOKS: Tuple[str, ...] = (
    "The move nobody saw coming.",
    "One move, and the game breaks open.",
    "This should not work. It does.",
    "Watch what he does here.",
)
STREAK_HOOKS: Tuple[str, ...] = (
    "One brilliant blow after another.",
    "He kept giving pieces away.",
    "{n} sacrifices, one idea.",
    "It did not stop at one.",
)
REVERSAL_HOOKS: Tuple[str, ...] = (
    "{loser} was winning. Then this.",
    "{loser} had it won.",
    "One move threw the whole game away.",
    "{loser} never recovered from this.",
)


def _words(text: Optional[str]) -> int:
    return len((text or "").split())


def _mover_is_white(beat: Dict[str, Any]) -> bool:
    return ((beat.get("ply") or 0) % 2) == 1


def find_wow(beats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The one moment worth a Short, or None.

    Returns {"index", "kind": "brilliant"|"reversal", "streak": [indices]}.
    A brilliancy streak (consecutive brilliant moves) beats a lone
    brilliancy beats a reversal, and the reversal must be measured against
    the eval — the mover was clearly winning before and is not after.
    """
    moves = [i for i, b in enumerate(beats)
             if b.get("kind") == "move" and not b.get("branch")]

    # Brilliancies, grouped into consecutive streaks (by mainline order).
    brilliant = [i for i in moves if beats[i].get("tag") == "brilliant"]
    streaks: List[List[int]] = []
    for i in brilliant:
        pos = moves.index(i)
        if streaks and moves.index(streaks[-1][-1]) in (pos - 1, pos - 2):
            # Same player's consecutive turns sit two plies apart.
            streaks[-1].append(i)
        else:
            streaks.append([i])
    if streaks:
        best = max(streaks, key=len)
        return {"index": best[0], "kind": "streak" if len(best) > 1 else "brilliant",
                "streak": best}

    # Reversals: the mover was clearly winning, and after this move is not.
    prev_eval: Optional[float] = None
    for i in moves:
        b = beats[i]
        ev = b.get("evalCp")
        if b.get("tag") in ("blunder", "mistake") and                 isinstance(prev_eval, (int, float)) and isinstance(ev, (int, float)):
            sign = 1 if _mover_is_white(b) else -1
            before_m, after_m = sign * prev_eval, sign * ev
            if before_m >= REVERSAL_BEFORE_CP and after_m <= REVERSAL_AFTER_CP:
                return {"index": i, "kind": "reversal", "streak": [i]}
        if isinstance(ev, (int, float)):
            prev_eval = ev
    return None


def _sacrificed_piece(hero: Dict[str, Any]) -> Optional[str]:
    """Which piece was offered, from the SAN. None when it cannot be read."""
    san = ((hero.get("move") or {}).get("san") or "").lstrip("(")
    if not san:
        return None
    first = san[0]
    if first in "QRBNK":
        return first
    return "P" if first.islower() else None


def make_hook(
    kind: str, hero: Dict[str, Any], meta: Dict[str, Any], streak: int = 1
) -> str:
    """A hook drawn from this game, chosen the same way every rebuild.

    Seeded on the pairing and the move, so a Short rebuilt after a layout
    change keeps the line it was published with, while a different game gets
    a different one. crc32, not hash() — Python salts hash() per process,
    which would make "stable" a coin flip between runs.
    """
    seed = zlib.crc32(
        "|".join(str(x) for x in (
            meta.get("white"), meta.get("black"), meta.get("date"),
            (hero.get("move") or {}).get("san"), kind,
        )).encode("utf-8")
    )

    if kind == "reversal":
        loser = meta.get("whiteFull") if _mover_is_white(hero) else meta.get("blackFull")
        loser = loser or ("White" if _mover_is_white(hero) else "Black")
        return REVERSAL_HOOKS[seed % len(REVERSAL_HOOKS)].format(loser=loser)

    if kind == "streak":
        # Spelt, not numeric: "2 sacrifices" reads like a spec sheet on screen
        # and the voice says the word anyway.
        words = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}
        pool = [h for h in STREAK_HOOKS if "{n}" not in h or streak in words]
        return pool[seed % len(pool)].format(n=words.get(streak, str(streak)))

    # A brilliancy is an only-move sacrifice, so naming the offered piece is
    # always true — and far stronger than a generic line, which is why the
    # generic pool is a fallback for an unreadable SAN rather than an equal
    # sibling. Two knight sacrifices drew "Watch what he does here" while
    # "The knight walked in unprotected" sat unused.
    piece = _sacrificed_piece(hero)
    pool = list(PIECE_HOOKS.get(piece or "", ())) or list(GENERIC_HOOKS)
    return pool[seed % len(pool)]


def select_window(beats: List[Dict[str, Any]]) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    """The wow moment, one beat of setup, the streak, and the refutation.

    Trimming order when over budget: setup first, then trailing beats — the
    payoff stays. Returns (window, wow) or None.
    """
    wow = find_wow(beats)
    if wow is None:
        return None
    hero = wow["index"]

    # Lead-up: walk back through the mainline collecting build-up beats. The
    # tension before the moment is what makes the moment land — and it is
    # also what carries a Short past the sub-40s monetization floor honestly,
    # with story rather than padding.
    setups: List[Dict[str, Any]] = []
    for j in range(hero - 1, -1, -1):
        if len(setups) >= MAX_SETUP_BEATS:
            break
        b = beats[j]
        if b.get("kind") in ("move", "hold") and not b.get("branch"):
            setups.insert(0, b)

    last = wow["streak"][-1]
    tail: List[Dict[str, Any]] = [beats[k] for k in range(hero + 1, last + 1)]
    j = last + 1
    while j < len(beats) and beats[j].get("kind") == "variation" and beats[j].get("branch"):
        tail.append(beats[j])
        j += 1
    if j < len(beats) and beats[j].get("kind") == "resume":
        tail.append(beats[j])

    window = setups + [beats[hero]] + tail

    def total() -> int:
        return sum(_words(b.get("text")) for b in window)

    # Over budget: shed lead-up from the FRONT first (the earliest context is
    # the most expendable), then trailing beats — the payoff stays.
    while total() > MAX_WORDS and window and window[0] is not beats[hero]:
        window = window[1:]
    while total() > MAX_WORDS and len(window) > 2:
        window.pop()
    if total() > MAX_WORDS:
        return None
    return window, wow


def build_short_script(script: Dict[str, Any], full_url: Optional[str]) -> Optional[Dict[str, Any]]:
    beats = script.get("beats") or []
    meta = dict(script.get("meta") or {})
    selected = select_window(beats)
    if not selected:
        return None
    window, wow = selected

    hook_text = make_hook(wow["kind"], beats[wow["index"]], meta,
                          streak=len(wow.get("streak") or [1]))

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

    # ffprobe sits beside ffmpeg, but the resolved path can be any casing —
    # WinGet hands back "ffmpeg.EXE", so a case-sensitive replace silently
    # left the path pointing at ffmpeg and ran it with ffprobe's arguments.
    ff = _ffmpeg()
    probe = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if not probe and ff:
        cand = Path(ff).with_name("ffprobe" + Path(ff).suffix)
        probe = str(cand) if cand.exists() else None
    if not probe:
        print("[short] ffprobe not found; skipping the render check")
        return
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
    # The script lands with the video, before the check. A crash between the
    # two used to leave a new mp4 beside the previous run's json, and the
    # next verification then compared a 59 s video against a 23 s script and
    # called the render broken.
    (out_mp4.parent / f"{stem}.json").write_text(
        json.dumps(short, indent=2, ensure_ascii=False), encoding="utf-8")
    verify_rendered(short, out_mp4)
    print(f"[short] done -> {out_mp4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
