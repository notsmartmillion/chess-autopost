"""
Chess.com game fetcher.

Usage:
  python services/ingest/chesscom_fetch.py month --user eric --year 2024 --month 11
  python services/ingest/chesscom_fetch.py latest --user eric --months 3

API docs: https://www.chess.com/news/view/published-data-api
"""

from __future__ import annotations

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Optional

import requests
import chess.pgn

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

def fetch_month(username: str, year: int, month: int) -> List[Dict]:
    url = f"https://api.chess.com/pub/player/{username}/games/{year:04d}/{month:02d}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    data = r.json()
    out: List[Dict] = []
    for g in data.get("games", []):
        pgn = g.get("pgn")
        if not pgn:
            # try fallback to downloading PGN file if present (rarely needed)
            continue
        out.append({"pgn": pgn, "meta": _normalize_metadata(pgn)})
    return out

def fetch_latest(username: str, months_back: int = 1) -> List[Dict]:
    """
    Pull recent months archives (up to months_back).
    """
    # First get list of monthly archive URLs
    url = f"https://api.chess.com/pub/player/{username}/games/archives"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    archives = r.json().get("archives", [])
    archives = sorted(archives)[-months_back:] if months_back > 0 else archives[-1:]
    out: List[Dict] = []
    for a in archives:
        rr = requests.get(a, timeout=60)
        rr.raise_for_status()
        data = rr.json()
        for g in data.get("games", []):
            pgn = g.get("pgn")
            if not pgn:
                continue
            out.append({"pgn": pgn, "meta": _normalize_metadata(pgn)})
    return out

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

def _cli():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("month")
    p1.add_argument("--user", required=True)
    p1.add_argument("--year", type=int, required=True)
    p1.add_argument("--month", type=int, required=True)
    p1.add_argument("--out", default="outputs/pgns/chesscom")

    p2 = sub.add_parser("latest")
    p2.add_argument("--user", required=True)
    p2.add_argument("--months", type=int, default=1)
    p2.add_argument("--out", default="outputs/pgns/chesscom")

    args = ap.parse_args()
    if args.cmd == "month":
        games = fetch_month(args.user, args.year, args.month)
        saved = save_pgns(games, Path(args.out))
        print(f"[ok] saved {len(saved)} PGNs → {Path(args.out).resolve()}")
    elif args.cmd == "latest":
        games = fetch_latest(args.user, args.months)
        saved = save_pgns(games, Path(args.out))
        print(f"[ok] saved {len(saved)} PGNs → {Path(args.out).resolve()}")

if __name__ == "__main__":
    _cli()
