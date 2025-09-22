"""
Persist PGNs to DB into table `games`.

Schema created (if missing):

CREATE TABLE games (
  id INTEGER PRIMARY KEY AUTOINCREMENT,   -- or SERIAL for Postgres
  white TEXT,
  black TEXT,
  date TEXT,
  event TEXT,
  result TEXT,
  eco TEXT,
  site TEXT,
  ply_count INTEGER,
  pgn TEXT NOT NULL
);

Swap AUTOINCREMENT to SERIAL if you use Postgres. With SQLAlchemy it works cross-DB.
"""

from __future__ import annotations

from typing import Dict, List, Optional
from sqlalchemy import text, create_engine
from sqlalchemy.engine import Engine

from chessbot_analyzer.config import settings

def _engine() -> Engine:
    return create_engine(settings.DB_URL)

def ensure_schema(engine: Optional[Engine] = None) -> None:
    eng = engine or _engine()
    ddl = """
    CREATE TABLE IF NOT EXISTS games (
      id INTEGER PRIMARY KEY,
      white TEXT,
      black TEXT,
      date TEXT,
      event TEXT,
      result TEXT,
      eco TEXT,
      site TEXT,
      ply_count INTEGER,
      pgn TEXT NOT NULL
    );
    """
    # For Postgres, PRIMARY KEY without AUTOINCREMENT is fine (uses sequences).
    # If using SQLite, INTEGER PRIMARY KEY auto-increments.
    with eng.begin() as conn:
        conn.execute(text(ddl))

def insert_games(games: List[Dict], engine: Optional[Engine] = None) -> List[int]:
    """
    games: [{"pgn": "...", "meta": {...}}, ...]
    returns inserted ids
    """
    eng = engine or _engine()
    ensure_schema(eng)

    ids: List[int] = []
    ins = text("""
      INSERT INTO games (white, black, date, event, result, eco, site, ply_count, pgn)
      VALUES (:white, :black, :date, :event, :result, :eco, :site, :ply_count, :pgn)
      RETURNING id
    """)

    with eng.begin() as conn:
        for g in games:
            m = g.get("meta") or {}
            res = conn.execute(ins, {
                "white": m.get("white"),
                "black": m.get("black"),
                "date": m.get("date"),
                "event": m.get("event"),
                "result": m.get("result"),
                "eco": m.get("eco"),
                "site": m.get("site"),
                "ply_count": m.get("ply_count"),
                "pgn": g.get("pgn"),
            })
            try:
                new_id = res.scalar_one()
            except Exception:
                # SQLite without RETURNING in old versions; fallback:
                new_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
            ids.append(int(new_id))
    return ids
