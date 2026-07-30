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

# How many words one synthesis request may cover. Deliberately far above the
# director's writing budget: breath groups are about how the script is written,
# takes are about how few times the voice restarts.
SYNTH_WORD_BUDGET = 170


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
        model_cache["aligned"] = False
        return _estimate_words(text, duration_ms)
    try:
        import whisperx  # type: ignore

        # CPU alignment is plenty fast (wav2vec2 is small); requesting cuda on
        # a CPU-only torch install would throw and silently cost us alignment.
        try:
            import torch  # type: ignore

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
        if "align_model" not in model_cache:
            model_cache["align_model"], model_cache["align_meta"] = whisperx.load_align_model(
                language_code="en", device=device
            )
        # whisperx.load_audio shells out to ffmpeg, which this box does not
        # have. The clips are plain PCM wavs, so decode and resample natively.
        import wave as _wave

        import numpy as np  # type: ignore

        with _wave.open(str(wav_path), "rb") as fh:
            sr = fh.getframerate()
            ch = fh.getnchannels()
            pcm = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16)
        if ch > 1:
            pcm = pcm.reshape(-1, ch).mean(axis=1)
        audio = pcm.astype(np.float32) / 32768.0
        if sr != 16000:
            import torchaudio  # type: ignore

            audio = torchaudio.functional.resample(
                torch.from_numpy(audio)[None], sr, 16000
            )[0].numpy()
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
            model_cache["aligned"] = True
            return words
    except ImportError as exc:
        print(f"[tts] alignment unavailable ({exc}) — using estimated word "
              "timings (pip install whisperx for exact move cues)")
        model_cache["align_warned"] = True
    except Exception as exc:  # noqa: BLE001
        if not model_cache.get("align_warned"):
            print(f"[tts] forced alignment unavailable ({exc}); using estimates")
            model_cache["align_warned"] = True
    model_cache["aligned"] = False
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


def _ffmpeg() -> Optional[str]:
    """Locate ffmpeg, which is not on PATH in every shell on this box."""
    import shutil as _shutil

    found = _shutil.which("ffmpeg") or _shutil.which("ffmpeg.exe")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        hits = list(Path(local).glob("Microsoft/WinGet/Packages/*FFmpeg*/**/ffmpeg.exe"))
        if hits:
            return str(hits[0])
    return None


def _median_f0(path: Path, start_s: float = 0.0, dur_s: Optional[float] = None) -> float:
    """Median voiced pitch of a clip (or a segment of it), by autocorrelation.

    ``start_s`` may be negative to measure from the end — ``-1.0`` reads the
    final second, which is how seam edges are inspected. Returns 0.0 when the
    segment holds no voiced frames.
    """
    import wave as _wave

    import numpy as np  # type: ignore

    with _wave.open(str(path), "rb") as fh:
        sr = fh.getframerate()
        ch = fh.getnchannels()
        pcm = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    if start_s:
        pcm = pcm[int(start_s * sr) :]  # negative start reads from the end
    if dur_s is not None:
        pcm = pcm[: int(dur_s * sr)]
    win = int(sr * 0.04)
    lo, hi = int(sr / 350), int(sr / 70)
    out = []
    for i in range(0, max(0, len(pcm) - win), int(sr * 0.02)):
        frame = pcm[i : i + win].astype(np.float64)
        if np.sqrt((frame ** 2).mean()) < 300:  # silence / unvoiced
            continue
        frame -= frame.mean()
        ac = np.correlate(frame, frame, "full")[win - 1 :]
        if hi >= len(ac):
            continue
        k = int(np.argmax(ac[lo:hi]) + lo)
        if ac[k] > 0.3 * ac[0]:
            out.append(sr / k)
    return float(np.median(out)) if out else 0.0


