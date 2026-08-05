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
# Mirrors build_video.MIN_ARROW_DWELL_MS. Kept as its own number deliberately:
# the audit is meant to catch the build changing behaviour, which it cannot do
# if it imports the very constant it is checking.
MIN_ARROW_DWELL_MS = 1500
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
    #
    # A lower-case a-file square is read as the English article: transcribing
    # the synthesised audio, "a4" comes back as "a 4" while "A4" comes back as
    # "a4", the same as an explicit "ay four". The director capitalises these,
    # so any that survive to the script mean that pass did not run.
    ("un-capitalised a-file square", r"(?<![A-Za-z0-9])a[1-8](?![a-z0-9])"),
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
    defensive, flashed = [], []
    for beat in beats:
        board = chess.Board(beat["fen"]) if _legal_fen(beat.get("fen")) else None
        move = beat.get("move") or {}
        frm, to = move.get("from"), move.get("to")
        if beat.get("arrows") and beat.get("durationMs"):
            dwell = int(beat["durationMs"]) - int(beat.get("moveAtMs") or 0)
            if dwell < MIN_ARROW_DWELL_MS:
                flashed.append(f"{beat['id']}:{dwell}ms")
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
                # An arrow means "the move just played attacks that piece". If
                # it points *at* the square the mover landed on, it says the
                # opposite — the viewer reads a defensive warning where the
                # narration is describing an attack.
                #
                # Except for a pin, which by definition ends on the king. When
                # the king is what just moved, the pin ray legitimately lands
                # on it: Darga-Keres drew b3->g8 after Kg8 while the narration
                # said "the knight on d5 is now tied to that king by the
                # bishop on b3" — the arrow was illustrating the sentence.
                if b == to and not is_pin:
                    defensive.append(f"{beat['id']}:{a}->{b}")
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
    if defensive:
        rep.error("arrows", f"{len(defensive)} arrow(s) point at the piece that "
                            f"just moved instead of from it: {defensive[:4]}")
    if flashed:
        rep.error("arrows", f"{len(flashed)} arrow(s) on screen for under "
                            f"{MIN_ARROW_DWELL_MS}ms: {flashed[:4]}")
    total = sum(len(b.get("arrows") or []) for b in beats)
    if not (edge_arrows or stale_arrows or off_board or defensive or flashed):
        rep.info("arrows", f"{total} arrows, all offensive, all terminating on "
                           "their target with time to be read")


_EXCHANGE_VALUE = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 20000,
}


