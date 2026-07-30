"""Pass 2 — the director: turns an engine fact sheet into a narration beat script.

This is the module that fixes the hard problem in the old pipeline. Previously
the *game* was the timeline and narration was retrofitted onto it, which made
interleaving "what could have been better" variations nearly impossible: the
scene cursor and the audio cursor disagreed the moment a variation appeared.

Here the **script is the timeline**. A beat is one spoken sentence plus the
board directives that go with it, and every beat carries an explicit ``fen``.
A variation is just a run of beats with ``branch=True``; resuming the game is a
beat whose ``fen`` is the real position again. Nothing has to be rewound,
because nothing was ever a cursor.

Beat schema::

    {
      "id": "b0007",
      "kind": "intro|move|variation|resume|hold|outro",
      "text": "Karpov develops the king's knight to f6.",
      "prevFen": "...",          # board before this beat's move (drives animation)
      "fen": "...",              # board after this beat
      "move": {"from","to","san"} | None,
      "branch": false,           # true while inside a variation
      "label": "Better was Qb6", # banner shown during variations
      "highlights": [{"square":"d4","kind":"danger"}],
      "arrows": [{"from":"g7","to":"a1","color":"#f5c542"}],
      "checkSquare": null,
      "evalCp": 25,              # White POV, drives the eval bar
      "tag": "blunder",
      "ply": 12,
      "moveCueWords": ["f6"]     # animate the move when one of these is spoken
    }

Durations and cue times are filled in later by the TTS pass.
"""

from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import chess

from .utils.logging import get_logger

logger = get_logger(__name__)

PIECE_NAMES = {
    "pawn": "pawn",
    "knight": "knight",
    "bishop": "bishop",
    "rook": "rook",
    "queen": "queen",
    "king": "king",
}

# Arrow / highlight palette shared with the renderer.
COLOR_MOVE = "#5ac8fa"
COLOR_ALT = "#b28cff"
COLOR_DANGER = "#ff5d5d"
COLOR_GOOD = "#3ddc97"

# Pins and long diagonals stay true for many plies. Re-drawing them every ply
# leaves an arrow parked on screen; this is how long we wait before repeating
# the same arrow when it was not created by the move just played.
ARROW_COOLDOWN_PLIES = 14

# Good narration often describes a capture without naming the square — "Black
# recaptures with the c-pawn", "he grabs the queen". The verb is then the moment
# the move happens, and a far better animation cue than a blind fraction of the
# beat. Tried only after the destination square, which is always preferred.
CAPTURE_CUES = ("takes", "recaptures", "captures", "grabs", "takes.")

# Roughly how many spoken words each kind of beat should get. The board waits
# for the narrator — a beat's on-screen duration is however long its line takes
# to speak — so this table *is* the pacing of the video. "hold" beats are the
# ones that let the camera sit on a position while the plan gets explained.
WORD_BUDGET = {
    "intro": 45,
    "intro_second": 30,
    # The close carries the resignation reason, the payoff of the running
    # thread, and the sign-off — 40 words could only fit the sign-off.
    "outro": 70,
    "hold": 90,
    "hold_major": 130,
    "move_book": 8,
    "move_quiet": 12,
    "move_notable": 32,
    "move_critical": 45,
    "variation_first": 40,
    "variation_cont": 22,
    "variation_payoff": 30,
    "resume": 18,
}


