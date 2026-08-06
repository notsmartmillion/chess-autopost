""""Overloaded" means "not right now", not "no".

A transient Anthropic capacity error took down a whole pipeline run: the
narration silently became templates, and the build guard then stopped it.
An unattended daily channel meets this regularly.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SRC = (Path(__file__).resolve().parents[1] / "chessbot_analyzer"
       / "director.py").read_text(encoding="utf-8")


def test_transient_faults_are_retried():
    assert "NARRATION_ATTEMPTS" in SRC, "no retry budget"
    for signal in ("overloaded", "rate_limit", "429", "503", "timeout"):
        assert signal in SRC, f"{signal} is not treated as transient"


def test_permanent_faults_are_not_retried():
    """A bad key fails identically every time; retrying just wastes minutes."""
    assert "if not transient or attempt == attempts:" in SRC


def test_a_refusal_still_stops_immediately():
    """A refusal is an answer, not a fault — retrying would be nagging."""
    i = SRC.index('stop_reason == "refusal"')
    assert "return False" in SRC[i:i + 220]


def test_the_backoff_grows_and_is_capped():
    assert "min(60, 5 * 2 ** (attempt - 1))" in SRC
