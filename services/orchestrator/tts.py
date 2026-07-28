"""Pass 3 — voice synthesis with word-level timestamps.

Two backends, one output shape:

* ``elevenlabs`` (preferred) uses the ``/with-timestamps`` endpoint, which
  returns the audio *and* per-character alignment. That gives us both the exact
  clip duration and the moment every word is spoken — so a highlight can land
  precisely on "pinned" and a piece can start moving exactly when its square is
  named. No ffmpeg needed: the duration comes from the alignment, not from
  decoding the audio.
* ``local`` is the zero-cost fallback: Windows SAPI via PowerShell (reliable
  for long unattended batches, unlike pyttsx3, which wedges partway through a
  queued batch on SAPI5), or pyttsx3 one-clip-at-a-time elsewhere. Word times
  are estimated proportionally from character offsets, so the rest of the
  pipeline behaves identically.

Manifest written to ``audio_manifest.json``::

    {
      "backend": "elevenlabs",
      "ext": "mp3",
      "clips": {
        "b0001": {"file": "b0001.mp3", "durationMs": 3210,
                  "words": [{"w": "today", "s": 0.0, "e": 0.31}, ...]}
      }
    }
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
API_ROOT = "https://api.elevenlabs.io/v1"

_WORD_STRIP = re.compile(r"^[^\w#+=-]+|[^\w#+=-]+$")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _norm_word(w: str) -> str:
    return _WORD_STRIP.sub("", w).lower()


def _cache_key(text: str, voice_id: str, model_id: str, fmt: str) -> str:
    raw = f"{voice_id}|{model_id}|{fmt}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _words_from_alignment(alignment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Group ElevenLabs per-character timings into word timings."""
    chars: Sequence[str] = alignment.get("characters") or []
    starts: Sequence[float] = alignment.get("character_start_times_seconds") or []
    ends: Sequence[float] = alignment.get("character_end_times_seconds") or []
    if not chars or len(chars) != len(starts) or len(chars) != len(ends):
        return []

    words: List[Dict[str, Any]] = []
    buf: List[str] = []
    buf_start: Optional[float] = None
    buf_end: float = 0.0

    def flush() -> None:
        nonlocal buf, buf_start, buf_end
        if buf and buf_start is not None:
            w = _norm_word("".join(buf))
            if w:
                words.append({"w": w, "s": round(buf_start, 3), "e": round(buf_end, 3)})
        buf = []
        buf_start = None

    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            flush()
            continue
        if buf_start is None:
            buf_start = s
        buf.append(ch)
        buf_end = e
    flush()
    return words


def _estimate_words(text: str, duration_ms: int) -> List[Dict[str, Any]]:
    """Proportional word timings for backends without real alignment."""
    total = max(1, len(text))
    dur_s = duration_ms / 1000.0
    words: List[Dict[str, Any]] = []
    cursor = 0
    for raw in text.split():
        idx = text.find(raw, cursor)
        if idx < 0:
            idx = cursor
        start = (idx / total) * dur_s
        end = ((idx + len(raw)) / total) * dur_s
        w = _norm_word(raw)
        if w:
            words.append({"w": w, "s": round(start, 3), "e": round(end, 3)})
        cursor = idx + len(raw)
    return words


# --------------------------------------------------------------------------
# ElevenLabs
# --------------------------------------------------------------------------


