"""The title's job is to name the players the way the audience knows them."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chessbot_analyzer.director import expand_title_names, full_name  # noqa: E402

FISCHER = {"white": "Fischer, Robert James", "black": "Uhlmann, Wolfgang"}
KERES = {"white": "Geller, Efim P", "black": "Keres, Paul"}


def test_bare_surname_is_expanded():
    out = expand_title_names("Keres Put a Knight on a Doomed Square", KERES)
    assert out.startswith("Paul Keres")


def test_header_given_names_are_replaced_not_prefixed():
    """The bug that published "Robert James Bobby Fischer".

    The model is shown the PGN header, so it sometimes writes the formal name
    from it. Expanding the surname in place then left both names standing.
    """
    out = expand_title_names(
        "Robert James Fischer Threw Two Pawns Away", FISCHER
    )
    assert out == "Bobby Fischer Threw Two Pawns Away"
    assert "Robert" not in out


def test_partial_header_name_is_replaced():
    out = expand_title_names("Robert Fischer Threw Two Pawns Away", FISCHER)
    assert out == "Bobby Fischer Threw Two Pawns Away"


def test_already_correct_title_is_untouched():
    title = "Bobby Fischer Threw Two Pawns Away"
    assert expand_title_names(title, FISCHER) == title


def test_possessive_keeps_its_s():
    out = expand_title_names("Fischer's Queen Went Pawn Hunting", FISCHER)
    assert out == "Bobby Fischer's Queen Went Pawn Hunting"


def test_both_players_expand():
    out = expand_title_names("Geller Could Not Stop Keres", KERES)
    assert out == "Efim Geller Could Not Stop Paul Keres"


def test_surname_inside_a_word_is_left_alone():
    title = "Keresforth Hall Hosted the Match"
    assert expand_title_names(title, KERES) == title


def test_overlong_result_is_abandoned_not_truncated():
    long_title = "Keres " + "x" * 96
    out = expand_title_names(long_title, KERES)
    assert out == long_title  # expansion would exceed YouTube's 100 chars


def test_full_name_prefers_the_name_the_world_uses():
    assert full_name("Fischer, Robert James") == "Bobby Fischer"
    assert full_name("Uhlmann, Wolfgang") == "Wolfgang Uhlmann"


def test_renderer_compositions_use_the_resolved_names():
    """Every on-screen name comes from meta.whiteFull/blackFull.

    The director resolves each player's name once; "M1. Didier" reached a
    published intro card because ChessNarration re-derived names from the raw
    PGN header while the thumbnail used the resolved ones. This pins the
    convention for the live compositions.
    """
    root = Path(__file__).resolve().parents[3] / "apps" / "renderer" / "src"
    for comp in ("compositions/ChessNarration.tsx", "compositions/Thumbnail.tsx"):
        src = (root / comp).read_text(encoding="utf-8")
        assert "meta.whiteFull ??" in src, f"{comp} ignores the resolved white name"
        assert "meta.blackFull ??" in src, f"{comp} ignores the resolved black name"