def _piece_can_be_saved_in_place(board: "chess.Board", square_name: str) -> bool:
    """True if the piece on this square can be kept safe WITHOUT moving it.

    That is exactly the refutation of "the piece must move": block the attack,
    capture the attacker with something else, or defend it — where defending
    only counts against attackers of equal or greater value. A bishop attacked
    by a pawn is not saved by a defender: the pawn takes it and comes out
    ahead whatever recaptures. The first version of this function did not know
    that, and convicted a correct narration on the strength of three
    "defences" that all lost a bishop for a pawn.
    """
    try:
        sq = chess.parse_square(square_name)
    except ValueError:
        return False
    piece = board.piece_at(sq)
    if piece is None:
        return False

    def safe(b: "chess.Board") -> bool:
        attackers = b.attackers(not piece.color, sq)
        if not attackers:
            return True
        if not b.attackers(piece.color, sq):
            return False
        cheapest = min(
            _EXCHANGE_VALUE[b.piece_at(a).piece_type] for a in attackers
        )
        return cheapest >= _EXCHANGE_VALUE[piece.piece_type]

    if safe(board):
        return True
    work = board.copy(stack=False)
    work.turn = piece.color
    for mv in work.legal_moves:
        if mv.from_square == sq:
            continue  # that IS moving it
        after = work.copy(stack=False)
        after.push(mv)
        if after.piece_at(sq) == piece and safe(after):
            return True
    return False


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
            # "The bishop on g6 must move" is a claim about a piece, not the
            # king, and it is checkable on the board: the claim is true only
            # if no other move keeps that piece safe. Caught live: a narration
            # said exactly this while Rh6, Nf8 and Ne5 all defended the bishop.
            pm = re.search(
                r"\b(queen|rook|bishop|knight|pawn)\b[^.!?]{0,40}?"
                r"\bon\s+([a-hA-H][1-8])\b[^.!?]{0,60}?"
                r"\b(?:must|has to|is forced to)\s+move\b",
                text)
            if pm:
                fen = beat.get("fen")
                if _legal_fen(fen) and _piece_can_be_saved_in_place(
                        chess.Board(fen), pm.group(2).lower()):
                    lies.append(beat["id"])
            elif not ev or not ev.get("onlyKingMoves"):
                lies.append(beat["id"])
    if lies:
        rep.error("narration", f"claim contradicts the engine in {sorted(set(lies))[:5]}")

    # "It can't recapture" is a legality claim, and legality is checkable.
    # Shipped live: "the d7 pawn is pinned against its own king, so it can't
    # do the recapturing" — spoken over a position where dxc6 was legal. A pin
    # forbids leaving the line, never capturing the pinner. Every spoken
    # impossibility about a capture is now checked against the move list; a
    # chess audience pauses the video for exactly this. Filed under its own
    # section because these errors block uploads, and the narration section
    # mixes fact checks with style checks that should not.
    cap_claim = re.compile(
        r"\b(?:can't|cannot|can ?not|no way to|unable to)\b[^.!?]{0,60}?"
        r"\b(?:recaptur\w*|captur\w*|take|takes|taking|taken)\b"
        # A quantified object is a different claim entirely: "cannot take
        # everything" says the offers outnumber the captures — true and good
        # commentary when four pieces hang at once — not that any one capture
        # is illegal. The gate held a correct video over exactly this.
        r"(?!\s+(?:everything|all\b|both\b|them\s+all\b|every\b))", re.I)
    piece_words = {"queen": chess.QUEEN, "rook": chess.ROOK, "bishop": chess.BISHOP,
                   "knight": chess.KNIGHT, "pawn": chess.PAWN, "king": chess.KING}
    for beat in beats:
        move = beat.get("move") or {}
        fen = beat.get("fen")
        if not move.get("to") or not _legal_fen(fen):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", beat["text"]):
            m = cap_claim.search(sentence)
            if not m:
                continue
            board = chess.Board(fen)
            target = chess.parse_square(move["to"])
            named = re.search(r"\b(queen|rook|bishop|knight|pawn|king)\b",
                              sentence[: m.start()], re.I)
            want = piece_words.get(named.group(1).lower()) if named else None
            for lm in board.legal_moves:
                if lm.to_square != target or not board.is_capture(lm):
                    continue
                p = board.piece_at(lm.from_square)
                if want is None or (p and p.piece_type == want):
                    rep.error(
                        "claims",
                        f"{beat['id']} says capturing on {move['to']} is "
                        f"impossible, but "
                        f"{board.san(lm)} is legal — the claim is false",
                    )
                    break
            break

    words = [len(b["text"].split()) for b in beats]
    rep.info("narration", f"{sum(words)} words; per beat min={min(words)} "
                          f"max={max(words)} mean={sum(words)/len(words):.0f}")
    # A script with no questions reads as a list, and the voice never lifts.
    questions = [b["id"] for b in beats if "?" in b["text"]]
    # Proportional, not absolute: a 50-ply blitz game has a third of the beats
    # of a long classic, and demanding the same count would push questions into
    # moves that do not warrant one. Roughly one per fifteen beats.
    floor = max(3, min(8, len(beats) // 15))
    rep.info("narration", f"{len(questions)} beats ask a question (floor {floor})")
    if len(questions) < floor:
        rep.error("narration", f"only {len(questions)} question(s) across {len(beats)} "
                               f"beats; expected at least {floor}")
    holds = [b for b in beats if b["kind"] == "hold"]
    mute_holds = [b["id"] for b in holds if "?" not in b["text"]]
    if mute_holds:
        rep.warn("narration", f"{len(mute_holds)}/{len(holds)} hold beats ask nothing: "
                              f"{mute_holds[:4]}")

    # A sentence opening "e6 ..." is spoken "six ..." — the synthesiser reads
    # e-then-digit as scientific notation and drops the letter, which names no
    # square at all. The director repairs these; if any survive, the commentary
    # ships factually wrong.
    swallowed = [
        b["id"] for b in beats
        if re.search(r"(?:^|(?<=[.!?])\s+)e[1-8](?![a-z0-9])", b["text"], re.I)
    ]
    if swallowed:
        rep.error("narration", f"sentence opens on an e-file square (the letter "
                               f"will be swallowed): {swallowed[:4]}")

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

    # Voice consistency. "A different announcer takes over" has three separate
    # causes, and a render has shipped with each of them while the audit
    # measured only the first: a PITCH step at a take seam, a LEVEL jump at a
    # take seam (b0010 opened +5 dB with perfectly normal pitch), and a beat
    # spoken far faster or louder than its surroundings. So all three are
    # measured, at the two granularities they live at — the seam, and the
    # beat against its neighbourhood — and every finding carries a timestamp,
    # because a warning nobody can locate in the video never gets checked.
    try:
        sys.path.insert(0, str(ROOT / "services" / "orchestrator"))
        from tts import _level_db, _median_f0  # noqa: PLC0415

        # Beat start times on the final timeline, for reporting.
        at_ms: Dict[str, int] = {}
        cursor = 0
        for beat in beats:
            at_ms[beat["id"]] = cursor
            cursor += int(beat.get("durationMs") or 0)

        def ts(beat_id: str) -> str:
            t = at_ms.get(beat_id, 0) // 1000
            return f"{t // 60}:{t % 60:02d}"

        # Reconstruct TAKES, not paragraphs: merging means several breath
        # groups share one synthesis request, and a take ends where a clip is
        # not chained.
        import tempfile

        take_files: List[Path] = []
        take_first: List[str] = []
        frames = b""
        params = None
        first_id: Optional[str] = None
        for beat in beats:
            clip = clips.get(beat["id"])
            if not clip:
                continue
            path = OUT / "audio" / clip["file"]
            if not path.exists():
                continue
            first_id = first_id or beat["id"]
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
                take_first.append(first_id)
                frames = b""
                first_id = None
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

            def edge_f0(path: Path, head: bool) -> Optional[float]:
                """Pitch at a take's edge, robust to unvoiced onsets.

                A 0.6 s window on an edge that opens with breath or a
                fricative holds almost no voiced frames, and a median over
                five misread frames once reported +180 Hz at a seam whose
                true step was +60. Widen until the measurement is grounded
                in at least a second and a half of actual voicing.
                """
                for dur in (1.5, 2.5, 4.0):
                    v = _median_f0(path, 0.0 if head else -dur, dur if head else None)
                    if v:
                        return v
                return None

            # --- seams: pitch AND level, each seam judged on both ----------
            bad_seams, seam_rows = [], []
            for i in range(1, len(take_files)):
                a, b = take_files[i - 1], take_files[i]
                p_tail, p_head = edge_f0(a, False), edge_f0(b, True)
                l_tail, l_head = _level_db(a, -1.5), _level_db(b, 0.0, 1.5)
                dp = (p_head - p_tail) if p_tail and p_head else 0.0
                dl = (l_head - l_tail) if l_tail is not None and l_head is not None else 0.0
                seam_rows.append((take_first[i], dp, dl))
                # One dimension far out, or two moderately out together — the
                # combination is what the ear sums into "someone else".
                if abs(dp) > 60 or abs(dl) > 5 or (abs(dp) > 40 and abs(dl) > 3):
                    bad_seams.append(f"{ts(take_first[i])} ({dp:+.0f} Hz, {dl:+.1f} dB)")
            if seam_rows:
                worst_p = max(seam_rows, key=lambda r: abs(r[1]))
                worst_l = max(seam_rows, key=lambda r: abs(r[2]))
                rep.info("voice", f"{len(seam_rows)} seams; worst pitch "
                                  f"{worst_p[1]:+.0f} Hz at {ts(worst_p[0])}, "
                                  f"worst level {worst_l[2]:+.1f} dB at {ts(worst_l[0])}")
            for s in bad_seams:
                rep.error("voice", f"seam at {s} will be heard as a new announcer")
            mild = [r for r in seam_rows
                    if (abs(r[1]) > 40 or abs(r[2]) > 3)
                    and f"{ts(r[0])}" not in " ".join(bad_seams)]
            for r in mild:
                rep.warn("voice", f"seam at {ts(r[0])} is noticeable "
                                  f"({r[1]:+.0f} Hz, {r[2]:+.1f} dB)")

            # --- beats against their neighbourhood -------------------------
            # The b0010 case: one beat +5 dB louder and a third faster than
            # everything around it, pitch normal, seam gates blind. Compare
            # each substantial beat with the beats near it in time.
            rows = []
            for beat in beats:
                clip = clips.get(beat["id"])
                if not clip:
                    continue
                path = OUT / "audio" / clip["file"]
                # Same floor as the pre-render check (tts.BEAT_MIN_MS): a
                # clip this short cannot be measured against its neighbours,
                # only mismeasured.
                from tts import BEAT_MIN_MS  # noqa: PLC0415
                if not path.exists() or int(clip.get("durationMs") or 0) < BEAT_MIN_MS:
                    continue
                words = len(clip.get("words") or [])
                lv = _level_db(path)
                f0 = _median_f0(path)
                wpm = words / (clip["durationMs"] / 60000) if words else 0.0
                rows.append((beat["id"], at_ms[beat["id"]], f0, lv, wpm, words))
            # One arithmetic, defined once in tts.py and shared with the
            # pre-render check — two renders were built and then held in one
            # day because the two stages judged beats differently.
            from tts import find_offvoice_beats  # noqa: PLC0415

            different_read, outlier_rows, cluster = find_offvoice_beats(rows)
            loud_fast = [bid for bid, _, _ in different_read]
            for bid, ddb, ratio in different_read:
                rep.error("voice", f"{bid} at {ts(bid)} is spoken "
                                   f"{ddb:+.1f} dB and {(ratio - 1) * 100:+.0f}% "
                                   "wpm against its surroundings — a different read")
            for bid, _at, what in outlier_rows:
                rep.warn("voice", f"{bid} at {ts(bid)} is noticeably {what} "
                                  "than its surroundings")
            # One odd beat is the synthesis breathing; a RUN of them is a
            # stretch of narration in a different voice, and a listener called
            # one "considerably off tune" while three consecutive warnings
            # scrolled past as advice.
            if cluster:
                rep.error("voice", f"{len(cluster)} off-voice beats within 30s "
                                   f"({', '.join(cluster)}) — a stretch a viewer "
                                   "will hear as a different narrator")
            if not bad_seams and not loud_fast and not mild:
                rep.info("voice", "no seam or beat stands out in pitch, level or pace")
        finally:
            for p in take_files:
                p.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        rep.warn("voice", f"consistency scan did not complete ({exc})")


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
            # A focus highlight ("aims at c4", "dreaming of c6") points at a
            # square that is often empty by design — the sentence is about
            # where a piece is going, not where one stands. Only occupancy
            # claims are required to have a piece on the square.
            if m.get("focus"):
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
    # Eight minutes is where a video can carry mid-roll ads, so it is worth
    # knowing when one lands short — but only as information. A short game
    # honestly told is the right outcome; padding it to clear a threshold is
    # not, and this must never read as a failure the build should have fixed.
    if expected_s < 8 * 60:
        rep.info("video", f"under the 8:00 mid-roll threshold by "
                          f"{(8 * 60 - expected_s) / 60:.1f} min — fine for a "
                          "short game, worth noting if it becomes the norm")
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


def _check_title_names(title: str, meta: Dict[str, Any], rep: Report) -> None:
    """A player must be named once, and by the name the channel settled on.

    "Robert James Bobby Fischer Threw Two Pawns Away" was published: the model
    wrote the PGN's formal name, and the expansion step added the familiar one
    in front of the surname instead of replacing what was already there. The
    audit had printed that title and passed it, because it only measured the
    length. A title is the one piece of text every viewer reads, so it gets
    checked like the board does.
    """
    for side in ("white", "black"):
        full = (meta.get(f"{side}Full") or "").strip()
        raw = (meta.get(side) or "").strip()
        surname = (full.split() or [""])[-1]
        if not surname or surname not in title:
            continue
        # Given names from the header that the title should NOT still carry —
        # anything the resolved name dropped.
        header_given = raw.partition(",")[2] if "," in raw else ""
        kept = {w.lower() for w in full.split()[:-1]}
        stale = [
            w for w in re.split(r"[\s.]+", header_given)
            if w and len(w) > 1 and w.lower() not in kept
        ]
        # Read the whole run of name-words in front of the surname, then ask
        # whether any of them is one the channel dropped. Matching only on
        # name-words keeps ordinary prose out of it: "James Watched as Bobby
        # Fischer" has "Watched as" in the way, so the run starts at Bobby.
        name_words = {w.lower() for w in stale} | kept
        if not name_words:
            continue
        alts = "|".join(
            re.escape(w) for w in sorted(name_words, key=len, reverse=True)
        )
        run = re.search(
            rf"(?<![\w'])((?:(?:{alts})\s+)+){re.escape(surname)}(?![\w])",
            title,
            re.IGNORECASE,
        )
        if run:
            found = {w.lower() for w in run.group(1).split()}
            extra = sorted(found & {w.lower() for w in stale})
            if extra:
                rep.error(
                    "metadata",
                    f"title calls him '{run.group(0)}' but the channel calls "
                    f"him '{full}' — {'/'.join(extra)} was left in front",
                )
        if len(re.findall(rf"(?<![\w']){re.escape(surname)}(?![\w])", title)) > 1:
            rep.warn("metadata", f"title says '{surname}' more than once")


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
        _check_title_names(title, meta, rep)
    if hook and len(hook) < 40:
        rep.warn("metadata", "description hook is very short")

    # Thumbnail overlay. There is no room on the card to absorb a long line,
    # so anything out of shape has to fall back to the template hook rather
    # than ship a picture with text running off the edge.
    thumb = (meta.get("llmThumb") or "").strip()
    if not thumb:
        rep.warn("metadata", "no model-written thumbnail line; using the generic template")
    else:
        words = thumb.split()
        lines = [ln for ln in thumb.splitlines() if ln.strip()]
        if len(words) > 6 or len(lines) != 2:
            rep.error("metadata",
                      f"thumbnail line is {len(words)} words on {len(lines)} line(s); "
                      "it will overflow the card")
        elif thumb != thumb.upper():
            rep.warn("metadata", "thumbnail line is not upper case")
        else:
            rep.info("metadata", "thumbnail: " + thumb.replace("\n", " / "))

    # Intro quotation. Never model-written, so the only thing to check is that
    # what shipped is really one of the curated entries — a quote that drifted
    # is a misattribution under a real person's name.
    sys.path.insert(0, str(ROOT / "apps" / "analyzer"))
    from chessbot_analyzer import quotes  # noqa: PLC0415

    quote = meta.get("quote") or {}
    if not quote.get("text"):
        rep.info("quote", "no intro quotation for this pairing")
    else:
        known = {t for texts in quotes.BY_PLAYER.values() for t in texts}
        known |= {t for _, t in quotes.GENERAL}
        if quote["text"] not in known:
            rep.error("quote", "intro quotation is not in the curated table — "
                               "it must never be generated")
        else:
            portrait = quote.get("portrait")
            if portrait and not (PUB / "portraits" / portrait).exists():
                rep.error("quote", f"quote portrait {portrait} is missing; "
                                   "the card will show a broken image")
            rep.info("quote", f"{quote['author']}"
                              f"{' (with portrait)' if portrait else ''}")


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
