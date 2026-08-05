"""Classic master-game sourcing for the daily video.

The channel format is "famous game, deeply narrated", so the primary source is
a curated set of world-champion / legend game collections (PgnMentor archive,
mirrored on GitHub) rather than random online blitz.

Player files are downloaded once and cached under ``outputs/pgns/classics``,
after which the pipeline runs fully offline.

Usage:
    python services/orchestrator/ingest/classics_fetch.py --player Tal
    python services/orchestrator/ingest/classics_fetch.py --list
"""

from __future__ import annotations

import argparse
import io
import random
import re
from pathlib import Path
from typing import Dict, List, Optional

import chess.pgn
import requests

ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = ROOT / "outputs" / "pgns" / "classics"

BASE_URL = "https://raw.githubusercontent.com/rozim/ChessData/master/PgnMentor"

# Legends whose collections make good narrated content. The value is the
# display name used when the PGN headers are terse.
LEGENDS: Dict[str, str] = {
    # --- romantic and classical, to 1945 ---
    "Morphy": "Paul Morphy",
    "Steinitz": "Wilhelm Steinitz",
    "Zukertort": "Johannes Zukertort",
    "Chigorin": "Mikhail Chigorin",
    "Lasker": "Emanuel Lasker",
    "Tarrasch": "Siegbert Tarrasch",
    "Pillsbury": "Harry Nelson Pillsbury",
    "Marshall": "Frank Marshall",
    "Schlechter": "Carl Schlechter",
    "Rubinstein": "Akiba Rubinstein",
    "Capablanca": "Jose Raul Capablanca",
    "Alekhine": "Alexander Alekhine",
    "Nimzowitsch": "Aron Nimzowitsch",
    "Reti": "Richard Reti",
    "Euwe": "Max Euwe",
    "Spielmann": "Rudolf Spielmann",
    "Tartakower": "Savielly Tartakower",
    # --- the Soviet school and its rivals, 1945-1990 ---
    "Botvinnik": "Mikhail Botvinnik",
    "Smyslov": "Vasily Smyslov",
    "Tal": "Mikhail Tal",
    "Petrosian": "Tigran Petrosian",
    "Spassky": "Boris Spassky",
    "Fischer": "Bobby Fischer",
    "Karpov": "Anatoly Karpov",
    "Korchnoi": "Viktor Korchnoi",
    "Bronstein": "David Bronstein",
    "Keres": "Paul Keres",
    "Geller": "Efim Geller",
    "Larsen": "Bent Larsen",
    "Najdorf": "Miguel Najdorf",
    "Gligoric": "Svetozar Gligoric",
    "Portisch": "Lajos Portisch",
    "Reshevsky": "Samuel Reshevsky",
    "Taimanov": "Mark Taimanov",
    "Stein": "Leonid Stein",
    # --- the professional era, 1990-2010 ---
    "Kasparov": "Garry Kasparov",
    "Anand": "Viswanathan Anand",
    "Kramnik": "Vladimir Kramnik",
    "Ivanchuk": "Vassily Ivanchuk",
    "Shirov": "Alexei Shirov",
    "Topalov": "Veselin Topalov",
    "Gelfand": "Boris Gelfand",
    "Short": "Nigel Short",
    "Timman": "Jan Timman",
    "Adams": "Michael Adams",
    "Leko": "Peter Leko",
    "Morozevich": "Alexander Morozevich",
    "Ponomariov": "Ruslan Ponomariov",
    "Svidler": "Peter Svidler",
    "Seirawan": "Yasser Seirawan",
    "Andersson": "Ulf Andersson",
    # --- players the audience can watch this week ---
    "Carlsen": "Magnus Carlsen",
    "Nakamura": "Hikaru Nakamura",
    "Caruana": "Fabiano Caruana",
    "So": "Wesley So",
    "Ding": "Ding Liren",
    "Nepomniachtchi": "Ian Nepomniachtchi",
    "Giri": "Anish Giri",
    "Aronian": "Levon Aronian",
    "Grischuk": "Alexander Grischuk",
    "Karjakin": "Sergey Karjakin",
    "Radjabov": "Teimour Radjabov",
    "Mamedyarov": "Shakhriyar Mamedyarov",
    "Firouzja": "Alireza Firouzja",
    "Duda": "Jan-Krzysztof Duda",
    "Rapport": "Richard Rapport",
    "Wojtaszek": "Radoslaw Wojtaszek",
}

