"""A beat read several semitones above the render's centre is a defect.

Tal-Botvinnik was uploaded, watched, and deleted for "a real voice
discrepancy". Two moments carry it, both measured on the finished mix:

    0:53  b0013   239 Hz  (+3.7 semitones)  +6.1 dB   4.8 s
    2:49  b0042   258 Hz  (+5.1 semitones)  +5.4 dB   3.9 s

against a render median of 193 Hz. The audit passed the render with zero
errors, for two reasons this module pins:

  * b0042 is 3.9 s long and BEAT_MIN_MS is 4 s, so the worst moment in the
    video was never measured at all;
  * pitch could only ever produce a WARNING — an audit error needed a beat to
    be hot AND fast, and this one is hot and SHARP.

The numbers below are the real measurements, so the thresholds cannot drift
away from the case that motivated them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "orchestrator"))

from tts import (  # noqa: E402
    BEAT_MIN_MS, RAISED_MIN_MS, find_offvoice_beats, find_raised_beats,
)

# (id, at_ms, duration_ms, f0, level_db) — an ordinary render at 193 Hz.
def _render(*special):
    rows = [(f"b{i:04d}", i * 4000, 4000, 193.0 + (i % 5) - 2, -25.0)
            for i in range(1, 40)]
    return rows + list(special)


TAL_B0042 = ("b0042", 169_000, 3_900, 258.0, -20.6)
TAL_B0013 = ("b0013", 53_000, 4_800, 239.0, -19.9)


def test_the_beat_that_shipped_is_caught():
    raised = find_raised_beats(_render(TAL_B0042, TAL_B0013))
    caught = {r[0] for r in raised}
    assert caught == {"b0042", "b0013"}, raised
    by_id = {r[0]: r for r in raised}
    assert by_id["b0042"][2] > 5.0   # semitones above the render's centre
    assert by_id["b0042"][3] > 4.0   # dB above it


def test_the_worst_beat_was_shorter_than_the_neighbourhood_floor():
    """3.9 s — the audit's own floor is what let it through."""
    assert TAL_B0042[2] < BEAT_MIN_MS
    assert TAL_B0042[2] >= RAISED_MIN_MS


def test_the_old_check_could_not_have_failed_it():
    """Reconstructs the pre-fix verdict: a warning at most, never an error."""
    rows = [(f"b{i:04d}", i * 4000, 193.0, -25.0, 150.0, 20) for i in range(1, 40)]
    rows.append(("b0042", 169_000, 258.0, -20.6, 150.0, 20))
    different_read, outliers, _cluster = find_offvoice_beats(rows)
    assert different_read == []                       # no error
    assert any(o[0] == "b0042" for o in outliers)     # only a warning


def test_ordinary_emphasis_is_left_alone():
    """Gligoric-Fischer tops out at +2.6 semitones and drew no complaint.

    Pitch alone must not gate: every render carries a sentence or two of
    genuine emphasis, and a gate that fires on those blocks good work.
    """
    gligoric_peak = ("b0014", 59_000, 2_000, 227.0, -21.0)   # +2.6 st, +3.8 dB
    morphy_peak = ("b0003", 22_000, 3_300, 225.0, -21.6)     # +2.9 st, +3.4 dB
    assert find_raised_beats(_render(gligoric_peak, morphy_peak)) == []


def test_sharp_but_not_loud_is_not_a_raised_read():
    """Both conditions together, or the test fires on a quiet high sentence."""
    assert find_raised_beats(_render(("b0050", 200_000, 4_000, 260.0, -25.0))) == []


def test_a_short_beat_is_still_not_guessed_at():
    """Below RAISED_MIN_MS there is too little voiced audio to trust."""
    assert find_raised_beats(_render(("b0051", 204_000, 1_200, 280.0, -19.0))) == []


def test_a_thin_render_is_not_judged():
    """A Short has a handful of beats; a median over them means nothing."""
    assert find_raised_beats([TAL_B0042]) == []
