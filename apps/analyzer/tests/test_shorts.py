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
    MAX_WORDS, build_short_script, enforce_audio_contract, find_wow,
    make_hook, select_window,
)


def _beat(i, kind="move", tag=None, branch=False, words=20, ev=0, ply=None, **kw):
    return {
        "id": f"b{i:04d}", "kind": kind, "tag": tag, "branch": branch,
        "ply": ply if ply is not None else i,
        "text": " ".join(["word"] * words), "evalCp": ev,
        "prevFen": "8/8/8/8/8/8/8/K6k w - - 0 1",
        "fen": "8/8/8/8/8/8/8/K6k b - - 0 1",
        "move": {"from": "a1", "to": "a2", "san": "Ka2"} if kind == "move" else None,
        **kw,
    }


def test_a_brilliancy_is_a_wow():
    beats = [_beat(1), _beat(2, tag="brilliant"), _beat(3)]
    wow = find_wow(beats)
    assert wow and wow["kind"] == "brilliant" and wow["index"] == 1


def test_consecutive_brilliancies_are_a_streak():
    """"2 or 3 brilliant sacrifices in a row" is the strongest cut of all.
    The same player's consecutive turns sit two plies apart."""
    beats = [_beat(1, tag="brilliant"), _beat(2), _beat(3, tag="brilliant")]
    wow = find_wow(beats)
    assert wow and wow["kind"] == "streak" and wow["streak"] == [0, 2]


def test_a_true_reversal_is_a_wow():
    """White was +4, one blunder and it is gone: "sure of victory, threw it
    all away"."""
    beats = [
        _beat(1, ply=11, ev=400),                     # White clearly winning
        _beat(2, ply=12, ev=380),                     # Black replies
        _beat(3, ply=13, tag="blunder", ev=-30),      # White throws it away
    ]
    wow = find_wow(beats)
    assert wow and wow["kind"] == "reversal" and wow["index"] == 2


def test_a_losing_player_losing_harder_is_not_a_wow():
    """The Kramnik case that shipped: Aronian at -2.4 blundered to -4.1 and
    the hook said "the moment it started to slip". Nothing slipped — no
    Short."""
    beats = [
        _beat(1, ply=11, ev=244),                     # Black already losing
        _beat(2, ply=12, tag="mistake", ev=409),      # ...and loses harder
    ]
    assert find_wow(beats) is None
    assert select_window(beats) is None


def test_a_small_advantage_lost_is_not_sure_of_victory():
    """+0.6 to -1.4 is a game changing hands, not a throne collapsing."""
    beats = [_beat(1, ply=11, ev=-59), _beat(2, ply=12, tag="mistake", ev=144)]
    assert find_wow(beats) is None


def test_reversal_hooks_name_the_player_who_was_winning():
    hero = {"ply": 13}  # White moved
    meta = {"whiteFull": "Vladimir Kramnik", "blackFull": "Levon Aronian"}
    assert make_hook("reversal", hero, meta) == "Vladimir Kramnik was winning. Then this."


def test_window_is_setup_hero_refutation():
    beats = [
        _beat(1), _beat(2, kind="hold"), _beat(3, tag="brilliant"),
        _beat(4, kind="variation", branch=True),
        _beat(5, kind="variation", branch=True),
        _beat(6, kind="resume"), _beat(7),
    ]
    win, wow = select_window(beats)
    assert [b["id"] for b in win] == ["b0002", "b0003", "b0004", "b0005", "b0006"]
    assert wow["kind"] == "brilliant"


def test_a_streak_window_spans_the_whole_streak():
    beats = [
        _beat(1), _beat(2, tag="brilliant"), _beat(3), _beat(4, tag="brilliant"),
        _beat(5, kind="variation", branch=True),
    ]
    win, wow = select_window(beats)
    assert [b["id"] for b in win] == ["b0001", "b0002", "b0003", "b0004", "b0005"]


def test_setup_is_dropped_before_the_refutation():
    beats = [
        _beat(1, words=60), _beat(2, tag="brilliant", words=60),
        _beat(3, kind="variation", branch=True, words=60),
    ]
    win, _ = select_window(beats)  # 180 words > budget; setup goes first
    assert [b["id"] for b in win] == ["b0002", "b0003"]


def test_an_unshortable_game_yields_no_short():
    """Silence beats filler: one enormous beat is not a clip."""
    beats = [_beat(1, tag="brilliant", words=MAX_WORDS + 40)]
    assert select_window(beats) is None
    assert build_short_script({"meta": {}, "beats": beats}, None) is None


def test_a_game_with_no_wow_yields_no_short():
    """No brilliancy and no reversal -> no Short at all. This also refuses
    degenerate scripts (a template-prose build, tags all book/good/best)."""
    beats = [_beat(1, tag="good", ev=10), _beat(2, tag="best", ev=-400),
             _beat(3, tag="good", ev=-380)]
    assert find_wow(beats) is None
    assert select_window(beats) is None


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
    beats = [_beat(1), _beat(2, tag="brilliant", thinkPauseMs=5000,
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


def test_the_short_composition_gates_on_the_reveal_and_shows_the_eval():
    """Nothing names the move before the piece moves — the long-form learned
    this twice, and the first Short shipped "Bd8" on screen while the bishop
    still stood on b6. And the eval bar must exist, driven by revealed
    positions only."""
    src = (Path(__file__).resolve().parents[3] / "apps" / "renderer" / "src"
           / "compositions" / "ChessShort.tsx").read_text(encoding="utf-8")
    assert "frame >= moveStartFrame" in src, "no reveal gate"
    assert "beat?.move && revealed" in src, "the SAN row ignores the reveal"
    assert "shownEvalCp" in src and "EvalColumn" in src, (
        "no eval column — vertical, beside the board, like the long form"
    )
    assert "revealed\n" in src or "revealed ?" in src