def _clean(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip()
    if not v or set(v) <= {"?", "."}:
        return None
    return v


def _short_name(full: Optional[str]) -> str:
    """"Tal, Mihail" -> "Tal";  "Magnus Carlsen" -> "Carlsen"."""
    name = _clean(full)
    if not name:
        return "our player"
    if "," in name:
        return name.split(",")[0].strip()
    return name.split()[-1]


def _display_name(full: Optional[str]) -> str:
    """"Tal, Mihail" -> "Mihail Tal"."""
    name = _clean(full)
    if not name:
        return "Unknown"
    if "," in name:
        last, _, first = name.partition(",")
        return f"{first.strip()} {last.strip()}".strip()
    return name


def _year(date_header: Optional[str]) -> Optional[str]:
    d = _clean(date_header)
    if not d:
        return None
    m = re.match(r"(\d{4})", d)
    return m.group(1) if m else None


class Director:
    """Builds a narration beat script from a fact sheet."""

    def __init__(
        self,
        channel_name: str = "Nocturne Chess",
        *,
        seed: Optional[int] = None,
        max_variation_plies: int = 4,
        max_variations: int = 8,
        max_holds: int = 8,
    ) -> None:
        self.channel_name = channel_name
        self.rng = random.Random(seed)
        self.max_variation_plies = max_variation_plies
        self.max_variations = max_variations
        self.max_holds = max_holds
        self._counter = 0
        self._last_choice: Dict[str, int] = {}
        self._arrow_seen: Dict[str, int] = {}
        self._last_eval_bucket: Optional[str] = None

    def _pick(self, key: str, options: Sequence[str]) -> str:
        """Random phrasing that never repeats the previous pick for this key.

        Narration that reuses the same clause two moves running is the single
        biggest tell that a script was generated, so this matters.

        Tracks the chosen *index*, not the rendered string: the options here are
        already interpolated with the move, so "and then Nd1" and "and then c5"
        are different strings but the same phrasing.
        """
        if len(options) == 1:
            return options[0]
        previous = self._last_choice.get(key)
        indices = [i for i in range(len(options)) if i != previous] or list(range(len(options)))
        chosen = self.rng.choice(indices)
        self._last_choice[key] = chosen
        return options[chosen]

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def build_script(self, facts: Dict[str, Any]) -> Dict[str, Any]:
        meta = facts.get("meta", {}) or {}
        plies: List[Dict[str, Any]] = facts.get("plies", []) or []
        summary = facts.get("summary", {}) or {}
        key_by_ply = {km["ply"]: km for km in (facts.get("keyMoments") or [])}

        beats: List[Dict[str, Any]] = []
        self._counter = 0
        self._arrow_seen = {}
        self._last_eval_bucket = None
        holds_used = 0

        beats.extend(self._intro_beats(meta, facts))

        variations_used = 0
        holds_used = 0
        for ply in plies:
            key_moment = key_by_ply.get(ply["ply"])
            quality = ply.get("quality")
            critical = quality in ("blunder", "mistake", "brilliant", "great")

            # Set the scene *before* a decisive move: the board freezes and the
            # narrator gets a long line to explain what is at stake.
            if (
                holds_used < self.max_holds
                and critical
                and (ply.get("ply") or 0) > 8
            ):
                beats.append(self._hold_beat(ply, before=True, major=quality in ("blunder", "brilliant")))
                holds_used += 1

            beats.append(self._move_beat(ply, facts, key_moment))

            if variations_used >= self.max_variations:
                continue
            if not self._deserves_variation(ply, key_moment):
                continue

            quality = ply.get("quality")
            if quality in ("brilliant", "great") and ply.get("alternatives"):
                # Explain the brilliancy by refuting the natural alternative.
                var_beats = self._refutation_beats(ply)
            else:
                var_beats = self._variation_beats(ply)

            if var_beats:
                beats.extend(var_beats)
                beats.append(self._resume_beat(ply))
                variations_used += 1
                if holds_used < self.max_holds and quality in ("blunder", "brilliant"):
                    beats.append(self._hold_beat(ply, before=False, major=False))
                    holds_used += 1

        beats.extend(self._outro_beats(meta, summary, facts))
        self._assign_paragraphs(beats)

        return {
            "meta": {
                **meta,
                "channel": self.channel_name,
                "opening": facts.get("opening"),
            },
            "beats": beats,
        }

    # --------------------------- paragraphs ---------------------------

    PARA_TARGET_WORDS = 80

    def _assign_paragraphs(self, beats: List[Dict[str, Any]]) -> None:
        """Group contiguous beats into spoken paragraphs.

        A paragraph is one *breath group*: the whole thing is synthesized as a
        single TTS request, so the voice carries one intonation contour across
        it instead of restarting at every beat. That is what turns 123 clipped
        announcements into something that sounds like a person talking. The
        narrator LLM sees the same grouping and writes prose that flows across
        the beats inside a paragraph.

        Boundaries fall where a real pause belongs: around holds (the board
        freezes and the narrator settles in), when a variation branch begins,
        when the game resumes after one, and at the intro/outro cards. Inside
        those regions, beats chain until the word budget suggests a breath.
        """
        para = -1
        budget = 0
        prev_kind: Optional[str] = None
        prev_branch = False
        for beat in beats:
            kind = beat["kind"]
            branch = bool(beat.get("branch"))
            new = (
                para < 0
                or kind in ("hold", "outro")
                or prev_kind in ("hold",)
                or (kind == "intro") != (prev_kind == "intro")
                or (branch and not prev_branch)
                or (prev_kind == "resume")
                # The budget is a breath heuristic, and a variation run is one
                # thought — "the point is that after X, Y, and Z" reads as a
                # single sentence. Splitting it mid-run cut the voice off on a
                # comma and restarted it cold; a variation and its resume stay
                # in one take no matter the budget.
                or (
                    not branch
                    and kind != "resume"
                    and budget + int(beat.get("targetWords") or 12) > self.PARA_TARGET_WORDS
                )
            )
            if new:
                para += 1
                budget = 0
            beat["para"] = para
            budget += int(beat.get("targetWords") or 12)
            prev_kind, prev_branch = kind, branch

    # ------------------------------------------------------------------
    # beat construction
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        self._counter += 1
        return f"b{self._counter:04d}"

    def _beat(self, **kwargs: Any) -> Dict[str, Any]:
        beat = {
            "id": self._next_id(),
            "kind": "hold",
            "text": "",
            "prevFen": None,
            "fen": None,
            "move": None,
            "branch": False,
            "label": None,
            "highlights": [],
            "arrows": [],
            "checkSquare": None,
            "evalCp": None,
            "tag": None,
            "ply": None,
            "moveCueWords": [],
            "targetWords": WORD_BUDGET["move_quiet"],
        }
        beat.update(kwargs)
        return beat

    # -------------------------- intro / outro -------------------------

    def _intro_beats(self, meta: Dict[str, Any], facts: Dict[str, Any]) -> List[Dict[str, Any]]:
        start_fen = chess.STARTING_FEN
        plies = facts.get("plies") or []
        if plies:
            start_fen = plies[0].get("fenBefore") or start_fen

        white = _display_name(meta.get("white"))
        black = _display_name(meta.get("black"))
        event = _clean(meta.get("event"))
        year = _year(meta.get("date"))
        summary = facts.get("summary", {}) or {}
        opening = (facts.get("opening") or {}).get("name")

        hook_bits: List[str] = []
        if summary.get("sacrifices"):
            n = len(summary["sacrifices"])
            hook_bits.append("a game with a piece sacrifice" if n == 1 else f"a game with {n} sacrifices")
        elif summary.get("brilliancies"):
            hook_bits.append("a game with a truly beautiful idea")
        elif summary.get("blunders"):
            hook_bits.append("a game that turns on a single mistake")

        opener = self.rng.choice([
            "Today I prepared for you a game",
            "Today we look at a game",
            "Let me show you a game",
        ])
        line = f"{opener} between {white} and {black}"
        if year:
            line += f", played in {year}"
        line += "."
        if hook_bits:
            line += f" {hook_bits[0].capitalize()}."

        beats = [
            self._beat(
                kind="intro",
                text=line,
                prevFen=start_fen,
                fen=start_fen,
                evalCp=0,
                targetWords=WORD_BUDGET["intro"],
            )
        ]

        second_bits: List[str] = []
        if event:
            second_bits.append(f"The game comes from {event}")
        if opening:
            second_bits.append(f"On the board is the {opening}")
        if second_bits:
            beats.append(
                self._beat(
                    kind="intro",
                    text=". ".join(second_bits) + ". Let's begin.",
                    prevFen=start_fen,
                    fen=start_fen,
                    evalCp=0,
                    targetWords=WORD_BUDGET["intro_second"],
                )
            )
        return beats

    def _outro_beats(
        self, meta: Dict[str, Any], summary: Dict[str, Any], facts: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        plies = facts.get("plies") or []
        final_fen = plies[-1].get("fenAfter") if plies else chess.STARTING_FEN
        result = _clean(meta.get("result")) or "*"
        white = _display_name(meta.get("white"))
        black = _display_name(meta.get("black"))

        if result == "1-0":
            verdict = f"{white} takes the point."
        elif result == "0-1":
            verdict = f"{black} takes the point."
        elif result == "1/2-1/2":
            verdict = "The game is drawn."
        else:
            verdict = "And that is where our game leaves off."

        return [
            self._beat(
                kind="outro",
                text=(
                    f"{verdict} Thank you for watching. If you enjoyed this game, "
                    "a like really helps the channel, and I will see you in the next one."
                ),
                prevFen=final_fen,
                fen=final_fen,
                evalCp=plies[-1].get("evalAfterCp") if plies else 0,
                targetWords=WORD_BUDGET["outro"],
            )
        ]

    # ---------------------------- main line ---------------------------

    def _move_beat(
        self,
        ply: Dict[str, Any],
        facts: Dict[str, Any],
        key_moment: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        highlights, arrows = self._board_directives(ply)
        text = self._describe_move(ply, facts, key_moment)

        return self._beat(
            kind="move",
            text=text,
            prevFen=ply.get("fenBefore"),
            fen=ply.get("fenAfter"),
            move={"from": ply.get("from"), "to": ply.get("to"), "san": ply.get("san")},
            highlights=highlights,
            arrows=arrows,
            checkSquare=(ply.get("features") or {}).get("checkSquare"),
            evalCp=ply.get("evalAfterCp"),
            tag=ply.get("quality"),
            ply=ply.get("ply"),
            moveCueWords=self._cue_words(ply),
            targetWords=self._move_word_budget(ply, key_moment),
        )

    def _move_word_budget(
        self, ply: Dict[str, Any], key_moment: Optional[Dict[str, Any]]
    ) -> int:
        """How much airtime this move deserves.

        Opening theory gets a handful of words; the move that decides the game
        gets a paragraph. Uniform-length narration is the main thing that makes
        a generated script sound generated.
        """
        quality = ply.get("quality")
        if quality in ("blunder", "brilliant"):
            return WORD_BUDGET["move_critical"]
        if quality in ("mistake", "great") or key_moment:
            return WORD_BUDGET["move_notable"]
        if quality == "book" or (ply.get("ply") or 0) <= 8:
            return WORD_BUDGET["move_book"]
        return WORD_BUDGET["move_quiet"]

    def _cue_words(self, ply: Dict[str, Any]) -> List[str]:
        """Words whose utterance should trigger the piece animation.

        Order matters: the resolver takes the first of these it can find, so
        the most specific cue comes first.
        """
        words = []
        to_sq = ply.get("to")
        if to_sq:
            words.append(to_sq)
        piece = ply.get("pieceType")
        if piece and piece != "pawn":
            words.append(PIECE_NAMES.get(piece, piece))
        if ply.get("isCastle"):
            words.append("castles")
        if ply.get("isCapture"):
            words.extend(CAPTURE_CUES)
        return words

    # ---------------------------- variations --------------------------

    def _deserves_variation(self, ply: Dict[str, Any], key_moment: Optional[Dict[str, Any]]) -> bool:
        """Show a branch when it teaches something — an error, or a refutation."""
        quality = ply.get("quality")
        has_pv = bool(ply.get("bestPvSan"))

        # A missed forced mate is always worth showing.
        if ply.get("mateBefore") is not None and ply.get("mateAfter") is None and has_pv:
            return True
        if quality in ("blunder", "mistake"):
            return has_pv and not ply.get("playedBest")
        # A costly inaccuracy at a moment the engine flagged as important.
        if quality == "inaccuracy" and key_moment and has_pv and not ply.get("playedBest"):
            cp_loss = ply.get("cpLoss")
            return isinstance(cp_loss, (int, float)) and cp_loss >= 80
        # A brilliancy is worth explaining by showing what the alternative loses to.
        if quality in ("brilliant", "great") and ply.get("alternatives"):
            return True
        return False

    def _refutation_beats(self, ply: Dict[str, Any]) -> List[Dict[str, Any]]:
        """"If instead X, then…" — show why the runner-up move fails."""
        alts = ply.get("alternatives") or []
        if not alts:
            return []
        alt = alts[0]
        full_pv = list(alt.get("pvSan") or [])
        pv_san = full_pv[: self._variation_depth(ply.get("fenBefore") or "", full_pv)]
        if not pv_san:
            return []

        try:
            board = chess.Board(ply["fenBefore"])
        except Exception:
            return []

        label = f"If instead {pv_san[0]}"
        beats: List[Dict[str, Any]] = []
        for idx, san in enumerate(pv_san):
            prev_fen = board.fen()
            try:
                move = board.parse_san(san)
            except Exception:
                break
            spoken = self._spoken_san(san, board)
            frm = chess.square_name(move.from_square)
            to = chess.square_name(move.to_square)
            board.push(move)

            if idx == 0:
                text = self.rng.choice([
                    f"It is worth seeing why the natural {spoken} does not work.",
                    f"Suppose instead {spoken}.",
                    f"What happens after {spoken}?",
                ])
            else:
                text = self.rng.choice([
                    f"Then {spoken}",
                    f"There follows {spoken}",
                    f"Now {spoken}",
                ])

            beats.append(
                self._beat(
                    kind="variation",
                    text=text,
                    prevFen=prev_fen,
                    fen=board.fen(),
                    move={"from": frm, "to": to, "san": san},
                    branch=True,
                    label=label,
                    highlights=[{"square": frm, "kind": "alt"}, {"square": to, "kind": "alt"}],
                    checkSquare=self._check_square(board),
                    evalCp=self._alt_eval_cp(alt, ply),
                    ply=ply.get("ply"),
                    # A variation line is spoken the same way, so it needs
                    # the same verb fallback when the square is not named.
                    moveCueWords=([to] + list(CAPTURE_CUES) if "x" in san else [to]),
                )
            )

        if beats:
            verdict = self._refutation_verdict(alt, ply)
            beats[-1]["text"] = beats[-1]["text"].rstrip(".") + f", {verdict}"
        return beats

    def _refutation_verdict(self, alt: Dict[str, Any], ply: Dict[str, Any]) -> str:
        if alt.get("mate") is not None:
            return "and the attack crashes through"
        best = ply.get("evalBeforeCp")
        alt_cp = alt.get("cp")
        if isinstance(best, (int, float)) and isinstance(alt_cp, (int, float)):
            gap = abs(best - alt_cp) / 100.0
            if gap >= 4:
                return "and the position simply falls apart"
            if gap >= 2:
                return "and the advantage is gone"
        return "and the whole idea breaks down"

    def _alt_eval_cp(self, alt: Dict[str, Any], ply: Dict[str, Any]) -> Optional[int]:
        """Alternative-line eval, normalised to White POV."""
        cp = alt.get("cp")
        if not isinstance(cp, (int, float)):
            return ply.get("evalBeforeCp")
        # `cp` is from the POV of the side to move at the branch point.
        return int(cp) if ply.get("side") == "white" else -int(cp)

    def _variation_depth(self, fen_before: str, pv_san: List[str]) -> int:
        """How many plies of an engine line actually teach something.

        When the better move's point is the move itself — it defends, it
        develops, it simply avoids the mistake — playing four quiet engine
        moves afterwards is dead air. One move plus the payoff sentence tells
        the story. The line earns more length only when the continuation is
        the proof: checks, captures, a mate — the forcing sequence that shows
        WHY the move wins. Depth runs to the last forcing move we can show.
        """
        try:
            board = chess.Board(fen_before)
        except Exception:
            return 1
        depth = 1
        for idx, san in enumerate(pv_san[: self.max_variation_plies]):
            try:
                move = board.parse_san(san)
            except Exception:
                break
            forcing = board.is_capture(move) or "+" in san or "#" in san
            board.push(move)
            # Only a *connected* sequence extends the line: a forcing move may
            # follow at most one quiet setup move. An incidental trade four
            # quiet plies deep does not justify dragging the viewer through
            # the shuffling in between.
            if idx > 0 and forcing and (idx + 1) - depth <= 2:
                depth = idx + 1
        return depth

    def _variation_beats(self, ply: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Play out the engine's recommendation as a branch off the real game."""
        full_pv: List[str] = list(ply.get("bestPvSan") or [])
        pv_san = full_pv[: self._variation_depth(ply.get("fenBefore") or "", full_pv)]
        if not pv_san:
            return []

        try:
            board = chess.Board(ply["fenBefore"])
        except Exception:
            logger.warning("variation skipped: bad fenBefore at ply %s", ply.get("ply"))
            return []

        best_san = pv_san[0]
        label = f"Better was {best_san}"
        beats: List[Dict[str, Any]] = []

        opener = self._pick("var_open", [
            f"Much stronger here was {self._spoken_san(best_san, board)}.",
            f"Instead, {self._spoken_san(best_san, board)} was the move.",
            f"The engine points to {self._spoken_san(best_san, board)} here.",
            f"Far better was {self._spoken_san(best_san, board)}.",
        ])

        for idx, san in enumerate(pv_san):
            prev_fen = board.fen()
            try:
                move = board.parse_san(san)
            except Exception:
                break
            spoken = self._spoken_san(san, board)
            frm = chess.square_name(move.from_square)
            to = chess.square_name(move.to_square)
            board.push(move)

            if idx == 0:
                text = opener
            elif idx == 1:
                text = self._pick("var_reply", [
                    f"The point is that after {spoken},",
                    f"The reply would be {spoken},",
                    f"Play might continue {spoken},",
                ])
            else:
                text = self._pick("var_cont", [
                    f"and then {spoken}",
                    f"followed by {spoken}",
                    f"and now {spoken}",
                ]) + "."

            beats.append(
                self._beat(
                    kind="variation",
                    text=text,
                    prevFen=prev_fen,
                    fen=board.fen(),
                    move={"from": frm, "to": to, "san": san},
                    branch=True,
                    label=label,
                    highlights=[
                        {"square": frm, "kind": "alt"},
                        {"square": to, "kind": "alt"},
                    ],
                    checkSquare=self._check_square(board),
                    evalCp=self._pv_eval_cp(ply),
                    ply=ply.get("ply"),
                    # A variation line is spoken the same way, so it needs
                    # the same verb fallback when the square is not named.
                    moveCueWords=([to] + list(CAPTURE_CUES) if "x" in san else [to]),
                    targetWords=WORD_BUDGET["variation_first" if idx == 0 else "variation_cont"],
                )
            )

        if beats:
            # Explain the payoff on the last branch beat.
            payoff = self._variation_payoff(ply)
            if payoff:
                beats[-1]["text"] = beats[-1]["text"].rstrip(".") + f", {payoff}"
        return beats

    def _variation_payoff(self, ply: Dict[str, Any]) -> Optional[str]:
        cp_loss = ply.get("cpLoss")
        if ply.get("mateBefore") is not None:
            return "with a forced mate to follow"
        if isinstance(cp_loss, (int, float)):
            pawns = abs(cp_loss) / 100.0
            if pawns >= 5:
                return "and the position is simply winning"
            if pawns >= 2.5:
                return f"which is worth about {pawns:.0f} pawns more"
            if pawns >= 1:
                return "keeping a clear advantage"
        return "with a much healthier position"

    def _pv_eval_cp(self, ply: Dict[str, Any]) -> Optional[int]:
        """Eval of the engine's best line, White POV."""
        before = ply.get("evalBeforeCp")
        return before if isinstance(before, int) else None

    def _hold_beat(
        self,
        ply: Dict[str, Any],
        *,
        before: bool,
        major: bool = False,
    ) -> Dict[str, Any]:
        """A pause on the position — the narrator talks, nothing moves.

        This is what lets the video spend ninety seconds on one position. The
        beat carries no move, so the board simply holds while the line is
        spoken; highlights and arrows still render, so the commentary can point
        at what it is describing.
        """
        fen = ply.get("fenBefore") if before else ply.get("fenAfter")
        features = ply.get("features") or {}
        if before:
            # A setup hold shows the board as it stands BEFORE the move, but the
            # fact sheet's features describe the position after it. Drawing them
            # here puts the future board's geometry on the present one: rays
            # whose slider has not arrived yet (so the arrow starts from an empty
            # square), blockers in the wrong places, pieces marked as hanging
            # that are not hanging until the move is played. Nothing derived
            # from those features is safe on this position, so the hold points
            # at nothing and lets the narration — and the verified spoken-mention
            # highlights, which are checked against the board actually shown —
            # carry it.
            highlights, arrows = [], []
        else:
            highlights, arrows = self._board_directives(ply)

        opener = (
            self._pick("hold_before", [
                "Before we see what happened, take in this position.",
                "Let's pause here, because this is the critical moment.",
                "Stop the clock for a second and look at what both sides want.",
            ])
            if before
            else self._pick("hold_after", [
                "Let's take stock of what just changed.",
                "It is worth sitting with this position for a moment.",
                "Look at what that move has done to the structure.",
            ])
        )
        text = " ".join([opener] + self._position_reading(ply, features, before))

        return self._beat(
            kind="hold",
            text=text,
            prevFen=fen,
            fen=fen,
            highlights=highlights,
            arrows=arrows,
            checkSquare=features.get("checkSquare") if not before else None,
            evalCp=ply.get("evalBeforeCp") if before else ply.get("evalAfterCp"),
            ply=ply.get("ply"),
            targetWords=WORD_BUDGET["hold_major" if major else "hold"],
        )

    def _position_reading(
        self, ply: Dict[str, Any], features: Dict[str, Any], before: bool
    ) -> List[str]:
        """Several sentences of substance for a hold beat, built from the facts.

        Without this the template narrator answers a 90-word budget with a
        12-word line and the pause looks like dead air. The LLM will write this
        far better, but the pipeline has to stand on its own without an API key.
        """
        out: List[str] = []

        cp = ply.get("evalBeforeCp") if before else ply.get("evalAfterCp")
        if isinstance(cp, (int, float)):
            pawns = cp / 100.0
            if abs(pawns) < 0.4:
                out.append("Materially and positionally this is close to level.")
            else:
                side = "White" if pawns > 0 else "Black"
                margin = abs(pawns)
                if margin > 3:
                    out.append(f"{side} is winning here, and by some distance.")
                elif margin > 1.2:
                    out.append(f"{side} holds a clear advantage.")
                else:
                    out.append(f"{side} is a little better, though nothing is decided.")

        material = features.get("material") or {}
        balance = material.get("balancePawns")
        if isinstance(balance, (int, float)) and abs(balance) >= 1:
            leader = "White" if balance > 0 else "Black"
            out.append(f"{leader} is up material, worth about {abs(balance):.0f} pawns.")

        for pin in (features.get("pins") or [])[:1]:
            if pin.get("pinned"):
                out.append(
                    f"The {pin.get('pinnedPiece') or 'piece'} on {pin['pinned']} is pinned "
                    "and cannot step aside."
                )

        for ray in sorted(features.get("longRays") or [], key=lambda r: -int(r.get("length") or 0))[:1]:
            if int(ray.get("length") or 0) >= 4 and ray.get("hits"):
                hit = ray["hits"][0]
                out.append(
                    f"Watch the {ray.get('piece')} on {ray.get('from')}, cutting all the way "
                    f"across to the {hit.get('piece')} on {hit.get('square')}."
                )

        hanging = [h for h in (features.get("hanging") or []) if h.get("piece") != "pawn"][:1]
        for hang in hanging:
            out.append(f"The {hang.get('piece')} on {hang.get('square')} has no defender.")

        safety = features.get("kingSafety") or {}
        for side_name in ("white", "black"):
            info = safety.get(side_name) or {}
            if info.get("attackersNearKing", 0) >= 3:
                out.append(f"{side_name.capitalize()}'s king is starting to feel the draught.")
                break

        structure = features.get("pawnStructure") or {}
        for side_name in ("white", "black"):
            isolated = (structure.get("isolated") or {}).get(side_name) or []
            if isolated:
                out.append(
                    f"{side_name.capitalize()} has an isolated pawn on {isolated[0]} "
                    "that will need watching in an endgame."
                )
                break

        if features.get("bishopPair"):
            out.append(f"{features['bishopPair'].capitalize()} owns the two bishops.")

        if before:
            out.append("Keep that in mind, because what comes next changes the picture.")
        return out[:6]

    def _resume_beat(self, ply: Dict[str, Any]) -> Dict[str, Any]:
        """Return the board to the real game after a variation."""
        san = ply.get("san") or "the move"
        text = self._pick("resume", [
            f"But in the game, {san} was played.",
            f"In the game, however, we saw {san}.",
            f"Back to the game, where {san} appeared on the board.",
            f"That is not what happened. In the game it was {san}.",
        ])
        return self._beat(
            kind="resume",
            text=text,
            prevFen=ply.get("fenAfter"),
            fen=ply.get("fenAfter"),
            highlights=[
                {"square": ply.get("from"), "kind": "move"},
                {"square": ply.get("to"), "kind": "move"},
            ],
            checkSquare=(ply.get("features") or {}).get("checkSquare"),
            evalCp=ply.get("evalAfterCp"),
            ply=ply.get("ply"),
            targetWords=WORD_BUDGET["resume"],
        )

    # ------------------------------------------------------------------
    # board directives
    # ------------------------------------------------------------------

    def _board_directives(self, ply: Dict[str, Any]):
        """Pick the few visuals that matter for this move — never clutter."""
        features = ply.get("features") or {}
        highlights: List[Dict[str, str]] = []
        arrows: List[Dict[str, str]] = []

        frm, to = ply.get("from"), ply.get("to")
        if frm:
            highlights.append({"square": frm, "kind": "move"})
        if to:
            highlights.append({"square": to, "kind": "danger" if ply.get("isCapture") else "move"})

        ply_idx = int(ply.get("ply") or 0)

        # Features like pins and long diagonals persist for many plies, so the
        # raw fact sheet reports them again on every subsequent move. Drawing
        # them each time leaves an arrow sitting on screen for a dozen beats.
        # Show one when it *becomes* true — the piece just landed there — and
        # otherwise only after a cooldown.
        def may_draw(key: str, created_now: bool) -> bool:
            last = self._arrow_seen.get(key)
            if created_now or last is None or (ply_idx - last) >= ARROW_COOLDOWN_PLIES:
                self._arrow_seen[key] = ply_idx
                return True
            return False

        def move_touches(*squares: Optional[str]) -> bool:
            """Did the move just played change anything on this line?

            An arrow is a statement about the move on screen. Drawing a line
            the move had nothing to do with — a queen's diagonal, moments
            after a knight recaptured elsewhere — reads as a non sequitur, so
            a feature only earns an arrow when the move created, opened or
            landed on it.
            """
            live = {s for s in squares if s}
            return bool(live & {frm, to})

        # A pin is the single most narratable feature — show the ray.
        for pin in (features.get("pins") or [])[:1]:
            pinned, attacker, king = pin.get("pinned"), pin.get("attacker"), pin.get("king")
            if not (attacker and king):
                continue
            # The pin must be this move's doing: the pinner arrived, the pinned
            # piece stepped onto the line, or the king moved onto it.
            if not move_touches(attacker, pinned, king):
                continue
            if not may_draw(f"pin:{attacker}->{king}", attacker == to):
                continue
            if pinned:
                highlights.append({"square": pinned, "kind": "alt"})
            arrows.append({"from": attacker, "to": king, "color": COLOR_ALT})

        # The "bishop shoots across the position" visual: a long open ray that
        # actually hits something.
        if len(arrows) < 2:
            for ray in sorted(
                features.get("longRays") or [], key=lambda r: -int(r.get("length") or 0)
            ):
                if int(ray.get("length") or 0) < 4 or not ray.get("hits"):
                    continue
                origin = ray.get("from")
                path = ray.get("ray") or []
                hit = ray["hits"][0]
                target = hit.get("square")
                if not origin or not path or not target:
                    continue
                # Point at the piece under attack, not at the board edge. The
                # ray runs to the edge geometrically, but drawing that far sends
                # the arrow straight through the very piece it is about to hit.
                #
                # And only when this move is the reason the line matters: the
                # slider landed on it, the target stepped into it, or the move
                # vacated a square that was blocking it.
                if not move_touches(origin, target, *path[: path.index(target) + 1]):
                    continue
                if not may_draw(f"ray:{origin}->{target}", origin == to):
                    continue
                arrows.append({"from": origin, "to": target, "color": COLOR_MOVE})
                highlights.append({"square": target, "kind": "danger"})
                break

        # Hanging material belonging to the side that just moved.
        mover = ply.get("side")
        for hang in (features.get("hanging") or [])[:2]:
            if hang.get("color") == mover and hang.get("square") not in {h["square"] for h in highlights}:
                highlights.append({"square": hang["square"], "kind": "danger"})

        # Forks are worth pointing at explicitly.
        for fork in (features.get("forks") or [])[:1]:
            if fork.get("square"):
                highlights.append({"square": fork["square"], "kind": "good"})
            for target in (fork.get("targets") or [])[:2]:
                if target.get("square"):
                    highlights.append({"square": target["square"], "kind": "danger"})

        # De-duplicate, keep it readable.
        seen = set()
        deduped = []
        for h in highlights:
            sq = h.get("square")
            if not sq or sq in seen:
                continue
            seen.add(sq)
            deduped.append(h)
        return deduped[:6], arrows[:2]

    def _check_square(self, board: chess.Board) -> Optional[str]:
        if not board.is_check():
            return None
        king_sq = board.king(board.turn)
        return chess.square_name(king_sq) if king_sq is not None else None

    # ------------------------------------------------------------------
    # narration text (template mode)
    # ------------------------------------------------------------------

    def _spoken_san(self, san: str, board: Optional[chess.Board] = None) -> str:
        """Turn SAN into words a narrator would actually say."""
        if not san:
            return san
        if san.startswith("O-O-O") or san.startswith("0-0-0"):
            return "castles queenside"
        if san.startswith("O-O") or san.startswith("0-0"):
            return "castles kingside"

        core = san.replace("!", "").replace("?", "")
        is_mate = core.endswith("#")
        is_check = core.endswith("+")
        core = core.rstrip("#+")

        promo = None
        if "=" in core:
            core, _, promo_ch = core.partition("=")
            promo = {"Q": "queen", "R": "rook", "B": "bishop", "N": "knight"}.get(promo_ch[:1])

        letters = {"K": "king", "Q": "queen", "R": "rook", "B": "bishop", "N": "knight"}
        piece = letters.get(core[0]) if core and core[0] in letters else "pawn"
        body = core[1:] if piece != "pawn" else core

        captures = "x" in body
        dest = body.split("x")[-1] if captures else body
        dest = dest[-2:] if len(dest) >= 2 else dest

        if captures:
            phrase = f"{piece} takes {dest}"
        else:
            phrase = f"{piece} to {dest}" if piece != "pawn" else dest

        if promo:
            phrase += f", promoting to a {promo}"
        if is_mate:
            phrase += ", checkmate"
        elif is_check:
            phrase += ", check"
        return phrase

    def _describe_move(
        self,
        ply: Dict[str, Any],
        facts: Dict[str, Any],
        key_moment: Optional[Dict[str, Any]],
    ) -> str:
        features = ply.get("features") or {}
        side = ply.get("side", "white")
        meta = facts.get("meta", {}) or {}
        surname = _short_name(meta.get("white") if side == "white" else meta.get("black"))
        spoken = self._spoken_san(ply.get("san", ""))
        quality = ply.get("quality")
        parts: List[str] = []

        intent = self._move_intent(ply, features)
        parts.append(self._move_sentence(surname, side, spoken, intent))

        # --- quality commentary ---
        # Only the big moments always earn a remark. Commenting on every single
        # inaccuracy is what makes a script feel like a machine reading a table.
        remark: Optional[str] = None
        if quality == "blunder":
            remark = self._pick("blunder", [
                "And this is the mistake that decides the game",
                "But this is a serious error",
                "This one throws the position away",
                "And just like that, everything changes",
            ])
        elif quality == "mistake":
            remark = self._pick("mistake", [
                "This is not the most precise",
                "But there was something much better here",
                "A real error, and the position starts to slide",
            ])
        elif quality == "brilliant":
            remark = self._pick("brilliant", [
                "And this is a wonderful idea",
                "A brilliant move, and the whole point of the game",
                "This is the move worth remembering",
            ])
        elif quality == "great":
            remark = self._pick("great_remark", [
                "A strong practical choice",
                "Exactly the right idea",
                "Precise, and not easy to find",
            ])
        elif quality == "inaccuracy" and self.rng.random() < 0.3:
            remark = self._pick("inaccuracy", [
                "A small imprecision",
                "Slightly loose, though nothing fatal",
                "Not quite the most testing",
            ])
        if remark:
            parts.append(remark)

        if ply.get("isSacrifice"):
            parts[0] = parts[0].rstrip(".") + ", giving up material for the initiative"

        # --- tactical observations from the fact sheet ---
        parts.extend(self._tactical_observations(ply, features))

        # --- eval commentary, only when the assessment actually changed ---
        verdict = self._eval_sentence(ply)
        if verdict:
            bucket = self._eval_bucket(ply)
            important = bool(key_moment) or quality in ("blunder", "mistake", "brilliant")
            if bucket != self._last_eval_bucket and (important or self.rng.random() < 0.55):
                parts.append(verdict)
                self._last_eval_bucket = bucket
            elif important and self.rng.random() < 0.4:
                parts.append(verdict)

        sentences = []
        for part in parts:
            clean = (part or "").strip().rstrip(".")
            if not clean:
                continue
            # Don't capitalise a leading square name — "e5" must not become "E5".
            if not re.match(r"^[a-h][1-8]\b", clean):
                clean = clean[0].upper() + clean[1:]
            sentences.append(clean)
        return ". ".join(sentences) + "."

    def _move_sentence(
        self, surname: str, side: str, spoken: str, intent: Optional[str]
    ) -> str:
        """The move announcement, varied in *shape* rather than just wording.

        Swapping the verb inside one fixed sentence pattern still reads as a
        machine: "X replies with a, X replies with b". Real commentary varies
        the whole construction, and often drops the player's name entirely
        because it is obvious whose turn it is.
        """
        colour = "White" if side == "white" else "Black"
        subject = self._pick("subject", [surname, surname, colour, ""])

        if intent:
            if subject:
                forms = [
                    f"{subject} plays {spoken}, {intent}",
                    f"{subject} goes {spoken}, {intent}",
                    f"{spoken} from {subject}, {intent}",
                ]
            else:
                forms = [
                    f"{spoken}, {intent}",
                    f"Now {spoken}, {intent}",
                    f"Then {spoken}, {intent}",
                ]
            return self._pick("form_intent", forms)

        if subject:
            forms = [
                f"{subject} plays {spoken}",
                f"{subject} answers {spoken}",
                f"{subject} continues {spoken}",
                f"The reply is {spoken}",
                f"{spoken} from {subject}",
            ]
        else:
            forms = [
                f"{spoken}",
                f"Now {spoken}",
                f"Then {spoken}",
                f"In reply, {spoken}",
            ]
        return self._pick("form_plain", forms)

    def _eval_bucket(self, ply: Dict[str, Any]) -> str:
        """Coarse assessment band, so we only speak when the verdict changes."""
        if ply.get("mateAfter") is not None:
            return "mate"
        cp = ply.get("evalAfterCp")
        if not isinstance(cp, (int, float)):
            return "unknown"
        pawns = cp / 100.0
        for edge, name in ((4, "white_winning"), (2, "white_big"), (0.8, "white_clear"),
                           (0.3, "white_edge")):
            if pawns > edge:
                return name
        for edge, name in ((-4, "black_winning"), (-2, "black_big"), (-0.8, "black_clear"),
                           (-0.3, "black_edge")):
            if pawns < edge:
                return name
        return "level"

    def _move_intent(self, ply: Dict[str, Any], features: Dict[str, Any]) -> Optional[str]:
        """A short clause explaining what the move is trying to do."""
        san = ply.get("san") or ""
        piece = ply.get("pieceType")
        to = ply.get("to") or ""
        ply_no = ply.get("ply") or 0

        if ply.get("isCastle"):
            return "tucking the king away into safety"
        if ply.get("isMate"):
            return "and that is checkmate"
        if ply.get("promotion"):
            return "and a new queen arrives on the board"

        if ply_no <= 6 and piece == "pawn" and to in ("e4", "d4", "e5", "d5"):
            return self._pick("intent_centre", [
                "taking a share of the centre",
                "staking a claim in the middle",
                "grabbing central space",
            ])
        if ply_no <= 12 and piece in ("knight", "bishop"):
            if to in ("f3", "c3", "f6", "c6"):
                return self._pick("intent_dev", [
                    "developing naturally",
                    "a normal developing move",
                    "bringing the piece to its best square",
                ])
            if to in ("g2", "b2", "g7", "b7"):
                return "fianchettoing the bishop onto the long diagonal"
            return self._pick("intent_dev2", [
                "bringing another piece into the game",
                "adding a piece to the attack",
                "completing development",
            ])
        if piece == "rook" and to and to[0] in ("d", "e"):
            return "bringing the rook to a central file"
        if ply.get("isCheck"):
            return self._pick("intent_check", [
                "with check, and the king must respond",
                "with check",
                "forcing the king to move",
            ])
        if ply.get("isCapture"):
            captured = ply.get("capturedPiece")
            if captured and captured != "pawn":
                return self._pick("intent_capture", [
                    f"removing the {captured}",
                    f"taking the {captured} off the board",
                ])
            return None
        return None

    def _tactical_observations(self, ply: Dict[str, Any], features: Dict[str, Any]) -> List[str]:
        out: List[str] = []

        for pin in (features.get("pins") or [])[:1]:
            pinned_piece = pin.get("pinnedPiece") or "piece"
            pinned_sq = pin.get("pinned")
            if pinned_sq:
                out.append(f"Notice the {pinned_piece} on {pinned_sq} is pinned and cannot move")

        for ray in sorted(features.get("longRays") or [], key=lambda r: -int(r.get("length") or 0))[:1]:
            if int(ray.get("length") or 0) >= 4 and ray.get("hits"):
                hit = ray["hits"][0]
                piece = ray.get("piece") or "bishop"
                out.append(
                    f"The {piece} on {ray.get('from')} shoots right across the board, "
                    f"hitting the {hit.get('piece')} on {hit.get('square')}"
                )

        for fork in (features.get("forks") or [])[:1]:
            targets = fork.get("targets") or []
            if len(targets) >= 2:
                out.append(
                    f"The {fork.get('piece')} on {fork.get('square')} forks "
                    f"{targets[0].get('square')} and {targets[1].get('square')}"
                )

        mover = ply.get("side")
        for hang in (features.get("hanging") or [])[:1]:
            if hang.get("color") != mover and hang.get("piece") != "pawn":
                out.append(f"The {hang.get('piece')} on {hang.get('square')} is left hanging")

        structure = features.get("pawnStructure") or {}
        isolated = (structure.get("isolated") or {}).get(mover or "white") or []
        if isolated and (ply.get("ply") or 0) < 24 and self.rng.random() < 0.5:
            out.append(f"That leaves an isolated pawn on {isolated[0]}")

        if features.get("bishopPair") and self.rng.random() < 0.3:
            side = features["bishopPair"]
            out.append(f"{side.capitalize()} holds the advantage of the two bishops")

        return out[:2]

    def _eval_sentence(self, ply: Dict[str, Any]) -> Optional[str]:
        mate = ply.get("mateAfter")
        if mate is not None:
            side = "White" if mate > 0 else "Black"
            return f"{side} now has mate in {abs(int(mate))}"

        cp = ply.get("evalAfterCp")
        if not isinstance(cp, (int, float)):
            return None
        pawns = cp / 100.0
        if pawns > 4:
            return "White is completely winning"
        if pawns > 2:
            return "White has a decisive advantage"
        if pawns > 0.8:
            return "White is clearly better"
        if pawns > 0.3:
            return "White is a little more comfortable"
        if pawns < -4:
            return "Black is completely winning"
        if pawns < -2:
            return "Black has a decisive advantage"
        if pawns < -0.8:
            return "Black is clearly better"
        if pawns < -0.3:
            return "Black is a little more comfortable"
        return "The position is roughly balanced"


# ----------------------------------------------------------------------
# LLM narration (optional, keeps the voice from sounding templated)
# ----------------------------------------------------------------------

SYSTEM_PROMPT = """You are the narrator of a chess analysis video on a faceless YouTube channel. Your register: a knowledgeable, warm host telling the story of one game to a viewer who is watching the board. You speak in first person, address the viewer as "you", and when it helps you adopt a side's perspective as "we". You explain intentions, then let the move land as the consequence. You are engaged but never breathless; excitement is earned at key moments, not sprayed everywhere.

You will be given a JSON list of BEATS. Each beat already has the board action decided (a move played, a variation shown, a pause on the position, or a return to the game) plus engine facts about that position. Rewrite ONLY the narration text for each beat.

THE SCRIPT IS ONE CONTINUOUS MONOLOGUE, NOT 123 CAPTIONS.
Beats sharing the same "para" number are spoken as ONE breath group — the voice will read
them as a single flowing paragraph with no restart between beats. Write them that way:
- Sentences may and should flow ACROSS beats inside a para. A non-final beat may end
  mid-sentence with a comma; the para's LAST beat must complete the sentence.
- Chain quick moves inside a para the way a person recaps a known sequence:
  "We get knight to f3, knight to c6, and after bishop to c4 the stage is set."
- A new para is a new breath: it may open with a connective that leans on what was just
  said — "So", "Now", "Instead", "And here", "But watch" — so paragraphs link into one talk.

HOW MOVES ENTER A SENTENCE — the single most important style rule.
The move is the PAYOFF of a thought, not the headline. Give the intention, the fear, or
the question first; then the move answers it. Never write more than two consecutive beats
in bare "Piece to square, comment" announcement form.
  Flat (avoid): "Bishop to b2, eyeing the e5 pawn. f5 is ambitious."
  Yours: "White wants that long diagonal working, so the bishop slides to b2, staring at
  e5 — and Spassky answers with the ambitious f5, grabbing space and loosening his own king."
Every beat that plays a move must still SAY its move once, with the square written as a
letter-number token ("knight to f3", "queen takes e5", "castles kingside") at the moment
the piece should be seen to move — early in the beat if the move is the point, later if
you are building up to it. Castling is the easy one to forget because it has no square
to name: a castling beat must contain the word "castles", even mid-sentence — "White
castles and now the g7 bishop stares at d4" — or the king will slide while you talk
about something else.

RHYTHM DEVICES — use all of these across the video:
- Question then answer. THIS IS NOT OPTIONAL AND IT IS THE MOST OFTEN IGNORED RULE HERE.
  A question makes the listener lean in and, spoken aloud, lifts the voice instead of
  letting it fall — which is what stops fifteen minutes sounding like a list.
  Requirements, all of them:
    * EVERY 'hold' beat must contain at least one question. A hold exists to make the
      viewer think, so ask them what they would play, or what they think White is
      worried about, before you answer it.
    * EVERY beat tagged blunder or brilliant must be set up by a question, either in
      that beat or the one before it: "Can he really take? / What is wrong with the
      obvious recapture?"
    * At least SIX questions across the whole script.
  Ask them the way a person does — "So what is actually holding this together?",
  "Can't the knight just take it?", "Why not simply defend?" — and answer immediately
  after. Rhetorical filler with no answer is worse than no question at all.
- Running threads. Pick one to three motifs the facts support (a pin that never resolves, a
  piece nobody can take, a king stuck in the middle) and count them out loud: "that is the
  second piece White is not allowed to capture." Set them up early, pay them off at the end.
- The pause challenge. At the single best moment of the game, invite the viewer to find the
  move: "Pause here and try to find it. I will show you." Use it once, maybe twice.
- Phase compression. When several quiet or forced moves pass in a row, frame once and chain
  fast: "Both sides tidy up — rook to d1, rook to c8, the knights come to their squares —
  and nothing has changed except everything is loaded." Do not give ceremony to moves that
  do not deserve it.
- Echo for emphasis, sparingly: "He gave up every pawn. All eight."

PACING. Every beat carries a "words" budget — roughly how many words that beat should be.
Honour it; the board waits for you, so narration length IS screen time.
- words <= 10  -> a clause or a very short sentence, often chaining with its neighbours.
- words ~ 15-40 -> a sentence or two of real content.
- words >= 60  -> a "hold": the position is frozen, settle in. Explain the plan, the
  threat, what each side wants, what to watch. This is where the video earns its length.

NEVER SPEAK IN ENGINE UNITS. "evalCp" and "cpLoss" are there to tell you HOW MUCH
something matters — they are not vocabulary. Say the verdict in plain words and let
the board justify it. A viewer hears "two pawns better" as arithmetic; they hear
"the knight is pinned and nobody can defend it" as chess.
  Banned: "the evaluation drifts", "worth more than a pawn and a half", "a clear
  extra pawn's worth of pressure", "two pawns down", "losing by more than five",
  "plus one point three".
  Instead: "level", "a shade more comfortable", "clearly better", "winning
  comfortably", "completely lost" — then name the reason on the board: the piece
  that cannot move, the king with no shelter, the pawn nobody can defend.
Material you can always state plainly, because it is a fact and not a score: "a
pawn up", "a piece down", "rook for knight".

FACTS ARE LAW:
- Use the supplied facts (pins, hanging pieces, long diagonals, evaluation, move quality). Never invent a tactic that is not in the facts.
- Never claim a move is forced, only, or impossible unless the facts say so. On a
  check, "checkEvasions" lists every legal reply: "blocks" are the interposing
  moves, "captures" take the checking piece, "kingMoves" step away. Say "the king
  has to move" ONLY when "onlyKingMoves" is true, and never say a check cannot be
  blocked when "canBlock" is true. If a claim is not in the facts, describe what
  is on the board instead.
- A "longRays" entry ends at the piece it hits. The line stops there — do not
  describe it as sweeping past that piece or reaching the far side of the board.

OTHER RULES:
- Spoken aloud: no markdown, no lists, no symbols, no move numbers like "12.".
- Vary sentence openings. Never open two beats in a row with the player's name.
- For 'variation' beats, explain the IDEA behind the engine's suggestion, in the voice of
  showing the viewer an alternate world: "let me show you what was waiting", "watch what
  happens if". Do not re-announce in the resume what the variation already named.
- For 'resume' beats, come back to reality with contrast: "but that is not what happened."
- For 'hold' beats, do not announce a move — nothing moves on screen during them.
- THE ENDING. The outro is the last thing anyone hears, so do not spend it on
  admin. In order: say why the loser stopped — the concrete reason, a piece down
  with a king in the open, not "he was worse"; then land the thread you have been
  running all video, so the finish pays off the opening promise ("one pinned
  knight decided the whole thing, and it never moved a square"); then one short,
  warm sign-off. Never open the outro with "Thank you for watching". Do not
  recap the move order, and do not add a moral about chess in general.
- You can see the whole game: build across it. What you set up in minute one should pay
  off in the finale.

ALSO WRITE THE VIDEO LISTING. You have seen the whole game, so you are the best
placed to describe it.
- "title": a YouTube title under 90 characters. What performs, in order of pull:
  a concrete extreme number the game actually contains ("Four Sacrifices in One
  Game", "A Queen Offered on Move 26"); a paradox the game cashes ("He Offered
  His Queen — and No One Could Take It"); then the famous name, and only if the
  name itself is the hook (Tal, Fischer, Kasparov, Spassky qualify). "He/She +
  extreme act" with the name held back often outdraws the name itself. No venue,
  no year, no "| Site 1986" suffix — those cost clicks. Never promise what the
  game does not deliver.
- "hook": two or three sentences for the video description. Say what happens and why
  it is worth ten minutes, without spoiling the final move.

Return JSON: {"title": "...", "hook": "...", "beats": [{"id": "<beat id>", "text": "<narration>"}, ...]}
covering every beat id given."""


def _compact_beat_for_llm(beat: Dict[str, Any], ply_facts: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": beat["id"],
        "kind": beat["kind"],
        "draft": beat["text"],
        "words": beat.get("targetWords"),
        "para": beat.get("para"),
    }
    if beat.get("move"):
        out["move"] = beat["move"]["san"]
    if beat.get("label"):
        out["label"] = beat["label"]
    if beat.get("evalCp") is not None:
        out["evalCp"] = beat["evalCp"]
    if beat.get("tag"):
        out["quality"] = beat["tag"]

    if ply_facts:
        features = ply_facts.get("features") or {}
        facts_out: Dict[str, Any] = {}
        if features.get("pins"):
            facts_out["pins"] = features["pins"][:2]
        if features.get("hanging"):
            facts_out["hanging"] = features["hanging"][:2]
        if features.get("forks"):
            facts_out["forks"] = features["forks"][:1]
        long_rays = [r for r in (features.get("longRays") or []) if r.get("hits")][:1]
        if long_rays:
            # Trim the geometric ray at the piece it runs into. Handing over the
            # full line to the edge invites narration about a bishop raking a
            # square that a pawn is in fact standing in front of.
            trimmed = []
            for ray in long_rays:
                ray = dict(ray)
                target = (ray.get("hits") or [{}])[0].get("square")
                path = ray.get("ray") or []
                if target and target in path:
                    ray["ray"] = path[: path.index(target) + 1]
                trimmed.append(ray)
            facts_out["longRays"] = trimmed
        if features.get("checkEvasions"):
            facts_out["checkEvasions"] = features["checkEvasions"]
        if ply_facts.get("bestMoveSan"):
            facts_out["engineBest"] = ply_facts["bestMoveSan"]
        if ply_facts.get("cpLoss") is not None:
            facts_out["cpLoss"] = ply_facts["cpLoss"]
        if ply_facts.get("isSacrifice"):
            facts_out["sacrifice"] = True
        if features.get("phase"):
            facts_out["phase"] = features["phase"]
        if facts_out:
            out["facts"] = facts_out
    return out


NARRATION_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["title", "hook", "beats"],
    "additionalProperties": False,
}


def narrate_with_llm(
    script: Dict[str, Any],
    facts: Dict[str, Any],
    *,
    model: Optional[str] = None,
) -> bool:
    """Rewrite beat texts with an LLM in place. Returns True if it succeeded.

    The **whole script goes in one request**. Narrative continuity is the entire
    reason to use an LLM here — a model that can see every beat can vary its
    openings, call back to earlier moments, and pace the game. Chunking the
    script breaks exactly that, because each chunk is written blind to what the
    previous one already said. A full game is well under 40k tokens, so with a
    1M-token context window there is no reason to split it.

    Supports Anthropic (ANTHROPIC_API_KEY) and OpenAI (OPENAI_API_KEY). Falls
    back silently — the template narration is usable on its own.
    """
    beats: List[Dict[str, Any]] = script.get("beats") or []
    if not beats:
        return False

    ply_by_index = {p["ply"]: p for p in (facts.get("plies") or [])}
    meta = script.get("meta", {}) or {}
    summary = facts.get("summary", {}) or {}
    header = {
        "white": _display_name(meta.get("white")),
        "black": _display_name(meta.get("black")),
        "event": _clean(meta.get("event")),
        "date": _clean(meta.get("date")),
        "result": _clean(meta.get("result")),
        "opening": (meta.get("opening") or {}).get("name") if isinstance(meta.get("opening"), dict) else None,
        "plyCount": summary.get("plyCount"),
        "blunders": len(summary.get("blunders") or []),
        "brilliancies": len(summary.get("brilliancies") or []),
        "sacrifices": len(summary.get("sacrifices") or []),
    }

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not anthropic_key and not openai_key:
        logger.info("No LLM API key set; using template narration.")
        return False

    payload = json.dumps(
        {
            "game": header,
            "beats": [_compact_beat_for_llm(b, ply_by_index.get(b.get("ply"))) for b in beats],
        },
        ensure_ascii=False,
    )

    content: Optional[str] = None

    if anthropic_key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=anthropic_key)
            # Stream: a full script can run well past the non-streaming
            # timeout guard, and thinking tokens count toward max_tokens.
            with client.messages.stream(
                model=model or os.getenv("NARRATION_MODEL", "claude-opus-5"),
                max_tokens=32000,
                system=SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": os.getenv("NARRATION_EFFORT", "medium"),
                    "format": {"type": "json_schema", "schema": NARRATION_SCHEMA},
                },
                messages=[{"role": "user", "content": payload}],
            ) as stream:
                message = stream.get_final_message()

            if message.stop_reason == "refusal":
                logger.warning("Narration request was refused; keeping templates.")
                return False
            content = "".join(b.text for b in message.content if b.type == "text")
            usage = message.usage
            logger.info(
                f"Narration tokens: in={usage.input_tokens} out={usage.output_tokens}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Anthropic narration failed: {exc}")

    if content is None and openai_key:
        try:
            from openai import OpenAI

            client = OpenAI(api_key=openai_key)
            resp = client.chat.completions.create(
                model=model or os.getenv("NARRATION_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": payload},
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"OpenAI narration failed: {exc}")

    if not content:
        return False

    try:
        obj = json.loads(content)
    except Exception:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            logger.warning("LLM returned unparseable narration; keeping templates.")
            return False
        try:
            obj = json.loads(match.group(0))
        except Exception:
            return False

    title = (obj.get("title") or "").strip()
    hook = (obj.get("hook") or "").strip()
    if title:
        script["meta"]["llmTitle"] = title
    if hook:
        script["meta"]["llmHook"] = hook

    rewritten: Dict[str, str] = {}
    for item in obj.get("beats", obj if isinstance(obj, list) else []):
        bid = (item.get("id") or "").strip()
        text = (item.get("text") or "").strip()
        if bid and text:
            rewritten[bid] = text

    if not rewritten:
        return False

    for beat in beats:
        if beat["id"] in rewritten:
            beat["text"] = rewritten[beat["id"]]
    logger.info(f"LLM narration applied to {len(rewritten)}/{len(beats)} beats")
    return True


def build_script(
    facts: Dict[str, Any],
    *,
    channel_name: str = "Nocturne Chess",
    use_llm: bool = True,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Facts -> narration beat script (LLM-polished when a key is available)."""
    director = Director(channel_name=channel_name, seed=seed)
    script = director.build_script(facts)
    if use_llm:
        if narrate_with_llm(script, facts):
            script["meta"]["narration"] = "llm"
            _reflow_paragraphs(script["beats"])
            logger.info("Narration: LLM")
        else:
            script["meta"]["narration"] = "template"
            logger.info("Narration: built-in templates")
    else:
        script["meta"]["narration"] = "template"
    return script


_SENTENCE_END = tuple('.!?"”’)')


def _reflow_paragraphs(beats: List[Dict[str, Any]]) -> None:
    """Re-derive breath groups from the narration that was actually written.

    The paragraph numbers handed to the narrator are a *hint*: they tell it
    where a breath belongs so it can let sentences run across beats. But the
    model writes prose, not to a word budget, and it will happily carry a
    clause past a boundary we guessed at. Splitting the audio there ends a take
    on a comma — the voice stops mid-thought and the next take opens cold.

    So the boundary only survives if the beat before it actually finishes a
    sentence. Anything else merges forward, and the whole thought is spoken in
    one take.
    """
    if not beats:
        return
    original = [b.get("para") for b in beats]
    para = 0
    merged = 0
    beats[0]["para"] = 0
    for i in range(1, len(beats)):
        boundary = original[i] != original[i - 1]
        if boundary:
            prev = (beats[i - 1].get("text") or "").rstrip()
            if prev and not prev.endswith(_SENTENCE_END):
                boundary = False
                merged += 1
        if boundary:
            para += 1
        beats[i]["para"] = para
    if merged:
        logger.info(
            f"Paragraphs: merged {merged} boundary(ies) that fell mid-sentence "
            f"({len(set(original))} -> {para + 1} takes)"
        )


def save_script(script: Dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(script, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Script saved to {path} ({len(script.get('beats', []))} beats)")
