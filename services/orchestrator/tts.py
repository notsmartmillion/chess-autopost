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
#
# Every take boundary is a chance for the voice to shift, so the seam count is
# the thing to minimise — and it rises with script length. Pushing videos
# toward eight minutes took one script from 1157 words to 1735, which at 170
# meant 13 takes and 12 seams, and four of those seams failed the audit. The
# service was measured handling 455 words in a single request at normal pace
# before this was raised, so 320 leaves real headroom.
SYNTH_WORD_BUDGET = 320

# Spoken in front of the video's first take and cut away, exactly like the
# primers between takes: the model warms into its register before the words
# that will actually be kept. The content is irrelevant; the pace is not.
WARMUP_PRIMER = "Settle in, and let us take our time with this one."

# The channel's register is calm and deliberate, so takes that sprint past the
# video's own median pace get a bounded slow-down back toward it. Relative, not
# absolute: raw words-per-voiced-second depends on the voice and the measure,
# and an absolute number ended up governing the slow takes too. More than ~8%
# of stretch starts to smear articulation, so past the cap a take stays brisk.
FAST_OVER_MEDIAN = 1.06
MAX_TEMPO_STRETCH = 0.08


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


def _level_db(path: Path, start_s: float = 0.0, dur_s: Optional[float] = None) -> Optional[float]:
    """How loud the speech in a segment is, in dBFS.

    90th percentile of 20 ms frame RMS: robust to the pauses that dominate a
    mean and to the single consonant bursts that dominate a peak. ``start_s``
    may be negative to measure from the end, matching ``_median_f0``.
    """
    import array as _array
    import math as _math
    import wave as _wave

    with _wave.open(str(path), "rb") as fh:
        sr = fh.getframerate()
        n = fh.getnframes()
        pcm = _array.array("h")
        pcm.frombytes(fh.readframes(n))
    if start_s < 0:
        start_s = max(0.0, n / sr + start_s)
    s = int(start_s * sr)
    e = n if dur_s is None else min(n, s + int(dur_s * sr))
    step = int(0.02 * sr)
    frames = []
    for i in range(s, e - step, step):
        seg = pcm[i:i + step]
        frames.append(sum(v * v for v in seg) / len(seg))
    if not frames:
        return None
    frames.sort()
    v = frames[int(len(frames) * 0.9)]
    return 10 * _math.log10(max(v, 1.0) / (32768.0 ** 2))