def _pitch_glide(
    path: Path, head_factor: float, tail_factor: float, edge_s: float = 1.2
) -> bool:
    """Glide the pitch at a take's edges, leaving the middle untouched.

    A constant shift cannot fix a seam — the problem is the *contour*: takes
    open sharp and close low, so the join is a step however well their averages
    match. This eases the first ``edge_s`` from ``head_factor`` to unity and
    the last ``edge_s`` from unity to ``tail_factor``, in ~1% steps every
    120 ms, which is at the threshold of pitch discrimination in running
    speech — heard as natural drift, not as processing.

    Duration is sacred (beat lengths, word timings and the frame grid all hang
    off it), so the output is padded or clipped back to the exact input length.
    """
    if abs(head_factor - 1.0) < 0.01 and abs(tail_factor - 1.0) < 0.01:
        return True
    ff = _ffmpeg()
    if not ff:
        return False
    import math
    import subprocess
    import wave as _wave

    with _wave.open(str(path), "rb") as fh:
        sr = fh.getframerate()
        before = fh.getnframes()
    total_s = before / sr
    edge_s = min(edge_s, total_s / 3)
    if edge_s < 0.3:
        return False

    # Hold the full correction across the join itself, then ease it away. An
    # immediate taper is what made the first attempt too weak: by the time the
    # listener's ear settles on the new take, most of the correction had
    # already been given back.
    plateau = min(0.5, edge_s / 3)
    ramp = edge_s - plateau
    steps = 8
    lines = [f"0.000 rubberband pitch {head_factor:.5f};"]
    for i in range(steps + 1):
        t = plateau + ramp * i / steps
        w = (1 + math.cos(math.pi * i / steps)) / 2
        f = 1.0 + (head_factor - 1.0) * w
        lines.append(f"{t:.3f} rubberband pitch {f:.5f};")
    for i in range(steps + 1):
        t = (total_s - edge_s) + ramp * i / steps
        w = (1 - math.cos(math.pi * i / steps)) / 2
        f = 1.0 + (tail_factor - 1.0) * w
        lines.append(f"{max(0.0, t):.3f} rubberband pitch {f:.5f};")
    lines.append(f"{max(0.0, total_s - 0.05):.3f} rubberband pitch {tail_factor:.5f};")

    cmds = path.with_suffix(".cmds")
    cmds.write_text("\n".join(lines) + "\n", encoding="ascii")
    tmp = path.with_suffix(".glide.wav")
    try:
        # cwd trick: sendcmd's f= argument chokes on Windows drive colons.
        subprocess.run(
            [ff, "-y", "-hide_banner", "-loglevel", "error",
             "-i", path.name,
             "-af", f"asendcmd=f={cmds.name},rubberband=pitch={head_factor:.5f}",
             tmp.name],
            cwd=str(path.parent), capture_output=True, check=True,
        )
        with _wave.open(str(tmp), "rb") as fh:
            params = fh.getparams()
            data = fh.readframes(fh.getnframes())
        width = params.sampwidth * params.nchannels
        want = before * width
        data = data[:want] + b"\x00" * max(0, want - len(data))
        with _wave.open(str(path), "wb") as fh:
            fh.setparams(params)
            fh.setnframes(before)
            fh.writeframes(data)
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        tmp.unlink(missing_ok=True)
        cmds.unlink(missing_ok=True)


