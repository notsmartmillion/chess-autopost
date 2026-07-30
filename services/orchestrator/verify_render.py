"""Pass 5 — audit a finished render against everything it promised to be.

Run after build_video.py / flow.py:

    python services/orchestrator/verify_render.py
    python services/orchestrator/verify_render.py --json report.json
    python services/orchestrator/verify_render.py --frames        # + contact sheet

Why this exists: the run log is a progress narrative — it says what happened, in
order, and nothing about whether it was correct. Every defect found by hand so
far (arrows drawn to the board edge, a take ending on a comma, a rail that went
blank after a variation, narration priced in centipawns, a check described as
unblockable when g3 blocked it) was caught by a throwaway script. Codified here,
each one becomes a regression test that runs on every render instead of whenever
somebody happens to look.

Checks are graded:

    ERROR  — ship-blocking. The video is wrong, or an artifact contradicts another.
    WARN   — suspicious. Legitimate sometimes; worth reading every time.
    INFO   — measurements, for comparing one render against the next.

Exit code is the number of ERRORs, so a loop can gate on it.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
PUB = ROOT / "apps" / "renderer" / "public"
VIDEO = ROOT / "apps" / "renderer" / "out" / "video.mp4"
THUMB = ROOT / "apps" / "renderer" / "out" / "thumbnail.png"

FPS = 30
MOVE_ANIM_MS = 420
SENTENCE_END = tuple('.!?"”’)')

PIECE_BY_NAME = {
    "king": chess.KING, "queen": chess.QUEEN, "rook": chess.ROOK,
    "bishop": chess.BISHOP, "knight": chess.KNIGHT, "pawn": chess.PAWN,
}

MENTION_RE = re.compile(
    r"\b(king|queen|rook|bishop|knight|pawn)s?\s+"
    r"(?:(?:sitting|standing|back|still|over|waiting|stuck)\s+)?"
    r"(?:on|at)\s+([a-h][1-8])\b",
    re.IGNORECASE,
)

# Notation and engine units that a narrator must never be made to read aloud.
SPOKEN_BANS: List[Tuple[str, str]] = [
    ("raw SAN", r"\b(?:[KQRBN][a-h]?[1-8]?x?[a-h][1-8][+#]?|O-O(?:-O)?)\b"),
    # A spoken move number ("12.") — but not the digit of a square ending a
    # sentence, where "at e5." is perfectly good English.
    ("symbol", r"[#@%&*/\\_=]|(?<![a-h])\b\d{1,3}\.\s"),
    ("engine units", r"pawn'?s?\s+worth\s+of|\bevaluation\b|\bdeficit\b|"
                     r"losing by|\bcentipawn|\bcp\b|\+\d\.\d"),
    # No blanket ban on "the king has to move": that sentence is *correct* when
    # the engine says it is, and check_narration cross-checks each one against
    # checkEvasions. A pattern match here only duplicated that as noise.
]


class Report:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str]] = []

    def add(self, level: str, section: str, message: str) -> None:
        self.rows.append((level, section, message))

    def error(self, section: str, message: str) -> None:
        self.add("ERROR", section, message)

    def warn(self, section: str, message: str) -> None:
        self.add("WARN", section, message)

    def info(self, section: str, message: str) -> None:
        self.add("INFO", section, message)

    @property
    def errors(self) -> int:
        return sum(1 for lvl, _, _ in self.rows if lvl == "ERROR")

    @property
    def warns(self) -> int:
        return sum(1 for lvl, _, _ in self.rows if lvl == "WARN")

    def render(self) -> str:
        width = max((len(s) for _, s, _ in self.rows), default=8)
        lines = []
        for level, section, message in self.rows:
            mark = {"ERROR": "FAIL", "WARN": "warn", "INFO": "    "}[level]
            lines.append(f"  {mark}  {section.ljust(width)}  {message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# pass 1 — the fact sheet
# ---------------------------------------------------------------------------


def check_facts(facts: Dict[str, Any], rep: Report) -> None:
    plies = facts.get("plies") or []
    if not plies:
        rep.error("facts", "no plies in the fact sheet")
        return
    rep.info("facts", f"{len(plies)} plies, {len(facts.get('keyMoments') or [])} key moments")

    # The board must be continuous: each ply starts where the last one ended.
    breaks = 0
    for a, b in zip(plies, plies[1:]):
        if a.get("fenAfter") != b.get("fenBefore"):
            breaks += 1
    if breaks:
        rep.error("facts", f"{breaks} discontinuity(ies): fenAfter != next fenBefore")

    # Evaluations are one series seen from both ends; a mismatch means a POV bug.
    eval_breaks = [
        a["ply"] for a, b in zip(plies, plies[1:])
        if a.get("evalAfterCp") is not None
        and b.get("evalBeforeCp") is not None
        and a["evalAfterCp"] != b["evalBeforeCp"]
    ]
    if eval_breaks:
        rep.error("facts", f"eval discontinuity at plies {eval_breaks[:6]}")

    illegal = [p["ply"] for p in plies if not _legal_fen(p.get("fenAfter"))]
    if illegal:
        rep.error("facts", f"illegal FEN at plies {illegal[:6]}")

    missing = [p["ply"] for p in plies if not p.get("san")]
    if missing:
        rep.error("facts", f"{len(missing)} plies with no SAN")


def _legal_fen(fen: Optional[str]) -> bool:
    if not fen:
        return False
    try:
        chess.Board(fen)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# pass 2 — the beat script
# ---------------------------------------------------------------------------


def check_script_structure(script: Dict[str, Any], pgn_path: Optional[Path], rep: Report) -> None:
    beats = script.get("beats") or []
    if not beats:
        rep.error("script", "no beats")
        return
    meta = script.get("meta") or {}
    kinds = collections.Counter(b["kind"] for b in beats)
    rep.info("script", f"{len(beats)} beats {dict(kinds)}")
    rep.info("script", f"narration={meta.get('narration')} channel={meta.get('channel')!r}")

    if meta.get("narration") != "llm":
        rep.error("script", f"narration is {meta.get('narration')!r}, not LLM — "
                            "an API failure degrades silently to templates")
    if not meta.get("llmTitle"):
        rep.warn("script", "no LLM title; the uploader will fall back")

    # Main line must reproduce the real game exactly.
    if pgn_path and pgn_path.exists():
        with pgn_path.open(encoding="utf-8", errors="ignore") as fh:
            game = chess.pgn.read_game(fh)
        if game:
            real = [m.uci() for m in game.mainline_moves()]
            shown = [
                chess.Move.from_uci(b["move"]["from"] + b["move"]["to"]).uci()
                for b in beats
                if b.get("move") and not b["branch"] and b["kind"] == "move"
            ]
            # Promotions carry a suffix in the PGN that from/to cannot express.
            same = len(real) == len(shown) and all(
                r.startswith(s) for r, s in zip(real, shown)
            )
            if not same:
                rep.error("script", f"main line does not match the PGN "
                                    f"({len(shown)} beats vs {len(real)} moves)")
            else:
                rep.info("script", f"main line matches the PGN ({len(real)} moves)")

    # A variation must be legal from its own starting position, and the game
    # must resume on the real board — the guarantee the whole design rests on.
    bad_branch, bad_resume = 0, 0
    for i, beat in enumerate(beats):
        if beat.get("branch") and beat.get("move"):
            if not _legal_fen(beat.get("fen")) or not _legal_fen(beat.get("prevFen")):
                bad_branch += 1
        if beat["kind"] == "resume":
            prev_real = next(
                (b for b in reversed(beats[:i]) if not b["branch"] and b.get("fen")), None
            )
            if prev_real and beat.get("fen") != prev_real["fen"]:
                bad_resume += 1
    if bad_branch:
        rep.error("script", f"{bad_branch} variation beats with an illegal FEN")
    if bad_resume:
        rep.error("script", f"{bad_resume} resume beats do not return to the real position")
    else:
        rep.info("script", f"all {kinds.get('resume', 0)} resumes return to the real board")


def check_board_directives(script: Dict[str, Any], rep: Report) -> None:
    beats = script.get("beats") or []
    edge_arrows, stale_arrows, off_board, no_slider = 0, 0, 0, []
    for beat in beats:
        board = chess.Board(beat["fen"]) if _legal_fen(beat.get("fen")) else None
        move = beat.get("move") or {}
        frm, to = move.get("from"), move.get("to")
        for arrow in beat.get("arrows") or []:
            a, b = arrow.get("from"), arrow.get("to")
            if not (a and b):
                off_board += 1
                continue
            # An arrow says "this piece attacks that one". If its origin is
            # empty, the geometry was computed against a different position
            # than the one on screen.
            if board and board.piece_at(chess.parse_square(a)) is None:
                no_slider.append(f"{beat['id']}:{a}->{b}")
            # A pin arrow runs attacker -> king *through* the pinned piece; that
            # is what a pin is, so one occupied square in between is expected.
            is_pin = (arrow.get("color") or "").lower() == "#b28cff"
            if board and not is_pin:
                # Otherwise an arrow must stop at the first piece on the line,
                # never run through it to the rim.
                between = chess.SquareSet(
                    chess.between(chess.parse_square(a), chess.parse_square(b))
                )
                if any(board.piece_at(s) for s in between):
                    edge_arrows += 1
            # And it must be about the move on screen.
            if frm and to:
                seg = {a, b} | {
                    chess.square_name(s) for s in chess.SquareSet(
                        chess.between(chess.parse_square(a), chess.parse_square(b))
                    )
                }
                if frm not in seg and to not in seg and beat["kind"] != "hold":
                    stale_arrows += 1
        for h in beat.get("highlights") or []:
            if not re.fullmatch(r"[a-h][1-8]", h.get("square") or ""):
                off_board += 1
    if edge_arrows:
        rep.error("arrows", f"{edge_arrows} arrow(s) pass through a piece "
                            "instead of stopping at it")
    if stale_arrows:
        rep.error("arrows", f"{stale_arrows} arrow(s) unrelated to the move on screen")
    if off_board:
        rep.error("arrows", f"{off_board} directive(s) with an invalid square")
    if no_slider:
        rep.error("arrows", f"{len(no_slider)} arrow(s) start from an empty square: "
                            f"{no_slider[:4]}")
    total = sum(len(b.get("arrows") or []) for b in beats)
    if not (edge_arrows or stale_arrows or off_board):
        rep.info("arrows", f"{total} arrows, all terminating on their target")


def check_narration(script: Dict[str, Any], facts: Dict[str, Any], rep: Report) -> None:
    beats = script.get("beats") or []
    by_ply = {p["ply"]: p for p in (facts.get("plies") or [])}

    for label, pattern in SPOKEN_BANS:
        hits = [b["id"] for b in beats if re.search(pattern, b["text"])]
        if hits:
            level = rep.error if label != "unverified claim" else rep.warn
            level("narration", f"{label} in {len(hits)} beat(s): {hits[:5]}")

    # "The king has to move" is only true when the engine says so.
    lies = []
    for beat in beats:
        # Only claims about a position we have facts for can be checked. An
        # outro summarising the whole game has no ply, and "it only moved once"
        # is not a claim about check evasions.
        if beat.get("ply") is None:
            continue
        ev = ((by_ply.get(beat["ply"]) or {}).get("features") or {}).get("checkEvasions")
        text = beat["text"].lower()
        if re.search(r"cannot block|can't block|no way to block", text):
            if not ev or ev.get("canBlock"):
                lies.append(beat["id"])
        # Word boundaries matter: "it only moved once" is not "the only move".
        if re.search(r"\bhas to move\b|\bmust move\b|\bforced to move\b|\bonly move\b", text):
            if not ev or not ev.get("onlyKingMoves"):
                lies.append(beat["id"])
    if lies:
        rep.error("narration", f"claim contradicts the engine in {sorted(set(lies))[:5]}")

    words = [len(b["text"].split()) for b in beats]
    rep.info("narration", f"{sum(words)} words; per beat min={min(words)} "
                          f"max={max(words)} mean={sum(words)/len(words):.0f}")
    # A script with no questions reads as a list, and the voice never lifts.
    questions = [b["id"] for b in beats if "?" in b["text"]]
    rep.info("narration", f"{len(questions)} beats ask a question")
    if len(questions) < 6:
        rep.error("narration", f"only {len(questions)} question(s) in the script; "
                               "the brief requires at least 6")
    holds = [b for b in beats if b["kind"] == "hold"]
    mute_holds = [b["id"] for b in holds if "?" not in b["text"]]
    if mute_holds:
        rep.warn("narration", f"{len(mute_holds)}/{len(holds)} hold beats ask nothing: "
                              f"{mute_holds[:4]}")

    # A spoken "pause and find it" must actually pause; the challenge without
    # the thinking time is worse than no challenge.
    cue = re.compile(r"pause (?:here|the video|for a moment|with me)|try to find|"
                     r"see if you can (?:find|spot)|ask yourself", re.I)
    unhonoured = [b["id"] for b in beats if cue.search(b["text"]) and not b.get("thinkPauseMs")]
    if unhonoured:
        rep.warn("narration", f"pause challenge with no inserted pause: {unhonoured[:3]}")

    # Repetition is the loudest tell that a script was generated.
    openings = collections.Counter(" ".join(b["text"].split()[:3]).lower() for b in beats)
    dupes = {k: v for k, v in openings.items() if v > 2 and k}
    if dupes:
        rep.warn("narration", f"repeated openings: "
                              f"{sorted(dupes.items(), key=lambda x: -x[1])[:3]}")
    for a, b in zip(beats, beats[1:]):
        if a["text"].strip() and a["text"].strip() == b["text"].strip():
            rep.error("narration", f"{a['id']} and {b['id']} are identical")


def check_paragraphs(script: Dict[str, Any], rep: Report) -> None:
    beats = script.get("beats") or []
    if any(b.get("para") is None for b in beats):
        rep.warn("paragraphs", "some beats carry no paragraph number")
        return
    groups = collections.OrderedDict()
    for b in beats:
        groups.setdefault(b["para"], []).append(b)
    # A take that ends mid-sentence is a voice that stops mid-thought.
    cut = [
        (p, v[-1]["id"]) for p, v in groups.items()
        if v[-1]["text"].rstrip() and not v[-1]["text"].rstrip().endswith(SENTENCE_END)
    ]
    if cut:
        rep.error("paragraphs", f"{len(cut)} take(s) end mid-sentence: {cut[:4]}")
    words = [sum(len(x["text"].split()) for x in v) for v in groups.values()]
    rep.info("paragraphs", f"{len(groups)} takes; words min={min(words)} "
                           f"max={max(words)} mean={sum(words)/len(words):.0f}")
    if max(words) > 260:
        rep.warn("paragraphs", f"largest take is {max(words)} words — one long TTS request")


def check_spoiler_free(script: Dict[str, Any], rep: Report) -> None:
    """Nothing on screen may describe a move the viewer has not seen played."""
    beats = script.get("beats") or []
    future = 0
    seen_max = 0
    for beat in beats:
        if beat.get("branch") or not beat.get("ply"):
            continue
        if beat["kind"] == "move" and beat.get("move"):
            seen_max = max(seen_max, beat["ply"])
        elif beat["ply"] > seen_max + 1:
            future += 1
    if future:
        rep.warn("spoilers", f"{future} beat(s) reference a ply beyond the board")


# ---------------------------------------------------------------------------
# pass 3 — voice
# ---------------------------------------------------------------------------


def check_audio(script: Dict[str, Any], manifest: Dict[str, Any], rep: Report) -> None:
    beats = script.get("beats") or []
    clips = manifest.get("clips") or {}
    rep.info("voice", f"backend={manifest.get('backend')} "
                      f"profile={manifest.get('voice')} clips={len(clips)}")

    if manifest.get("backend") not in ("ttsapi", "qwen", "elevenlabs"):
        rep.error("voice", f"backend {manifest.get('backend')!r} is a fallback, "
                           "not the channel voice")

    aligned = [c.get("aligned") for c in clips.values() if "aligned" in c]
    if aligned and not all(aligned):
        n = sum(1 for a in aligned if not a)
        rep.error("voice", f"{n}/{len(aligned)} clips used estimated word times, "
                           "not forced alignment — move cues will drift")
    elif aligned:
        rep.info("voice", f"all {len(aligned)} clips forced-aligned")

    missing = [b["id"] for b in beats if b.get("text") and b["id"] not in clips]
    if missing:
        rep.error("voice", f"{len(missing)} beats have text but no audio: {missing[:5]}")

    # Every chained slice must land on a frame boundary, or all later audio
    # drifts against the picture.
    off_grid, silent = [], []
    for beat in beats:
        clip = clips.get(beat["id"])
        if not clip:
            continue
        path = OUT / "audio" / clip["file"]
        if not path.exists():
            rep.error("voice", f"missing audio file {clip['file']}")
            continue
        if clip.get("chain"):
            with wave.open(str(path), "rb") as fh:
                frames = fh.getnframes()
                rate = fh.getframerate()
            if frames % (rate // FPS):
                off_grid.append(beat["id"])
        if int(clip.get("durationMs") or 0) <= 0:
            silent.append(beat["id"])
    if off_grid:
        rep.error("voice", f"{len(off_grid)} chained clip(s) not frame-aligned: {off_grid[:4]}")
    if silent:
        rep.error("voice", f"{len(silent)} zero-length clip(s): {silent[:4]}")

    chained = sum(1 for c in clips.values() if c.get("chain"))
    rep.info("voice", f"{chained}/{len(clips)} clips are continuous-take slices")

    # Pitch drifting between takes is heard as the narrator changing tone. It is
    # invisible in the data unless measured, so measure it.
    try:
        sys.path.insert(0, str(ROOT / "services" / "orchestrator"))
        from tts import _median_f0  # noqa: PLC0415

        groups: Dict[Any, List[str]] = collections.OrderedDict()
        for beat in beats:
            if clips.get(beat["id"]):
                groups.setdefault(beat.get("para"), []).append(beat["id"])
        # Reconstruct TAKES, not paragraphs: merging means several breath
        # groups share one synthesis request, and a take ends where a clip is
        # not chained. Both failure modes live here — take-to-take drift
        # (medians apart) and the seam step (a falling cadence into a fresh
        # attack), which is the one heard as the announcer being swapped.
        import tempfile

        take_files: List[Path] = []
        frames = b""
        params = None
        for beat in beats:
            clip = clips.get(beat["id"])
            if not clip:
                continue
            path = OUT / "audio" / clip["file"]
            if not path.exists():
                continue
            with wave.open(str(path), "rb") as fh:
                params = params or fh.getparams()
                frames += fh.readframes(fh.getnframes())
            if not clip.get("chain") and frames and params:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    joined = Path(tmp.name)
                with wave.open(str(joined), "wb") as fh:
                    fh.setparams(params)
                    fh.writeframes(frames)
                take_files.append(joined)
                frames = b""
        try:
            f0s = [f for f in (_median_f0(p) for p in take_files) if f]
            if len(f0s) >= 4:
                srt = sorted(f0s)
                mid = srt[len(srt) // 2]
                iqr = srt[int(len(srt) * 0.75)] - srt[int(len(srt) * 0.25)]
                rep.info("voice", f"pitch median {mid:.0f} Hz across {len(f0s)} takes "
                                  f"(IQR {iqr:.1f})")
                if iqr > 8:
                    rep.warn("voice", f"pitch IQR {iqr:.1f} Hz — take medians drift audibly")
            steps = []
            for a, b in zip(take_files, take_files[1:]):
                tail = _median_f0(a, -0.6)
                head = _median_f0(b, 0.0, 0.6)
                if tail and head:
                    steps.append(head - tail)
            if steps:
                steps_abs = sorted(steps, key=abs, reverse=True)
                med = sorted(steps)[len(steps) // 2]
                rep.info("voice", f"seam pitch step median {med:+.0f} Hz, "
                                  f"worst {steps_abs[0]:+.0f} across {len(steps)} seams")
                if abs(med) > 25 or abs(steps_abs[0]) > 45:
                    # Warning, not error, while the cause lives in the TTS
                    # service: it re-splits requests into ~450-char chunks and
                    # samples each independently, so the cure is a seed reset
                    # per chunk server-side, not anything this pipeline can gate
                    # on. Re-promote once the service fix lands.
                    rep.warn("voice", "seam steps this large are heard as a second "
                                      "announcer taking over")
        finally:
            for p in take_files:
                p.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass


def check_cues(script: Dict[str, Any], manifest: Dict[str, Any], rep: Report) -> None:
    beats = script.get("beats") or []
    clips = manifest.get("clips") or {}
    no_room, guessed, missing_word = [], [], []
    for beat in beats:
        if not beat.get("move"):
            continue
        dur = int(beat.get("durationMs") or 0)
        at = int(beat.get("moveAtMs") or 0)
        if at + MOVE_ANIM_MS > dur:
            no_room.append(beat["id"])
        clip = clips.get(beat["id"]) or {}
        heard = {w["w"] for w in clip.get("words") or []}
        cues = [c.lower() for c in (beat.get("moveCueWords") or [])]
        if cues and not (heard & set(cues)):
            missing_word.append(beat["id"])
        # The 22% fallback means no cue word was found at all.
        if dur and abs(at - int(dur * 0.22)) <= 1 and at > 0:
            guessed.append(beat["id"])
    if no_room:
        rep.error("cues", f"{len(no_room)} move(s) cannot finish animating: {no_room[:4]}")
    if missing_word:
        rep.warn("cues", f"{len(missing_word)} move(s) whose cue word was never "
                         f"heard in its clip: {missing_word[:4]}")
    if guessed:
        rep.warn("cues", f"{len(guessed)} move(s) fell back to a guessed cue time")
    moves = sum(1 for b in beats if b.get("move"))
    rep.info("cues", f"{moves - len(missing_word) - len(guessed)}/{moves} moves "
                     "cued on a measured word")


def check_mentions(script: Dict[str, Any], rep: Report) -> None:
    """A named square may only light up if that piece is really standing there."""
    beats = script.get("beats") or []
    wrong, total = [], 0
    for beat in beats:
        for m in beat.get("mentions") or []:
            total += 1
            at = int(m.get("atMs") or 0)
            move_at = int(beat.get("moveAtMs") or 0)
            fen = beat.get("fen") if (not beat.get("move") or at >= move_at) else beat.get("prevFen")
            if not _legal_fen(fen):
                wrong.append(beat["id"])
                continue
            piece = chess.Board(fen).piece_at(chess.parse_square(m["square"]))
            if piece is None:
                wrong.append(f"{beat['id']}:{m['square']}")
    if wrong:
        rep.error("mentions", f"{len(wrong)} highlight(s) on an empty/illegal square: {wrong[:4]}")
    else:
        rep.info("mentions", f"{total} spoken-mention highlights, all verified")


# ---------------------------------------------------------------------------
# pass 4 — the rendered file
# ---------------------------------------------------------------------------


def _ffprobe() -> Optional[str]:
    for candidate in ("ffprobe", "ffprobe.exe"):
        try:
            subprocess.run([candidate, "-version"], capture_output=True, check=True)
            return candidate
        except Exception:
            pass
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        hits = list(Path(local).glob("Microsoft/WinGet/Packages/*FFmpeg*/**/ffprobe.exe"))
        if hits:
            return str(hits[0])
    return None


def check_video(script: Dict[str, Any], rep: Report) -> None:
    if not VIDEO.exists():
        rep.error("video", "video.mp4 is missing")
        return
    size_mb = VIDEO.stat().st_size / 1e6
    expected_s = sum(b.get("durationMs") or 0 for b in script.get("beats") or []) / 1000
    rep.info("video", f"{size_mb:.1f} MB, script expects {expected_s/60:.1f} min")
    if not THUMB.exists():
        rep.warn("video", "thumbnail.png is missing")

    probe = _ffprobe()
    if not probe:
        rep.warn("video", "ffprobe unavailable — cannot verify duration or audio")
        return
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries",
             "stream=codec_type,duration:format=duration",
             "-of", "json", str(VIDEO)],
            capture_output=True, text=True, check=True,
        ).stdout
        data = json.loads(out)
    except Exception as exc:  # noqa: BLE001
        rep.warn("video", f"ffprobe failed ({exc})")
        return

    actual = float(data.get("format", {}).get("duration") or 0)
    kinds = {s.get("codec_type") for s in data.get("streams", [])}
    rep.info("video", f"container duration {actual/60:.1f} min, streams={sorted(kinds)}")
    if "audio" not in kinds:
        rep.error("video", "no audio stream in the render")
    if expected_s and abs(actual - expected_s) > 1.5:
        rep.error("video", f"duration {actual:.1f}s disagrees with the script "
                           f"{expected_s:.1f}s")


def sample_frames(script: Dict[str, Any], rep: Report) -> None:
    """Render the frames most likely to expose a rail or board bug."""
    beats = script.get("beats") or []
    picks: List[Tuple[str, int]] = []
    cursor = 0
    starts: Dict[str, int] = {}
    for beat in beats:
        starts[beat["id"]] = cursor
        cursor += max(1, round((beat.get("durationMs") or 0) * FPS / 1000))
    for beat in beats:
        f0 = starts[beat["id"]]
        cue = f0 + round((beat.get("moveAtMs") or 0) * FPS / 1000)
        if beat["kind"] == "resume":
            picks.append((f"resume-{beat['id']}", f0 + 12))
        elif beat.get("tag") in ("blunder", "brilliant"):
            picks.append((f"{beat['tag']}-{beat['id']}", cue + 18))
        elif beat.get("mentions"):
            m = beat["mentions"][0]
            picks.append((f"mention-{beat['id']}", f0 + round(m["atMs"] * FPS / 1000) + 8))
    picks = picks[:8]
    if not picks:
        return
    outdir = OUT / "verify_frames"
    outdir.mkdir(parents=True, exist_ok=True)
    # Clear first: beat ids repeat across games, so a leftover frame from the
    # previous render is indistinguishable from this one's and would be reviewed
    # as if it were current.
    for stale in outdir.glob("*.png"):
        stale.unlink(missing_ok=True)
    npm = "npm.cmd" if os.name == "nt" else "npm"
    for label, frame in picks:
        dest = outdir / f"{frame:06d}_{label}.png"
        try:
            subprocess.run(
                [npm, "exec", "--", "remotion", "still", "src/index.tsx", "ChessVideo",
                 str(dest), f"--frame={frame}", "--overwrite"],
                cwd=str(ROOT / "apps" / "renderer"),
                capture_output=True, check=True,
            )
        except Exception as exc:  # noqa: BLE001
            rep.warn("frames", f"could not render frame {frame} ({exc})")
            return
    rep.info("frames", f"{len(picks)} critical frames -> {outdir.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# pass 5 — what YouTube would receive
# ---------------------------------------------------------------------------


def check_metadata(script: Dict[str, Any], rep: Report) -> None:
    meta = script.get("meta") or {}
    title = (meta.get("llmTitle") or "").strip()
    hook = (meta.get("llmHook") or "").strip()
    if title:
        if len(title) > 100:
            rep.error("metadata", f"title is {len(title)} chars (YouTube allows 100)")
        elif len(title) > 90:
            rep.warn("metadata", f"title is {len(title)} chars — truncates in search")
        rep.info("metadata", f"title ({len(title)} chars): {title}")
        if re.search(r"\|\s*[A-Za-z ]+ \d{4}\s*$", title):
            rep.warn("metadata", "title ends in a venue/year suffix, which costs clicks")
    if hook and len(hook) < 40:
        rep.warn("metadata", "description hook is very short")


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit the current render")
    ap.add_argument("--script", default=str(OUT / "script.json"))
    ap.add_argument("--facts", default=str(OUT / "facts.json"))
    ap.add_argument("--manifest", default=str(OUT / "audio_manifest.json"))
    ap.add_argument("--pgn", default=None, help="PGN to diff the main line against")
    ap.add_argument("--frames", action="store_true", help="also render critical stills")
    ap.add_argument("--json", default=None, help="write the report as JSON")
    args = ap.parse_args()

    rep = Report()

    def load(path: str, label: str) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            rep.error(label, f"{p} not found")
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError as exc:
            rep.error(label, f"{p} is not valid JSON ({exc})")
            return {}

    facts = load(args.facts, "facts")
    script = load(args.script, "script")
    manifest = load(args.manifest, "voice")

    pgn = Path(args.pgn) if args.pgn else None
    if pgn is None:
        daily = sorted((OUT / "pgns" / "daily").glob("*.pgn"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        pgn = daily[0] if daily else None

    if facts:
        check_facts(facts, rep)
    if script:
        check_script_structure(script, pgn, rep)
        check_board_directives(script, rep)
        check_paragraphs(script, rep)
        check_spoiler_free(script, rep)
        check_metadata(script, rep)
        if facts:
            check_narration(script, facts, rep)
        if manifest:
            check_audio(script, manifest, rep)
            check_cues(script, manifest, rep)
        check_mentions(script, rep)
        check_video(script, rep)
        if args.frames:
            sample_frames(script, rep)

    # The synced copy is what actually rendered; a stale one means the video
    # does not match the script we just audited.
    pub = PUB / "script.json"
    if pub.exists() and script:
        try:
            if json.loads(pub.read_text(encoding="utf-8")) != script:
                rep.error("sync", "renderer/public/script.json differs from outputs/script.json "
                                  "— the video was built from different data")
        except ValueError:
            rep.error("sync", "renderer/public/script.json is not valid JSON")

    print(f"\nRender audit — {rep.errors} error(s), {rep.warns} warning(s)\n")
    print(rep.render())
    print()

    if args.json:
        Path(args.json).write_text(
            json.dumps([{"level": l, "section": s, "message": m} for l, s, m in rep.rows],
                       indent=2),
            encoding="utf-8",
        )
        print(f"report -> {args.json}\n")
    return rep.errors


if __name__ == "__main__":
    sys.exit(main())
