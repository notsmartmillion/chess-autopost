"""Raw SAN in LLM prose is rewritten to spoken words before synthesis.

Botvinnik-Capablanca rendered thirteen minutes of video and then failed its
audit because the model wrote "after Qe5" and "the quieter-looking Qd3" —
the narrator read notation aloud, and the only guard was a post-render ban.
The rewrite is deterministic and shares the audit ban's own pattern, so the
two cannot disagree about what counts as raw SAN.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chessbot_analyzer.director import despan_prose, spoken_san  # noqa: E402


def test_the_two_shipped_slips_are_rewritten():
    assert despan_prose("So here is the position after Qe5, and it is worth "
                        "a moment.") == \
        "So here is the position after queen to e5, and it is worth a moment."
    assert despan_prose("But the move played was the quieter-looking Qd3.") == \
        "But the move played was the quieter-looking queen to d3."


def test_captures_checks_and_castling():
    assert despan_prose("and Nxf7+ wins on the spot") == \
        "and knight takes f7, check wins on the spot"
    assert despan_prose("White should simply O-O here") == \
        "White should simply castles kingside here"


def test_prose_pawn_squares_are_left_alone():
    """"e4 arrives" is how commentators speak; only piece-letter SAN rewrites."""
    text = "The pawn to e4 arrives, and e5 is the classical reply."
    assert despan_prose(text) == text


def test_spoken_san_itself_is_unchanged_by_the_lift():
    assert spoken_san("Nf3") == "knight to f3"
    assert spoken_san("exd5") == "pawn takes d5"
    assert spoken_san("e8=Q#") == "e8, promoting to a queen, checkmate"
