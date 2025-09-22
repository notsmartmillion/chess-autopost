"""
Lichess game fetcher.

Usage (examples):
  python services/ingest/lichess_fetch.py export --user notsmartmillion --since 2023-01-01 --until 2023-12-31 --limit 50
  python services/ingest/lichess_fetch.py latest --user notsmartmillion --limit 10

Notes:
- Public endpoints work without a token, but a token (read:study) increases limits.
- Set LICHESS_TOKEN in your .env if available.
"""

from __future__ import annotations

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from dateutil import parser as dtparser

import chess.pgn

# ---------- Helpers ----------

def _headers() -> Dict[str, str]:
    token = os.getenv("LICHESS_TOKEN")
    h = {"Accept": "application/x-ndjson"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def _parse_date(s: Optional[str]) -> Optional[int]:
    """Return Unix ms from YYYY-MM-DD (or None)."""
    if not s:
        return None
    return int(dtparser.parse(s).timestamp() * 1000)

def _iter_ndjson(resp: requests.Response) -> Iterable[Dict]:
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue

def _game_to_pgn(game_json: Dict) -> str:
    """Convert a single Lichess game JSON (from export API) to PGN string."""
    # API already provides "pgn" in many modes. If present, return it.
    if "pgn" in game_json and isinstance(game_json["pgn"], str):
        return game_json["pgn"]

    # Fallback: build a minimal PGN from headers/moves if necessary.
    headers = game_json.get("players", {})
    white = headers.get("white", {}).get("user", {}).get("name") or "White"
    black = headers.get("black", {}).get("user", {}).get("name") or "Black"
    result = game_json.get("status", "")
    site = "https://lichess.org/" + game_json.get("id", "")

    g = chess.pgn.Game()
    g.headers["White"] = white
    g.headers["Black"] = black
    g.headers["Site"] = site
    if "createdAt" in game_json:
        g.headers["Date"] = time.strftime("%Y.%m.%d", time.gmtime(game_json["createdAt"] / 1000))
    if game_json.get("opening"):
        g.headers["ECO"] = game_json["opening"].get("eco", "")
        g.headers["Opening"] = game_json["opening"].get("name", "")

    # If no moves provided, leave empty:
    # Lichess export should include PGN though, so this path is rare.
    return str(g)

def _normalize_metadata(pgn: str) -> Dict:
    """Parse PGN headers into a consistent shape."""
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

# ---------- Public API ----------

def fetch_lichess_games(
    username: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: Optional[int] = None,
    rated_only: bool = False,
) -> List[Dict]:
    """
    Return a list of dicts: {"pgn": "...", "meta": {...}}
    """
    # API docs: https://lichess.org/api#operation/apiGamesUser
    url = f"https://lichess.org/api/games/user/{username}"
    params = {
        "max": min(int(limit), 300) if limit else 50,  # API page max is 300
        "evals": "false",
        "clocks": "false",
        "opening": "true",
        "moves": "true",
        "pgnInJson": "true",
        "perfType": "classical,rapid,blitz",  # adjust as desired
    }
    if rated_only:
        params["rated"] = "true"
    if since:
        params["since"] = _parse_date(since)
    if until:
        params["until"] = _parse_date(until)

    out: List[Dict] = []
    with requests.get(url, headers=_headers(), params=params, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        for j in _iter_ndjson(resp):
            pgn = _game_to_pgn(j)
            out.append({"pgn": pgn, "meta": _normalize_metadata(pgn)})
            if limit and len(out) >= limit:
                break
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

# ---------- CLI ----------

def _cli() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("export", help="Export games within a date range")
    p1.add_argument("--user", required=True)
    p1.add_argument("--since", required=False)
    p1.add_argument("--until", required=False)
    p1.add_argument("--limit", type=int, default=50)
    p1.add_argument("--rated", action="store_true", default=False)
    p1.add_argument("--out", default="outputs/pgns/lichess")

    p2 = sub.add_parser("latest", help="Grab recent games")
    p2.add_argument("--user", required=True)
    p2.add_argument("--limit", type=int, default=10)
    p2.add_argument("--rated", action="store_true", default=False)
    p2.add_argument("--out", default="outputs/pgns/lichess")

    args = ap.parse_args()
    if args.cmd in {"export", "latest"}:
        games = fetch_lichess_games(
            username=args.user,
            since=getattr(args, "since", None),
            until=getattr(args, "until", None),
            limit=args.limit,
            rated_only=args.rated,
        )
        out_dir = Path(args.out)
        saved = save_pgns(games, out_dir)
        print(f"[ok] saved {len(saved)} PGNs → {out_dir.resolve()}")

if __name__ == "__main__":
    _cli()
