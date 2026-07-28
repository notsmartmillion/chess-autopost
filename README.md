# Chess Autopost

A fully autonomous pipeline for creating professional chess analysis videos with audio-visual synchronization. The system fetches a fresh game daily, analyzes it with Stockfish, generates banter-style voice-over, synthesizes speech, renders a video, and uploads it to YouTube.

## 🚀 Daily one-shot (the important command)

```bash
# From repo root, after one-time setup below:
python services/orchestrator/flow.py            # fetch → analyze → narrate → TTS → render → upload
python services/orchestrator/flow.py --no-upload   # same, keep video local
python services/orchestrator/flow.py --pgn my.pgn  # render a specific game
```

`flow.py` needs **no credentials** to produce a video (public Lichess API + local
pyttsx3 TTS). The YouTube upload step runs only when `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN` are set in `.env`; otherwise
it's skipped and the finished video stays at `apps/renderer/out/video.mp4`.
A state file (`outputs/state/used_games.json`) guarantees the same game is never
posted twice.

Schedule it:

- **Windows**: `schtasks /Create /TN "ChessAutopost" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File <repo>\services\orchestrator\run_daily.ps1" /SC DAILY /ST 07:00`
- **Linux/macOS**: cron `0 7 * * * <repo>/services/orchestrator/run_daily.sh`

## 🎯 Overview

Chess Autopost automatically creates daily chess analysis videos by:

1. **Fetching** a recent game from a pool of strong Lichess players (configurable via `DAILY_LICHESS_PLAYERS`)
2. **Selecting** the most watchable unused game (decisive, mid-length, high-rated)
3. **Analyzing** each move with Stockfish MultiPV analysis
4. **Detecting** tactical features (pins, attacks, blunders/brilliancies)
5. **Generating** banter-style voice-over scripts (built-in narrator; optional LLM via `OPENAI_API_KEY`)
6. **Synthesizing** speech locally with pyttsx3 (ElevenLabs client available as an alternative)
7. **Rendering** videos with Remotion (board, move arrows, eval bar, move captions, "better was…" alternative-line previews)
8. **Uploading** to YouTube with metadata and chapters (optional)

## 🏗️ Architecture

```
chess-autopost/
├── apps/
│   ├── analyzer/           # Python analysis pipeline
│   ├── renderer/           # TypeScript/Remotion video rendering
│   ├── voice/              # ElevenLabs TTS with alignment
│   └── uploader/           # YouTube API integration
├── services/
│   └── orchestrator/       # Daily automation flow
├── infra/
│   ├── docker/            # Container definitions
│   └── migrations/        # Database schema
├── storage/
│   └── assets/            # Portraits, sounds, music
└── outputs/               # Generated videos, thumbnails, logs
```

## 🧠 How it works (four passes)

The script is the timeline — not the game. This is the central design decision
and it is what makes narrated variations possible.

```
PGN ──► facts.py ──► director.py ──► tts.py ──► Remotion ──► YouTube
        (engine)     (beats)         (voice)     (render)
```

**1. Facts** (`apps/analyzer/chessbot_analyzer/facts.py`)
Stockfish walks the game **once** (one analysis per position) and emits a fact
sheet per ply: White-POV evaluation, best line, move quality, and positional
features — pins, skewers, forks, hanging pieces, batteries, long diagonals
("the bishop on g7 shoots across the board"), pawn structure, king safety,
material, phase. Plus ranked `keyMoments` for the whole game.

**2. Director** (`apps/analyzer/chessbot_analyzer/director.py`)
Facts become a **beat script**. A beat is one spoken sentence *plus the board
directives that belong with it* — which squares to highlight, which arrow to
draw, which move to play. Crucially every beat carries an explicit `fen`.

