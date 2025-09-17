"""
PGN ingestion utilities.

- Supports local .pgn files, directories of PGNs, and .zst-compressed PGNs (Lichess dumps).
- Computes a stable moves_hash to deduplicate games.
- Creates minimal tables (games, analysis_cache, media) if they don't exist.
"""

from __future__ import annotations

import hashlib
import io
import os
import pathlib
import typing as t

import chess.pgn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

try:
    import zstandard as zstd  # for .zst dumps
except Exception:  # pragma: no cover
    zstd = None  # optional


try:
    import requests  # for URL ingestion
except Exception:  # pragma: no cover
    requests = None

from .config import settings


DDL_GAMES = """
CREATE TABLE IF NOT EXISTS games (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  event  TEXT,
  site   TEXT,
  date   DATE,
  white  TEXT,
  black  TEXT,
  result TEXT,
  eco    TEXT,
  ply_count INT,
  pgn    TEXT NOT NULL,
  moves_hash TEXT UNIQUE
);
"""

DDL_ANALYSIS_CACHE = """
CREATE TABLE IF NOT EXISTS analysis_cache (
  id BIGSERIAL PRIMARY KEY,
  game_id BIGINT REFERENCES games(id),
  ply INT,
  fen TEXT,
  multipv_json JSONB,
  pins_json JSONB,
  attacks_json JSONB,
  best_move TEXT,
  alt_moves JSONB,
  eval_cp INT,
  tag TEXT
);
"""

DDL_MEDIA = """
CREATE TABLE IF NOT EXISTS media (
  id BIGSERIAL PRIMARY KEY,
  game_id BIGINT REFERENCES games(id),
  video_path TEXT,
  thumb_path TEXT,
  youtube_id TEXT,
  status TEXT,
  published_at TIMESTAMPTZ
);
"""


def _engine() -> Engine:
    return create_engine(settings.DB_URL)


def ensure_tables(engine: Engine | None = None) -> None:
    """Create minimal tables if absent."""
    engine = engine or _engine()
    with engine.begin() as conn:
        conn.execute(text(DDL_GAMES))
        conn.execute(text(DDL_ANALYSIS_CACHE))
        conn.execute(text(DDL_MEDIA))


def _compute_moves_hash(white: str, black: str, date: str | None, san_moves: list[str]) -> str:
    h = hashlib.sha256()
    key = f"{white}|{black}|{date or ''}|{' '.join(san_moves)}".encode("utf-8", "ignore")
    h.update(key)
    return h.hexdigest()


def _export_clean_pgn(game: chess.pgn.Game) -> str:
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    return game.accept(exporter)


def _iter_pgn_games(stream: t.BinaryIO) -> t.Iterator[chess.pgn.Game]:
    """Yield games from a binary text stream (utf-8 assumed)."""
    # chess.pgn.read_game expects a *text* stream; wrap bytes with TextIOWrapper
    with io.TextIOWrapper(stream, encoding="utf-8", errors="ignore", newline="") as tf:
        while True:
            game = chess.pgn.read_game(tf)
            if game is None:
                break
            yield game


def _iter_zst_games(stream: t.BinaryIO) -> t.Iterator[chess.pgn.Game]:
    if zstd is None:
        raise RuntimeError("zstandard is not installed; cannot read .zst files. Add 'zstandard' to deps.")
    dctx = zstd.ZstdDecompressor()
    with dctx.stream_reader(stream) as reader:
        yield from _iter_pgn_games(reader)


def _san_list(game: chess.pgn.Game) -> list[str]:
    san: list[str] = []
    board = game.board()
    for mv in game.mainline_moves():
        san.append(board.san(mv))
        board.push(mv)
    return san


class GameIngestor:
    """Import PGNs into the database with deduplication."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or _engine()
        ensure_tables(self.engine)

    def ingest_path(self, path: str, source: str = "manual") -> dict:
        """
        Ingest a file or directory.
        - If directory: scans *.pgn and *.pgn.zst.
        Returns counts: {"inserted": n, "duplicates": m, "errors": k}
        """
        p = pathlib.Path(path)
        if not p.exists():
            raise FileNotFoundError(path)

        if p.is_dir():
            inserted = dup = errs = 0
            for entry in p.rglob("*"):
                if entry.is_file() and (entry.suffix.lower() == ".pgn" or entry.suffix.lower() == ".zst"):
                    c = self._ingest_file(entry, source=source)
                    inserted += c["inserted"]
                    dup += c["duplicates"]
                    errs += c["errors"]
            return {"inserted": inserted, "duplicates": dup, "errors": errs}
        else:
            return self._ingest_file(p, source=source)

    def ingest_url(self, url: str, source: str = "lichess") -> dict:
        """
        Ingest a remote PGN or .zst (e.g., Lichess dump URL).
        Requires 'requests' and (for .zst) 'zstandard'.
        """
        if requests is None:
            raise RuntimeError("requests is not installed; cannot fetch URLs. Add 'requests' to deps.")

        inserted = dup = errs = 0
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            if url.endswith(".zst"):
                iterator = _iter_zst_games(io.BytesIO(resp.content))
            else:
                iterator = _iter_pgn_games(io.BytesIO(resp.content))
            for game in iterator:
                ok = self._insert_game(game, source)
                if ok is True:
                    inserted += 1
                elif ok is False:
                    dup += 1
                else:
                    errs += 1
        return {"inserted": inserted, "duplicates": dup, "errors": errs}

    # ---- internals ----

    def _ingest_file(self, path: os.PathLike[str] | str, source: str) -> dict:
        inserted = dup = errs = 0
        path = pathlib.Path(path)
        op = open
        if path.suffix.lower() == ".zst":
            # raw bytes; we'll route through _iter_zst_games
            iterator_factory = _iter_zst_games
        else:
            iterator_factory = _iter_pgn_games

        with op(path, "rb") as f:
            for game in iterator_factory(f):
                ok = self._insert_game(game, source)
                if ok is True:
                    inserted += 1
                elif ok is False:
                    dup += 1
                else:
                    errs += 1

        return {"inserted": inserted, "duplicates": dup, "errors": errs}

    def _insert_game(self, game: chess.pgn.Game, source: str) -> bool | None:
        """Return True if inserted, False if duplicate, None on error."""
        headers = game.headers
        white = headers.get("White", "") or ""
        black = headers.get("Black", "") or ""
        date = headers.get("Date", "") or None
        event = headers.get("Event", "") or None
        site = headers.get("Site", "") or None
        result = headers.get("Result", "") or None
        eco = headers.get("ECO", "") or None

        san_moves = _san_list(game)
        ply_count = len(san_moves)
        pgn_text = _export_clean_pgn(game)
        moves_hash = _compute_moves_hash(white, black, date, san_moves)

        stmt = text(
            """
            INSERT INTO games (source, event, site, date, white, black, result, eco, ply_count, pgn, moves_hash)
            VALUES (:source, :event, :site, NULLIF(:date,''), :white, :black, :result, :eco, :ply_count, :pgn, :moves_hash)
            """
        )

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    stmt,
                    {
                        "source": source,
                        "event": event,
                        "site": site,
                        "date": date,
                        "white": white,
                        "black": black,
                        "result": result,
                        "eco": eco,
                        "ply_count": ply_count,
                        "pgn": pgn_text,
                        "moves_hash": moves_hash,
                    },
                )
            return True
        except IntegrityError:
            # Duplicate by moves_hash UNIQUE constraint
            return False
        except Exception:
            return None
