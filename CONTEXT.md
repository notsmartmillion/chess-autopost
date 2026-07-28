# Chess Autopost – Context for AI assistants

## Goal
Produce a complete YouTube-ready chess video daily: board replay + arrows/pins/heatmap + banter narration + intro/outro + "better was…" alt-line previews + upload.

## Architecture note (important)

The **script is the timeline**, not the game. A *beat* is one spoken sentence
plus the board directives that belong with it, and every beat carries an
explicit `fen`. This is what makes "better was Qb6…" variations work: a
variation is just a run of beats with `branch=true`, and resuming the game is a
beat whose `fen` is the real position again. Nothing is ever rewound, because
nothing is a cursor. The old scene-based `timeline.py` design is superseded.

Passes: `facts.py` (engine + positional facts) -> `director.py` (beats) ->
`services/orchestrator/tts.py` (audio + word timings) -> Remotion.

## Current pipeline (works end to end)

0) **Daily orchestrator** — `services/orchestrator/flow.py`
   - Picks an unused classic master game (`ingest/classics_fetch.py`), dedupes
     via `outputs/state/used_games.json`, then builds, renders and optionally uploads.
   - Wrappers: `run_daily.ps1` (Task Scheduler), `run_daily.sh` (cron).
1) **Facts** — `apps/analyzer/chessbot_analyzer/facts.py`
   - One Stockfish analysis per position. White-POV evals, best lines, move
     quality, pins/forks/hanging/long-rays/pawn structure, ranked `keyMoments`.
2) **Director** — `apps/analyzer/chessbot_analyzer/director.py`
   - Facts -> beats (narration + board directives). Variations on blunders,
     mistakes, missed mates, and brilliancies (refuting the natural alternative).
   - Optional LLM polish via `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`.
3) **Voice** — `services/orchestrator/tts.py`
   - Backends: `qwen` (Qwen3-TTS local, Apache-2.0 — set up the voice once with
     `voice_design.py`), `elevenlabs` (`/with-timestamps`), `local` (Windows
     SAPI), `silent`. `auto` picks qwen > elevenlabs > local.
   - Local models return no alignment, so word timings come from whisperx
     forced alignment (`QWEN_ALIGN=1`), falling back to proportional estimates.
   - `moveCueWords` resolve to `moveAtMs` so pieces move on the spoken word.
   - Never clone a real person's voice — use `voice_design.py` to *design* one.
4) **Render** — `apps/renderer`
   - `ChessNarration.tsx` + `AnimatedBoard.tsx`; length from `calculateMetadata`.
   - Preview: `npm --prefix apps/renderer run preview`
   - Render: `npm --prefix apps/renderer run render` -> `apps/renderer/out/video.mp4`
   - Thumbnail: `npm --prefix apps/renderer run render:thumb`
5) **Uploader** — `apps/uploader`, `npm run cli -- upload -v video.mp4 -t script.json`
   - Needs GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN; skipped gracefully without them.
   - Chapters and metadata derive from the beats, so timestamps are exact.

## Visual identity — "Analysis Deck"

Deliberately *not* the reference channel's look. Dark slate (`#0b0e13`) with a
single cyan accent (`#5ac8fa`) and violet for variations (`#b28cff`).
Board sits left; a right-hand rail carries players, a numeric eval readout,
the current move with its quality badge, and a live move list.
Palette lives in `apps/renderer/src/components/AnalysisRail.tsx` (`THEME`) and
is mirrored by the director's arrow colours in `director.py` (`COLOR_*`) — keep
those two in sync.

## Gotchas

- Use the Python 3.11 venv (`.venv`). pydantic is pinned <2; Python 3.14 fails.
- Windows consoles are cp1252 — the orchestrator scripts reconfigure stdout to
  UTF-8 before printing anything.
- lichess.org rate-limits aggressively from some IPs and returns 404 without a
  descriptive User-Agent. `DAILY_SOURCE=classics` (the default) avoids the API
  entirely after the first collection download.
- The board is mounted **once** and driven by the current beat. Do not move it
  back inside a per-beat `<Sequence>`: remounting recreates all 32 sprites at
  every beat boundary and the pieces visibly flicker.
- Piece sprites must use Remotion's `<Img>`, not `<img>` — Remotion only waits
  for `<Img>` to load before capturing a frame.
- `apps/voice/` and `apps/renderer/src/{compositions/Video.tsx,scenes/*}` are
  superseded by the beat pipeline and are not part of the render path.

## Files to look at

- `services/orchestrator/flow.py` — daily entry point
- `services/orchestrator/build_video.py` — one game, all four passes
- `services/orchestrator/tts.py` — voice + word timings
- `apps/analyzer/chessbot_analyzer/facts.py` — engine/positional facts
- `apps/analyzer/chessbot_analyzer/director.py` — beats + narration
- `apps/renderer/src/compositions/ChessNarration.tsx` — the video
- `apps/renderer/src/components/AnimatedBoard.tsx` — piece animation
- `apps/renderer/src/components/AnalysisRail.tsx` — theme + rail widgets
- `apps/renderer/src/types/script.d.ts` — beat schema

## How to run locally

```bash
# One-off video from a specific game
.venv/Scripts/python services/orchestrator/build_video.py --pgn outputs/pgns/daily/game.pgn

# Fast structural check (no engine depth, silent audio, no render)
.venv/Scripts/python services/orchestrator/build_video.py --pgn game.pgn     --tts silent --depth 8 --no-llm --no-render

# The full daily run
.venv/Scripts/python services/orchestrator/flow.py --no-upload

# Browser preview
npm --prefix apps/renderer run preview
```
