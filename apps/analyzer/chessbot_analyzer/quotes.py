"""Curated chess quotations for the intro card.

Deliberately a hand-written table rather than anything generated.

A quote on screen under a real person's name is a factual claim about what
that person said. A language model asked for "a Tal quote" will produce
something that *sounds* like Tal every time, including the times no such
sentence exists — and a chess audience is exactly the audience that notices.
Several of the players in the pool are alive. So: nothing here is generated,
and nothing gets added without being checked.

Everything below is widely documented and repeatedly printed in chess
literature. Even so, treat the list as a draft to be vetted rather than as an
authority: chess quotations are famously passed around with drifting wording,
and a few well-loved ones have never been sourced to their supposed author at
all. Trimming this file costs nothing — a game whose players have no quote
simply shows no quote card.

Keys are the same surname slugs the portrait cache uses, so an author with a
cached portrait gets their face on the card for free.
"""

from __future__ import annotations

import random
import re
from typing import Dict, List, Optional

# Attributed quotes, keyed by the surname slug used for portraits.
BY_PLAYER: Dict[str, List[str]] = {
    "tal": [
        "You must take your opponent into a deep dark forest where two plus "
        "two equals five, and the path leading out is only wide enough for one.",
        "There are two types of sacrifices: correct ones, and mine.",
    ],
    "capablanca": [
        "You may learn much more from a game you lose than from a game you win.",
    ],
    "lasker": [
        "When you see a good move, look for a better one.",
        "On the chessboard lies and hypocrisy do not survive long.",
    ],
    "alekhine": [
        "During a chess competition a chess master should be a combination of "
        "a beast of prey and a monk.",
    ],
    "fischer": [
        "All that matters on the chessboard is good moves.",
    ],
    "botvinnik": [
        "Chess is the art of analysis.",
    ],
    "petrosian": [
        "They say my games should be more interesting. I could be more "
        "interesting, and also lose.",
    ],
    "spassky": [
        "The best indicator of a chess player's form is his ability to sense "
        "the climax of the game.",
    ],
    "karpov": [
        "Chess is everything: art, science and sport.",
    ],
    "kasparov": [
        "Chess is mental torture.",
    ],
    "nimzowitsch": [
        "The threat is stronger than the execution.",
    ],
    "tarrasch": [
        "Chess, like love, like music, has the power to make men happy.",
    ],
    "reti": [
        "The beauty of a move lies not in its appearance but in the thought "
        "behind it.",
    ],
    "smyslov": [
        "In chess, as in life, a man is his own most dangerous opponent.",
    ],
}

# Shown when neither player has an entry above. Attribution still matters, so
# these carry their author too — there is no such thing as an anonymous quote.
GENERAL: List[tuple] = [
    ("Nimzowitsch", "The threat is stronger than the execution."),
    ("Tarrasch", "Chess, like love, like music, has the power to make men happy."),
    ("Lasker", "When you see a good move, look for a better one."),
    ("Capablanca", "You may learn much more from a game you lose than from a "
                   "game you win."),
]


def surname_slug(pgn_name: Optional[str]) -> str:
    """"Tal, Mihail" -> "tal". Matches the portrait cache's key."""
    name = (pgn_name or "").strip()
    if not name or set(name) <= {"?", "."}:
        return ""
    first = name.split(",")[0].strip() if "," in name else name.split()[-1]
    return re.sub(r"[^a-z]", "", first.lower())


def _pretty(slug: str, pgn_name: Optional[str]) -> str:
    """The name to print under the quote."""
    if pgn_name:
        base = pgn_name.split(",")[0].strip() if "," in pgn_name else pgn_name
        base = base.strip()
        if base and not set(base) <= {"?", "."}:
            return base
    return slug.title()


def pick(white: Optional[str], black: Optional[str], *,
         seed: Optional[int] = None) -> Optional[Dict[str, str]]:
    """A quote for this game, preferring one of its own players.

    Returns ``{"text", "author", "portrait"}``, or None when nothing fits —
    the card is decoration, and no card is better than a doubtful one.
    """
    rng = random.Random(seed)

    for pgn_name in (white, black):
        slug = surname_slug(pgn_name)
        options = BY_PLAYER.get(slug)
        if options:
            return {
                "text": rng.choice(options),
                "author": _pretty(slug, pgn_name),
                "portrait": f"{slug}.jpg",
            }

    if not GENERAL:
        return None
    author, text = rng.choice(GENERAL)
    slug = surname_slug(author)
    return {"text": text, "author": author, "portrait": f"{slug}.jpg"}