def _flatten_seams(
    paths: Sequence[Path], target_step_hz: float = 12.0, edge_s: float = 1.2
) -> None:
    """Make consecutive takes meet like sentences, not like separate speakers.

    Each take opens ~26 Hz above its own median and closes ~25 Hz below, so a
    seam is a ~50 Hz step from a falling cadence into a fresh attack — heard as
    the narrator being swapped. A natural speaker resets pitch at a sentence
    boundary too, just far less, so the goal is not zero: each seam is eased
    until its step matches ``target_step_hz``, splitting the correction between
    the tail below and the head above it.

    The first take's opening and the last take's closing cadence are left
    alone — a video should start fresh and end final.
    """
    if os.getenv("TTS_SEAM_FLATTEN", "1").strip().lower() in ("0", "false", "no"):
        return
    if len(paths) < 2 or not _ffmpeg():
        return

    # The join is judged over its last/first beat of speech, so measure tight:
    # a wide window dilutes the very step being corrected.
    meas = 0.6

    def steps_now() -> List[Optional[float]]:
        heads = [_median_f0(p, 0.0, meas) for p in paths]
        tails = [_median_f0(p, -meas) for p in paths]
        return [
            (heads[i] - tails[i - 1]) if heads[i] and tails[i - 1] else None
            for i in range(1, len(paths))
        ]

    import statistics

    before = steps_now()
    seams = [s for s in before if s is not None]
    if not seams:
        return

    # Correcting through a pitch shifter is not exact, so converge in bounded
    # passes: apply, re-measure, correct the remainder.
    fixed = 0
    for _ in range(2):
        current = steps_now()
        heads = [_median_f0(p, 0.0, meas) for p in paths]
        tails = [_median_f0(p, -meas) for p in paths]
        head_fac = [1.0] * len(paths)
        tail_fac = [1.0] * len(paths)
        any_work = False
        for i in range(1, len(paths)):
            step = current[i - 1]
            if step is None:
                continue
            excess = step - target_step_hz
            if excess <= 4:
                continue
            tail_fac[i - 1] = min((tails[i - 1] + excess / 2) / tails[i - 1], 1.10)
            head_fac[i] = max((heads[i] - excess / 2) / heads[i], 0.90)
            any_work = True
        if not any_work:
            break
        # First take opens the video and last take closes it: leave the
        # opening attack and the final cadence as spoken.
        head_fac[0] = 1.0
        tail_fac[-1] = 1.0
        for i, p in enumerate(paths):
            if head_fac[i] != 1.0 or tail_fac[i] != 1.0:
                _pitch_glide(p, head_fac[i], tail_fac[i], edge_s)
        fixed += 1

    after = [s for s in steps_now() if s is not None]
    if fixed and after:
        print(f"[tts] seams eased in {fixed} pass(es): median step "
              f"{statistics.median(seams):+.0f} -> {statistics.median(after):+.0f} Hz "
              f"(worst {max(seams, key=abs):+.0f} -> {max(after, key=abs):+.0f})")


def _pitch_shift(path: Path, factor: float) -> bool:
    """Shift a clip's pitch by ``factor``, keeping its duration. In place.

    Duration is the constraint that makes this fiddly: beat lengths, word
    timings and the frame grid all derive from it, so a shifter that changes
    tempo would desync the video. rubberband shifts pitch alone; the
    asetrate+atempo pair is the fallback when it was not compiled in.
    """
    ff = _ffmpeg()
    if not ff:
        return False
    import subprocess
    import wave as _wave

    with _wave.open(str(path), "rb") as fh:
        sr = fh.getframerate()
        before = fh.getnframes()

    tmp = path.with_suffix(".shift.wav")
    chains = [
        f"rubberband=pitch={factor:.5f}",
        f"asetrate={int(sr * factor)},aresample={sr},atempo={1 / factor:.5f}",
    ]
    for chain in chains:
        try:
            subprocess.run(
                [ff, "-y", "-hide_banner", "-loglevel", "error",
                 "-i", str(path), "-filter:a", chain, str(tmp)],
                capture_output=True, check=True,
            )
        except Exception:  # noqa: BLE001
            continue
        # Pad or clip back to the exact original length: even a few
        # milliseconds of drift would move every later frame boundary.
        try:
            with _wave.open(str(tmp), "rb") as fh:
                params = fh.getparams()
                data = fh.readframes(fh.getnframes())
            width = params.sampwidth * params.nchannels
            want = before * width
            data = data[:want] + b"\x00" * max(0, want - len(data))
            with _wave.open(str(path), "wb") as fh:
                fh.setparams(params)
                fh.setnframes(before)
                fh.writeframes(data)
            tmp.unlink(missing_ok=True)
            return True
        except Exception:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
    return False


