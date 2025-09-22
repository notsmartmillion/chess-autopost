# Run from repo root:  python services/orchestrator/build_video.py
# Requires (in .venv):
#   pip install -e ./apps/analyzer[dev] pyttsx3 pydub
# Optional (for LLM narration):
#   pip install openai  (and set OPENAI_API_KEY)

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from chessbot_analyzer.timeline import TimelineBuilder
from chessbot_analyzer.scripting import ScriptGenerator
from chessbot_analyzer.utils.logging import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
AUDIO_DIR = OUT / "audio"
PUB = ROOT / "apps" / "renderer" / "public"
PUB_AUDIO = PUB / "audio"

FPS = 30  # must match renderer


def ensure_dirs() -> None:
    OUT.mkdir(exist_ok=True, parents=True)
    AUDIO_DIR.mkdir(exist_ok=True, parents=True)
    PUB.mkdir(exist_ok=True, parents=True)
    PUB_AUDIO.mkdir(exist_ok=True, parents=True)


def approx_cues_for_scene(scene: Dict, has_pin: bool) -> Dict[str, float]:
    cues = {"move": 0.05, "eval": 0.35}
    if has_pin:
        cues["pinned"] = 0.60
    return cues


def choose_female_voice(engine) -> None:
    try:
        voices = engine.getProperty("voices") or []
        for v in voices:
            name = (getattr(v, "name", "") or "").lower()
            gender = (getattr(v, "gender", "") or "").lower()
            if "female" in gender or any(
                k in name for k in ["female", "zira", "susan", "eva", "helen", "sophie", "mary", "zofia", "anna"]
            ):
                engine.setProperty("voice", v.id)
                break
    except Exception:
        pass


def ensure_silent_wav(path: Path, duration_ms: int) -> None:
    from pydub import AudioSegment

    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    AudioSegment.silent(duration=max(100, duration_ms)).export(path, format="wav")


def synthesize_batched(lines: List[Tuple[str, str, int]], batch_size: int = 8) -> Dict[str, int]:
    """
    lines: list of (scene_id, text, fallback_ms)
    Returns: dict scene_id -> measured duration_ms
    """
    from pydub import AudioSegment
    import pyttsx3

    durations: Dict[str, int] = {}

    for b in range(0, len(lines), batch_size):
        batch = lines[b : b + batch_size]
        if not batch:
            continue

        engine = pyttsx3.init()
        engine.setProperty("rate", 175)
        engine.setProperty("volume", 0.95)
        choose_female_voice(engine)

        print(f"[tts] batching {len(batch)} clip(s) ({b+1}–{b+len(batch)}/{len(lines)})…")
        for sid, text, _fallback in batch:
            engine.save_to_file(text, str(AUDIO_DIR / f"{sid}.wav"))
        engine.runAndWait()
        engine.stop()
        time.sleep(0.25)

        for sid, _text, fallback_ms in batch:
            p = AUDIO_DIR / f"{sid}.wav"
            try:
                if not p.exists() or p.stat().st_size == 0:
                    raise FileNotFoundError
                seg = AudioSegment.from_file(p)
                durations[sid] = int(seg.duration_seconds * 1000)
            except Exception:
                ensure_silent_wav(p, fallback_ms)
                durations[sid] = fallback_ms
                print(f"[tts] fallback silent clip for {sid} ({fallback_ms} ms)")
    return durations


