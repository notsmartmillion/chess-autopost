"""
Game selection for daily publishing.

Two sources supported:

1) Database-backed (class GameSelector)
   - Avoid repeats (no media.youtube_id/status='uploaded')
   - Prefer anniversary (same MM-DD)
   - Score by length curve, eval swings (analysis_cache), mate/brilliant tags, event bonus

2) Filesystem-backed (functions pick_random_local / pick_by_simple_interest)
   - Work off PGNs downloaded to storage/pgns/
   - Score by simple SAN heuristics (checks/captures/mates, shorter decisive games)

Use whichever is available; orchestrator can try DB first then fallback to FS.
"""

from __future__ import annotations

import datetime as dt
import io
import math
import random
import typing as t
from dataclasses import dataclass
from pathlib import Path

import chess.pgn

# --- Optional SQLAlchemy: DB selector only if installed ---
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine, RowMapping  # type: ignore
    _HAVE_SQLA = True
except Exception:  # pragma: no cover
    Engine = t.Any  # type: ignore
    RowMapping = t.Dict[str, t.Any]  # type: ignore
    _HAVE_SQLA = False

from .config import settings
from .pgn_ingest import PGN_DIR, read_pgn_files, read_pgn_text
from .utils.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Filesystem-based selection (works without DB)
# =============================================================================

@dataclass
class PickResult:
    path: Path
    pgn: str
    headers: dict
    plies: int


def _headers_and_plies(pgn_text: str) -> tuple[dict, int]:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        return {}, 0
    headers = dict(game.headers)
    board = game.board()
    plies = 0
    for mv in game.mainline_moves():
        board.push(mv)
        plies += 1
    return headers, plies


def pick_random_local(min_plies: int = 20) -> PickResult | None:
    """Pick a random PGN from storage/pgns with at least `min_plies` plies."""
    files = read_pgn_files(PGN_DIR)
    random.shuffle(files)
    for p in files:
        try:
            txt = read_pgn_text(p)
            headers, plies = _headers_and_plies(txt)
            if plies >= min_plies:
                return PickResult(path=p, pgn=txt, headers=headers, plies=plies)
        except Exception:
            continue
    return None


def pick_by_simple_interest(top_k: int = 50, min_plies: int = 20) -> PickResult | None:
    """
    Lightweight heuristic from local PGNs:
      score = checks + 0.5*captures + 5*mate + small bias for shorter (but not tiny) games.
    """
    files = read_pgn_files(PGN_DIR)
    scored: list[tuple[float, Path]] = []

    for p in files:
        try:
            txt = read_pgn_text(p)
            headers, plies = _headers_and_plies(txt)
            if plies < min_plies:
                continue

            # SAN body after headers
            body = txt.split("\n\n", 1)[-1]
            score = (
                body.count("+") * 1.0   # checks
                + body.count("x") * 0.5 # captures
                + body.count("#") * 5.0 # mate
                + max(0.0, 60 - plies) * 0.05  # slight preference for <= 60 plies
            )
            scored.append((score, p))
        except Exception:
            continue

    if not scored:
        return None

    scored.sort(reverse=True)
    for _score, p in scored[:top_k]:
        txt = read_pgn_text(p)
        headers, plies = _headers_and_plies(txt)
        return PickResult(path=p, pgn=txt, headers=headers, plies=plies)
    return None


# =============================================================================
# Database-backed selector (your original logic)
# =============================================================================

def _today_mm_dd() -> tuple[int, int]:
    today = dt.date.today()
    return today.month, today.day


def _engine() -> Engine:
    if not _HAVE_SQLA:  # pragma: no cover
        raise RuntimeError("SQLAlchemy not installed; DB selector unavailable.")
    return create_engine(settings.DB_URL)


