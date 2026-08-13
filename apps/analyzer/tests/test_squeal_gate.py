"""A sustained mid-phrase pitch break is a blocking defect; a whoop is not.

Smyslov-Larsen shipped with the voice breaking to 364 Hz for 1.8 s at 3:10
("So what was wrong with the pawn push?") and whooping to 353 Hz at 6:53
("Queen to A4") — through an audit whose every instrument was a median over
something longer than the break, and whose only nod to the problem was an
advisory "worth a human ear" line.

Two detectors, two roles, calibrated on the mix audio of all 36 finished
renders:

  * find_squeals — HOLDS at >= 1.5x the centre. At the blocking bar
    (>= 0.5 s AND >= 1.75x) every corpus hit is in a rejected or superseded
    render and no live render hits at all, so this one gates.
  * _whoop_runs — the fast up-down glide. Live renders carry several per
    video (they are stressed syllables), so it must NEVER gate; it feeds
    _squeal_penalty, where between two draws of the same text, fewer
    whoops is simply the better draw.

Synthetic voices below: a modulated 190 Hz carrier, with breaks written in.
"""

import math
import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "orchestrator"))

from tts import (  # noqa: E402
    SQUEAL_BLOCK_RATIO, SQUEAL_BLOCK_S, _squeal_penalty, _whoop_runs,
    find_squeals,
)

SR = 24000


def _voice(path: Path, segments):
    """Write a wav of (duration_s, f0) segments — crude vowels, real pitch."""
    frames = bytearray()
    phase = 0.0
    for dur, f0 in segments:
        for i in range(int(dur * SR)):
            phase += 2 * math.pi * f0 / SR
            # a fundamental with two harmonics reads as voiced to
            # autocorrelation without being a pure lab tone
            s = (math.sin(phase) + 0.5 * math.sin(2 * phase)
                 + 0.25 * math.sin(3 * phase))
            frames += int(6000 * s).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(bytes(frames))


@pytest.fixture
def tmp_wav(tmp_path):
    return tmp_path / "clip.wav"


def test_the_shipped_hold_is_a_blocking_squeal(tmp_wav):
    """3:10's shape: seconds of normal voice, then a held break."""
    _voice(tmp_wav, [(3.0, 190), (0.8, 350), (3.0, 190)])
    runs = find_squeals(tmp_wav, 194.0)
    blocking = [r for r in runs
                if r[1] >= SQUEAL_BLOCK_S and r[2] >= SQUEAL_BLOCK_RATIO]
    assert blocking, runs
    at, dur, ratio = blocking[0]
    assert 2.5 < at < 3.5
    assert ratio > 1.7


def test_a_whoop_does_not_block_but_is_scored(tmp_wav):
    """6:53's shape: a fast glide up to 350 Hz and straight back down."""
    _voice(tmp_wav, [(3.0, 190), (0.1, 240), (0.1, 300), (0.15, 350),
                     (0.1, 290), (3.0, 190)])
    runs = find_squeals(tmp_wav, 194.0)
    blocking = [r for r in runs
                if r[1] >= SQUEAL_BLOCK_S and r[2] >= SQUEAL_BLOCK_RATIO]
    assert blocking == [], runs
    assert _whoop_runs(tmp_wav, 194.0), "the glide should at least be scored"
    assert _squeal_penalty(tmp_wav, 194.0) > 0


def test_a_clean_read_scores_zero(tmp_wav):
    """Ordinary declination and a brief stress never register."""
    _voice(tmp_wav, [(2.0, 200), (2.0, 190), (0.1, 245), (2.0, 185)])
    assert find_squeals(tmp_wav, 194.0) == []
    assert _squeal_penalty(tmp_wav, 194.0) == 0.0


def test_a_break_below_speech_level_still_counts(tmp_wav):
    """The shipped squeals were QUIETER than the surrounding speech."""
    frames = bytearray()
    phase = 0.0
    for dur, f0, amp in [(3.0, 190, 6000), (0.8, 350, 2400), (3.0, 190, 6000)]:
        for _ in range(int(dur * SR)):
            phase += 2 * math.pi * f0 / SR
            s = (math.sin(phase) + 0.5 * math.sin(2 * phase)
                 + 0.25 * math.sin(3 * phase))
            frames += int(amp * s).to_bytes(2, "little", signed=True)
    with wave.open(str(tmp_wav), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(bytes(frames))
    assert find_squeals(tmp_wav, 194.0), "a -8 dB break is still a break"


def test_the_rescue_accept_test_counts_the_interior():
    """badness() must include _squeal_penalty — edges were all it saw when
    it accepted the sample that squealed on "Queen to A4"."""
    src = (Path(__file__).resolve().parents[3] / "services" / "orchestrator"
           / "tts.py").read_text(encoding="utf-8")
    fn = src.split("def badness(", 1)[1].split("\n    def ", 1)[0]
    assert "_squeal_penalty" in fn