def main() -> None:
    ensure_dirs()

    # --- 1) choose / load a game (swap later to selectors/ingest) ---
    pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *"
    tb = TimelineBuilder()
    timeline = tb.from_pgn(pgn, alt_preview_plies=2, alt_max=2)
    tl_json = timeline.dict() if hasattr(timeline, "dict") else timeline
    meta = tl_json.get("meta", {}) or {}

    # --- 2) Narration (intro/outro from ASMR ScriptGenerator; per-scene via LLM-first) ---
    sg = ScriptGenerator(channel_name="Quiet Chess")
    intro_text = sg.make_intro(meta, tl_json)
    outro_text = sg.make_outro(meta, tl_json)

    # Try LLM narration that is aware of precomputed alt-lines; fall back to ScriptGenerator.
    move_lines: List[Dict[str, str]] = []
    try:
        from chessbot_analyzer.scripting_llm import from_timeline_llm  # optional module
        move_lines = from_timeline_llm(tl_json)
        if move_lines:
            print(f"[narration] Using LLM narration → {len(move_lines)} lines.")
        else:
            print("[narration] LLM returned no lines; falling back to built-in ScriptGenerator.")
    except Exception as e:
        print(f"[narration] LLM unavailable or failed: {e}. Falling back to built-in ScriptGenerator.")

    if not move_lines:
        move_lines = sg.from_timeline(tl_json, include_keywords=True, include_reset=False)
        move_lines = sg.optimize_for_audio_sync(move_lines)
        print(f"[narration] Using built-in ScriptGenerator → {len(move_lines)} lines.")

    by_id = {v["id"]: v for v in move_lines}

    # Inject cueTimes for renderer animation
    for s in tl_json["scenes"]:
        if s["type"] == "main":
            s["cueTimes"] = approx_cues_for_scene(s, bool(s.get("pins")))
        elif s["type"] == "alt":
            s["cueTimes"] = {"alt": 0.05, "arrow": 0.18, "attacked": 0.35}
        # reset scenes: no cueTimes

    # Persist timeline + VO text
    (OUT / "timeline.json").write_text(json.dumps(tl_json, indent=2), encoding="utf-8")
    (OUT / "voice_lines.json").write_text(json.dumps(move_lines, indent=2), encoding="utf-8")
    print("[ok] wrote outputs/timeline.json and outputs/voice_lines.json")

    # --- 3) TTS tasks list (intro + all scene lines + outro) ---
    tasks: List[Tuple[str, str, int]] = []
    if intro_text:
        tasks.append(("intro", intro_text, 3000))
    for s in tl_json["scenes"]:
        if s["type"] == "reset":
            continue
        sid = s["id"]
        text = by_id.get(sid, {}).get("text")
        if text:
            tasks.append((sid, text, int(s.get("durationMs", 1200))))
    if outro_text:
        tasks.append(("outro", outro_text, 2500))

    durations = synthesize_batched(tasks, batch_size=8) if tasks else {}
    (OUT / "audio_durations.json").write_text(json.dumps(durations, indent=2), encoding="utf-8")
    print(f"[ok] synthesized {len(durations)} audio clips")

    # Stash intro/outro durations into meta for renderer sequencing
    meta["introMs"] = int(durations.get("intro", 0))
    meta["outroMs"] = int(durations.get("outro", 0))
    tl_json["meta"] = meta
    (OUT / "timeline.json").write_text(json.dumps(tl_json, indent=2), encoding="utf-8")

    # --- 4) sync to renderer/public ---
    shutil.copy2(OUT / "timeline.json", PUB / "timeline.json")
    shutil.copy2(OUT / "audio_durations.json", PUB / "audio_durations.json")
    PUB_AUDIO.mkdir(exist_ok=True, parents=True)
    for wav in AUDIO_DIR.glob("*.wav"):
        shutil.copy2(wav, PUB_AUDIO / wav.name)
    print("[ok] assets synced to apps/renderer/public")

    # --- 5) render exact length ---
    total_ms = int(tl_json.get("totalDurationMs", 0)) + meta.get("introMs", 0) + meta.get("outroMs", 0)
    frames = max(1, round((total_ms / 1000) * FPS))
    cmd = ["npm", "--prefix", "apps/renderer", "run", "render", "--", f"--frame-range=0-{frames-1}"]
    print("[render] running:", " ".join(cmd))
    subprocess.check_call(cmd)
    print("[ok] render complete → apps/renderer/out/video.mp4")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