class GameSelector:
    """
    DB-backed selector.
    Requires tables:
      - games(id, date, event, ply_count, ...)
      - media(game_id, youtube_id, status)
      - analysis_cache(game_id, ply, eval_cp, tag)
    """

    def __init__(self, engine: Engine | None = None) -> None:
        if not _HAVE_SQLA:  # pragma: no cover
            raise RuntimeError("SQLAlchemy not installed; GameSelector cannot be used.")
        self.engine = engine or _engine()

    # -------- Public API --------

    def pick_today(self) -> int:
        """
        Strategy:
          1) Try a top-scored anniversary game.
          2) Else best unused game overall.
        Returns game_id.
        """
        gid = self.pick_anniversary_first()
        if gid is not None:
            return gid

        candidates = self._unused_games(limit=2000)
        if not candidates:
            raise ValueError("No unused games available.")
        scored = sorted(
            ((self._score_row(row), int(row["id"])) for row in candidates),
            reverse=True
        )
        return scored[0][1]

    def pick_anniversary_first(self) -> int | None:
        """Return a top-scored anniversary game if any, else None."""
        mm, dd = _today_mm_dd()
        rows = self._unused_games(limit=500, anniversary=(mm, dd))
        if not rows:
            return None
        scored = sorted(
            ((self._score_row(r), int(r["id"])) for r in rows),
            reverse=True
        )
        return scored[0][1]

    def score_game(self, game_id: int) -> float:
        """Compute a score for a specific game id."""
        with self.engine.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM games WHERE id = :id"),
                {"id": game_id},
            ).mappings().first()
        if not row:
            raise ValueError(f"Game {game_id} not found")
        return self._score_row(row)

    # -------- Internals --------

    def _unused_games(
        self, limit: int = 1000, anniversary: tuple[int, int] | None = None
    ) -> list[RowMapping]:
        """
        Get games not yet published (no media row with youtube_id or status='uploaded').
        If anniversary=(mm, dd), filter by month/day match (ignoring year).
        """
        wheres = [
            "g.id NOT IN (SELECT game_id FROM media WHERE youtube_id IS NOT NULL OR status = 'uploaded')"
        ]
        params: dict[str, t.Any] = {}
        if anniversary:
            mm, dd = anniversary
            wheres.append(
                "g.date IS NOT NULL AND EXTRACT(MONTH FROM g.date) = :mm AND EXTRACT(DAY FROM g.date) = :dd"
            )
            params.update({"mm": mm, "dd": dd})

        where_clause = " AND ".join(wheres)
        sql = f"""
            SELECT g.*
            FROM games g
            WHERE {where_clause}
            ORDER BY g.date NULLS LAST, g.id
            LIMIT :limit
        """
        params["limit"] = limit

        with self.engine.begin() as conn:
            rows = list(conn.execute(text(sql), params).mappings())
        return rows

    def _score_row(self, row: RowMapping) -> float:
        """
        Composite score:
          - length component (bell curve favoring ~40–90 plies)
          - eval swings (analysis_cache; |Δeval| >= 150cp)
          - mate tags bonus
          - +1.0 per 'brilliant' tag (if present)
          - small bonus for famous events
        """
        gid = int(row["id"])
        ply_count = int(row.get("ply_count") or 0)
        event = str(row.get("event") or "").lower()

        length_score = self._length_score(ply_count)
        swings, mates, tags_bonus = self._analysis_signals(gid)

        event_bonus = 0.0
        for k in ("candidates", "world championship", "olympiad", "superbet", "tata steel", "sinquefield", "twic"):
            if k in event:
                event_bonus += 0.5

        score = (
            length_score * 2.0
            + swings * 1.5
            + mates * 2.5
            + tags_bonus
            + event_bonus
        )
        return float(score)

    def _length_score(self, ply_count: int) -> float:
        """Bell curve centered ~60 plies (30 moves)."""
        if ply_count <= 6:
            return 0.0
        mu = 60.0
        sigma = 25.0
        return math.exp(-((ply_count - mu) ** 2) / (2 * sigma * sigma))

    def _analysis_signals(self, game_id: int) -> tuple[int, int, float]:
        """
        Returns (swings, mates, tags_bonus).
        - swings: count of eval jumps >= 150cp between consecutive plies
        - mates: number of positions tagged 'mate'
        - tags_bonus: +1.0 per 'brilliant'
        Falls back to (0,0,0.0) if no cached analysis.
        """
        sql = """
        SELECT ply, eval_cp, tag
        FROM analysis_cache
        WHERE game_id = :gid
        ORDER BY ply
        """
        swings = 0
        mates = 0
        tags_bonus = 0.0

        with self.engine.begin() as conn:
            rows = list(conn.execute(text(sql), {"gid": game_id}).mappings())

        if not rows:
            return (0, 0, 0.0)

        prev = None
        for r in rows:
            ev = r.get("eval_cp")
            tag = (r.get("tag") or "").lower()
            if tag:
                if "brilliant" in tag:
                    tags_bonus += 1.0
                if "mate" in tag:
                    mates += 1
            if prev is not None and ev is not None:
                if abs(ev - prev) >= 150:
                    swings += 1
            prev = ev

        return (swings, mates, tags_bonus)


# =============================================================================
# Convenience facade
# =============================================================================

def pick_best_available(min_plies: int = 20) -> tuple[str, str] | None:
    """
    Convenience:
      - Try DB (if SQLAlchemy installed & DB reachable).
      - Else try local PGNs by interest heuristic.
    Returns tuple (source, pgn_text) where source is 'db:<id>' or 'fs:<path>',
    or None if nothing found.
    """
    # DB first
    if _HAVE_SQLA:
        try:
            gs = GameSelector()
            game_id = gs.pick_today()
            # Caller would then fetch PGN from DB; we don't do DB->PGN here.
            return (f"db:{game_id}", "")
        except Exception as e:  # no games / no DB / etc.
            logger.info(f"[selectors] DB fallback: {e}")

    # FS fallback
    pick = pick_by_simple_interest(min_plies=min_plies) or pick_random_local(min_plies=min_plies)
    if pick:
        return (f"fs:{pick.path.name}", pick.pgn)
    return None


__all__ = [
    # FS mode
    "PickResult",
    "pick_random_local",
    "pick_by_simple_interest",
    # DB mode
    "GameSelector",
    # facade
    "pick_best_available",
]
