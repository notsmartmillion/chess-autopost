"""A thinking pause must be spliced into silence, not into a word.

Shipped live in Kramnik-Aronian: "...try to find it. Th—" then five seconds
of nothing, then "—ere is one move". The splice sat 50 ms inside the onset of
the following word, because the insertion point was a blind +0.15s after the
aligned end of the previous one and the gap was only 0.10s.
"""

import array
import math
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "services" / "orchestrator"))

from build_video import _silent_split  # noqa: E402

SR = 24000
WIDTH = 2


def _clip(word_spans, total_s=3.0):
    """Buffer of loud spans over silence; returns raw bytes."""
    pcm = array.array("h", [0] * int(SR * total_s))
    for lo, hi in word_spans:
        for i in range(int(lo * SR), int(hi * SR)):
            pcm[i] = int(9000 * math.sin(2 * math.pi * 190 * i / SR))
    return pcm.tobytes()


def test_the_splice_lands_in_the_gap_not_the_next_word():
    # "it" ends 1.00, "there" starts 1.10 — the real Kramnik geometry.
    data = _clip([(0.4, 1.00), (1.10, 2.2)])
    t = _silent_split(data, SR, WIDTH, 1.00, 1.10)
    assert 1.00 <= t <= 1.10, t
    # And the audio there is quiet.
    pcm = array.array("h"); pcm.frombytes(data)
    i = int(t * SR)
    assert max(abs(s) for s in pcm[i:i + int(SR * 0.01)]) < 500


def test_it_never_returns_a_point_inside_the_following_word():
    """The failure mode: overshooting into the onset."""
    data = _clip([(0.4, 1.00), (1.10, 2.2)])
    t = _silent_split(data, SR, WIDTH, 1.00, 1.10)
    assert t < 1.10, "splice would clip the next word's onset"


def test_a_degenerate_window_falls_back_to_the_word_end():
    data = _clip([(0.4, 1.0)])
    assert _silent_split(data, SR, WIDTH, 1.0, 1.0) == 1.0
    assert _silent_split(data, SR, WIDTH, 1.0, 0.9) == 1.0


def test_a_wide_gap_still_picks_a_quiet_instant():
    data = _clip([(0.2, 0.8), (1.8, 2.5)])
    t = _silent_split(data, SR, WIDTH, 0.8, 1.8)
    pcm = array.array("h"); pcm.frombytes(data)
    i = int(t * SR)
    assert max(abs(s) for s in pcm[i:i + int(SR * 0.01)]) < 500


def test_the_old_blind_offset_is_gone():
    src = (Path(__file__).resolve().parents[3] / "services" / "orchestrator"
           / "build_video.py").read_text(encoding="utf-8")
    assert '["e"]) + 0.15' not in src, "the blind +0.15s insertion point survives"
    assert "_silent_split(" in src
