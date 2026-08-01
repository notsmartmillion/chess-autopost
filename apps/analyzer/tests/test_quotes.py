"""The quote table is hand-maintained, so guard the things hands get wrong.

None of this can tell you whether a quotation is genuine — only a human
reading a source can. What it can do is stop the mechanical failures: a line
too long for the card, the same quote entered twice under two spellings, an
author whose name will not render, or a pick that changes between runs and
quietly makes yesterday's video a different video.
"""

from __future__ import annotations

import re

from chessbot_analyzer import quotes


def _all_texts():
    for slug, texts in quotes.BY_PLAYER.items():
        for t in texts:
            yield slug, t
    for author, t in quotes.GENERAL:
        yield author, t


def test_quotes_fit_the_card():
    too_long = [(who, t) for who, t in _all_texts() if len(t) > quotes.MAX_CHARS]
    assert not too_long, f"quotes exceed MAX_CHARS: {[t[:40] for _, t in too_long]}"


def test_no_duplicate_quotes():
    seen = {}
    for who, t in _all_texts():
        key = re.sub(r"[^a-z]", "", t.lower())
        assert key not in seen, f"duplicate quote under {who} and {seen[key]}"
        seen[key] = who


def test_every_quote_is_a_sentence():
    for who, t in _all_texts():
        assert t[0].isupper(), f"{who}: does not start with a capital"
        assert t.rstrip()[-1] in ".!?", f"{who}: does not end with a full stop"


def test_player_keys_are_portrait_slugs():
    for slug in quotes.BY_PLAYER:
        assert re.fullmatch(r"[a-z]+", slug), f"{slug!r} is not a portrait slug"


def test_pick_prefers_a_player_in_the_game():
    q = quotes.pick("Tal, Mihail", "Botvinnik, Mikhail", seed=1)
    assert q["author"] == "Tal"
    assert q["text"] in quotes.BY_PLAYER["tal"]
    assert q["portrait"] == "tal.jpg"


def test_pick_falls_back_when_neither_player_is_quotable():
    q = quotes.pick("Nobody, A", "Someone, B", seed=1)
    assert q and q["text"] and q["author"]


def test_pick_is_stable_for_the_same_pairing():
    a = quotes.pick("Nobody, A", "Someone, B", seed=7)
    b = quotes.pick("Nobody, A", "Someone, B", seed=7)
    assert a == b


def test_pick_survives_missing_names():
    assert quotes.pick(None, None, seed=1) is not None
    assert quotes.pick("?", "?", seed=1) is not None
