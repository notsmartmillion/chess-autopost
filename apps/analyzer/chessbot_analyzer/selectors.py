"""
Game selection logic for daily publishing.

Goals:
- Avoid repeats (exclude games already in 'media' with a youtube_id/status).
- Prefer anniversary games (same MM-DD as today).
- Score candidates by excitement:
    * eval swings (needs analysis_cache; falls back to heuristics),
    * mate tags,
    * reasonable length (avoid ultra-short or 200+ plies),
    * small bonus for famous events.
"""

from __future__ import annotations

import datetime as dt
import math
import typing as t

from sqlalchemy import create_engine, text, RowMapping
from sqlalchemy.engine import Engine

from .config import settings


def _engine() -> Engine:
    return create_engine(settings.DB_URL)


def _today_mm_dd() -> tuple[int, int]:
    # You can swap to zone-aware if you want Europe/Prague explicitly.
    today = dt.date.today()
    return today.month, today.day


class GameSelector:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or _engine()

    # -------- Public API --------

    def pick_today(self) -> int:
        """
        Pick the best game for today.
        Strategy:
          1) Try to pick an anniversary game with the highest score.
          2) Otherwise pick the highest score among unused games.
        Returns game_id.
        Raises ValueError if no candidates found.
        """
        gid = self.pick_anniversary_first()
        if gid is not None:
            return gid

        candidates = self._unused_games(limit=2000)
        if not candidates:
            raise ValueError("No unused games available.")
        scored = sorted(((self._score_row(row), row["id"]) for row in candidates), reverse=True)
        return scored[0][1]

    def pick_anniversary_first(self) -> int | None:
        """Return a top-scored anniversary game if any, else None."""
        mm, dd = _today_mm_dd()
        rows = self._unused_games(limit=500, anniversary=(mm, dd))
        if not rows:
            return None
        scored = sorted(((self._score_row(r), r["id"]) for r in rows), reverse=True)
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

    def _unused_games(self, limit: int = 1000, anniversary: tuple[int, int] | None = None) -> list[RowMapping]:
        """
        Get games not yet published (no media row with youtube_id or status='uploaded').
        If anniversary=(mm, dd), filter by month/day match (ignoring year).
        """
        wheres = ["g.id NOT IN (SELECT game_id FROM media WHERE youtube_id IS NOT NULL OR status = 'uploaded')"]
        params: dict[str, t.Any] = {}
        if anniversary:
            mm, dd = anniversary
            wheres.append("g.date IS NOT NULL AND EXTRACT(MONTH FROM g.date) = :mm AND EXTRACT(DAY FROM g.date) = :dd")
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
          - length component (bell curve favoring ~40-90 plies)
          - eval swings (from analysis_cache; count |Δeval| >= 150cp)
          - mate tags bonus
          - event bonus for famous events (basic substring match)
        """
        gid = int(row["id"])
        ply_count = int(row["ply_count"] or 0)
        event = (row.get("event") or "").lower()

        length_score = self._length_score(ply_count)

        swings, mates, tags_bonus = self._analysis_signals(gid)

        event_bonus = 0.0
        for k in ("candidates", "world championship", "olympiad", "superbet", "tata steel", "sinquefield", "twic"):
            if k in event:
                event_bonus += 0.5

        # Weighting
        score = (
            length_score * 2.0
            + swings * 1.5
            + mates * 2.5
            + tags_bonus
            + event_bonus
        )
        return float(score)

    def _length_score(self, ply_count: int) -> float:
        """
        Bell curve centered ~60 plies (30 moves), broad enough to include 40–90 plies as strong.
        """
        if ply_count <= 6:
            return 0.0
        mu = 60.0
        sigma = 25.0
        # normalized gaussian (peak ~1.0 at mu)
        return math.exp(-((ply_count - mu) ** 2) / (2 * sigma * sigma))

    def _analysis_signals(self, game_id: int) -> tuple[int, int, float]:
        """
        Returns (swings, mates, tags_bonus).
        - swings: count of eval jumps >= 150cp between consecutive plies
        - mates: number of positions marked with tag 'mate' (if you store such tags) or where eval is NULL but mate exists
        - tags_bonus: +1.0 per 'brilliant' tag if any (else 0)
        Falls back to (0, 0, 0.0) if no analysis is cached yet.
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
            # No cached analysis yet; neutral
            return (0, 0, 0.0)

        prev = None
        for r in rows:
            ev = r["eval_cp"]
            tag = r.get("tag")
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
