# apps/voice — superseded

**The pipeline does not use this app.** Voice synthesis now lives in
[`services/orchestrator/tts.py`](../../services/orchestrator/tts.py).

## Why it moved

The TypeScript client here synthesized audio but could not tell the renderer
*when* each word was spoken, so animations had to be timed by guesswork. The
Python implementation calls ElevenLabs' `/with-timestamps` endpoint instead,
which returns the audio **and** per-character alignment. That gives us:

- the exact clip duration without decoding audio (no ffmpeg dependency), and
- the moment every word is spoken, so a piece starts moving precisely as its
  destination square is named.

Keeping the synthesis in Python also means the whole pipeline
(facts → director → voice) is one language and one process.

## What is still here

| File | Status |
|---|---|
| `elevenlabs_client.ts` | Superseded by `services/orchestrator/tts.py` |
| `text_normalizer.ts` | Superseded — the director now writes moves as spoken words ("knight to f3") at generation time, which is more reliable than normalizing SAN afterwards |
| `cli.ts` | Superseded |
| `aligner.py` | Superseded — WhisperX forced alignment is unnecessary now that ElevenLabs returns alignment directly. Still useful if you ever switch to a TTS provider without timestamps. |

These files are kept for reference. They are not imported by the pipeline and
are not type-checked in CI. Delete them if you are confident you will not go
back to a provider that lacks word timings.
