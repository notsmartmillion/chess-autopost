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

    def __init__(self, channel_name: str = "Quiet Chess"):
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

        logger.info("Generated %d voice lines (ASMR style).", len(voice_lines))
        return voice_lines

    def optimize_for_audio_sync(self, lines: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Normalize spacing, add gentle pauses around hot words."""
        out: List[Dict[str, str]] = []
        for l in lines:
            t = l["text"]
            for w in ("checkmate", "mate", "check", "captures", "sacrifice", "fork", "pin"):
                t = t.replace(f" {w}", f" {w}…")
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

        parts: List[str] = []

        # announce move
        who = "white" if player == "white" else "black"
        if mvno:
            parts.append(f"move {mvno}: {move} by {who}")
        else:
            parts.append(f"{move}")

        # position sense from eval
        parts.append(self._eval_feel(eval_target))

        # tactics hints
        if pins:
            if len(pins) == 1:
                sq = pins[0].get("sq")
                if sq:
                    parts.append(f"a piece is pinned on {self._square_spoken(sq)}")
                else:
                    parts.append("a pinned piece appears")
            else:
                parts.append("multiple pins appear")

        total_attacked = len(attacked.get("white", [])) + len(attacked.get("black", []))
        if total_attacked > 10:
            parts.append("tension is rising across the board")

        return ". ".join(parts)

    def _alt_line(self, s: Dict[str, Any]) -> str:
        label = s.get("label", "alternative")
        cp = s.get("cp")
        mate = s.get("mate")
        pv = s.get("pv") or []
        start = f"{label}…"
        if mate:
            start += f" mate in {mate}"
        elif isinstance(cp, (int, float)):
            start += f" {self._cp_speech(cp)}"
        if pv:
            seq = " ".join(pv[:3])
            start += f". line: {seq}"
        return start

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
            "move_intros": ["now", "here", "then", "next", "and now"],
            "tension": ["tension rises", "lines are opening", "pressure builds"],
        }