def _trim_loud_takes(paths: Sequence[Path], over_db: float = 2.5, cap_db: float = 4.0) -> None:
    """Bring a take that is loud or quiet THROUGHOUT toward the video's level.

    The seam easing is bounded by each take's own body, deliberately — so a
    take whose whole body sits 6 dB above its neighbours sails through it,
    and re-rolling does not help when the next sample is just as loud (b0033:
    both rolls hot, score 0.84). Whole-take loudness *matching* was tried
    long ago and widened seams, because it moved every take, quiet ones up.
    This is narrower: downward only, outliers only, and only the excess above
    the tolerance, capped. A uniform gain has no envelope to pump and no
    resynthesis to smear; the seam passes run after and clean the residue.
    """
    if os.getenv("TTS_LEVEL_TRIM", "1").strip().lower() in ("0", "false", "no"):
        return
    if len(paths) < 4:
        return
    import array as _array
    import wave as _wave

    bodies = [(p, _level_db(p)) for p in paths]
    levels = sorted(l for _, l in bodies if l is not None)
    if len(levels) < 4:
        return
    med = levels[len(levels) // 2]
    trimmed = []
    for p, body in bodies:
        if body is None or abs(body - med) <= over_db:
            continue
        # Signed: positive cuts a loud take, negative lifts a quiet one. A take
        # sitting 6 dB under the video cannot be rescued at its seam alone —
        # the seam correction is bounded by the take's own body, so the body is
        # what has to move.
        sign = 1.0 if body > med else -1.0
        cut = sign * min(abs(body - med) - over_db, cap_db)
        with _wave.open(str(p), "rb") as fh:
            params = fh.getparams()
            pcm = _array.array("h")
            pcm.frombytes(fh.readframes(fh.getnframes()))
        g = 10 ** (-cut / 20)
        for i in range(len(pcm)):
            pcm[i] = max(-32768, min(32767, int(round(pcm[i] * g))))
        with _wave.open(str(p), "wb") as fh:
            fh.setparams(params)
            fh.writeframes(pcm.tobytes())
        trimmed.append((p.stem, body - med, cut))
    for stem, over, cut in trimmed:
        print(f"[tts] levelled {stem}: body {over:+.1f} dB against the video, "
              f"{-cut:+.1f} dB")


def _ease_seam_levels(
    paths: Sequence[Path],
    trigger_db: float = 3.0,
    allow_db: float = 2.0,
    cap_db: float = 6.0,
    span_s: float = 12.0,
) -> None:
    """Match a take's opening level to the voice it follows, either way.

    The b0010 lesson: a take can open several dB louder and a third faster
    than the voice around it while its pitch stays perfectly normal, and a
    level jump at a splice reads as a new announcer just as surely as a pitch
    jump does. Whole-take loudness matching was tried long ago and made seams
    worse, and a "hot window anywhere" detector false-positives on ordinary
    emphasis in most takes — so this is strictly seam-local: only a take's
    opening, only relative to the take it follows.

    Both directions, which the first version got wrong. It only attenuated hot
    openings, so a take that opened 9.5 dB *quieter* than the previous take's
    close sailed through untouched and the voice appeared to recede mid-video.
    A drop is as audible as a jump, and on headphones rather more so.

    Correction is pure gain — multiplication, no re-synthesis, none of the
    phase-vocoder risk that made earlier DSP the artifact. It follows the
    discrepancy for as long as it persists (b0010 stayed hot for ten seconds)
    and releases once the take settles toward its own body level, which also
    bounds it: the opening is never pushed past how the take itself speaks
    once calm, in either direction.
    """
    if os.getenv("TTS_SEAM_LEVEL", "1").strip().lower() in ("0", "false", "no"):
        return
    if len(paths) < 2:
        return
    import array as _array
    import wave as _wave

    eased = []
    for i in range(1, len(paths)):
        tail = _level_db(paths[i - 1], -1.5)
        head = _level_db(paths[i], 0.0, 1.5)
        body = _level_db(paths[i])
        if tail is None or head is None or body is None:
            continue
        if abs(head - tail) <= trigger_db:
            continue
        lifting = head < tail
        if lifting:
            # Bring a receding opening up toward the previous close, but never
            # past this take's own body: the take is simply quieter, and
            # dragging its start above its own voice would be a new artifact.
            target = min(tail - allow_db, body + 0.5)
            if target <= head:
                continue
        else:
            # Aim just above the previous take's close; never meaningfully
            # below how this take itself speaks once settled.
            target = max(tail + allow_db, body - 0.5)

        with _wave.open(str(paths[i]), "rb") as fh:
            sr = fh.getframerate()
            params = fh.getparams()
            pcm = _array.array("h")
            pcm.frombytes(fh.readframes(fh.getnframes()))

        hop = 0.25
        # Leave the closing seconds alone: they are the tail the next seam is
        # measured against. Takes are usually far longer than the span so this
        # rarely binds, but it costs nothing and a short take would otherwise
        # have its correction read back as the next seam's starting point.
        span = min(span_s, max(0.0, len(pcm) / sr - 4.0))
        if span < 1.0:
            continue
        att: List[float] = []
        calm = 0
        prev = 0.0
        t = 0.0
        while t < span:
            lv = _level_db(paths[i], t, 0.5)
            if lv is None or lv < target - 8:
                # A pause carries no level information; holding the previous
                # attenuation avoids pumping the gain across every gap — and a
                # pause is NOT evidence the voice has settled, which is the
                # mistake that made the first version stop tracking two
                # seconds into a ten-second-hot opening.
                att.append(prev)
            else:
                # Signed: positive attenuates, negative lifts — but each
                # seam only ever moves one way. Allowing both directions in a
                # single pass let the quiet moments inside a hot opening be
                # boosted, which widened the very seam being corrected
                # (+5.5 -> +7.9 dB).
                delta = lv - target
                excess = (min(max(delta, 0.0), cap_db) if not lifting
                          else max(min(delta, 0.0), -cap_db))
                att.append(excess)
                prev = excess
                calm = calm + 1 if abs(excess) < 1.0 else 0
                if calm >= 6:  # a sustained calm stretch of speech: done
                    break
            t += hop
        while att and abs(att[-1]) < 0.5:
            att.pop()
        if not att or max(abs(a) for a in att) < 1.0:
            continue

        # Per-sample envelope: linear between hops, then an 0.8 s release.
        release = int(0.8 * sr)
        env_len = int(len(att) * hop * sr)
        for j in range(min(len(pcm), env_len + release)):
            t_j = j / sr
            if j < env_len:
                pos = t_j / hop
                k = min(int(pos), len(att) - 1)
                frac = min(pos - k, 1.0)
                a = att[k] + (att[min(k + 1, len(att) - 1)] - att[k]) * frac
            else:
                a = att[-1] * (1.0 - (j - env_len) / release)
            if a != 0:
                # Clamped rather than wrapped: a lift near an existing peak
                # would otherwise fold over into a click.
                v = int(round(pcm[j] * (10 ** (-a / 20))))
                pcm[j] = max(-32768, min(32767, v))

        with _wave.open(str(paths[i]), "wb") as fh:
            fh.setparams(params)
            fh.writeframes(pcm.tobytes())
        after = _level_db(paths[i], 0.0, 1.5)
        eased.append((head - tail, (after - tail) if after is not None else 0.0))

    if eased:
        worst = max(eased, key=lambda x: x[0])
        print(f"[tts] level seams: {len(eased)} eased; "
              f"worst {worst[0]:+.1f} -> {worst[1]:+.1f} dB")


# What the voice should SAY for words it reads wrong. Applied only to the
# string sent to the synthesis service — the written text is what alignment,
# captions, cues and the screen all use, and the respellings are phonetically
# close enough that forced alignment against the written form stays grounded.
#
# Two kinds of entry. Chess terms the model anglicises ("en passant" came out
# "en passing"), and player names it reads a different way every take —
# "Gelfand" alternated between a hard and soft G within one video, which a
# viewer hears as the narrator not knowing who is on the board. A respelling
# pins one reading. Names only go in this table with a pronunciation worth
# pinning; a name absent here is simply read as written.
SPOKEN_FORMS: Dict[str, str] = {
    "en passant": "on passont",
    "fianchetto": "fyanketto",
    "fianchettoed": "fyankettoed",
    "zugzwang": "tsoogzvung",
    "zwischenzug": "tsvishenzoog",
    "Ruy Lopez": "Rooey Lopez",
    # Names. Keyed case-sensitively so ordinary words never match.
    "Gelfand": "Ghelfand",       # hard G
    "Anand": "Ahnand",           # AH-nand, never AY-nand
    "Uhlmann": "Oolmun",
    "Didier": "Deedyay",
    "Geller": "Gheller",         # hard G
    "Najdorf": "Nydorf",
    "Euwe": "Ervuh",
    "Keres": "Kerress",
    "Petrosian": "Petrosyan",
    "Smyslov": "Smislov",
}
_SPOKEN_RE = re.compile(
    "|".join(
        rf"(?<![\w']){re.escape(k)}(?![\w])"
        for k in sorted(SPOKEN_FORMS, key=len, reverse=True)
    )
)
_SPOKEN_CI = {k.lower(): v for k, v in SPOKEN_FORMS.items() if not k[0].isupper()}


def _spoken_form(text: str) -> str:
    """The text as the voice should read it. Terms match case-insensitively;
    names match exactly, so 'geller' in prose could never be a surname."""
    def sub(m: "re.Match[str]") -> str:
        word = m.group(0)
        exact = SPOKEN_FORMS.get(word)
        if exact is not None:
            return exact
        lowered = _SPOKEN_CI.get(word.lower())
        return lowered if lowered is not None else word

    # Case-insensitive scan, case-sensitive decision: build one pass that
    # sees "En passant" as well as "en passant".
    pattern = re.compile(_SPOKEN_RE.pattern, re.IGNORECASE)
    return pattern.sub(sub, text)


# --- the shared definition of an off-voice beat ---------------------------
# Used twice: by the pre-render check below, and by the post-render audit.
# One set of numbers on purpose — the Kramnik-Aronian render passed every
# seam check here, spent twenty-five minutes rendering, and was then held by
# the audit's cluster rule, because the two stages were measuring different
# things. Whatever would fail the audit must fail before the render.
BEAT_NEIGHBOURHOOD_MS = 30_000
BEAT_HOT_DB = 3.5
BEAT_FAST_RATIO = 1.30
BEAT_FAST_MIN_WORDS = 15
BEAT_SHARP_RATIO = 0.12
BEAT_CLUSTER_N = 3
# Beats shorter than this are not judged at all. An eight-word clip holds
# two-ish seconds of voiced audio, which is too little to estimate pitch or
# level against a neighbourhood — three consecutive voice draws of
# Korchnoi-Carlsen each "found" a cluster in a different place, every flagged
# beat a short move announcement, while the clusters a listener actually
# heard were twenty-second hold beats. Below the floor the measurement is
# noise, and a gate fed noise blocks at random.
BEAT_MIN_MS = 4_000


def find_offvoice_beats(rows: Sequence[Tuple[str, int, float, Optional[float], float, int]]):
    """Judge each beat against its 30-second neighbourhood.

    ``rows`` is (id, at_ms, f0, level_db, wpm, words) per substantial beat.
    Returns (different_read, outliers, cluster):

    * different_read — beats both hot AND fast against their surroundings,
      each an audit error on its own;
    * outliers — beats off in one dimension (warnings individually);
    * cluster — the first run of BEAT_CLUSTER_N outliers inside one
      neighbourhood, which the audit blocks on, or None.
    """
    different_read: List[Tuple[str, float, float]] = []
    outliers: List[Tuple[str, int, str]] = []
    for bid, at, f0, lv, wpm, words in rows:
        near = [r for r in rows
                if abs(r[1] - at) <= BEAT_NEIGHBOURHOOD_MS and r[0] != bid]
        if len(near) < 3:
            continue
        med_lv = sorted(r[3] for r in near)[len(near) // 2]
        med_wpm = sorted(r[4] for r in near)[len(near) // 2]
        med_f0 = sorted(r[2] for r in near)[len(near) // 2]
        hot = lv is not None and med_lv is not None and lv - med_lv > BEAT_HOT_DB
        fast = (words >= BEAT_FAST_MIN_WORDS and med_wpm
                and wpm / med_wpm > BEAT_FAST_RATIO)
        sharp = f0 and med_f0 and abs(f0 / med_f0 - 1.0) > BEAT_SHARP_RATIO
        if hot and fast:
            different_read.append((bid, lv - med_lv, wpm / med_wpm))
        elif hot or fast or sharp:
            what = "louder" if hot else ("faster" if fast else "sharper")
            outliers.append((bid, at, what))
    outliers.sort(key=lambda o: o[1])
    cluster: Optional[List[str]] = None
    for k in range(len(outliers) - (BEAT_CLUSTER_N - 1)):
        if (outliers[k + BEAT_CLUSTER_N - 1][1] - outliers[k][1]
                <= BEAT_NEIGHBOURHOOD_MS):
            cluster = [o[0] for o in outliers[k:k + BEAT_CLUSTER_N]]
            break
    return different_read, outliers, cluster


def _fetch_primed(fetch, text: str, primer: str, dest: Path, label: str) -> None:
    """Synthesize ``text`` as a continuation of ``primer``, primer cut away.

    The one way this pipeline knows to make a take that does not cold-start.
    Phase 1 inlines the same steps; re-rolls and rescues must go through here,
    because a bare ``fetch(text)`` produces exactly the hot opening they are
    trying to replace.
    """
    if primer:
        full = primer + " " + text
        dest.write_bytes(fetch(full, label))
        _trim_lead_silence(dest)
        cut = _primer_end(dest, primer, full)
        if cut > 0:
            _drop_head(dest, cut)
            return
    dest.write_bytes(fetch(text, label))
    _trim_lead_silence(dest)


def _audible_seam(prev: Path, cur: Path) -> Optional[Tuple[float, float]]:
    """Measure one seam exactly the way the render audit will.

    Same edge windows, same widening on unvoiced onsets, same thresholds as
    verify_render.py — one definition of "will be heard as a new announcer",
    shared by the pass that must fix it and the audit that must catch it.
    Returns (dHz, dDb) when the seam fails, None when it passes.
    """
    def edge(path: Path, head: bool) -> Optional[float]:
        for dur in (1.5, 2.5, 4.0):
            v = _median_f0(path, 0.0 if head else -dur, dur if head else None)
            if v:
                return v
        return None

    p_tail, p_head = edge(prev, False), edge(cur, True)
    l_tail, l_head = _level_db(prev, -1.5), _level_db(cur, 0.0, 1.5)
    dp = (p_head - p_tail) if p_tail and p_head else 0.0
    dl = (l_head - l_tail) if l_tail is not None and l_head is not None else 0.0
    if abs(dp) > 60 or abs(dl) > 5 or (abs(dp) > 40 and abs(dl) > 3):
        return dp, dl
    return None


def _rescue_stubborn_seams(
    takes: Sequence[Tuple[Any, Path, str]], fetch, max_rolls: int = 3
) -> None:
    """Last line of defence: re-synthesize a take still opening an audible seam.

    Every easing pass above is bounded — deliberately, because a large DSP
    correction is itself audible — so a take synthesized far enough from its
    neighbour arrives here untouched. 6:34 of Fischer–Uhlmann was +5 dB after
    an easing pass that, by its own rules, had nothing it was allowed to do;
    the audit failed the render and the pipeline uploaded it anyway. Gain can
    only hide a mismatch that size. A different sample can remove it.

    So: measure every seam with the audit's own arithmetic, and where one
    still fails, ask the model for a fresh take — primed, on a different seed
    — keeping whichever file leaves the smaller seam. Bounded at a few
    requests, and whatever remains is printed in the audit's terms, so the log
    explains the held upload rather than the other way round.
    """
    if len(takes) < 2 or not _ffmpeg():
        return
    paths = [p for _, p, _ in takes]
    bodies = [_level_db(p) for p in paths]
    pitches = [_median_f0(p) for p in paths]
    lv = sorted(b for b in bodies if b is not None)
    f0 = sorted(f for f in pitches if f)
    if not lv or not f0:
        return
    med_l, med_f = lv[len(lv) // 2], f0[len(f0) // 2]

    def oddness(j: int) -> float:
        """How far take j sits from the video's own centre."""
        d = 0.0
        if bodies[j] is not None:
            d += abs(bodies[j] - med_l) / 5.0
        if pitches[j]:
            d += abs(pitches[j] - med_f) / 60.0
        return d

    def badness(j: int) -> float:
        """Summed audit-excess of the seams take j participates in.

        Both of them — a fresh sample that closes the left seam by opening
        the right one has fixed nothing.
        """
        total = 0.0
        for a, b in ((j - 1, j), (j, j + 1)):
            if a < 0 or b >= len(paths):
                continue
            seam = _audible_seam(paths[a], paths[b])
            if seam:
                dp, dl = seam
                total += max(0.0, abs(dp) - 40) / 60 + max(0.0, abs(dl) - 3) / 5
        return total

    base_seed = os.getenv("TTS_SEED", "42").strip()
    rolls = 0
    rescued = False
    attempts: Dict[int, int] = {}
    for i in range(1, len(takes)):
        # A while, not an if: a failed attempt leaves this seam audible, and
        # the next attempt must go to the same seam on a different seed — the
        # first version moved on after one roll, so its "second attempt"
        # existed only for a take that happened to break two seams at once.
        while rolls < max_rolls and _audible_seam(paths[i - 1], paths[i]):
            # Re-roll whichever side is the stranger against the whole video:
            # the seam only proves the two disagree, not which one is wrong.
            j = i if oddness(i) >= oddness(i - 1) else i - 1
            if attempts.get(j, 0) >= 2:
                # Two fresh samples both worse is a signal, not bad luck; a
                # third spends a request on a take the model keeps reading
                # one way.
                break
            attempts[j] = attempts.get(j, 0) + 1
            _, path, text = takes[j]
            primer = _tail_sentence(takes[j - 1][2]) if j else WARMUP_PRIMER
            fresh = path.with_suffix(".rescue.wav")
            if base_seed not in ("", "-1"):
                # A different seed per attempt — repeating one would reproduce
                # the rejected sample byte for byte.
                os.environ["TTS_SEED_OVERRIDE"] = str(
                    int(base_seed) + 101 + j + 500 * (attempts[j] - 1))
            try:
                _fetch_primed(fetch, text, primer, fresh,
                              f"seam rescue {path.stem}")
            except Exception as exc:  # noqa: BLE001
                print(f"[tts] seam rescue of {path.stem} failed ({exc})")
                break
            finally:
                os.environ.pop("TTS_SEED_OVERRIDE", None)
            rolls += 1
            before = badness(j)
            kept = path.with_suffix(".kept.wav")
            path.replace(kept)
            fresh.replace(path)
            after = badness(j)
            if after < before:
                kept.unlink()
                rescued = True
                print(f"[tts] rescued {path.stem}: seam badness "
                      f"{before:.2f} -> {after:.2f}")
            else:
                path.unlink()
                kept.replace(path)
                print(f"[tts] rescue of {path.stem} no better; "
                      f"keeping the original")
        if rolls >= max_rolls:
            break

    if rescued:
        # A fresh take bypassed the easing passes; give its seams the same
        # finishing every other take got. Both passes re-measure before they
        # touch anything, so the already-eased majority is left alone.
        _flatten_seams(paths)
        _ease_seam_levels(paths)

    remaining = []
    for i in range(1, len(paths)):
        seam = _audible_seam(paths[i - 1], paths[i])
        if seam:
            dp, dl = seam
            remaining.append({"take": paths[i].stem, "dHz": round(dp),
                              "dDb": round(dl, 1)})
            print(f"[tts] seam into {paths[i].stem} still audible "
                  f"({dp:+.0f} Hz, {dl:+.1f} dB) — the audit will fail it")
    # Written even when empty: the file is how the build step learns the
    # voice's fate before spending twenty-five minutes rendering it, and a
    # stale verdict from the previous game would be worse than none.
    (paths[0].parent / "unresolved_seams.json").write_text(
        json.dumps(remaining), encoding="utf-8")


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

    "Leaving the middle untouched" has to be enforced by only *feeding it* the
    edges. The first version drove one rubberband instance across the whole
    file with asendcmd and set the factor to 1.0 in the middle, on the
    assumption that unity means bypass. It does when it is constant — a whole
    file at pitch=1.0 comes back sample-identical — but once the stretcher has
    been engaged it keeps re-synthesizing, and the nominally untouched middle
    came back correlating 0.56 with the original. A phase vocoder rebuilding
    five of seven takes while the other two stayed raw is audible twice over:
    as a soft, smeared quality on the processed takes, and as a change of
    timbre at the joins between processed and unprocessed ones.

    So each edge is cut out, processed alone, and crossfaded back over the
    original body. Duration is sacred — beat lengths, word timings and the
    frame grid all hang off it — so every segment is padded or clipped back to
    the exact sample count it started with.
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

    import array as _array

    with _wave.open(str(path), "rb") as fh:
        params = fh.getparams()
        samples = _array.array("h")
        samples.frombytes(fh.readframes(before))
    if params.nchannels != 1 or params.sampwidth != 2:
        return False

    n_edge = int(edge_s * sr)
    xf = int(0.020 * sr)  # crossfade back onto the body
    # Hold the full correction across the join itself, then ease it away. An
    # immediate taper is what made the first attempt too weak: by the time the
    # listener's ear settles on the new take, most of the correction had
    # already been given back.
    plateau = min(0.5, edge_s / 3)
    ramp = edge_s - plateau
    steps = 8

    def _ramp(factor: float, head: bool) -> List[str]:
        out = []
        for i in range(steps + 1):
            if head:
                t = plateau + ramp * i / steps
                w = (1 + math.cos(math.pi * i / steps)) / 2
            else:
                t = ramp * i / steps
                w = (1 - math.cos(math.pi * i / steps)) / 2
            out.append(f"{t:.3f} rubberband pitch {1.0 + (factor - 1.0) * w:.5f};")
        return out

    def _process(seg: "_array.array", factor: float, head: bool) -> Optional["_array.array"]:
        """Run one edge through rubberband, back at exactly its own length."""
        want = len(seg)
        cmds = path.with_suffix(".cmds")
        src = path.with_suffix(".edge.wav")
        dst = path.with_suffix(".edgeout.wav")
        start = factor if head else 1.0
        cmds.write_text(
            "\n".join([f"0.000 rubberband pitch {start:.5f};"] + _ramp(factor, head)) + "\n",
            encoding="ascii",
        )
        try:
            with _wave.open(str(src), "wb") as fh:
                fh.setparams(params)
                fh.setnframes(want)
                fh.writeframes(seg.tobytes())
            # cwd trick: sendcmd's f= argument chokes on Windows drive colons.
            subprocess.run(
                [ff, "-y", "-hide_banner", "-loglevel", "error",
                 "-i", src.name,
                 "-af", f"asendcmd=f={cmds.name},rubberband=pitch={start:.5f}",
                 dst.name],
                cwd=str(path.parent), capture_output=True, check=True,
            )
            with _wave.open(str(dst), "rb") as fh:
                out = _array.array("h")
                out.frombytes(fh.readframes(fh.getnframes()))
            del out[want:]
            out.extend([0] * (want - len(out)))
            return out
        except Exception:  # noqa: BLE001
            return None
        finally:
            for f in (cmds, src, dst):
                f.unlink(missing_ok=True)

    def _blend(dst_off: int, edge: "_array.array", fade_at_end: bool) -> None:
        """Write an edge back, crossfading the join so no step survives it."""
        for i in range(len(edge)):
            if fade_at_end and i >= len(edge) - xf:
                w = (len(edge) - i) / xf
            elif not fade_at_end and i < xf:
                w = i / xf
            else:
                w = 1.0
            j = dst_off + i
            samples[j] = int(round(edge[i] * w + samples[j] * (1.0 - w)))

    touched = False
    if abs(head_factor - 1.0) >= 0.01 and n_edge + xf <= before:
        edge = _process(samples[0:n_edge + xf], head_factor, True)
        if edge is None:
            return False
        _blend(0, edge, fade_at_end=True)
        touched = True
    if abs(tail_factor - 1.0) >= 0.01 and n_edge + xf <= before:
        off = before - (n_edge + xf)
        edge = _process(samples[off:before], tail_factor, False)
        if edge is None:
            return False
        _blend(off, edge, fade_at_end=False)
        touched = True
    if not touched:
        return False

    with _wave.open(str(path), "wb") as fh:
        fh.setparams(params)
        fh.setnframes(before)
        fh.writeframes(samples.tobytes())
    return True


def _flatten_seams(
    paths: Sequence[Path], target_step_hz: float = 15.0, edge_s: float = 1.2
) -> None:
    """Ease the pitch step where one take hands over to the next.

    With sampling seeded, what remains at a boundary is the utterance arc: a
    take still closes low and the next still attacks high, deterministically.
    This softens that hand-off under three invariants learned the hard way:

    * SINGLE PASS — the old convergence loop compounded its per-pass caps.
    * BOUNDED BY THE BODY — a tail may rise at most to its take's own median
      and a head may fall at most to its own; deviation is removed, never
      inverted, so an opening can never be pushed below the voice's body,
      which is what listeners caught within a minute.
    * EMPHASIS GUARD — an edge more than ~25% from its own body is expressive
      delivery or a bad measurement, not a cold start; those seams are left
      exactly as spoken.
    """
    if os.getenv("TTS_SEAM_FLATTEN", "1").strip().lower() in ("0", "false", "no"):
        return
    if len(paths) < 2 or not _ffmpeg():
        return

    meas = 0.9
    med = [_median_f0(p) for p in paths]
    tails = [_median_f0(p, -meas) for p in paths]
    heads = [_median_f0(p, 0.0, meas) for p in paths]

    head_fac = [1.0] * len(paths)
    tail_fac = [1.0] * len(paths)
    eased = 0
    steps_before: List[float] = []
    for i in range(1, len(paths)):
        t_, h_, mt, mh = tails[i - 1], heads[i], med[i - 1], med[i]
        if not (t_ and h_ and mt and mh):
            continue
        steps_before.append(h_ - t_)
        # An edge far outside its take's body is expressive delivery or a bad
        # measurement — but skipping such seams entirely left the video's worst
        # seam (+90 Hz) exactly as spoken, and that was the one listeners
        # caught. Clamp the measurement to the plausible band instead: the
        # correction acts on the believable part of the step and the factor
        # caps below still bound how far anything can be pushed.
        t_ = min(max(t_, 0.78 * mt), 1.28 * mt)
        h_ = min(max(h_, 0.78 * mh), 1.28 * mh)
        excess = (h_ - t_) - target_step_hz
        if excess <= 5:
            continue
        tail_target = min(t_ + excess / 2, mt)
        head_target = max(h_ - excess / 2, mh)
        tail_fac[i - 1] = min(tail_target / t_, 1.06)
        head_fac[i] = max(head_target / h_, 0.94)
        eased += 1
    # The video opens fresh and ends final; leave both untouched.
    head_fac[0] = 1.0
    tail_fac[-1] = 1.0

    for i, p in enumerate(paths):
        if head_fac[i] != 1.0 or tail_fac[i] != 1.0:
            _pitch_glide(p, head_fac[i], tail_fac[i], edge_s)

    if steps_before:
        import statistics

        after = [
            (_median_f0(paths[i], 0.0, meas) - _median_f0(paths[i - 1], -meas))
            for i in range(1, len(paths))
            if tails[i - 1] and heads[i]
        ]
        print(f"[tts] seams: {eased} eased; "
              f"median {statistics.median(steps_before):+.0f} -> "
              f"{statistics.median(after):+.0f} Hz, "
              f"worst {max(steps_before, key=abs):+.0f} -> {max(after, key=abs):+.0f}")


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




def _centroid(path: Path) -> float:
    """Median spectral centroid over voiced frames — a timbre proxy in Hz."""
    import wave as _wave

    import numpy as np  # type: ignore

    with _wave.open(str(path), "rb") as fh:
        sr = fh.getframerate()
        ch = fh.getnchannels()
        pcm = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    sig = pcm.astype(np.float64)
    out = []
    n = 1024
    win = np.hanning(n)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    for i in range(0, len(sig) - n, n):
        frame = sig[i : i + n]
        if np.sqrt((frame ** 2).mean()) < 300:
            continue
        spec = np.abs(np.fft.rfft(frame * win))
        if spec.sum() > 0:
            out.append(float((spec * freqs).sum() / spec.sum()))
    return float(np.median(out)) if out else 0.0


def _voiced_seconds(path: Path) -> float:
    """Seconds of actual speech in a clip, by energy gating."""
    import wave as _wave

    import numpy as np  # type: ignore

    with _wave.open(str(path), "rb") as fh:
        sr = fh.getframerate()
        pcm = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16).astype(np.float64)
    n = int(sr * 0.04)
    voiced = sum(
        1 for i in range(0, max(0, len(pcm) - n), n)
        if np.sqrt((pcm[i : i + n] ** 2).mean()) > 300
    )
    return voiced * n / sr


def _slow_fast_takes(takes: Sequence[Tuple[Any, Path, str]]) -> None:
    """Hold the channel's calm register when the text invites a sprint.

    The model paces itself from the writing, and a run of quick moves gets a
    quick read — measured up to 218 wpm against a video median near 187. The
    prompt now writes those runs with breathing room, and this is the safety
    net behind it: takes over MAX_WPM are time-stretched toward TARGET_WPM,
    capped where stretching starts to smear articulation. Runs before
    alignment, so every word timing downstream describes the slowed audio.
    """
    if os.getenv("TTS_RATE_GOVERNOR", "1").strip().lower() in ("0", "false", "no"):
        return
    ff = _ffmpeg()
    if not ff:
        return
    import subprocess

    rates = []
    for _, path, text in takes:
        words = len(text.split())
        speech = _voiced_seconds(path)
        rates.append(words / speech * 60 if words and speech >= 3 else 0.0)
    valid = sorted(r for r in rates if r)
    if len(valid) < 4:
        return
    median = valid[len(valid) // 2]

    slowed = 0
    for (_, path, text), wpm in zip(takes, rates):
        if not wpm or wpm <= median * FAST_OVER_MEDIAN:
            continue
        stretch = min(wpm / median, 1.0 + MAX_TEMPO_STRETCH)
        tmp = path.with_suffix(".slow.wav")
        try:
            # atempo, not rubberband. The phase vocoder smears a solo voice
            # into an audible double of itself — "the announcer overlaid on
            # another of the same voice" was heard at 7:30 of a published
            # video, in the one take the governor had stretched. atempo is
            # time-domain overlap-add: at the few percent this pass applies,
            # it slows speech without the chorus.
            subprocess.run(
                [ff, "-y", "-hide_banner", "-loglevel", "error",
                 "-i", path.name,
                 "-af", f"atempo={1 / stretch:.5f}",
                 tmp.name],
                cwd=str(path.parent), capture_output=True, check=True,
            )
            tmp.replace(path)
            slowed += 1
            print(f"[tts] slowed {path.stem}: {wpm:.0f} -> ~{wpm / stretch:.0f} wpm")
        except Exception:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
    if slowed:
        print(f"[tts] rate governor: {slowed}/{len(takes)} takes eased toward "
              f"the video's own pace ({median:.0f} wpm)")


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
    # Seeded generation already removed the chaos this was built for (178-258 Hz
    # unseeded became 182-205 seeded). At that spread, a whole-take shift costs
    # more than it buys: dragging one 53-second take 8% down to chase the global
    # median darkened its timbre enough to be heard as a different narrator —
    # while pulling it AWAY from the take beside it. Global sameness is not the
    # goal; local continuity is, and the seam easing owns that.
    seed_active = os.getenv("TTS_SEED", "42").strip() not in ("", "-1")
    if seed_active:
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
    # budget.
    #
    # Variations used to keep their own take — the separation was deliberate,
    # meant to soften the step rather than remove the boundary. Three renders
    # of listening said otherwise: the moments repeatedly reported as "a
    # different announcer takes over" were variation entrances, which is
    # exactly where that policy placed a cold start. The boundary the viewer
    # needs is visual (the board tints, the banner names the line); the voice
    # should read straight through it.
    merged: List[List[Dict[str, Any]]] = []
    for g in groups:
        prev = merged[-1] if merged else None
        joinable = (
            prev is not None
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
        payload = {"text": _spoken_form(text), "voice": voice, "format": "wav"}
        # A fixed seed per request is the documented cure for Qwen3-TTS chunks
        # drifting in timbre. The service ignores the field until it supports
        # it, so this costs nothing to send today.
        seed = os.getenv("TTS_SEED_OVERRIDE") or os.getenv("TTS_SEED", "42").strip()
        if seed and seed != "-1":
            payload["seed"] = int(seed)
        # Optional steadiness knob; unset means the service default. Measured
        # inconclusive on cross-text baseline (n=4), so not set by default.
        temp = os.getenv("TTS_TEMPERATURE", "").strip()
        if temp:
            payload["temperature"] = float(temp)
        body = json.dumps(payload).encode()
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
        # The first take used to be the only one with no primer, and it showed:
        # it cold-started ~143 Hz darker in timbre than the rest of the video.
        # A canned warm-up line — cut away like any primer — fixes that.
        primer = _tail_sentence(takes[-1][2]) if takes else WARMUP_PRIMER
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
    #
    # Two triggers. Whole-take deviation catches a take that is simply the
    # wrong voice throughout. It is structurally blind to the commoner case —
    # a take that OPENS hot and settles, because a ten-second anomaly averages
    # out of a forty-second measurement (b0010: +5 dB and +34% wpm, whole-take
    # numbers innocuous; the next render drew a +180 Hz opening the same way).
    # So the seam each take makes with its predecessor is a trigger of its
    # own, and the downstream easing passes are explicitly NOT the answer
    # here: they are capped at corrections small enough to be inaudible, and
    # a cliff that size needs a different sample, not a nudge.
    if len(takes) >= 4 and _ffmpeg():
        try:
            measured = [(p, _median_f0(p), _centroid(p)) for _, p, _ in takes]
            voiced = sorted(f for _, f, _ in measured if f > 0)
            cents = sorted(c for _, _, c in measured if c > 0)
            if len(voiced) >= 4:
                target = voiced[len(voiced) // 2]
                ctarget = cents[len(cents) // 2] if cents else 0

                def dist(f, c):
                    d = abs(f - target) / target if f and target else 1.0
                    if ctarget and c:
                        d += abs(c - ctarget) / ctarget
                    return d

                def seam_pen(i: int, path: Path) -> float:
                    """How badly this take's opening clashes with the take
                    before it, in the same units dist() speaks."""
                    if i == 0:
                        return 0.0
                    prev = takes[i - 1][1]
                    pen = 0.0
                    tail, head = _median_f0(prev, -1.2), _median_f0(path, 0.0, 1.2)
                    if tail and head:
                        pen += max(0.0, abs(head - tail) - 30) / 150
                    lt, lh = _level_db(prev, -1.5), _level_db(path, 0.0, 1.5)
                    if lt is not None and lh is not None:
                        pen += max(0.0, (lh - lt) - 3.0) / 8
                    return pen

                # Timbre is what reads as "a different person" — pitch register
                # is allowed to breathe with the pace of the passage.
                candidates = []
                for i, (p, f, c) in enumerate(measured):
                    whole = (f and abs(target / f - 1.0) > 0.10) or (
                        c and ctarget and abs(ctarget / c - 1.0) > 0.12)
                    pen = seam_pen(i, p)
                    if whole or pen > 0.15:
                        candidates.append((i, f, c, pen))
                # Worst first. The budget is four rolls, and taking the first
                # four in video order spent them on mild early offenders while
                # a +5 dB cliff at 6:34 waited fifth in line and shipped.
                candidates.sort(key=lambda t: t[3] + dist(t[1], t[2]),
                                reverse=True)
                base_seed = os.getenv("TTS_SEED", "42").strip()
                for i, f0, cen, pen in candidates[:4]:
                    group, para_path, text = takes[i]
                    fresh = out_dir / f"{para_path.stem}.reroll.wav"
                    # Same seed would reproduce the same audio byte for byte, so
                    # a seeded re-roll must explore a different one.
                    if base_seed not in ("", "-1"):
                        os.environ["TTS_SEED_OVERRIDE"] = str(int(base_seed) + 1 + i)
                    try:
                        # Primed like any take. This used to fetch the bare
                        # text, so every re-roll cold-started — the exact
                        # pathology priming exists to prevent, handed a second
                        # chance at the very takes already flagged as odd.
                        _fetch_primed(
                            fetch, text,
                            _tail_sentence(takes[i - 1][2]) if i else WARMUP_PRIMER,
                            fresh, f"re-roll {para_path.stem}",
                        )
                    finally:
                        os.environ.pop("TTS_SEED_OVERRIDE", None)
                    new_f0 = _median_f0(fresh)
                    new_cen = _centroid(fresh)
                    old_score = dist(f0, cen) + pen
                    new_score = dist(new_f0, new_cen) + seam_pen(i, fresh)
                    if new_f0 and new_score < old_score:
                        fresh.replace(para_path)
                        print(f"[tts] re-rolled {para_path.stem}: "
                              f"{f0:.0f}Hz/{cen:.0f} -> {new_f0:.0f}Hz/{new_cen:.0f} "
                              f"(score {old_score:.2f} -> {new_score:.2f})")
                    else:
                        fresh.unlink(missing_ok=True)
                        print(f"[tts] re-roll of {para_path.stem} no better; "
                              f"keeping the original (score {old_score:.2f})")
        except Exception as exc:  # noqa: BLE001
            # Cosmetic pass: never let it cost the run.
            print(f"[tts] outlier re-roll skipped ({exc})")

    # --- phase 3: even out the remaining pitch and level ----------------
    # Pitch normalisation, then seam easing. Two *level* treatments were tried
    # here and dropped: matching whole-take loudness widened the step at the
    # seam rather than closing it (x1.59 -> x1.78), and tapering each take's
    # onset did no better (x2.56). Pitch is where the "two announcers" effect
    # actually lives, so pitch is what gets corrected.
    _slow_fast_takes(takes)
    _normalize_pitch([p for _, p, _ in takes])
    _trim_loud_takes([p for _, p, _ in takes])
    _flatten_seams([p for _, p, _ in takes])
    _ease_seam_levels([p for _, p, _ in takes])
    # Closed loop: everything above nudges; this one re-measures with the
    # audit's thresholds and re-synthesizes what nudging could not fix.
    _rescue_stubborn_seams(takes, fetch)

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
    _check_offvoice_beats(lines, clips, out_dir)
    return clips


def _check_offvoice_beats(
    lines: Sequence[Dict[str, str]],
    clips: Dict[str, Dict[str, Any]],
    out_dir: Path,
) -> None:
    """The pre-render half of the audit's per-beat verdict.

    The seam checks judge take boundaries; these judge each beat against its
    own thirty seconds, with the audit's exact arithmetic via
    find_offvoice_beats — the same clip files the audit will measure, before
    the render spends twenty-five minutes on them. Two renders were built and
    then held by the audit's cluster rule in one day because this half was
    missing. Verdicts are appended to the marker the build step already reads.
    """
    rows = []
    at = 0
    for item in lines:
        clip = clips.get(item["id"])
        if not clip:
            continue
        dur = int(clip.get("durationMs") or 0)
        path = out_dir / (clip.get("file") or "")
        if dur >= BEAT_MIN_MS and path.exists():
            words = len(clip.get("words") or [])
            rows.append((
                item["id"], at, _median_f0(path), _level_db(path),
                words / (dur / 60000) if words else 0.0, words,
            ))
        at += dur

    try:
        different_read, _outliers, cluster = find_offvoice_beats(rows)
    except Exception as exc:  # noqa: BLE001
        # Measurement, not synthesis: never let the check cost the run.
        print(f"[tts] off-voice check skipped ({exc})")
        return

    defects: List[Dict[str, Any]] = []
    for bid, ddb, ratio in different_read:
        defects.append({"type": "different-read", "beat": bid,
                        "dDb": round(ddb, 1), "wpmRatio": round(ratio, 2)})
        print(f"[tts] beat {bid} is {ddb:+.1f} dB and x{ratio:.2f} wpm "
              "against its surroundings — the audit will fail it")
    if cluster:
        defects.append({"type": "off-voice-cluster", "beats": cluster})
        print(f"[tts] {len(cluster)} off-voice beats within 30s "
              f"({', '.join(cluster)}) — the audit will fail it")
    if not defects:
        return
    marker = out_dir / "unresolved_seams.json"
    try:
        existing = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = []
    marker.write_text(json.dumps(existing + defects), encoding="utf-8")


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