def _eleven_synthesize_one(
    text: str,
    *,
    api_key: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    stability: float,
    similarity: float,
    style: float,
    speed: float,
    retries: int = 3,
) -> Tuple[bytes, List[Dict[str, Any]], int]:
    """Return (audio_bytes, words, duration_ms) for a single line."""
    import requests

    url = f"{API_ROOT}/text-to-speech/{voice_id}/with-timestamps"
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity,
            "style": style,
            "use_speaker_boost": True,
            "speed": speed,
        },
    }
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}

    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                params={"output_format": output_format},
                timeout=180,
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = min(30, 2 ** attempt)
                print(f"[tts] ElevenLabs {resp.status_code}; retrying in {wait}s…")
                time.sleep(wait)
                last_err = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt == retries:
                raise
            time.sleep(min(30, 2 ** attempt))
    else:  # pragma: no cover - loop always breaks or raises
        raise last_err or RuntimeError("ElevenLabs synthesis failed")

    audio_b64 = data.get("audio_base64")
    if not audio_b64:
        raise RuntimeError("ElevenLabs response contained no audio")
    audio = base64.b64decode(audio_b64)

    alignment = data.get("normalized_alignment") or data.get("alignment") or {}
    words = _words_from_alignment(alignment)

    ends = alignment.get("character_end_times_seconds") or []
    duration_ms = int(round(float(ends[-1]) * 1000)) if ends else 0
    if duration_ms <= 0 and words:
        duration_ms = int(round(words[-1]["e"] * 1000))
    return audio, words, max(duration_ms, 200)


# --------------------------------------------------------------------------
# pyttsx3 fallback
# --------------------------------------------------------------------------


