# Chess Autopost

A fully autonomous pipeline for creating professional chess analysis videos with perfect audio-visual synchronization. The system ingests historic games, analyzes them with Stockfish, generates voice-over scripts, synthesizes speech, and renders videos with precise timing between narration and chess moves.

## 🎯 Overview

Chess Autopost automatically creates daily chess analysis videos by:

1. **Ingesting** historic games from Lichess, Chess.com, and TWIC
2. **Selecting** the best game for the day (scoring/anniversary-based)
3. **Analyzing** each move with Stockfish MultiPV analysis
4. **Detecting** tactical features (pins, attacks, sacrifices)
5. **Generating** concise voice-over scripts
6. **Synthesizing** natural speech with ElevenLabs
7. **Rendering** videos with Remotion (React/TypeScript)
8. **Uploading** to YouTube with metadata and chapters

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

## 🎬 Key Features

### **Perfect Audio-Visual Sync**
- **Word-Level Alignment**: Pin glow appears exactly when "pinned" is spoken
- **Audio-Driven Timing**: Scene duration matches audio clip length
- **Cue-Based Animations**: Animations trigger on specific spoken words
- **Fallback Safety**: Percentage-based timing if alignment fails

### **Professional Chess Analysis**
- **MultiPV Engine Analysis**: Stockfish with 4+ principal variations
- **Tactical Detection**: Automatic pin, fork, and sacrifice detection
- **Evaluation Tracking**: Smooth evaluation bar with centipawn precision
- **Alternative Moves**: Preview of best alternatives with reset scenes

### **Automated Content Creation**
- **Smart Game Selection**: Anniversary and quality-based selection
- **Natural Scripts**: Chess notation normalized for speech
- **Dynamic Metadata**: Auto-generated titles, descriptions, and tags
- **YouTube Integration**: Automated upload with chapters and thumbnails

## 🚀 Quick Start

### Prerequisites

- Python 3.10+ with virtual environment
- Node.js 18+ (or 20) and npm
- PostgreSQL database
- Stockfish engine binary
- ElevenLabs API key
- YouTube Data API credentials

### Installation

1. **Create a root virtual environment and install the analyzer (editable):**
```bash
# from repo root
python -m venv .venv
source .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ./apps/analyzer[dev]
```

2. **Setup TypeScript renderer:**
```bash
cd chess-autopost/apps/renderer
npm install
# Type-check
npx tsc --noEmit
# Optional: render video/thumbnail via scripts
npm run render:video
npm run render:thumb
```

3. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your API keys and database URL
```

4. **Initialize database:**
```bash
psql -d your_database -f infra/migrations/001_init.sql
```

### Basic Usage

1. **Ingest games:**
```bash
chessbot ingest --source lichess --path games.pgn
```

2. **Select today's game:**
```bash
chessbot select --strategy anniversary-or-topscore
```

3. **Run complete pipeline:**
```bash
chessbot pipeline --game-id 123 --output-dir ./outputs
```

4. **Generate voice:**
```bash
voice synth --lines outputs/lines.json --voice-id VOICE_ID --out audio/
```

5. **Align audio for perfect sync:**
```bash
voice align --lines outputs/lines.json --audio-dir audio/ --output alignment.json
```

6. **Render video:**
```bash
renderer render --timeline outputs/timeline.json --audio-dir audio/
```

### Quick commands

```bash
# Ingest → Select → Analyze + Script
chessbot ingest --source lichess --path games.pgn
chessbot select --strategy anniversary-or-topscore
chessbot pipeline --game-id 123 --output-dir ./outputs

# Voice (generate + align)
voice synth --lines ./outputs/lines.json --voice-id $VOICE_ID --out ./outputs/audio/
voice align --lines ./outputs/lines.json --audio-dir ./outputs/audio/ --output ./outputs/alignment.json

# Render (via Remotion scripts, optional)
cd apps/renderer
npm run render:video
```

7. **Upload to YouTube:**
```bash
uploader upload --video outputs/video.mp4 --timeline outputs/timeline.json
```

## 📚 Detailed Documentation

### **Python Analyzer (`apps/analyzer/`)**

The analyzer is the core engine that processes chess games and generates render-ready timelines.

#### **Core Modules:**

- **`config.py`**: Central configuration with Pydantic settings
- **`engine.py`**: Stockfish wrapper with MultiPV analysis and caching
- **`detectors.py`**: Feature detection for pins, attacks, and move evaluation
- **`timeline.py`**: Converts analysis into renderer-ready timeline structure
- **`scripting.py`**: Generates voice-over scripts optimized for audio sync
- **`cli.py`**: Command-line interface for all operations

#### **Key Classes:**

```python
# Engine analysis with caching
with StockfishEngine() as engine:
    results = engine.analyse(board)  # Returns MultiPV analysis

# Feature detection
pins = FeatureDetectors.compute_pins(board)
attacked = FeatureDetectors.attacked_squares(board)
tag = FeatureDetectors.tag_move(eval_before, eval_after)

# Timeline building
builder = TimelineBuilder()
timeline = builder.from_game(game_id, audio_durations)
```

#### **CLI Commands:**

```bash
# Ingest games from various sources
chessbot ingest --source lichess --path games.pgn
chessbot ingest --source chesscom --username magnus --month 2023-01
chessbot ingest --source twic --path twic1234.pgn

# Select and analyze games
chessbot select --strategy anniversary-or-topscore
chessbot analyse --game-id 123 --out timeline.json
chessbot script --timeline timeline.json --out lines.json

