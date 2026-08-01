"""The per-game library copy, tested through the code path that runs it.

This exists because the first version shipped broken: _named_video_copy was
verified by calling it from a scratch snippet, where the script dict was
obviously in scope. In the real caller it was not, and the daily run died
with a NameError *after* spending forty minutes rendering. So this checks the
signature the pipeline actually calls, not just the helper in isolation.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "orchestrator"))

import build_video  # noqa: E402


def test_render_receives_the_script_it_names_files_from():
    params = list(inspect.signature(build_video.render).parameters)
    assert "script" in params, (
        "render() names the library copy from the script; without it in the "
        "signature the call is a NameError at the end of a long render"
    )


def test_naming_uses_surnames_and_year(tmp_path, monkeypatch):
    monkeypatch.setattr(build_video, "OUT", tmp_path)
    monkeypatch.setattr(build_video, "ROOT", tmp_path)
    real = tmp_path / "apps" / "renderer" / "out"
    real.mkdir(parents=True)
    (real / "video.mp4").write_bytes(b"video")
    (real / "thumbnail.png").write_bytes(b"thumb")

    script = {"meta": {"white": "Geller, Efim P", "black": "Keres, Paul",
                       "date": "1953.??.??"}}
    dest = build_video._named_video_copy(script)
    assert dest is not None
    # One folder per game, with the files keeping the descriptive stem so a
    # file dragged out of its folder still says what it is.
    assert dest.parent.name == "Geller-v-Keres-1953"
    assert dest.name == "Geller-v-Keres-1953.mp4"
    assert dest.with_suffix(".png").exists()


def test_naming_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(build_video, "OUT", tmp_path)
    monkeypatch.setattr(build_video, "ROOT", tmp_path)
    real = tmp_path / "apps" / "renderer" / "out"
    real.mkdir(parents=True)
    (real / "video.mp4").write_bytes(b"video")

    script = {"meta": {"white": "Tal, Mihail", "black": "Botvinnik, Mikhail",
                       "date": "1960.03.15"}}
    first = build_video._named_video_copy(script)
    second = build_video._named_video_copy(script)
    assert first.parent.name == "Tal-v-Botvinnik-1960"
    assert second.parent.name == "Tal-v-Botvinnik-1960-2"
    assert first.exists() and second.exists()


def test_naming_survives_unknown_players(tmp_path, monkeypatch):
    monkeypatch.setattr(build_video, "OUT", tmp_path)
    monkeypatch.setattr(build_video, "ROOT", tmp_path)
    real = tmp_path / "apps" / "renderer" / "out"
    real.mkdir(parents=True)
    (real / "video.mp4").write_bytes(b"video")

    dest = build_video._named_video_copy({"meta": {"white": "?", "black": None}})
    assert dest is not None and dest.parent.name.startswith("Unknown-v-Unknown")