_SAPI_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $female = $synth.GetInstalledVoices() |
        Where-Object { $_.Enabled -and $_.VoiceInfo.Gender -eq 'Female' } |
        Select-Object -First 1
    if ($female) { $synth.SelectVoice($female.VoiceInfo.Name) }
} catch { }
$synth.Rate = 0
$synth.Volume = 100
$items = Get-Content -Raw -Encoding UTF8 $env:TTS_MANIFEST | ConvertFrom-Json
foreach ($item in $items) {
    $path = Join-Path $env:TTS_OUTDIR ($item.id + '.wav')
    $synth.SetOutputToWaveFile($path)
    $synth.Speak($item.text)
}
$synth.SetOutputToNull()
$synth.Dispose()
"""


def _windows_sapi_synthesize(
    lines: Sequence[Dict[str, str]], out_dir: Path
) -> Dict[str, Dict[str, Any]]:
    """Synthesize via Windows SAPI directly.

    pyttsx3 queues several `save_to_file` calls before a single `runAndWait()`,
    which hangs indefinitely on Windows SAPI5 partway through a long batch —
    fatal for an unattended daily run. Driving System.Speech from one
    PowerShell process is reliable and needs no extra dependencies.
    """
    import shutil as _shutil
    import subprocess

    powershell = _shutil.which("powershell") or _shutil.which("pwsh")
    if not powershell:
        raise RuntimeError("PowerShell not found")

    manifest = out_dir / "_sapi_manifest.json"
    manifest.write_text(
        json.dumps([{"id": l["id"], "text": l["text"]} for l in lines], ensure_ascii=False),
        encoding="utf-8",
    )
    script_path = out_dir / "_sapi_synth.ps1"
    script_path.write_text(_SAPI_SCRIPT, encoding="utf-8")

    env = dict(os.environ, TTS_MANIFEST=str(manifest), TTS_OUTDIR=str(out_dir))
    print(f"[tts] synthesizing {len(lines)} lines via Windows SAPI…")
    subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script_path)],
        check=True,
        env=env,
        timeout=60 * 30,
    )
    for tmp in (manifest, script_path):
        try:
            tmp.unlink()
        except OSError:
            pass
    return _measure_wavs(lines, out_dir)


def _measure_wavs(
    lines: Sequence[Dict[str, str]], out_dir: Path
) -> Dict[str, Dict[str, Any]]:
    """Read durations from generated WAVs, filling gaps with silence."""
    import wave

    from pydub import AudioSegment

    clips: Dict[str, Dict[str, Any]] = {}
    for item in lines:
        path = out_dir / f"{item['id']}.wav"
        duration_ms = 0
        try:
            # stdlib `wave` reads PCM WAV without needing ffmpeg.
            with wave.open(str(path), "rb") as wav:
                duration_ms = int(wav.getnframes() / float(wav.getframerate()) * 1000)
        except Exception:
            duration_ms = 0

        if duration_ms <= 0:
            duration_ms = max(1200, int(len(item["text"]) / 14.0 * 1000))
            AudioSegment.silent(duration=duration_ms).export(path, format="wav")
            print(f"[tts] placeholder for {item['id']} ({duration_ms} ms)")

        clips[item["id"]] = {
            "file": path.name,
            "durationMs": duration_ms,
            "words": _estimate_words(item["text"], duration_ms),
        }
    return clips


def _pyttsx3_synthesize(
    lines: Sequence[Dict[str, str]], out_dir: Path
) -> Dict[str, Dict[str, Any]]:
    """One clip per engine lifecycle — slower, but it does not wedge."""
    import pyttsx3

    total = len(lines)
    for idx, item in enumerate(lines, start=1):
        engine = pyttsx3.init()
        engine.setProperty("rate", 170)
        engine.setProperty("volume", 0.95)
        try:
            for v in engine.getProperty("voices") or []:
                name = (getattr(v, "name", "") or "").lower()
                if any(k in name for k in ("zira", "female", "hazel", "eva", "samantha")):
                    engine.setProperty("voice", v.id)
                    break
        except Exception:
            pass
        engine.save_to_file(item["text"], str(out_dir / f"{item['id']}.wav"))
        engine.runAndWait()
        engine.stop()
        if idx % 10 == 0 or idx == total:
            print(f"[tts] local {idx}/{total}")
    return _measure_wavs(lines, out_dir)


def _local_synthesize(
    lines: Sequence[Dict[str, str]],
    out_dir: Path,
    batch_size: int = 8,  # kept for call compatibility; unused
) -> Dict[str, Dict[str, Any]]:
    if sys.platform == "win32":
        try:
            return _windows_sapi_synthesize(lines, out_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"[tts] SAPI path failed ({exc}); falling back to pyttsx3")
    return _pyttsx3_synthesize(lines, out_dir)


# --------------------------------------------------------------------------
# Qwen3-TTS (local, Apache-2.0)
# --------------------------------------------------------------------------


def _align_words(
    wav_path: Path, text: str, duration_ms: int, model_cache: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Word timings for a locally generated clip.

    Local TTS returns audio but no alignment, and the pipeline needs to know
    when each word is spoken so a piece can start moving as its square is named.
    Forced alignment recovers that: we already know the exact transcript, so
    this is a well-posed problem rather than open-ended transcription.

    Falls back to proportional estimates, which are good enough that the video
    still works — the move just lands approximately rather than exactly.
    """
    if os.getenv("QWEN_ALIGN", "1").strip().lower() in ("0", "false", "no"):
        return _estimate_words(text, duration_ms)
    try:
        import whisperx  # type: ignore

        device = "cuda" if os.getenv("QWEN_DEVICE", "cuda:0").startswith("cuda") else "cpu"
        if "align_model" not in model_cache:
            model_cache["align_model"], model_cache["align_meta"] = whisperx.load_align_model(
                language_code="en", device=device
            )
        audio = whisperx.load_audio(str(wav_path))
        aligned = whisperx.align(
            [{"start": 0.0, "end": duration_ms / 1000.0, "text": text}],
            model_cache["align_model"],
            model_cache["align_meta"],
            audio,
            device,
            return_char_alignments=False,
        )
        words: List[Dict[str, Any]] = []
        for seg in aligned.get("segments", []):
            for w in seg.get("words", []):
                token = _norm_word(str(w.get("word", "")))
                if token and w.get("start") is not None:
                    words.append(
                        {"w": token, "s": round(float(w["start"]), 3), "e": round(float(w.get("end", w["start"])), 3)}
                    )
        if words:
            return words
    except ImportError:
        print("[tts] whisperx not installed — using estimated word timings "
              "(pip install whisperx for exact move cues)")
        model_cache["align_warned"] = True
    except Exception as exc:  # noqa: BLE001
        if not model_cache.get("align_warned"):
            print(f"[tts] forced alignment unavailable ({exc}); using estimates")
            model_cache["align_warned"] = True
    return _estimate_words(text, duration_ms)