# Which era each legend belongs to, so the channel can deliberately alternate
# rather than trust a shuffle.
#
# A pool that was eighteen names, all but three of them dead, produced a run
# of videos where every thumbnail was a grainy portrait from the 1950s. A
# viewer searching "Hikaru" or "Magnus" — the two most-searched names in
# chess — found nothing here. Weighting the draw toward living players who
# are still competing is how a back catalogue of classics gets discovered at
# all: the recent names bring the traffic, the classics keep it.
ERAS: Dict[str, tuple] = {
    "classical": (
        "Morphy", "Steinitz", "Zukertort", "Chigorin", "Lasker", "Tarrasch",
        "Pillsbury", "Marshall", "Schlechter", "Rubinstein", "Capablanca",
        "Alekhine", "Nimzowitsch", "Reti", "Euwe", "Spielmann", "Tartakower",
    ),
    "soviet": (
        "Botvinnik", "Smyslov", "Tal", "Petrosian", "Spassky", "Fischer",
        "Karpov", "Korchnoi", "Bronstein", "Keres", "Geller", "Larsen",
        "Najdorf", "Gligoric", "Portisch", "Reshevsky", "Taimanov", "Stein",
    ),
    "professional": (
        "Kasparov", "Anand", "Kramnik", "Ivanchuk", "Shirov", "Topalov",
        "Gelfand", "Short", "Timman", "Adams", "Leko", "Morozevich",
        "Ponomariov", "Svidler", "Seirawan", "Andersson",
    ),
    "current": (
        "Carlsen", "Nakamura", "Caruana", "So", "Ding", "Nepomniachtchi",
        "Giri", "Aronian", "Grischuk", "Karjakin", "Radjabov", "Mamedyarov",
        "Firouzja", "Duda", "Rapport", "Wojtaszek",
    ),
}

# Draw weights. Deliberately front-loaded onto players who are still playing:
# they are what people search for, and a channel nobody finds cannot show
# anybody a Capablanca endgame.
ERA_WEIGHTS: Dict[str, float] = {
    "current": 0.40,
    "professional": 0.25,
    "soviet": 0.25,
    "classical": 0.10,
}


def pick_era(rng: Optional[random.Random] = None) -> str:
    r = rng or random
    names = list(ERA_WEIGHTS)
    return r.choices(names, weights=[ERA_WEIGHTS[n] for n in names], k=1)[0]


def _user_agent() -> str:
    return "chess-autopost/1.0 (daily chess video bot)"


