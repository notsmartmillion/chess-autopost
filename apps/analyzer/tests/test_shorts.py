"""A Short is one key moment, its refutation, and ONE continuous take.

Every voice defect this channel has shipped lived at or across take
boundaries; the Short's word budget guarantees a single take, so the defect
class cannot occur. These tests pin the selection and the audio contract.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "services" / "orchestrator"))

import build_short  # noqa: E402
from build_short import (  # noqa: E402
    MAX_WORDS, build_short_script, enforce_audio_contract, pick_hero,
    select_window,
)


def _beat(i, kind="move", tag=None, branch=False, words=20, ev=0, **kw):
    return {
        "id": f"b{i:04d}", "kind": kind, "tag": tag, "branch": branch,
        "text": " ".join(["word"] * words), "evalCp": ev,
        "prevFen": "8/8/8/8/8/8/8/K6k w - - 0 1",
        "fen": "8/8/8/8/8/8/8/K6k b - - 0 1",
        "move": {"from": "a1", "to": "a2", "san": "Ka2"} if kind == "move" else None,
        **kw,
    }


def test_hero_prefers_the_brilliancy():
    beats = [_beat(1), _beat(2, tag="mistake"), _beat(3, tag="brilliant"), _beat(4)]
    assert pick_hero(beats) == 2


def test_no_eval_swing_fallback_survives():
    """A big eval swing with no quality tag is not a story, and the fallback
    that used it is how a template-prose build almost became a Short."""
    beats = [_beat(1, ev=10), _beat(2, ev=30), _beat(3, ev=-400), _beat(4, ev=-380)]
    assert pick_hero(beats) is None


def test_window_is_setup_hero_refutation():
    beats = [
        _beat(1), _beat(2, kind="hold"), _beat(3, tag="blunder"),
        _beat(4, kind="variation", branch=True),
        _beat(5, kind="variation", branch=True),
        _beat(6, kind="resume"), _beat(7),
    ]
    win = select_window(beats)
    assert [b["id"] for b in win] == ["b0002", "b0003", "b0004", "b0005", "b0006"]


def test_setup_is_dropped_before_the_refutation():
    beats = [
        _beat(1, words=60), _beat(2, tag="blunder", words=60),
        _beat(3, kind="variation", branch=True, words=60),
    ]
    win = select_window(beats)  # 180 words > budget; setup goes first
    assert [b["id"] for b in win] == ["b0002", "b0003"]


def test_an_unshortable_game_yields_no_short():
    """Silence beats filler: one enormous beat is not a clip."""
    beats = [_beat(1, tag="brilliant", words=MAX_WORDS + 40)]
    assert select_window(beats) is None
    assert build_short_script({"meta": {}, "beats": beats}, None) is None


def test_every_short_beat_is_one_paragraph():
    beats = [
        _beat(1), _beat(2, tag="brilliant", para=7),
        _beat(3, kind="variation", branch=True, para=8),
    ]
    short = build_short_script({"meta": {"white": "A", "black": "B"}, "beats": beats}, None)
    assert {b.get("para") for b in short["beats"]} == {0}, (
        "one paragraph -> one take -> no seams; anything else re-opens the "
        "entire seam defect class"
    )


def test_think_pauses_and_stale_mentions_do_not_survive():
    beats = [_beat(1), _beat(2, tag="great", thinkPauseMs=5000,
                            mentions=[{"square": "e4", "atMs": 100}])]
    short = build_short_script({"meta": {}, "beats": beats}, None)
    for b in short["beats"]:
        assert "thinkPauseMs" not in b
        assert "mentions" not in b


def _contract_case(tmp_path, monkeypatch, *, heads=1, marker=None, secs=40.0):
    monkeypatch.setattr(build_short, "AUDIO_DIR", tmp_path)
    beats = [
        {"id": "s0001", "text": "hook words here"},
        {"id": "s0002", "text": "the move itself"},
    ]
    clips = {}
    per = int(secs * 1000 / len(beats))
    for i, b in enumerate(beats):
        name = f"{b['id']}.wav"
        (tmp_path / name).write_bytes(b"RIFF")
        clips[b["id"]] = {
            "file": name, "durationMs": per,
            "words": [{"w": "x", "s": 0.1, "e": 0.4}],
            "chain": i >= heads,
        }
    if marker is not None:
        (tmp_path / "unresolved_seams.json").write_text(
            __import__("json").dumps(marker), encoding="utf-8")
    manifest = {"backend": "ttsapi", "clips": clips}
    return {"beats": beats}, manifest


def test_contract_accepts_one_clean_take(tmp_path, monkeypatch):
    short, man = _contract_case(tmp_path, monkeypatch)
    enforce_audio_contract(short, man)  # must not raise


def test_contract_refuses_two_takes(tmp_path, monkeypatch):
    short, man = _contract_case(tmp_path, monkeypatch, heads=2)
    with pytest.raises(SystemExit):
        enforce_audio_contract(short, man)


def test_contract_refuses_unresolved_defects(tmp_path, monkeypatch):
    short, man = _contract_case(tmp_path, monkeypatch,
                                marker=[{"take": "s0001", "dHz": 70}])
    with pytest.raises(SystemExit):
        enforce_audio_contract(short, man)


def test_contract_refuses_fallback_voice(tmp_path, monkeypatch):
    short, man = _contract_case(tmp_path, monkeypatch)
    man["backend"] = "sapi"
    with pytest.raises(SystemExit):
        enforce_audio_contract(short, man)


def test_contract_refuses_overlong_audio(tmp_path, monkeypatch):
    short, man = _contract_case(tmp_path, monkeypatch, secs=75.0)
    with pytest.raises(SystemExit):
        enforce_audio_contract(short, man)


def test_an_error_with_its_refutation_beats_a_lone_tagged_move():
    """The refutation is the payoff of the format.

    The first cut of this selector picked a bare "great" and produced
    nineteen thin seconds while a blunder with its punishment attached sat
    unused in the same script.
    """
    beats = [
        _beat(1, tag="great"),                       # shiny but alone
        _beat(2, tag="blunder"),
        _beat(3, kind="variation", branch=True),     # the punishment
    ]
    assert pick_hero(beats) == 1


def test_a_brilliancy_still_beats_an_unrefuted_error():
    beats = [_beat(1, tag="blunder"), _beat(2, tag="brilliant")]
    assert pick_hero(beats) == 1


def test_a_game_with_no_strong_moment_yields_no_short():
    """No brilliancy, blunder, great or mistake -> no Short at all.

    This also refuses degenerate scripts outright: a template-prose build
    (tags all book/good/best) almost became a Short through the old
    eval-swing fallback.
    """
    beats = [_beat(1, tag="good", ev=10), _beat(2, tag="best", ev=-400),
             _beat(3, tag="good", ev=-380)]
    assert pick_hero(beats) is None
    assert select_window(beats) is None


def test_the_short_composition_gates_on_the_reveal_and_shows_the_eval():
    """Nothing names the move before the piece moves — the long-form learned
    this twice, and the first Short shipped "Bd8" on screen while the bishop
    still stood on b6. And the eval bar must exist, driven by revealed
    positions only."""
    src = (Path(__file__).resolve().parents[3] / "apps" / "renderer" / "src"
           / "compositions" / "ChessShort.tsx").read_text(encoding="utf-8")
    assert "frame >= moveStartFrame" in src, "no reveal gate"
    assert "beat?.move && revealed" in src, "the SAN row ignores the reveal"
    assert "shownEvalCp" in src and "Math.tanh" in src, "no eval bar"
    assert "revealed\n" in src or "revealed ?" in src