def _qwen_synthesize(
    lines: Sequence[Dict[str, str]], out_dir: Path, batch_size: int = 16
) -> Dict[str, Dict[str, Any]]:
    """Local narration via Qwen3-TTS, cloned from the channel's reference voice.

    Set up the voice once with ``services/orchestrator/voice_design.py``; this
    reads the clip it produced and reuses it for every line, so the narrator
    sounds identical across the whole channel.
    """
    import wave

    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    ref_audio = os.getenv("VOICE_REF_AUDIO", "").strip()
    if not ref_audio or not Path(ref_audio).exists():
        raise RuntimeError(
            "VOICE_REF_AUDIO is not set or missing. Run: "
            "python services/orchestrator/voice_design.py --list"
        )

    ref_text_path = os.getenv("VOICE_REF_TEXT", "").strip()
    if ref_text_path and Path(ref_text_path).exists():
        ref_text = Path(ref_text_path).read_text(encoding="utf-8").strip()
    else:
        ref_text = os.getenv("VOICE_REF_TEXT_INLINE", "").strip()
    if not ref_text:
        raise RuntimeError("VOICE_REF_TEXT must point at the reference clip's transcript.")

    device = os.getenv("QWEN_DEVICE", "cuda:0")
    attn = os.getenv("QWEN_ATTN", "sdpa")
    model_id = os.getenv("QWEN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")

    print(f"[tts] loading {model_id} on {device} (attn={attn})…")
    model = Qwen3TTSModel.from_pretrained(
        model_id, device_map=device, dtype=torch.bfloat16, attn_implementation=attn
    )

    # Build the clone prompt once; it is reused for every line in the video.
    prompt = model.create_voice_clone_prompt(
        ref_audio=ref_audio, ref_text=ref_text, x_vector_only_mode=False
    )

    clips: Dict[str, Dict[str, Any]] = {}
    cache: Dict[str, Any] = {}
    total = len(lines)

    for start in range(0, total, batch_size):
        batch = list(lines[start : start + batch_size])
        texts = [b["text"] for b in batch]
        wavs, sr = model.generate_voice_clone(
            text=texts,
            language=["English"] * len(texts),
            voice_clone_prompt=prompt,
        )
        for item, wav in zip(batch, wavs):
            path = out_dir / f"{item['id']}.wav"
            sf.write(str(path), wav, sr)
            # Duration comes from the file, so beat timing is exact.
            with wave.open(str(path), "rb") as fh:
                duration_ms = int(fh.getnframes() / float(fh.getframerate()) * 1000)
            clips[item["id"]] = {
                "file": path.name,
                "durationMs": duration_ms,
                "words": _align_words(path, item["text"], duration_ms, cache),
            }
        print(f"[tts] qwen {min(start + batch_size, total)}/{total}")

    return clips


