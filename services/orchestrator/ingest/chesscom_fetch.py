"""
Chess.com game fetcher.

Usage:
  python services/orchestrator/ingest/chesscom_fetch.py month --user eric --year 2024 --month 11
  python services/orchestrator/ingest/chesscom_fetch.py latest --user eric --months 3

Notes:
- Chess.com requires a custom User-Agent header. This script sends one by default.
  You can override with --ua or CHESSCOM_USER_AGENT env var.
- API docs: https://www.chess.com/news/view/published-data-api
"""

from __future__ import annotations

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, List, Optional

import requests
import chess.pgn

# ----------------- Config / headers -----------------

def _user_agent(override: Optional[str] = None) -> str:
    if override:
        return override
    return (
        os.getenv("CHESSCOM_USER_AGENT")
        or "EricChessAutopost/1.0 (+contact: youremail@example.com)"
    )

def _headers(ua: Optional[str] = None) -> Dict[str, str]:
    return {"User-Agent": _user_agent(ua)}

def _get_json(url: str, ua: Optional[str], timeout: int = 60, retries: int = 3, backoff: float = 1.5) -> Dict:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=_headers(ua), timeout=timeout)
            # Handle 429/5xx politely with backoff
            if r.status_code in (429, 500, 502, 503, 504):
                wait = backoff ** (attempt - 1)
                time.sleep(wait)
                last_err = requests.HTTPError(f"{r.status_code} for {url}")
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            # small linear backoff for all other cases
            time.sleep(0.75 * attempt)
    raise last_err or RuntimeError(f"Failed to fetch {url}")

# ----------------- PGN helpers -----------------

def _normalize_metadata(pgn: str) -> Dict:
    game = chess.pgn.read_game(io := __import__("io").StringIO(pgn))
    headers = game.headers if game else {}
    meta = {
        "white": headers.get("White"),
        "black": headers.get("Black"),
        "date": headers.get("Date"),
        "event": headers.get("Event"),
        "result": headers.get("Result"),
        "eco": headers.get("ECO"),
        "site": headers.get("Site"),
        "ply_count": None,
    }
    if game:
        ply = 0
        node = game
        while node.variations:
            node = node.variations[0]
            ply += 1
        meta["ply_count"] = ply
    return meta

# ----------------- Fetchers -----------------

def fetch_month(username: str, year: int, month: int, ua: Optional[str]) -> List[Dict]:
    url = f"https://api.chess.com/pub/player/{username}/games/{year:04d}/{month:02d}"
    data = _get_json(url, ua=ua)
    out: List[Dict] = []
    for g in data.get("games", []):
        pgn = g.get("pgn")
        if not pgn:
            continue
        out.append({"pgn": pgn, "meta": _normalize_metadata(pgn)})
    return out

def fetch_latest(username: str, months_back: int = 1, ua: Optional[str] = None) -> List[Dict]:
    """
    Pull recent months archives (up to months_back).
    """
    # List monthly archive URLs
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    data = _get_json(url, ua=ua)
    archives = data.get("archives", [])
    archives = sorted(archives)[-months_back:] if months_back > 0 else archives[-1:]
    out: List[Dict] = []
    for a in archives:
        month_data = _get_json(a, ua=ua)
        for g in month_data.get("games", []):
            pgn = g.get("pgn")
            if not pgn:
                continue
            out.append({"pgn": pgn, "meta": _normalize_metadata(pgn)})
        # small courtesy delay
        time.sleep(0.25)
    return out

# ----------------- IO -----------------

def save_pgns(games: List[Dict], dest_dir: Path) -> List[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for i, g in enumerate(games, start=1):
        w = (g["meta"].get("white") or "White").replace(" ", "_")
        b = (g["meta"].get("black") or "Black").replace(" ", "_")
        fname = f"{i:03d}_{w}_vs_{b}.pgn"
        p = dest_dir / fname
        p.write_text(g["pgn"], encoding="utf-8")
        paths.append(p)
    return paths

# ----------------- CLI -----------------

def _cli():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("month", help="Fetch a single month")
    p1.add_argument("--user", required=True, help="Chess.com username (case-insensitive)")
    p1.add_argument("--year", type=int, required=True)
    p1.add_argument("--month", type=int, required=True)
    p1.add_argument("--out", default="outputs/pgns/chesscom")
    p1.add_argument("--ua", default=None, help="Custom User-Agent (overrides env)")

    p2 = sub.add_parser("latest", help="Fetch last N months")
    p2.add_argument("--user", required=True, help="Chess.com username (case-insensitive)")
    p2.add_argument("--months", type=int, default=1)
    p2.add_argument("--out", default="outputs/pgns/chesscom")
    p2.add_argument("--ua", default=None, help="Custom User-Agent (overrides env)")

    args = ap.parse_args()
    user = args.user.strip()

    if args.cmd == "month":
        games = fetch_month(user, args.year, args.month, ua=args.ua)
        saved = save_pgns(games, Path(args.out))
        print(f"[ok] saved {len(saved)} PGNs → {Path(args.out).resolve()}")
    elif args.cmd == "latest":
        games = fetch_latest(user, args.months, ua=args.ua)
        saved = save_pgns(games, Path(args.out))
        print(f"[ok] saved {len(saved)} PGNs → {Path(args.out).resolve()}")

if __name__ == "__main__":
    _cli()
