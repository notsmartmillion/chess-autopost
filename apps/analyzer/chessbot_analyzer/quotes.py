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

Deliberately NOT included, from lists that circulate online:

* "Chess is the gymnasium of the mind" (Pascal). A famous orphan — it appears
  nowhere in Pascal, and is handed to Lenin about as often, with as little
  evidence. Exactly the kind of line a chess audience enjoys correcting.
* Anything political. One widely circulated list attributes a chess quote to
  Vladimir Putin; true or not, a head of state's name over a Russian
  grandmaster's game is a comment this channel is not making, and it would
  post unattended at three in the morning.
* Quotations too long to read in the seconds the card is on screen, and
  quotations whose only interest is a dated joke about women or rabbits.
"""

from __future__ import annotations

import random
import re
from typing import Dict, List, Optional, Tuple

# A quote has to be read off a card in a few seconds. Longer than this and it
# either shrinks past legibility or outlasts the intro.
MAX_CHARS = 190

# Attributed quotes, keyed by the surname slug used for portraits.
BY_PLAYER: Dict[str, List[str]] = {
    "tal": [
        "You must take your opponent into a deep dark forest where two plus "
        "two equals five, and the path leading out is only wide enough for one.",
        "There are two types of sacrifices: correct ones, and mine.",
    ],
    "capablanca": [
        "You may learn much more from a game you lose than from a game you win.",
        "A good player is always lucky.",
        "Chess is a very logical game, and it is the man who can reason most "
        "logically and profoundly in it that ought to win.",
    ],
    "lasker": [
        "When you see a good move, look for a better one.",
        "On the chessboard lies and hypocrisy do not survive long.",
        "The hardest game to win is a won game.",
    ],
    "alekhine": [
        "During a chess competition a chess master should be a combination of "
        "a beast of prey and a monk.",
        "I think up my own moves, and I make my opponent think up his.",
    ],
    "fischer": [
        "All that matters on the chessboard is good moves.",
        "I don't believe in psychology. I believe in good moves.",
        "Chess is a war over the board. The object is to crush the opponent's mind.",
        "Your chess deteriorates as your body does. You cannot separate body and mind.",
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
        "I used to attack because it was the only thing I knew. Now I attack "
        "because I know it works best.",
    ],
    "kramnik": [
        "I don't know whether computers are improving the style of play. "
        "I know they are changing it.",
    ],
    "nimzowitsch": [
        "The threat is stronger than the execution.",
        "Even the laziest king flees wildly in the face of a double check.",
    ],
    "tarrasch": [
        "Chess, like love, like music, has the power to make men happy.",
        "One does not have to play well; it is enough to play better than "
        "your opponent.",
        "Up to this point White has been following well-known analysis. But "
        "now he makes a fatal error: he begins to use his own head.",
        "He who fears an isolated queen's pawn should give up chess.",
    ],
    "reti": [
        "The beauty of a move lies not in its appearance but in the thought "
        "behind it.",
        "In the idea of chess and the development of the chess mind we have a "
        "picture of the intellectual struggle of mankind.",
    ],
    "smyslov": [
        "In chess, as in life, a man is his own most dangerous opponent.",
    ],
    "steinitz": [
        "Only the player with the initiative has the right to attack.",
        "A win by an unsound combination, however showy, fills me with "
        "artistic horror.",
        "Chess is not for timid souls.",
    ],
    "morphy": [
        "Help your pieces so they can help you.",
    ],
    "spielmann": [
        "We cannot resist the fascination of sacrifice, since a passion for "
        "sacrifices is part of a chess player's nature.",
        "Play the opening like a book, the middlegame like a magician, and "
        "the endgame like a machine.",
    ],
    "tartakower": [
        "Tactics is knowing what to do when there is something to do; "
        "strategy is knowing what to do when there is nothing to do.",
        "It is always better to sacrifice your opponent's men.",
        "Chess is a fairy tale of one thousand and one blunders.",
    ],
    "zukertort": [
        "Chess is the struggle against the error.",
    ],
    "chigorin": [
        "Even a poor plan is better than no plan at all.",
    ],
    "timman": [
        "Half the variations calculated in a tournament game turn out to be "
        "completely superfluous. Unfortunately, no one knows which half.",
    ],
    "short": [
        "If your opponent offers you a draw, try to work out why he thinks "
        "he is worse off.",
    ],
    "hubner": [
        "Those who say they understand chess understand nothing.",
    ],
    "prins": [
        "The only thing chess players have in common is chess.",
    ],
    "horwitz": [
        "One bad move nullifies forty good ones.",
    ],
    "reinfeld": [
        "The pin is mightier than the sword.",
    ],
    "chernev": [
        "Every chess master was once a beginner.",
    ],
    "mednis": [
        "After a bad opening there is hope for the middlegame. After a bad "
        "middlegame there is hope for the endgame. But once you are in the "
        "endgame, the moment of truth has arrived.",
    ],
    "flohr": [
        "Chess, like love, is infectious at any age.",
    ],
    "napier": [
        "Life is not long enough for chess — but that is the fault of life, "
        "not chess.",
    ],
    "ree": [
        "Chess is beautiful enough to waste your life for.",
    ],
    "pollock": [
        "It is no easy matter to reply correctly to Lasker's bad moves.",
    ],
    "emms": [
        "It doesn't matter how strong a player you are: if you fail to "
        "develop in the opening, you are asking for trouble.",
    ],
}

# Writers, scientists and novelists on chess. Shown when neither player has an
# entry above — and the players' own words are pooled in as well, so the
# fallback is as varied as the table is long.
GENERAL: List[Tuple[str, str]] = [
    ("Einstein", "Chess holds its master in its own bonds, shackling the mind "
                 "and brain so that the inner freedom of the very strongest "
                 "must suffer."),
    ("Goethe", "To venture an opinion is like moving a piece at chess: it may "
               "be taken, but it forms the beginning of a game that is won."),
    ("E. M. Forster", "Chess is a forcing house where the fruits of character "
                      "can ripen more fully than in life."),
    ("H. G. Wells", "Chess is a curse upon a man."),
    ("David Shenk", "Chess is rarely a game of ideal moves. Almost always, a "
                    "player faces a series of difficult consequences whichever "
                    "move he makes."),
    ("Charles Buxton", "In life, as in chess, forethought wins."),
    ("Dominic Lawson", "Nothing excites jaded grandmasters more than a "
                       "theoretical novelty."),
    ("Ralph Charell", "Avoid the crowd. Do your own thinking independently. "
                      "Be the chess player, not the chess piece."),
    ("Renaud and Kahn", "Chess is played with the mind, not with the hands."),
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

    # Neither player is quotable. Fall back to the whole table — a player's
    # own words are worth showing even when he is not at this board — plus the
    # writers. Sorted so the pool is identical run to run before the draw.
    pool: List[Tuple[str, str]] = [
        (slug.title(), text)
        for slug in sorted(BY_PLAYER)
        for text in BY_PLAYER[slug]
    ] + sorted(GENERAL)
    if not pool:
        return None
    author, text = rng.choice(pool)
    return {
        "text": text,
        "author": author,
        "portrait": f"{surname_slug(author)}.jpg",
    }