# Run complete pipeline
chessbot pipeline --game-id 123 --output-dir ./outputs
```

### **TypeScript Renderer (`apps/renderer/`)**

The renderer creates professional chess videos using Remotion with perfect audio synchronization.

#### **Core Components:**

- **`Board.tsx`**: SVG chess board with piece placement
- **`Arrow.tsx`**: Animated move arrows with customizable styles
- **`Heatmap.tsx`**: Attack/defense square highlighting
- **`PinHighlight.tsx`**: Pin detection with ray visualization
- **`EvalBar.tsx`**: Animated evaluation bar
- **`PortraitPanel.tsx`**: Player portraits and names

#### **Scene Types:**

- **`SceneMainMove.tsx`**: Main move with all tactical elements
- **`SceneAltPreview.tsx`**: Alternative move previews
- **`SceneReset.tsx`**: Quick transition between scenes

#### **Audio Sync System:**

```typescript
// Cue-based animation timing
const pinTiming = getAnimationTiming(
  scene.durationMs,
  scene.cueTimes,
  'pinned',    // Keyword to sync with
  0.35,        // Fallback percentage
  fps
);

// Pin glow appears exactly when "pinned" is spoken
const pinOpacity = interpolate(
  frame,
  [pinTiming.startFrame, pinTiming.startFrame + 10],
  [0, 1],
  { easing: Easing.out(Easing.cubic) }
);
```

### **Voice Synthesis (`apps/voice/`)**

Advanced text-to-speech with forced alignment for word-level synchronization.

#### **Key Features:**

- **Batch Synthesis**: Process multiple voice lines efficiently
- **Caching**: Avoid re-synthesizing identical text
- **Text Normalization**: Convert chess notation to natural speech
- **Forced Alignment**: Get precise word timestamps with WhisperX

#### **Usage:**

```bash
# Synthesize voice lines
voice synth --lines lines.json --voice-id VOICE_ID --out audio/

# List available voices
voice voices

# Normalize text for better pronunciation
voice normalize --input script.txt --output script.normalized.txt

# Test voice synthesis
voice test --voice-id VOICE_ID --text "Hello, this is a test"
```

#### **Text Normalization:**

```typescript
// Converts chess notation to natural speech
"Kxe4" → "King takes e4"
"O-O" → "castles kingside"
"#3" → "mate in 3"
"g2" → "gee two"
```

### **YouTube Uploader (`apps/uploader/`)**

Automated YouTube upload with intelligent metadata generation.

#### **Features:**

- **Auto Metadata**: Generate titles, descriptions, and tags
- **Chapter Generation**: Automatic chapters from game phases
- **Thumbnail Upload**: Custom thumbnail support
- **Scheduling**: Schedule videos for optimal posting times

#### **Usage:**

```bash
# Upload video with auto-generated metadata
uploader upload --video video.mp4 --timeline timeline.json

# Generate metadata only
uploader metadata --timeline timeline.json --output metadata.json

# Generate chapters
uploader chapters --timeline timeline.json --output chapters.txt

# Update video metadata
uploader update --video-id VIDEO_ID --title "New Title"
```

## 🔧 Configuration

### **Environment Variables**

```bash
# Database
DB_URL=postgresql+psycopg2://user:pass@host:5432/chessbot

# ElevenLabs TTS
ELEVENLABS_API_KEY=your_api_key

# YouTube API
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
GOOGLE_REFRESH_TOKEN=your_refresh_token

# Engine Settings
STOCKFISH_PATH=/usr/local/bin/stockfish
ENGINE_THREADS=4
ENGINE_HASH_MB=1024
ENGINE_DEPTH=20
ENGINE_MULTIPV=4

# Optional Services
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
SLACK_WEBHOOK_URL=your_slack_webhook
```

### **Engine Configuration**

```python
# config.py
class Settings(BaseSettings):
    ENGINE_THREADS: int = 4          # CPU threads for Stockfish
    ENGINE_HASH_MB: int = 1024       # Memory allocation
    ENGINE_DEPTH: int = 20           # Analysis depth
    ENGINE_MULTIPV: int = 4          # Number of principal variations
    ALT_PREVIEW_PLIES: int = 2       # Moves to preview in alternatives
    MAX_SCENE_DURATION_MS: int = 1600 # Maximum scene length
```

## 🎬 Audio-Visual Synchronization

The system ensures perfect sync between narration and chess moves through a multi-stage process:

### **1. Scene-Based Architecture**
- Each move gets a unique scene ID (`m1`, `m2`, etc.)
- One voice line per scene with matching ID
- Audio files named by scene ID (`m1.wav`, `m2.wav`)

### **2. Audio-Driven Timing**
```python
# Scene duration based on audio length
duration_ms = max(1200, min(2500, audio_duration_ms + 150))
```

### **3. Word-Level Alignment**
```python
# Forced alignment with WhisperX
aligner = AudioAligner()
words = aligner.align_audio("m1.wav", "The knight is pinned on e3")
# Returns: [{"word": "pinned", "start": 1.17, "end": 1.23}]
```

### **4. Cue-Based Animations**
```typescript
// Pin glow appears exactly when "pinned" is spoken
const pinTiming = getAnimationTiming(scene.durationMs, scene.cueTimes, 'pinned', 0.35, fps);
```

### **5. Fallback Safety**
- Percentage-based timing if alignment fails
- Natural speech rhythm optimization
- Graceful degradation for edge cases

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
