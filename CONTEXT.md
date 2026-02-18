# Chess Autopost – Context for AI assistants

## Goal
Produce a complete YouTube-ready chess video daily: board replay + arrows/pins/heatmap + ASMR female narration + (later) intro/outro + upload.

## Current pipeline (works)
1) **Analyzer** (Python / Stockfish)
   - `apps/analyzer/chessbot_analyzer/timeline.py` → builds `Timeline` (scenes: main/alt/reset).
   - Optional: `scripting.py` → simple narration lines (ASMR tone).
2) **Orchestrator** (Python)
   - `services/orchestrator/build_video.py`
   - Writes:
     - `apps/renderer/public/timeline.json`
     - `apps/renderer/public/audio/*.wav`
     - `apps/renderer/public/audio_durations.json`
   - TTS: pyttsx3 (swappable later).
3) **Renderer** (Remotion/React)
   - `apps/renderer` (Remotion 4.0.347)
   - Composition: `ChessVideo` in `src/index.tsx`
   - Scenes: `src/scenes/*`, types in `src/types/timeline.ts`
   - Run preview: `npm --prefix apps/renderer run preview`
   - Render mp4: `npm --prefix apps/renderer run render` → `apps/renderer/out/video.mp4`

## Files to look at
- Python:
  - `services/orchestrator/build_video.py` (entrypoint)
  - `apps/analyzer/chessbot_analyzer/timeline.py` (timeline builder)
  - `apps/analyzer/chessbot_analyzer/scripting.py` (ASMR narrator, non-LLM)
  - `services/orchestrator/tts_client.py` (optional adapter; future)
- Renderer:
  - `apps/renderer/src/compositions/Video.tsx`
  - `apps/renderer/src/scenes/SceneMainMove.tsx`, `SceneAltPreview.tsx`, `SceneReset.tsx`
  - `apps/renderer/src/components/*` (Board, Arrow, Heatmap, EvalBar, PortraitPanel)
  - `apps/renderer/src/lib/audio.ts` (browser-safe helpers)
  - `apps/renderer/src/types/timeline.ts`

## How to run locally
```bash
# Python (from repo root, with .venv activated)
pip install -e ./apps/analyzer[dev] pyttsx3 pydub
python services/orchestrator/build_video.py

# Preview in browser
npm --prefix apps/renderer run preview

# Final mp4
npm --prefix apps/renderer run render
# outputs: apps/renderer/out/video.mp4