That is what fixes variation stitching. A "better was Qb6…" digression is just
a run of beats with `branch: true`, and returning to the game is a beat whose
`fen` is the real position again. Nothing is rewound, because nothing is a
cursor. Variations trigger on blunders, mistakes, missed mates, costly
inaccuracies at key moments, and on brilliancies (where the branch instead
*refutes* the natural alternative — "it is worth seeing why the obvious move
fails").

**3. Voice** (`services/orchestrator/tts.py`)
ElevenLabs `/with-timestamps` returns the audio **and** per-character
alignment, so we get the exact clip duration and the moment every word is
spoken — no ffmpeg required. The director tags each beat with `moveCueWords`,
so a piece begins sliding precisely as its destination square is named.
Falls back to local pyttsx3 (with estimated word times) when no API key is set,
so the pipeline never hard-fails. Clips are cached by content hash, so re-runs
do not burn credits.

**4. Render** (`apps/renderer`)
Remotion renders the beats. `AnimatedBoard` slides pieces with a spring —
correctly handling castling, en passant and promotion by diffing the two FENs —
so motion is smooth rather than snapping between positions. Composition length
comes from `calculateMetadata` reading the measured audio, so the video is
exactly as long as the narration.

## 🎬 Key Features

- **Smooth piece motion** — spring-animated slides, fading captures, no hard cuts
- **Cue-accurate highlights** — visuals land on the spoken word, not a guess
- **Inline variations** — branch into the engine's line and resume cleanly
- **Grounded narration** — commentary is generated from real engine facts, and
  optionally polished by an LLM (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) so it
  does not sound templated
- **Classic game library** — daily games are drawn from world-champion
  collections (Tal, Fischer, Kasparov, Capablanca, …), cached locally after
  first download
- **Never repeats a game** — `outputs/state/used_games.json` tracks move hashes

## 🚀 Quick Start

### Prerequisites

- **Python 3.11** (pydantic is pinned <2; 3.12+ works, 3.14 does not)
- **Node.js 18+** and npm
- **Stockfish** — the setup step below downloads it automatically
- Optional: ElevenLabs API key (voice), Anthropic/OpenAI key (narration polish),
  YouTube OAuth credentials (upload)

No database is required.

### One-time setup

```bash
# 1. Python environment
py -3.11 -m venv .venv                 # Windows
# python3.11 -m venv .venv             # Linux/macOS
.venv/Scripts/python -m pip install -U pip
.venv/Scripts/python -m pip install -e "./apps/analyzer[dev]" pyttsx3 pydub requests python-dateutil

# 2. Renderer
npm --prefix apps/renderer install

# 3. Stockfish (Windows example; use your package manager on Linux/macOS)
mkdir -p tools/stockfish && cd tools/stockfish
curl -L -o sf.zip https://github.com/official-stockfish/Stockfish/releases/download/sf_18/stockfish-windows-x86-64-avx2.zip
unzip -o sf.zip && mv stockfish/*.exe ./stockfish.exe && rm -rf stockfish sf.zip && cd ../..

# 4. Configuration
cp .env.example .env
# Set STOCKFISH_PATH, and any API keys you want to use.
```

Then produce a video:

```bash
.venv/Scripts/python services/orchestrator/flow.py --no-upload
```

### Useful invocations

```bash
# Render one specific game
python services/orchestrator/build_video.py --pgn outputs/pgns/daily/game.pgn

# Fast structural check: no engine depth, silent placeholder audio, no render
python services/orchestrator/build_video.py --pgn game.pgn --tts silent --depth 8 --no-llm --no-render

# Preview in the browser instead of rendering
npm --prefix apps/renderer run preview

# Pick a classic game by hand
python services/orchestrator/ingest/classics_fetch.py --list
python services/orchestrator/ingest/classics_fetch.py --player Fischer --out outputs/pgns/daily/game.pgn

# Inspect what the uploader would post
npm --prefix apps/uploader run cli -- upload -v apps/renderer/out/video.mp4 -t outputs/script.json --dry-run
```

### Build artifacts

| File | Contents |
|---|---|
| `outputs/facts.json` | Per-ply engine + positional facts (pass 1) |
| `outputs/script.json` | Narration beats with board directives (pass 2) |
| `outputs/audio/` | One narration clip per beat (pass 3) |
| `apps/renderer/out/video.mp4` | Final video (pass 4) |

## 📚 Module reference

| Module | Role |
|---|---|
| `apps/analyzer/chessbot_analyzer/facts.py` | **Pass 1.** `extract_facts(pgn)` → per-ply engine + positional fact sheet |
| `apps/analyzer/chessbot_analyzer/director.py` | **Pass 2.** `build_script(facts)` → narration beats + board directives |
| `services/orchestrator/tts.py` | **Pass 3.** `synthesize(lines, dir)` → audio + word timings |
| `apps/renderer/src/compositions/ChessNarration.tsx` | **Pass 4.** Beat-driven Remotion composition |
| `apps/renderer/src/components/AnimatedBoard.tsx` | Spring-animated board (castling / en passant / promotion aware) |
| `services/orchestrator/build_video.py` | Chains all four passes for one game |
| `services/orchestrator/flow.py` | Daily runner: pick game → build → upload |
| `services/orchestrator/ingest/classics_fetch.py` | Classic master-game library |
| `apps/uploader/` | YouTube upload, metadata, chapters |

### The beat schema

Everything downstream of the director is driven by this one structure:

```jsonc
{
  "id": "b0042",
  "kind": "move",              // intro | move | variation | resume | hold | outro
  "text": "Tal answers with knight takes g4, giving up material for the initiative.",
  "prevFen": "...",            // position before  → drives the slide animation
  "fen": "...",                // position after
  "move": {"from": "f6", "to": "g4", "san": "Nxg4"},
  "branch": false,             // true inside a variation
  "label": "Better was Rd7",   // banner shown while branching
  "highlights": [{"square": "g4", "kind": "danger"}],
  "arrows": [{"from": "g7", "to": "a1", "color": "#f5c542"}],
  "checkSquare": null,
  "evalCp": -120,              // White POV, drives the eval bar
  "tag": "inaccuracy",
  "ply": 41,
  "moveCueWords": ["g4"],      // animate the move when this word is spoken
  "durationMs": 4820,          // measured from the narration clip
  "moveAtMs": 1180,            // resolved from word-level timestamps
  "audioFile": "b0042.mp3"
}
```

`highlights[].kind` maps to the palette: `move` amber, `alt` orange,
`danger` red, `good` green.

## 🔧 Configuration

All configuration lives in `.env` (see `.env.example` for the annotated list).
The ones that matter most:

| Variable | Effect |
|---|---|
| `STOCKFISH_PATH` | Path to the engine binary (**required**) |
| `ENGINE_DEPTH` / `ENGINE_MULTIPV` | Analysis quality vs. speed. 16 / 3 is a good default |
| `ELEVENLABS_API_KEY` + `VOICE_ID` | Enables ElevenLabs voice with word-level timestamps |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Enables LLM narration polish |
| `TTS_BACKEND` | `auto` (default), `elevenlabs`, `local`, `silent` |
| `DAILY_SOURCE` | `classics` (default) or `lichess` |
| `DAILY_LEGENDS` | Restrict the classics pool, e.g. `Tal,Fischer` |
| `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN` | Enables the upload step |
| `YOUTUBE_PRIVACY` | `public`, `unlisted` (default), `private` |

Engine analysis is cached on disk (`cache/engine_cache.sqlite`), so re-rendering
the same game does not pay Stockfish cost twice.

## 🚀 Deployment

### **Docker Deployment**

```bash
# Build analyzer container
docker build -f infra/docker/analyzer.Dockerfile -t chess-analyzer .

# Build renderer container  
docker build -f infra/docker/renderer.Dockerfile -t chess-renderer .

# Run with docker-compose
docker-compose up -d
```

### **Daily Automation**

```bash
# services/orchestrator/run_daily.sh
#!/bin/bash
cd /app/chess-autopost

# 1. Ingest new games
chessbot ingest --source lichess --path /data/games.pgn

# 2. Select today's game
GAME_ID=$(chessbot select --strategy anniversary-or-topscore)

# 3. Run complete pipeline
chessbot pipeline --game-id $GAME_ID --output-dir /outputs

# 4. Generate voice
voice synth --lines /outputs/lines.json --voice-id $VOICE_ID --out /outputs/audio/

# 5. Align audio
voice align --lines /outputs/lines.json --audio-dir /outputs/audio/ --output /outputs/alignment.json

# 6. Render video
renderer render --timeline /outputs/timeline.json --audio-dir /outputs/audio/

# 7. Upload to YouTube
uploader upload --video /outputs/video.mp4 --timeline /outputs/timeline.json

# 8. Notify success
curl -X POST $SLACK_WEBHOOK_URL -d '{"text":"Daily chess video uploaded successfully!"}'
```

## 📊 Performance

### **Analysis Speed**
- **Engine Analysis**: ~2-5 seconds per position (depth 20, MultiPV 4)
- **Feature Detection**: ~50ms per position
- **Timeline Generation**: ~100ms per game

### **Rendering Performance**
- **Video Rendering**: ~1-2 minutes for 10-minute video (1080p)
- **Audio Synthesis**: ~30 seconds per minute of speech
- **Alignment Processing**: ~10 seconds per minute of audio

### **Storage Requirements**
- **Database**: ~1MB per 1000 games
- **Audio Cache**: ~1MB per minute of speech
- **Video Output**: ~100MB per 10-minute video (1080p)

## 🐛 Troubleshooting

### **Common Issues**

1. **Stockfish not found**
   ```bash
   # Install Stockfish
   brew install stockfish  # macOS
   apt-get install stockfish  # Ubuntu
   ```

2. **Audio sync issues**
   ```bash
   # Check alignment data
   voice align --lines lines.json --audio-dir audio/ --output alignment.json
   # Verify cue times in timeline.json
   ```

3. **YouTube upload fails**
   ```bash
   # Refresh OAuth token
   uploader auth --refresh-token
   ```

4. **Database connection issues**
   ```bash
   # Test connection
   psql $DB_URL -c "SELECT 1;"
   ```

### **Debug Mode**

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
chessbot pipeline --game-id 123 --output-dir ./outputs
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

### **Development Setup**

```bash
# Install development dependencies
pip install -r requirements-dev.txt
npm install --dev

# Run tests
pytest tests/
npm test

# Format code
black .
prettier --write "**/*.{ts,tsx,js,jsx}"
```

## 📄 License

MIT License - see LICENSE file for details.

## 🙏 Acknowledgments

- **Stockfish**: Chess engine for position analysis
- **ElevenLabs**: Text-to-speech synthesis
- **Remotion**: Video rendering framework
- **WhisperX**: Forced alignment for audio sync
- **python-chess**: Chess position handling

---

**Built with ❤️ for the chess community**
