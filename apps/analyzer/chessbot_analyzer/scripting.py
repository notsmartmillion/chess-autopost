"""ASMR script generator for turning scenes into VO lines, with intro/outro."""

from __future__ import annotations
import random
from typing import List, Dict, Any, Optional, Tuple
from .utils.logging import get_logger

logger = get_logger(__name__)


class ScriptGenerator:
    """
    Generates calm, ASMR-style narration:
      - make_intro(meta, timeline)
      - make_outro(meta, timeline)
      - from_timeline(timeline, include_keywords=True, include_reset=False)
      - optimize_for_audio_sync(lines)
    """

    def __init__(self, channel_name: str = "Midnight Chess"):
        self.channel_name = channel_name
        self.phrase_bank = self._build_phrase_bank()

    # ---------- public API ----------

    def make_intro(self, meta: Dict[str, Any], timeline: Dict[str, Any]) -> str:
        """Short, cozy intro before the first move."""
        w = meta.get("white") or "White"
        b = meta.get("black") or "Black"
        event = meta.get("event")
        date = meta.get("date")
        opener = random.choice([
            "welcome back",
            "good to see you again",
            "thanks for joining me",
            "settle in",
        ])
        line = f"{opener}. this is {self.channel_name}. "
        if event and date:
            line += f"today, a game from {event}, {date}. "
        elif event:
            line += f"today, a game from {event}. "
        line += f"{w} against {b}. let's enjoy the flow and the ideas."
        return self._soften(line)

    def make_outro(self, meta: Dict[str, Any], timeline: Dict[str, Any]) -> str:
        """Gentle outro after the last move."""
        result = meta.get("result") or ""
        tail = "thank you for watching. if you enjoyed this, a like helps a lot. sleep well, and see you soon."
        if result:
            return self._soften(f"and that is the game. result: {result}. {tail}")
        return self._soften(f"and that is the finish. {tail}")

    def from_timeline(
        self,
        timeline: Dict[str, Any],
        include_keywords: bool = True,
        include_reset: bool = False,
    ) -> List[Dict[str, str]]:
        """
        Create move-by-move VO lines for all main/alt scenes.
        Returns list of {id, text}.
        """
        voice_lines: List[Dict[str, str]] = []

        for s in timeline.get("scenes", []):
            t = s.get("type")
            sid = s.get("id")
            if t == "main":
                text = self._main_line(s)
            elif t == "alt":
                text = self._alt_line(s)
            elif t == "reset":
                if include_reset:
                    text = "…"
                else:
                    continue
            else:
                logger.warning("unknown scene type: %s", t)
                continue

            if text:
                voice_lines.append({"id": sid, "text": self._soften(text)})

        logger.info(f"Generated {len(voice_lines)} voice lines (ASMR style).")
        return voice_lines

    def optimize_for_audio_sync(self, lines: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Normalize spacing, add gentle pauses after hot words (word-boundary safe)."""
        import re

        hot = ("checkmate", "mate", "check", "captures", "sacrifice", "fork", "pin")
        pattern = re.compile(r"\b(" + "|".join(hot) + r")\b(?!…)")
        out: List[Dict[str, str]] = []
        for l in lines:
            t = pattern.sub(r"\1…", l["text"])
            t = " ".join(t.split())
            out.append({"id": l["id"], "text": t})
        return out

    # ---------- internal helpers ----------

    def _main_line(self, s: Dict[str, Any]) -> str:
        move = s.get("move", "")
        mvno = s.get("moveNumber")
        player = s.get("player")
        eval_target = float(s.get("evalBarTarget", 0.0))
        pins = s.get("pins") or []
        attacked = s.get("attacked") or {"white": [], "black": []}
        tag = s.get("tag")
        captured = bool(s.get("captured"))

        parts: List[str] = []

        who = "white" if player == "white" else "black"
        spoken_move = self._move_spoken(move)

        # announce move, with a little personality
        if mvno:
            opener = random.choice(self.phrase_bank["move_intros"])
            parts.append(f"{opener}, {spoken_move} from {who}")
        else:
            parts.append(spoken_move)

        # move-quality banter
        if tag == "blunder":
            parts.append(random.choice(self.phrase_bank["blunder"]))
        elif tag == "mistake":
            parts.append(random.choice(self.phrase_bank["mistake"]))
        elif tag == "inaccuracy":
            parts.append(random.choice(self.phrase_bank["inaccuracy"]))
        elif tag in ("great", "brilliant"):
            parts.append(random.choice(self.phrase_bank["great"]))
        elif tag == "best":
            if random.random() < 0.35:
                parts.append(random.choice(self.phrase_bank["best"]))

        # flavor for special moves
        if "#" in move:
            parts.append("and that is checkmate… the game ends right here")
        elif "+" in move:
            parts.append(random.choice(self.phrase_bank["check"]))
        elif move in ("O-O", "O-O-O"):
            parts.append("the king tucks away to safety")
        elif "=" in move:
            parts.append("a new queen steps onto the board")
        elif captured and tag not in ("blunder", "mistake"):
            if random.random() < 0.5:
                parts.append(random.choice(self.phrase_bank["capture"]))

        # position sense from eval (skip when the tag already told the story)
        if tag not in ("blunder", "great", "brilliant") and random.random() < 0.7:
            parts.append(self._eval_feel(eval_target))

        # tactics hints
        if pins:
            if len(pins) == 1:
                sq = pins[0].get("sq")
                if sq:
                    parts.append(f"notice the pin on {self._square_spoken(sq)}")
                else:
                    parts.append("a pinned piece appears")
            else:
                parts.append("pins everywhere… nobody can move freely")

        total_attacked = len(attacked.get("white", [])) + len(attacked.get("black", []))
        if not pins and total_attacked > 40 and random.random() < 0.25:
            parts.append("tension is rising across the board")

        return ". ".join(parts)

    def _alt_line(self, s: Dict[str, Any]) -> str:
        cp = s.get("cp")
        mate = s.get("mate")
        pv = s.get("pv") or []
        first = self._move_spoken(pv[0]) if pv else "another idea"
        start = random.choice([
            f"instead, {first} was stronger",
            f"the engine prefers {first} here",
            f"a better try was {first}",
            f"stronger was {first}",
        ])
        if mate:
            start += f"… leading to mate in {abs(int(mate))}"
        elif isinstance(cp, (int, float)):
            start += f"… worth {self._cp_speech(cp)}"
        if len(pv) > 1:
            start += f". the idea continues with {self._move_spoken(pv[1])}"
        return start

    def _move_spoken(self, san: str) -> str:
        """Convert SAN to something natural to speak."""
        if not san:
            return san
        if san in ("O-O", "0-0"):
            return "castles kingside"
        if san in ("O-O-O", "0-0-0"):
            return "castles queenside"
        s = san.replace("#", "").replace("+", "")
        pieces = {"K": "king", "Q": "queen", "R": "rook", "B": "bishop", "N": "knight"}
        out = []
        i = 0
        if s and s[0] in pieces:
            out.append(pieces[s[0]])
            i = 1
        rest = s[i:]
        if "x" in rest:
            pre, post = rest.split("x", 1)
            if not out:  # pawn capture like exd5
                out.append(f"pawn on {self._square_spoken(pre)}" if pre else "pawn")
            elif pre:
                out.append(pre)  # disambiguation like Nbd2 -> keep terse
            out.append("takes")
            rest = post
        if "=" in rest:
            sq, promo = rest.split("=", 1)
            out.append(self._square_spoken(sq))
            out.append(f"promoting to a {pieces.get(promo[:1], 'queen')}")
            return " ".join(out)
        if len(rest) >= 2 and rest[-1].isdigit():
            out.append(self._square_spoken(rest[-2:]))
            if len(rest) > 2 and not out[0].startswith(("king", "queen", "rook", "bishop", "knight", "pawn")):
                pass
        elif rest:
            out.append(rest)
        return " ".join(out) if out else san

    def _eval_feel(self, e: float) -> str:
        # -1..+1 mapping chosen by your analyzer
        if e > 0.75:
            return "white is pressing hard"
        if e > 0.45:
            return "white keeps a healthy edge"
        if e > 0.15:
            return "white is a little better"
        if e < -0.75:
            return "black is pressing hard"
        if e < -0.45:
            return "black takes over"
        if e < -0.15:
            return "black is a little better"
        return "roughly balanced"

    def _cp_speech(self, cp: float) -> str:
        v = abs(cp)
        side = "white" if cp > 0 else "black"
        if v < 25:
            return "rough equality"
        if v < 80:
            return f"a slight pull for {side}"
        if v < 200:
            pawns = v / 100.0
            return f"about {pawns:.1f} pawns for {side}"
        pawns = v / 100.0
        return f"{pawns:.1f} pawns for {side}"

    def _square_spoken(self, sq: str) -> str:
        if len(sq) != 2:
            return sq
        files = dict(a="ay", b="bee", c="see", d="dee", e="ee", f="eff", g="gee", h="aitch")
        return f"{files.get(sq[0].lower(), sq[0])} {sq[1]}"

    def _soften(self, s: str) -> str:
        """Lowercase vibe, fewer hard stops, gentle ellipses."""
        s = s.strip()
        if not s:
            return s
        s = s[0].lower() + s[1:]
        s = s.replace("!", "…").replace("  ", " ")
        if not s.endswith((".", "…")):
            s += "."
        return s

    def _build_phrase_bank(self) -> Dict[str, List[str]]:
        return {
            "move_intros": ["now", "here", "then", "next", "and now", "quietly", "so"],
            "tension": ["tension rises", "lines are opening", "pressure builds"],
            "blunder": [
                "oh… that's a blunder. the position just slipped away",
                "hmm, that one hurts… the engine is not happy at all",
                "and that is the mistake of the game… everything changes here",
                "oh no… that hands the advantage straight over",
            ],
            "mistake": [
                "that's not the best… some of the advantage drifts away",
                "a real mistake… the position starts to lean the other way",
                "hmm… there was something much better here",
            ],
            "inaccuracy": [
                "a small slip… nothing fatal, but the edge fades a little",
                "slightly imprecise… the position loosens",
                "not quite the best… just a touch soft",
            ],
            "great": [
                "what a move… this is the kind of idea we watch chess for",
                "beautiful… the engine loves this",
                "a wonderful find… everything clicks together now",
                "excellent… this was the only way to keep the thread",
            ],
            "best": [
                "precise… exactly what the position asked for",
                "clean and correct",
                "yes… right on the engine's first line",
            ],
            "check": [
                "check… the king has to respond",
                "and it comes with check",
                "check… no time to breathe",
            ],
            "capture": [
                "a trade… material comes off the board",
                "taking… and the position simplifies",
                "captures… sharpening things a little",
            ],
        }
