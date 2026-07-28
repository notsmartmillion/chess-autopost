"""Render one game's narration in every candidate voice, for A/B auditioning.

Reads the beats from an existing outputs/script.json (build it once with
``--tts silent --no-render`` if you don't have one), then asks the local TTS
service for a full narration track per voice. Nothing is re-analysed, so the
words are identical across voices — only the voice changes.

Usage:
    python services/orchestrator/voice_ab_test.py                    # all voices
    python services/orchestrator/voice_ab_test.py --voices asmr_03,candidate_02
    python services/orchestrator/voice_ab_test.py --max-beats 12     # short sample
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_JSON = ROOT / "outputs" / "script.json"
OUT_DIR = ROOT / "outputs" / "voice_ab"
API = os.getenv("TTS_API_URL", "http://127.0.0.1:8010").rstrip("/")


def api_post(path: str, payload: dict, timeout: int = 3600,
             attempts: int = 3) -> bytes:
    """POST with retries. A voice takes ~10 minutes to render, so losing the
    whole batch to one dropped connection is expensive."""
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            f"{API}{path}", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as exc:
            if exc.code < 500 or attempt == attempts:
                raise
            reason = f"HTTP {exc.code}"
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            if attempt == attempts:
                raise
            reason = str(exc)
        print(f"    {reason} — retry {attempt}/{attempts - 1}")
        time.sleep(5 * attempt)
    raise RuntimeError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default=str(SCRIPT_JSON))
    ap.add_argument("--voices", default="", help="comma-separated (default: all)")
    ap.add_argument("--max-beats", type=int, default=0, help="0 = whole game")
    ap.add_argument("--gap-ms", type=int, default=280)
    ap.add_argument("--format", default="mp3", choices=["wav", "mp3"])
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--overwrite", action="store_true",
                    help="re-render voices that already have a file")
    a = ap.parse_args()

    script_path = Path(a.script)
    if not script_path.exists():
        raise SystemExit(
            f"{script_path} not found — build one first:\n"
            "  python services/orchestrator/build_video.py --pgn <game.pgn> "
            "--tts silent --no-render")
    data = json.loads(script_path.read_text(encoding="utf-8"))
    beats = data.get("beats", data if isinstance(data, list) else [])
    segments = [b["text"] for b in beats if (b.get("text") or "").strip()]
    if a.max_beats:
        segments = segments[: a.max_beats]
    if not segments:
        raise SystemExit("no narration text found in script.json")

    voices = [v.strip() for v in a.voices.split(",") if v.strip()]
    if not voices:
        with urllib.request.urlopen(f"{API}/voices", timeout=30) as r:
            voices = json.loads(r.read())["voices"]
    if not voices:
        raise SystemExit("no voice profiles on the TTS service")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    words = sum(len(s.split()) for s in segments)
    print(f"{len(segments)} beats, ~{words} words, {len(voices)} voices -> {out}")

    failed: list[str] = []
    for v in voices:
        dest = out / f"{v}.{a.format}"
        if dest.exists() and dest.stat().st_size > 0 and not a.overwrite:
            print(f"  {v:<14} already rendered — skipping (--overwrite to redo)")
            continue
        t0 = time.time()
        try:
            audio = api_post("/tts/batch", {
                "segments": segments, "voice": v,
                "gap_ms": a.gap_ms, "format": a.format})
        except Exception as exc:  # noqa: BLE001
            # One bad voice should not cost the other eleven.
            print(f"  {v:<14} FAILED: {exc}")
            failed.append(v)
            continue
        dest.write_bytes(audio)
        mb = len(audio) / 1e6
        print(f"  {v:<14} {time.time() - t0:6.1f}s  {mb:5.1f} MB  {dest.name}")

    if failed:
        print(f"\n{len(failed)} voice(s) failed: {', '.join(failed)}")
        print("Re-run the same command to retry only those.")

    print(f"\nListen and pick one, then set in .env:\n  TTS_BACKEND=ttsapi\n  TTS_VOICE=<name>")


if __name__ == "__main__":
    main()
