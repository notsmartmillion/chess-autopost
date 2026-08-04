"""Variations show the road not taken — never a detour off a played brilliancy.

The published Fischer-Uhlmann render followed a brilliant pawn thrust with a
line showing why the king should not have gone to b1 instead: a quiet move
nobody had considered, 179 centipawns worse, arriving straight after a hold
beat that had asked the viewer to find the attack. It read as a bug, and the
device was retired. A brilliancy is only worth branching on when it was
*missed*.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chessbot_analyzer.director import Director  # noqa: E402
from chessbot_analyzer.facts import _classify_quality  # noqa: E402


def test_the_unplayed_best_move_can_be_graded_brilliant():
    """facts.py grades the road not taken with these exact arguments.

    Without this the director's missed-brilliancy rule would be unreachable
    code that no game could ever trigger.
    """
    graded = _classify_quality(
        ply=30, in_book=False, cp_loss=0, played_best=True,
        only_move=True, is_sacrifice=True,
    )
    assert graded == "brilliant"
    # A quiet only-move is merely best, and a sacrifice with alternatives is
    # not brilliant either — both must stay out of the branch.
    assert _classify_quality(
        ply=30, in_book=False, cp_loss=0, played_best=True,
        only_move=True, is_sacrifice=False,
    ) != "brilliant"
    assert _classify_quality(
        ply=30, in_book=False, cp_loss=0, played_best=True,
        only_move=False, is_sacrifice=True,
    ) != "brilliant"


def _director() -> Director:
    return Director.__new__(Director)  # these helpers need no config


def test_a_played_brilliancy_gets_no_variation():
    """The exact case that shipped: c5 was brilliant and had alternatives."""
    d = _director()
    ply = {
        "ply": 43, "quality": "brilliant", "playedBest": True, "cpLoss": 0,
        "bestPvSan": ["c5"], "bestQuality": None,
        "alternatives": [{"rank": 2, "san": "Kb1", "cp": -118, "pvSan": ["Kb1"]}],
    }
    assert d._deserves_variation(ply, None) is False


def test_a_played_great_move_gets_no_variation():
    d = _director()
    ply = {
        "ply": 20, "quality": "great", "playedBest": True, "cpLoss": 0,
        "bestPvSan": ["Nd5"], "bestQuality": None,
        "alternatives": [{"rank": 2, "san": "Kh1", "cp": -50, "pvSan": ["Kh1"]}],
    }
    assert d._deserves_variation(ply, None) is False


def test_a_missed_brilliancy_is_shown():
    """The mirror case: the move he did not play would have been brilliant."""
    d = _director()
    ply = {
        "ply": 30, "quality": "mistake", "playedBest": False,
        "bestPvSan": ["Rxh7", "Kxh7", "Qh5"], "bestQuality": "brilliant",
    }
    assert d._deserves_variation(ply, None) is True


def test_a_missed_brilliancy_is_shown_even_when_the_move_played_was_ordinary():
    """Quality is about what was played; the branch is about what was not."""
    d = _director()
    ply = {
        "ply": 30, "quality": "good", "playedBest": False,
        "bestPvSan": ["Rxh7"], "bestQuality": "brilliant",
    }
    assert d._deserves_variation(ply, None) is True


def test_a_missed_brilliancy_outranks_a_blunder():
    d = _director()
    d.max_variations = 1
    plies = [
        {"ply": 10, "quality": "blunder", "playedBest": False,
         "bestPvSan": ["Qa4"], "cpLoss": 300, "bestQuality": "best"},
        {"ply": 20, "quality": "mistake", "playedBest": False,
         "bestPvSan": ["Rxh7"], "cpLoss": 200, "bestQuality": "brilliant"},
    ]
    assert d._choose_variations(plies, {}) == {20}


def test_ordinary_errors_still_get_their_better_move():
    d = _director()
    blunder = {"ply": 44, "quality": "blunder", "playedBest": False,
               "bestPvSan": ["Nxc5"], "bestQuality": "best"}
    assert d._deserves_variation(blunder, None) is True


def test_a_blunder_that_was_somehow_best_is_not_branched():
    d = _director()
    ply = {"ply": 44, "quality": "blunder", "playedBest": True,
           "bestPvSan": ["Nxc5"], "bestQuality": None}
    assert d._deserves_variation(ply, None) is False


def test_a_missed_forced_mate_is_still_always_shown():
    d = _director()
    ply = {"ply": 50, "quality": "mistake", "playedBest": False,
           "mateBefore": 3, "mateAfter": None, "bestPvSan": ["Qh8+"],
           "bestQuality": "best"}
    assert d._deserves_variation(ply, None) is True


def test_the_refutation_device_is_gone():
    """Nothing should be able to branch off a played brilliancy again."""
    assert not hasattr(Director, "_refutation_beats")
    assert not hasattr(Director, "_tempting_alternative")
