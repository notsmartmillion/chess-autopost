"""PGN ingestion: download & store games from Lichess and Chess.com."""

from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import chess.pgn
import requests

from .config import settings
from .utils.logging import get_logger

logger = get_logger(__name__)

# Where we place downloaded PGNs
PGN_DIR = Path(settings.OUTPUT_DIR).parent / "storage" / "pgns"
PGN_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------- utilities -------------------------------- #

def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    for ch in bad:
        s = s.replace(ch, "_")
    return s.strip().replace(" ", "_")


def _normalize_pgn_for_hash(pgn: str) -> str:
    """Strip comments/clock/evals; keep headers+moves so we can dedup."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None:
            return pgn.strip()
        # Re-emit compact PGN: headers then SAN moves only.
        out = io.StringIO()
        headers = "\n".join(f'[{k} "{v}"]' for k, v in game.headers.items())
        out.write(headers + "\n\n")
        board = game.board()
        moves = []
        for mv in game.mainline_moves():
            moves.append(board.san(mv))
            board.push(mv)
        out.write(" ".join(moves))
        return out.getvalue().strip()
    except Exception:
        return pgn.strip()


def pgn_hash(pgn: str) -> str:
    return hashlib.sha1(_normalize_pgn_for_hash(pgn).encode("utf-8")).hexdigest()


def save_unique_pgn(pgn: str, source: str = "unknown") -> Optional[Path]:
    """Save PGN if not already on disk. Returns path or None if duplicate/invalid."""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None:
            return None
        hv = pgn_hash(pgn)
        white = _safe_filename(game.headers.get("White", "White"))
        black = _safe_filename(game.headers.get("Black", "Black"))
        date = _safe_filename(game.headers.get("Date", "????.??.??"))
        event = _safe_filename(game.headers.get("Event", source))

        fname = f"{date}_{white}_vs_{black}_{event}_{hv[:10]}.pgn"
        fpath = PGN_DIR / fname
        if fpath.exists():
            logger.info(f"Skip duplicate: {fpath.name}")
            return None

        fpath.write_text(pgn, encoding="utf-8")
        logger.info(f"Saved PGN → {fpath.relative_to(PGN_DIR.parent)}")
        return fpath
    except Exception as e:
        logger.warning(f"Failed to save PGN: {e}")
        return None


# ------------------------------- lichess ----------------------------------- #

@dataclass
class LichessQuery:
    username: str
    max_games: int = 100
    since_ms: Optional[int] = None
    until_ms: Optional[int] = None
    perf_type: Optional[str] = None  # "classical","rapid","blitz","bullet","correspondence"
    rated: Optional[bool] = None
    pgn_in_json: bool = True
    opening: bool = True


def download_lichess_user_games(q: LichessQuery) -> List[Path]:
    """
    Download games for a user from Lichess Export API.
    Docs: https://lichess.org/api#operation/apiGamesUser
    """
    url = f"https://lichess.org/api/games/user/{q.username}"
    headers = {"Accept": "application/x-ndjson"}
    if settings.LICHESS_TOKEN:
        headers["Authorization"] = f"Bearer {settings.LICHESS_TOKEN}"

    params = {
        "max": q.max_games,
        "moves": "true",
        "clocks": "false",
        "evals": "false",
        "opening": "true" if q.opening else "false",
        "pgnInJson": "true" if q.pgn_in_json else "false",
        "since": q.since_ms or "",
        "until": q.until_ms or "",
    }
    if q.perf_type:
        params["perfType"] = q.perf_type
    if q.rated is not None:
        params["rated"] = "true" if q.rated else "false"

    logger.info(f"[lichess] GET {url} (max={q.max_games}, perf={q.perf_type})")
    with requests.get(url, headers=headers, params=params, stream=True, timeout=60) as r:
        r.raise_for_status()
        saved: List[Path] = []
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            # if pgnInJson=true, line is JSON with a "pgn" field
            if q.pgn_in_json:
                try:
                    obj = json.loads(line)
                    pgn = obj.get("pgn")
                    if pgn:
                        p = save_unique_pgn(pgn, source=f"lichess:{q.username}")
                        if p:
                            saved.append(p)
                except json.JSONDecodeError:
                    # If server responded with raw PGN lines (rare), try to buffer them
                    pass
            else:
                # raw PGN stream (rarely used here)
                p = save_unique_pgn(line, source=f"lichess:{q.username}")
                if p:
                    saved.append(p)
        return saved


# ------------------------------- chess.com --------------------------------- #

def _chesscom_get_archives(username: str) -> List[str]:
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    logger.info(f"[chess.com] GET archives {username}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    return list(data.get("archives", []))


def download_chesscom_user_games(
    username: str,
    year_from: Optional[int] = None,
    month_from: Optional[int] = None,
    year_to: Optional[int] = None,
    month_to: Optional[int] = None,
    max_months: Optional[int] = None,
) -> List[Path]:
    """
    Fetch Chess.com monthly archives for a player, extract PGNs.
    Public docs: https://www.chess.com/news/view/published-data-api
    """
    archives = _chesscom_get_archives(username)
    # Filter by range, if provided
    def in_range(url: str) -> bool:
        # urls look like .../games/YYYY/MM
        try:
            parts = url.rstrip("/").split("/")
            yy = int(parts[-2]); mm = int(parts[-1])
        except Exception:
            return True
        def key(y: int, m: int) -> int: return y * 12 + m
        if year_from and month_from and key(yy, mm) < key(year_from, month_from):
            return False
        if year_to and month_to and key(yy, mm) > key(year_to, month_to):
            return False
        return True

    archives = [u for u in archives if in_range(u)]
    if max_months:
        archives = archives[-max_months:]

    saved: List[Path] = []
    for url in archives:
        logger.info(f"[chess.com] GET {url}")
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            logger.warning(f"[chess.com] {url} -> {r.status_code}")
            continue
        data = r.json()
        games = data.get("games", [])
        for g in games:
            pgn = g.get("pgn")
            if not pgn:
                # some entries have only FEN/moves; skip
                continue
            p = save_unique_pgn(pgn, source=f"chesscom:{username}")
            if p:
                saved.append(p)
    return saved


# ------------------------------- folder ingest ----------------------------- #

def read_pgn_files(folder: Path = PGN_DIR) -> List[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return sorted([p for p in folder.glob("*.pgn") if p.is_file()])


def read_pgn_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