def _tail_sentence(text: str, max_words: int = 22) -> str:
    """The last complete sentence of a take, used to prime the next one."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    if not parts:
        return ""
    tail = parts[-1]
    words = tail.split()
    return " ".join(words[-max_words:]) if len(words) > max_words else tail


def _primer_end(path: Path, primer: str, full: str) -> float:
    """Where the primer stops and the real text begins, in seconds.

    Uses the same forced alignment the move cues rely on, so the cut lands in
    the pause between the two rather than inside a word. Returns 0.0 when the
    alignment cannot place it, which makes the caller fall back to a plain
    cold-start take — a slightly harsher seam beats a clipped first word.
    """
    import wave as _wave

    try:
        with _wave.open(str(path), "rb") as fh:
            duration_ms = int(fh.getnframes() / float(fh.getframerate()) * 1000)
        words = _align_words(path, full, duration_ms, {})
        n_primer = len([w for w in primer.split() if _norm_word(w)])
        if len(words) <= n_primer + 1:
            return 0.0
        prev_end = float(words[n_primer - 1]["e"])
        next_start = float(words[n_primer]["s"])
        if next_start <= prev_end:
            return 0.0
        return (prev_end + next_start) / 2.0
    except Exception:  # noqa: BLE001
        return 0.0


def _drop_head(path: Path, seconds: float) -> None:
    """Remove the first ``seconds`` of a clip, in place."""
    import wave as _wave

    with _wave.open(str(path), "rb") as fh:
        params = fh.getparams()
        sr = fh.getframerate()
        data = fh.readframes(fh.getnframes())
    width = params.sampwidth * params.nchannels
    offset = int(round(seconds * sr)) * width
    if offset <= 0 or offset >= len(data):
        return
    with _wave.open(str(path), "wb") as fh:
        fh.setparams(params)
        fh.writeframes(data[offset:])




def _normalize_pitch(
    paths: Sequence[Path], tolerance: float = 0.025, max_shift: float = 0.10
) -> None:
    """Pull every take toward the run's own median pitch.

    Each synthesis request establishes its own prosodic baseline, and across one
    game those baselines spread far enough to be heard as the narrator changing
    tone — 178 to 258 Hz measured on Fischer-Berliner, with eleven of thirty-five
    boundaries jumping more than 15 Hz. The target is the median of the takes
    themselves, so the voice stays self-consistent without a hand-tuned constant
    that would need revisiting per profile.

    Takes already within ``tolerance`` are left untouched, and no take is moved
    by more than ``max_shift``: past that the artefacts cost more than the
    inconsistency, and it usually means the take is unvoiced or mismeasured.
    """
    if os.getenv("TTS_PITCH_NORMALIZE", "1").strip().lower() in ("0", "false", "no"):
        return
    if len(paths) < 4:  # nothing meaningful to take a median of
        return
    try:
        import numpy as np  # type: ignore  # noqa: F401
    except ImportError:
        print("[tts] numpy missing — skipping pitch normalisation")
        return
    if not _ffmpeg():
        print("[tts] ffmpeg missing — skipping pitch normalisation")
        return

    measured = [(p, _median_f0(p)) for p in paths]
    voiced = [f for _, f in measured if f > 0]
    if len(voiced) < 4:
        return
    voiced.sort()
    target = voiced[len(voiced) // 2]

    shifted = 0
    clamped = 0
    for path, f0 in measured:
        if not f0:
            continue
        factor = target / f0
        if abs(factor - 1.0) <= tolerance:
            continue
        if abs(factor - 1.0) > max_shift:
            factor = 1.0 + max_shift * (1 if factor > 1 else -1)
            clamped += 1
        if _pitch_shift(path, factor):
            shifted += 1

    after = [f for f in (_median_f0(p) for p in paths) if f > 0]
    if after:
        print(f"[tts] pitch normalised to {target:.0f} Hz: {shifted}/{len(paths)} takes "
              f"adjusted{f' ({clamped} clamped)' if clamped else ''}; "
              f"spread {min(voiced):.0f}-{max(voiced):.0f} -> "
              f"{min(after):.0f}-{max(after):.0f} Hz")


def _trim_lead_silence(path: Path, keep_ms: int = 60, threshold_db: float = -45.0) -> int:
    """Strip dead air from the front of a clip, in place. Returns ms removed.

    Qwen voices open with 0.6-0.8s of silence. Word timings are measured
    against the whole file — by forced alignment and, more crudely, by
    :func:`_estimate_words` — so that silence drags every cue earlier than the
    word it names, and a piece starts moving before its square is spoken.
    Trimming at the source keeps the cue contract honest for both timing paths
    rather than teaching each one about the lead-in separately.
    """
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence

    seg = AudioSegment.from_wav(str(path))
    lead = detect_leading_silence(seg, silence_threshold=threshold_db, chunk_size=5)
    if lead >= len(seg):  # nothing but silence — leave it alone
        return 0
    trim = max(0, lead - keep_ms)
    if trim <= 0:
        return 0
    seg[trim:].export(str(path), format="wav")
    return trim


def _partition_para_words(
    para_words: List[Dict[str, Any]], beat_texts: Sequence[str]
) -> List[List[Dict[str, Any]]]:
    """Assign a paragraph's aligned words back to the beats that spoke them.

    The paragraph transcript is the beat texts joined with spaces, so the
    expected token stream is known exactly. Forced alignment may drop the odd
    word, so the walk is tolerant: each aligned word matches the next expected
    token it can find within a short lookahead, and inherits that token's beat.
    """
    expected: List[Tuple[int, str]] = []  # (beat index, normalized token)
    for bi, text in enumerate(beat_texts):
        for raw in text.split():
            tok = _norm_word(raw)
            if tok:
                expected.append((bi, tok))

    out: List[List[Dict[str, Any]]] = [[] for _ in beat_texts]
    ptr = 0
    for word in para_words:
        beat_idx = expected[min(ptr, len(expected) - 1)][0] if expected else 0
        for look in range(ptr, min(ptr + 4, len(expected))):
            if expected[look][1] == word["w"]:
                beat_idx = expected[look][0]
                ptr = look + 1
                break
        else:
            ptr = min(ptr + 1, len(expected))
        out[beat_idx].append(word)
    return out


def _split_para_wav(
    wav_path: Path,
    ids: Sequence[str],
    beat_words: List[List[Dict[str, Any]]],
    out_dir: Path,
    fps: int = 30,
) -> Dict[str, Dict[str, Any]]:
    """Slice one paragraph wav into per-beat clips at frame-snapped boundaries.

    The renderer plays one clip per beat back to back, so as long as every cut
    lands exactly on a video-frame boundary (800 samples at 24 kHz / 30 fps),
    the reassembled paragraph is sample-identical to the original take — the
    beats inherit continuous speech instead of each recording its own.
    """
    import wave

    with wave.open(str(wav_path), "rb") as fh:
        sr = fh.getframerate()
        params = fh.getparams()
        raw = fh.readframes(fh.getnframes())
    sw = params.sampwidth * params.nchannels
    total_s = len(raw) / sw / sr

    # A boundary sits midway through the pause between the last word of one
    # beat and the first word of the next, snapped to the frame grid.
    bounds = [0.0]
    for k in range(1, len(ids)):
        prev_words = beat_words[k - 1]
        next_words = beat_words[k]
        prev_end = prev_words[-1]["e"] if prev_words else bounds[-1]
        next_start = next_words[0]["s"] if next_words else prev_end
        mid = (prev_end + next_start) / 2.0
        # The renderer shows every beat for at least one frame, so a zero-length
        # slice would push all later audio out of sync. Keep cuts a frame apart.
        mid = max(mid, bounds[-1] + 1.0 / fps)
        bounds.append(min(round(mid * fps) / fps, total_s))
    bounds.append(total_s)

    clips: Dict[str, Dict[str, Any]] = {}
    last = len(ids) - 1
    for k, beat_id in enumerate(ids):
        t0, t1 = bounds[k], max(bounds[k], bounds[k + 1])
        s0, s1 = int(round(t0 * sr)) * sw, int(round(t1 * sr)) * sw
        piece = out_dir / f"{beat_id}.wav"
        with wave.open(str(piece), "wb") as fh:
            fh.setparams(params)
            fh.writeframes(raw[s0:s1])
        clips[beat_id] = {
            "file": piece.name,
            "durationMs": int(round((t1 - t0) * 1000)),
            "words": [
                {"w": w["w"], "s": round(max(0.0, w["s"] - t0), 3),
                 "e": round(max(0.0, w["e"] - t0), 3)}
                for w in beat_words[k]
            ],
            # Mid-paragraph clips must play gaplessly: no tail padding, no
            # minimum duration — the next beat's audio continues this breath.
            "chain": k != last,
        }
    return clips


def _ttsapi_synthesize(
    lines: Sequence[Dict[str, Any]], out_dir: Path, attempts: int = 3, fps: int = 30
) -> Dict[str, Dict[str, Any]]:
    """Narration via the local TTS service (D:\\ai\\projects\\tts-service).

    Same Qwen3-TTS voices as the ``qwen`` backend, but the model stays resident
    in the service across runs. ``TTS_VOICE`` picks the saved profile.

    Beats that share a ``para`` value are synthesized as ONE request — a single
    breath group with one intonation contour — and the returned take is sliced
    back into per-beat clips. Lines without ``para`` fall back to one request
    per line, which is how every beat used to sound: 123 separate recordings.
    """
    import urllib.error
    import urllib.request

    base = os.getenv("TTS_API_URL", "http://127.0.0.1:8010").rstrip("/")
    voice = os.getenv("TTS_VOICE", "").strip()
    if not voice:
        raise RuntimeError("TTS_VOICE must name a saved profile (GET /voices)")

    # Group contiguous lines by paragraph. None -> its own group.
    groups: List[List[Dict[str, Any]]] = []
    for item in lines:
        para = item.get("para")
        if groups and para is not None and groups[-1][0].get("para") == para:
            groups[-1].append(item)
        else:
            groups.append([item])

    # Every take opens ~26 Hz above its own median and closes ~25 Hz below it,
    # so each seam is a ~50 Hz step and the voice reads as two alternating
    # narrators. The cheapest half of the cure is simply to have fewer seams:
    # merge neighbouring runs up to a synthesis budget well above the writing
    # budget. Variations keep their own take — that separation is deliberate,
    # and the point is to soften the step, not to remove the boundary.
    def _branchy(g: List[Dict[str, Any]]) -> bool:
        return any(i.get("branch") for i in g)

    merged: List[List[Dict[str, Any]]] = []
    for g in groups:
        prev = merged[-1] if merged else None
        joinable = (
            prev is not None
            and not _branchy(prev)
            and not _branchy(g)
            and sum(len(i["text"].split()) for i in prev + g) <= SYNTH_WORD_BUDGET
        )
        if joinable:
            merged[-1] = prev + g
        else:
            merged.append(g)
    if len(merged) != len(groups):
        print(f"[tts] merged {len(groups)} breath groups into {len(merged)} takes")
    groups = merged

    def fetch(text: str, label: str) -> bytes:
        body = json.dumps({"text": text, "voice": voice, "format": "wav"}).encode()
        for attempt in range(1, attempts + 1):
            req = urllib.request.Request(
                f"{base}/tts", data=body,
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=900) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                # A bad request or an unknown profile fails identically every
                # time; only server-side faults are worth another go.
                if exc.code < 500 or attempt == attempts:
                    raise
                reason = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt == attempts:
                    raise
                reason = str(exc)
            print(f"[tts] {label} failed ({reason}); retrying {attempt}/{attempts - 1}")
            time.sleep(2 * attempt)
        raise RuntimeError("unreachable")

    clips: Dict[str, Dict[str, Any]] = {}
    cache: Dict[str, Any] = {}
    total = len(groups)
    trimmed_ms = 0

    # --- phase 1: fetch every take -------------------------------------
    # The model sets a fresh prosodic baseline per request, and some requests
    # land a long way from the voice's centre — measured at 178-258 Hz across
    # one game, which is heard as the narrator changing tone mid-video. Nothing
    # can be corrected until all the takes exist, because the target is their
    # own median: that keeps the voice self-consistent without a tuned constant.
    takes: List[Tuple[List[Dict[str, Any]], Path, str]] = []
    primed = 0
    for gi, group in enumerate(groups, start=1):
        text = " ".join(item["text"] for item in group)
        para_path = out_dir / f"{group[0]['id']}.wav"

        # Cold-starting a take is what makes it open high and loud. Giving the
        # model the sentence that precedes it means this text is continuing an
        # utterance rather than beginning one; the primer's audio is then cut
        # away using its own word timings. Measured on one seam: the opening
        # overshoot falls from +22 Hz to +13 Hz.
        primer = _tail_sentence(takes[-1][2]) if takes else ""
        cut_s = 0.0
        if primer:
            full = primer + " " + text
            para_path.write_bytes(fetch(full, f"take {gi}/{total}"))
            _trim_lead_silence(para_path)
            cut_s = _primer_end(para_path, primer, full)
        if not primer or cut_s <= 0:
            para_path.write_bytes(fetch(text, f"take {gi}/{total}"))
            trimmed_ms += _trim_lead_silence(para_path)
        else:
            _drop_head(para_path, cut_s)
            primed += 1

        takes.append((group, para_path, text))
        if gi % 5 == 0 or gi == total:
            print(f"[tts] ttsapi take {gi}/{total} ({voice})")
    if primed:
        print(f"[tts] {primed}/{total} takes primed with the preceding sentence")

    # --- phase 2: re-roll the takes no shift could rescue ----------------
    # A take far enough from the median needs a correction big enough to
    # artefact, so ask for a fresh sample instead: the baseline is re-drawn per
    # request, and a second roll usually lands nearer the voice's centre. Only
    # kept if it is actually closer. Bounded, because this costs a request each.
    if len(takes) >= 4 and _ffmpeg():
        try:
            measured = [(p, _median_f0(p)) for _, p, _ in takes]
            voiced = sorted(f for _, f in measured if f > 0)
            if len(voiced) >= 4:
                target = voiced[len(voiced) // 2]
                outliers = [
                    (i, f) for i, (_, f) in enumerate(measured)
                    if f and abs(target / f - 1.0) > 0.10
                ]
                for i, f0 in outliers[:4]:
                    group, para_path, text = takes[i]
                    fresh = out_dir / f"{para_path.stem}.reroll.wav"
                    fresh.write_bytes(fetch(text, f"re-roll {para_path.stem}"))
                    _trim_lead_silence(fresh)
                    new_f0 = _median_f0(fresh)
                    if new_f0 and abs(new_f0 - target) < abs(f0 - target):
                        fresh.replace(para_path)
                        print(f"[tts] re-rolled {para_path.stem}: "
                              f"{f0:.0f} -> {new_f0:.0f} Hz (target {target:.0f})")
                    else:
                        fresh.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            # Cosmetic pass: never let it cost the run.
            print(f"[tts] outlier re-roll skipped ({exc})")

    # --- phase 3: even out the remaining pitch and level ----------------
    # Pitch normalisation, then seam easing. Two *level* treatments were tried
    # here and dropped: matching whole-take loudness widened the step at the
    # seam rather than closing it (x1.59 -> x1.78), and tapering each take's
    # onset did no better (x2.56). Pitch is where the "two announcers" effect
    # actually lives, so pitch is what gets corrected.
    _normalize_pitch([p for _, p, _ in takes])
    _flatten_seams([p for _, p, _ in takes])

    # --- phase 4: align and slice ---------------------------------------
    import wave
    for group, para_path, text in takes:
        with wave.open(str(para_path), "rb") as fh:
            duration_ms = int(fh.getnframes() / float(fh.getframerate()) * 1000)
        words = _align_words(para_path, text, duration_ms, cache)

        if len(group) == 1:
            clips[group[0]["id"]] = {
                "file": para_path.name,
                "durationMs": duration_ms,
                "words": words,
                "aligned": bool(cache.get("aligned")),
            }
        else:
            ids = [item["id"] for item in group]
            texts = [item["text"] for item in group]
            per_beat = _partition_para_words(words, texts)
            aligned = bool(cache.get("aligned"))
            # The first slice overwrites the paragraph file (same name) — write
            # slices only after the full take has been read into memory above.
            sliced = _split_para_wav(para_path, ids, per_beat, out_dir, fps=fps)
            for c in sliced.values():
                c["aligned"] = aligned
            clips.update(sliced)
    if trimmed_ms:
        print(f"[tts] trimmed {trimmed_ms / 1000:.1f}s of lead-in silence "
              f"across {total} takes")
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
        if os.getenv("TTS_VOICE", "").strip():
            resolved = "ttsapi"
        elif os.getenv("VOICE_REF_AUDIO", "").strip():
            resolved = "qwen"
        elif api_key and voice_id:
            resolved = "elevenlabs"
        else:
            resolved = "local"

    if resolved == "elevenlabs" and not (api_key and voice_id):
        print("[tts] ELEVENLABS_API_KEY/VOICE_ID missing — falling back to local TTS")
        resolved = "local"

    if resolved in ("qwen", "ttsapi"):
        try:
            clips = (_ttsapi_synthesize(lines, out_dir) if resolved == "ttsapi"
                     else _qwen_synthesize(lines, out_dir))
            ext = "wav"
            # Which profile spoke it, so a render can be traced back to a voice.
            manifest = {"backend": resolved, "ext": ext,
                        "voice": os.getenv("TTS_VOICE", "").strip() or None,
                        "clips": clips}
            (out_dir.parent / "audio_manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
            return manifest
        except Exception as exc:  # noqa: BLE001
            # A daily unattended run must still produce a video.
            print(f"[tts] {resolved} backend failed ({exc}); falling back to local TTS")
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
