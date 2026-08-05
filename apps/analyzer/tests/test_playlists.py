"""Which playlists a game belongs in is decided once, in the director.

The uploader must not own this: the channel would end up with both a
"Bobby Fischer" and a "Fischer" list the moment the two name tables drifted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chessbot_analyzer.director import playlists_for, COMMON_NAMES  # noqa: E402


def test_both_recognisable_players_get_a_playlist():
    assert playlists_for({"white": "Kramnik,V", "black": "Aronian,L"}) == [
        "Vladimir Kramnik", "Levon Aronian",
    ]


def test_an_unknown_opponent_gets_none():
    """A "Didier" playlist of one video helps nobody find anything."""
    assert playlists_for({"white": "Lasker, Emanuel", "black": "Didier, M1."}) == [
        "Emanuel Lasker",
    ]


def test_names_match_the_ones_printed_on_screen():
    """The playlist name is the resolved name, never the raw header."""
    out = playlists_for({"white": "Fischer, Robert James", "black": "Spassky, Boris V"})
    assert out == ["Bobby Fischer", "Boris Spassky"]


def test_missing_players_are_survivable():
    assert playlists_for({"white": "?", "black": None}) == []
    assert playlists_for({}) == []


def test_a_player_is_never_listed_twice():
    assert playlists_for({"white": "Tal, Mihail", "black": "Tal, Mihail"}) == [
        "Mikhail Tal",
    ]


def test_every_playlist_name_is_a_full_name():
    """A bare surname as a playlist title would read as a different channel's."""
    for surname, full in COMMON_NAMES.items():
        assert " " in full, f"{surname} resolves to {full!r}, which has no given name"
        assert full.split()[-1].lower().startswith(surname[:4]) or surname in full.lower(), \
            f"{surname} -> {full!r} looks mismatched"


def test_every_legend_in_the_pool_has_a_resolvable_full_name():
    """A player who headlines a video must have a name to print.

    The pool grew from 18 to 67 in one edit; without this, adding a legend
    and forgetting the name table gives them a bare-surname title, a
    bare-surname thumbnail and a bare-surname playlist, all silently.
    """
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[3]
                            / "services" / "orchestrator"))
    from ingest.classics_fetch import LEGENDS, ERAS

    missing = [p for p in LEGENDS if p.lower() not in COMMON_NAMES]
    assert not missing, f"legends with no full name: {missing}"

    # And the era table must partition the pool exactly — a player in no era
    # is never drawn, one in two eras is drawn twice as often.
    flat = [p for players in ERAS.values() for p in players]
    assert sorted(flat) == sorted(LEGENDS), (
        f"era/pool mismatch: {sorted(set(flat) ^ set(LEGENDS))}"
    )
    assert len(flat) == len(set(flat)), "a player appears in two eras"


def test_current_players_are_the_heaviest_draw():
    """The names with search traffic have to actually come up."""
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[3]
                            / "services" / "orchestrator"))
    from ingest.classics_fetch import ERA_WEIGHTS, ERAS

    assert abs(sum(ERA_WEIGHTS.values()) - 1.0) < 1e-9
    assert ERA_WEIGHTS["current"] == max(ERA_WEIGHTS.values())
    for era in ERAS:
        assert era in ERA_WEIGHTS, f"{era} can never be drawn"
    for name in ("Carlsen", "Nakamura", "Caruana", "Firouzja"):
        assert name in ERAS["current"]