def ensure_player_pgn(player: str, *, force: bool = False) -> Path:
    """Download (once) and return the local path to a player's game collection."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / f"{player}.pgn"
    if dest.exists() and dest.stat().st_size > 1000 and not force:
        return dest

    url = f"{BASE_URL}/{player}.pgn"
    resp = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=180)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def _clean(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if not v or set(v) <= {"?", "."}:
        return None
    return v


def _year(date_header: Optional[str]) -> Optional[int]:
    d = _clean(date_header)
    if not d:
        return None
    m = re.match(r"(\d{4})", d)
    return int(m.group(1)) if m else None


# Names a browsing chess viewer recognises without being told who they are.
# The pool's own legends plus the opponents worth billing beside them: the
# collections are full of games against club players and long-forgotten
# masters, and "Lasker vs Didier" asks the audience to care about a name they
# have never seen.
#
# This exists because of what the competition looks like. A channel running
# this same format — near-daily narrated classics, consistent template — sat
# at 244 uploads and single-digit views per video, while the genre's biggest
# channel covers famous players in famous games almost exclusively. Cadence
# and polish were never the difference; the matchup on the thumbnail is.
FAMOUS: set = {k.lower() for k in LEGENDS} | {
    "nimzowitsch", "reti", "euwe", "steinitz", "zukertort", "marshall",
    "pillsbury", "chigorin", "tarrasch", "korchnoi", "larsen", "polgar",
    "nakamura", "caruana", "ding", "nepomniachtchi", "aronian", "topalov",
    "ivanchuk", "shirov", "short", "timman", "portisch", "gligoric",
    "geller", "taimanov", "averbakh", "polugaevsky", "stein", "najdorf",
    "reshevsky", "flohr", "boleslavsky", "szabo", "beliavsky", "andersson",
    "seirawan", "adams", "svidler", "grischuk", "giri", "so", "firouzja",
    "dubov", "rapport", "vidit", "gukesh", "praggnanandhaa", "erigaisi",
    "morozevich", "leko", "ponomariov", "khalifman", "kasimdzhanov",
    "bogoljubov", "spielmann", "tartakower", "rubinstein", "schlechter",
    "janowski", "burn", "blackburne", "winawer", "gunsberg", "showalter",
}

# Events that carry their own weight in a title.
BIG_EVENTS = (
    "world championship", "world chess championship", "candidates",
    "interzonal", "olympiad", "linares", "wijk aan zee", "tata steel",
    "hoogovens", "corus", "dortmund", "tal memorial", "sinquefield",
    "zurich", "avro", "nottingham", "hastings",
)


def _surname(raw: Optional[str]) -> str:
    v = _clean(raw) or ""
    first = v.split(",")[0] if "," in v else v.split(" ")[-1]
    return re.sub(r"[^a-z]", "", first.lower())


def is_famous(raw: Optional[str]) -> bool:
    return _surname(raw) in FAMOUS


def score_game(headers: chess.pgn.Headers, plies: int, hero: str) -> float:
    """Heuristic 'is this a good video' score, before any engine analysis."""
    score = 0.0
    result = _clean(headers.get("Result")) or "*"

    # Decisive games tell a story; draws rarely do.
    if result in ("1-0", "0-1"):
        score += 40
    elif result == "1/2-1/2":
        score -= 25
    else:
        return -1000  # unfinished

    # Sweet spot for a 8-12 minute narrated video.
    if 40 <= plies <= 90:
        score += 35
    elif 30 <= plies < 40 or 90 < plies <= 110:
        score += 15
    elif plies < 24:
        return -1000  # too short to narrate
    elif plies > 140:
        score -= 20

    # Prefer games the legend won — brilliancies, not losses.
    white = (_clean(headers.get("White")) or "").lower()
    black = (_clean(headers.get("Black")) or "").lower()
    hero_l = hero.lower()
    if result == "1-0" and hero_l in white:
        score += 20
    elif result == "0-1" and hero_l in black:
        score += 20

    # A named event beats an unknown one, and a famous one sells itself.
    event = (_clean(headers.get("Event")) or "").lower()
    if event:
        score += 8
    if any(e in event for e in BIG_EVENTS):
        score += 18

    # Both players identified.
    if _clean(headers.get("White")) and _clean(headers.get("Black")):
        score += 8

    # The matchup. One legend is a given — it is their collection — so what
    # decides whether the thumbnail reads as an event is the OTHER name.
    # Weighted heavily on purpose: a famous pairing is the single strongest
    # predictor available before any analysis, and the pool is large enough
    # that insisting on one rarely comes up empty.
    opponent = headers.get("Black") if _surname(headers.get("White")) == _surname(hero) \
        else headers.get("White")
    if is_famous(opponent):
        score += 60

    year = _year(headers.get("Date"))
    if year:
        score += 5

    score += random.uniform(0, 12)  # keep daily picks varied
    return score


def iter_games(pgn_path: Path, limit: Optional[int] = None):
    """Yield (headers, game, pgn_text, plies) for each game in a collection."""
    text = pgn_path.read_text(encoding="utf-8", errors="ignore")
    stream = io.StringIO(text)
    count = 0
    while True:
        offset = stream.tell()
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        end = stream.tell()
        stream.seek(offset)
        raw = stream.read(end - offset)
        stream.seek(end)

        plies = len(list(game.mainline_moves()))
        yield game.headers, game, raw, plies
        count += 1
        if limit and count >= limit:
            break


def pick_game(
    player: Optional[str] = None,
    *,
    exclude_hashes: Optional[set] = None,
    hash_fn=None,
    sample: int = 400,
) -> Optional[Dict]:
    """Pick the best unused classic game from a legend's collection.

    Returns {"pgn", "headers", "plies", "score", "player"} or None.
    """
    exclude_hashes = exclude_hashes or set()
    chosen_player = player or random.choice(list(LEGENDS))

    try:
        pgn_path = ensure_player_pgn(chosen_player)
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller's log
        raise RuntimeError(f"could not obtain games for {chosen_player}: {exc}") from exc

    hero_surname = chosen_player
    candidates: List[Dict] = []

    all_games = list(iter_games(pgn_path))
    if not all_games:
        return None

    # Sample rather than scoring thousands of games every day.
    pool = random.sample(all_games, min(sample, len(all_games)))

    for headers, _game, raw, plies in pool:
        if hash_fn is not None:
            h = hash_fn(raw)
            if h in exclude_hashes:
                continue
        else:
            h = None
        s = score_game(headers, plies, hero_surname)
        if s <= 0:
            continue
        candidates.append(
            {
                "pgn": raw,
                "headers": dict(headers),
                "plies": plies,
                "score": s,
                "player": LEGENDS.get(chosen_player, chosen_player),
                "hash": h,
            }
        )

    if not candidates:
        return None
    return max(candidates, key=lambda c: c["score"])


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Fetch classic master games")
    ap.add_argument("--player", default=None, help=f"One of: {', '.join(LEGENDS)}")
    ap.add_argument("--list", action="store_true", help="List available legends")
    ap.add_argument("--out", default=None, help="Write the picked game to this path")
    args = ap.parse_args()

    if args.list:
        for key, name in LEGENDS.items():
            print(f"{key:<12} {name}")
        return

    pick = pick_game(args.player)
    if not pick:
        print("no suitable game found")
        return
    h = pick["headers"]
    print(f"{h.get('White')} vs {h.get('Black')} — {h.get('Result')} — "
          f"{h.get('Event')} {h.get('Date')} ({pick['plies']} plies, score {pick['score']:.1f})")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(pick["pgn"], encoding="utf-8")
        print(f"[ok] wrote {args.out}")


if __name__ == "__main__":
    _cli()
