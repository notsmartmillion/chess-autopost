"""One definition of an off-voice beat, shared by synthesis and audit.

Two renders in one day passed every pre-render seam check, spent ~25 minutes
rendering, and were then held by the audit's cluster rule — because the
pre-render stage had no per-beat check at all. Now both stages call the same
function, so whatever would fail the audit fails before the render.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "services" / "orchestrator"))

from tts import find_offvoice_beats  # noqa: E402


def _row(bid, at_s, f0=190.0, lv=-20.0, wpm=180.0, words=30):
    return (bid, int(at_s * 1000), f0, lv, wpm, words)


def normal_video(n=20, spacing_s=8.0):
    return [_row(f"b{i:04d}", i * spacing_s) for i in range(n)]


def test_a_steady_video_raises_nothing():
    different, outliers, cluster = find_offvoice_beats(normal_video())
    assert different == [] and outliers == [] and cluster is None


def test_the_cluster_that_held_two_renders():
    """Three sharper beats inside 30s — the Kramnik-Aronian hold.

    Attribution can shift by one: a run of deviant beats drags the median of
    its neighbours, so a beat at the cluster's edge may be flagged in place
    of the last one. The verdict — a cluster exists right there — is what
    blocks, and both stages share this function, so they agree on it.
    """
    rows = normal_video()
    for i in (5, 6, 7):  # 40s, 48s, 56s — inside one neighbourhood
        bid, at, f0, lv, wpm, words = rows[i]
        rows[i] = (bid, at, f0 * 1.15, lv, wpm, words)
    _different, outliers, cluster = find_offvoice_beats(rows)
    assert cluster is not None and len(cluster) == 3
    assert set(cluster) <= {"b0004", "b0005", "b0006", "b0007"}
    assert all(what == "sharper" for _, _, what in outliers)


def test_two_outliers_do_not_block():
    rows = normal_video()
    for i in (5, 6):
        bid, at, f0, lv, wpm, words = rows[i]
        rows[i] = (bid, at, f0 * 1.15, lv, wpm, words)
    _d, outliers, cluster = find_offvoice_beats(rows)
    assert len(outliers) == 2 and cluster is None


def test_three_outliers_spread_across_minutes_do_not_block():
    rows = normal_video(40)
    for i in (3, 18, 33):  # far apart
        bid, at, f0, lv, wpm, words = rows[i]
        rows[i] = (bid, at, f0 * 1.15, lv, wpm, words)
    _d, outliers, cluster = find_offvoice_beats(rows)
    assert len(outliers) == 3 and cluster is None


def test_hot_and_fast_together_is_a_different_read():
    """The b0010 case: +5 dB and a third faster, pitch normal."""
    rows = normal_video()
    bid, at, f0, lv, wpm, words = rows[5]
    rows[5] = (bid, at, f0, lv + 5.0, wpm * 1.4, words)
    different, _o, _c = find_offvoice_beats(rows)
    assert [d[0] for d in different] == ["b0005"]


def test_short_beats_lack_the_words_to_be_called_fast():
    rows = normal_video()
    bid, at, f0, lv, wpm, words = rows[5]
    rows[5] = (bid, at, f0, lv, wpm * 1.4, 8)  # 8 words: too little signal
    _d, outliers, _c = find_offvoice_beats(rows)
    assert outliers == []


def test_the_audit_and_the_prerender_check_share_the_function():
    """Not the same numbers — the same code object."""
    import ast
    root = Path(__file__).resolve().parents[3] / "services" / "orchestrator"
    for consumer in ("verify_render.py", "tts.py"):
        src = (root / consumer).read_text(encoding="utf-8")
        assert "find_offvoice_beats" in src, f"{consumer} does not use the shared check"
    # And verify_render must not keep a private copy of the thresholds.
    audit_src = (root / "verify_render.py").read_text(encoding="utf-8")
    assert "1.30" not in audit_src and "> 3.5" not in audit_src, (
        "verify_render re-states the outlier thresholds instead of importing them"
    )


def test_beats_below_the_floor_are_not_judged():
    """An 8-word move announcement holds ~2.5s of voiced audio — too little
    to estimate pitch or level. Three voice draws each "found" a cluster of
    short beats in a different place; the floor is what stops a gate from
    blocking on measurement noise. Both stages share it via tts.BEAT_MIN_MS.
    """
    from tts import BEAT_MIN_MS

    assert BEAT_MIN_MS >= 4000
    root = Path(__file__).resolve().parents[3] / "services" / "orchestrator"
    audit_src = (root / "verify_render.py").read_text(encoding="utf-8")
    assert "BEAT_MIN_MS" in audit_src, "the audit keeps its own floor"
    assert "3000" not in audit_src.split("BEAT_MIN_MS")[1][:200], (
        "a hardcoded floor survives next to the shared one"
    )
