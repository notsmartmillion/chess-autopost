"""Two finished sentences need a breath between them.

Measured on a real render: 40 of 87 sentence-to-sentence transitions had
under 0.20 s of silence and many had 0.01 s — two thoughts butted together,
which is what makes a narrator sound assembled from pieces rather than
talking. Natural speech leaves 0.4-0.7 s at a full stop.
"""

import array
import json
import math
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]
                       / "services" / "orchestrator"))

import build_video  # noqa: E402
from build_video import plan_sentence_pauses, FPS  # noqa: E402

SR = 24000


def _write(path: Path, lead_s: float, speech_s: float, trail_s: float):
    total = lead_s + speech_s + trail_s
    pcm = array.array("h", [0] * int(SR * total))
    for i in range(int(lead_s * SR), int((lead_s + speech_s) * SR)):
        pcm[i] = int(9000 * math.sin(2 * math.pi * 190 * i / SR))
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(pcm.tobytes())
    return int(total * 1000)


def _case(tmp_path, monkeypatch, texts, gaps, kinds=None, branches=None):
    """Build a script+manifest whose clips have the given inter-beat gaps."""
    monkeypatch.setattr(build_video, "AUDIO_DIR", tmp_path)
    beats, clips = [], {}
    for i, text in enumerate(texts):
        # Split the requested gap either side of the boundary.
        trail = gaps[i] / 2 if i < len(gaps) else 0.3
        lead = gaps[i - 1] / 2 if i > 0 else 0.05
        name = f"b{i:04d}.wav"
        dur = _write(tmp_path / name, lead, 1.2, trail)
        beats.append({
            "id": f"b{i:04d}", "text": text,
            "kind": (kinds or ["move"] * len(texts))[i],
            "branch": (branches or [False] * len(texts))[i],
        })
        clips[f"b{i:04d}"] = {"file": name, "durationMs": dur,
                              "words": [{"w": "x", "s": lead, "e": lead + 1.2}]}
    return {"beats": beats}, {"clips": clips}


def test_a_butted_sentence_boundary_gets_a_breath(tmp_path, monkeypatch):
    script, man = _case(tmp_path, monkeypatch,
                        ["First thought ends here.", "Second one begins."],
                        [0.02])
    assert plan_sentence_pauses(script, man) == 1
    pad = script["beats"][0]["tailMs"]
    assert 350 <= pad <= 450, pad


def test_a_sentence_running_on_is_never_torn_apart(tmp_path, monkeypatch):
    """The beat's text does not end the sentence — silence here would be
    inserted mid-thought, which is worse than no pause at all."""
    script, man = _case(tmp_path, monkeypatch,
                        ["and the rook swings across", "to take the file."],
                        [0.02])
    assert plan_sentence_pauses(script, man) == 0
    assert "tailMs" not in script["beats"][0]


def test_a_well_paced_transition_is_left_alone(tmp_path, monkeypatch):
    script, man = _case(tmp_path, monkeypatch,
                        ["First thought ends here.", "Second one begins."],
                        [0.9])
    assert plan_sentence_pauses(script, man) == 0


def test_crossing_into_a_variation_gets_a_longer_pause(tmp_path, monkeypatch):
    script, man = _case(
        tmp_path, monkeypatch,
        ["That was the game move.", "But what if instead?"],
        [0.02], kinds=["move", "variation"], branches=[False, True])
    pad = script["beats"][0]["tailMs"] if plan_sentence_pauses(script, man) else 0
    assert pad > 600, pad


def test_pads_are_whole_video_frames(tmp_path, monkeypatch):
    script, man = _case(tmp_path, monkeypatch,
                        ["One ends.", "Two starts.", "Three starts."],
                        [0.02, 0.05])
    plan_sentence_pauses(script, man)
    frame = 1000.0 / FPS
    for b in script["beats"]:
        if b.get("tailMs"):
            # A frame is 33.33 ms, so a whole number of them is never a whole
            # number of milliseconds; within 1 ms is sub-frame and exact for
            # every purpose downstream.
            frames = round(b["tailMs"] / frame)
            assert abs(b["tailMs"] - frames * frame) <= 1.0, b["tailMs"]


def test_the_last_beat_is_never_padded(tmp_path, monkeypatch):
    script, man = _case(tmp_path, monkeypatch,
                        ["Only one sentence."], [])
    assert plan_sentence_pauses(script, man) == 0