def _silent_synthesize(lines: Sequence[Dict[str, str]], out_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Silent placeholders sized to the text — for fast structural test renders."""
    from pydub import AudioSegment

    clips: Dict[str, Dict[str, Any]] = {}
    for item in lines:
        # ~14 characters per second is close to natural narration pace.
        duration_ms = max(1200, int(len(item["text"]) / 14.0 * 1000))
        path = out_dir / f"{item['id']}.wav"
        AudioSegment.silent(duration=duration_ms).export(path, format="wav")
        clips[item["id"]] = {
            "file": path.name,
            "durationMs": duration_ms,
            "words": _estimate_words(item["text"], duration_ms),
        }
    print(f"[tts] generated {len(clips)} silent placeholder clips")
    return clips


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def synthesize(
    lines: Sequence[Dict[str, str]],
    out_dir: str | Path,
    *,
    backend: str = "auto",
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
    output_format: Optional[str] = None,
    cache_dir: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Synthesize ``[{"id","text"}, ...]`` and return an audio manifest.

    ``backend``: ``auto`` (Qwen when VOICE_REF_AUDIO is set, else ElevenLabs
    when configured, else local), ``qwen``, ``elevenlabs``, ``local``, or
    ``silent``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [l for l in lines if (l.get("text") or "").strip()]

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice_id = voice_id or os.getenv("VOICE_ID", "").strip()
    model_id = model_id or os.getenv("ELEVENLABS_MODEL", DEFAULT_MODEL)
    output_format = output_format or os.getenv("ELEVENLABS_FORMAT", DEFAULT_OUTPUT_FORMAT)

    resolved = backend
    if backend == "auto":
        if os.getenv("VOICE_REF_AUDIO", "").strip():
            resolved = "qwen"
        elif api_key and voice_id:
            resolved = "elevenlabs"
        else:
            resolved = "local"

    if resolved == "elevenlabs" and not (api_key and voice_id):
        print("[tts] ELEVENLABS_API_KEY/VOICE_ID missing — falling back to local TTS")
        resolved = "local"

    if resolved == "qwen":
        try:
            clips = _qwen_synthesize(lines, out_dir)
            ext = "wav"
            manifest = {"backend": resolved, "ext": ext, "clips": clips}
            (out_dir.parent / "audio_manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            return manifest
        except Exception as exc:  # noqa: BLE001
            # A daily unattended run must still produce a video.
            print(f"[tts] Qwen backend failed ({exc}); falling back to local TTS")
            resolved = "local"

    if resolved == "silent":
        clips = _silent_synthesize(lines, out_dir)
        ext = "wav"
    elif resolved == "local":
        clips = _local_synthesize(lines, out_dir)
        ext = "wav"
    else:
        ext = "wav" if output_format.startswith("wav") else "mp3"
        cache_root = Path(cache_dir) if cache_dir else out_dir / "cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        clips = {}

        stability = float(os.getenv("ELEVENLABS_STABILITY", "0.45"))
        similarity = float(os.getenv("ELEVENLABS_SIMILARITY", "0.80"))
        style = float(os.getenv("ELEVENLABS_STYLE", "0.35"))
        speed = float(os.getenv("ELEVENLABS_SPEED", "1.0"))

        total = len(lines)
        for idx, item in enumerate(lines, start=1):
            key = _cache_key(item["text"], voice_id, model_id, output_format)
            meta_path = cache_root / f"{key}.json"
            audio_cache = cache_root / f"{key}.{ext}"
            dest = out_dir / f"{item['id']}.{ext}"

            if meta_path.exists() and audio_cache.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                dest.write_bytes(audio_cache.read_bytes())
                clips[item["id"]] = {
                    "file": dest.name,
                    "durationMs": meta["durationMs"],
                    "words": meta["words"],
                }
                print(f"[tts] {idx}/{total} {item['id']} (cached)")
                continue

            audio, words, duration_ms = _eleven_synthesize_one(
                item["text"],
                api_key=api_key,
                voice_id=voice_id,
                model_id=model_id,
                output_format=output_format,
                stability=stability,
                similarity=similarity,
                style=style,
                speed=speed,
            )
            dest.write_bytes(audio)
            audio_cache.write_bytes(audio)
            meta_path.write_text(
                json.dumps({"durationMs": duration_ms, "words": words}), encoding="utf-8"
            )
            clips[item["id"]] = {
                "file": dest.name,
                "durationMs": duration_ms,
                "words": words,
            }
            print(f"[tts] {idx}/{total} {item['id']} ({duration_ms} ms)")

    manifest = {"backend": resolved, "ext": ext, "clips": clips}
    (out_dir.parent / "audio_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def word_time(clip: Dict[str, Any], *targets: str, default: Optional[float] = None) -> Optional[float]:
    """Seconds at which the first of ``targets`` is spoken in ``clip``."""
    words = clip.get("words") or []
    wanted = [_norm_word(t) for t in targets if t]
    for target in wanted:
        if not target:
            continue
        for entry in words:
            if entry["w"] == target:
                return entry["s"]
    # Loose match: a word that contains the target (e.g. "e4," or "knight's")
    for target in wanted:
        for entry in words:
            if target and target in entry["w"]:
                return entry["s"]
    return default
