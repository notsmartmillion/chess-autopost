-- games metadata + raw PGN
CREATE TABLE IF NOT EXISTS games (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,             -- lichess|chesscom|twic|manual
  event TEXT, site TEXT, date DATE,
  white TEXT, black TEXT, result TEXT,
  eco TEXT, ply_count INT,
  pgn TEXT NOT NULL,
  moves_hash TEXT UNIQUE            -- dedupe: hash(white,black,date,moves SAN)
);

-- cached engine/feature info (per game, per ply)
CREATE TABLE IF NOT EXISTS analysis_cache (
  id BIGSERIAL PRIMARY KEY,
  game_id BIGINT REFERENCES games(id),
  ply INT,
  fen TEXT,
  multipv_json JSONB,               -- engine lines + evals
  pins_json JSONB,                  -- [{sq, ray:[...], attacker, king}]
  attacks_json JSONB,               -- {white:[sq], black:[sq]}
  best_move TEXT,
  alt_moves JSONB,                  -- [moveSAN, ...]
  eval_cp INT,
  tag TEXT                          -- e.g., "blunder","brilliant",NULL
);

-- media tracking
CREATE TABLE IF NOT EXISTS media (
  id BIGSERIAL PRIMARY KEY,
  game_id BIGINT REFERENCES games(id),
  video_path TEXT,
  thumb_path TEXT,
  youtube_id TEXT,
  status TEXT,                      -- queued|rendered|uploaded|failed
  published_at TIMESTAMPTZ
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_games_source ON games(source);
CREATE INDEX IF NOT EXISTS idx_games_date ON games(date);
CREATE INDEX IF NOT EXISTS idx_games_moves_hash ON games(moves_hash);
CREATE INDEX IF NOT EXISTS idx_analysis_cache_game_ply ON analysis_cache(game_id, ply);
CREATE INDEX IF NOT EXISTS idx_media_game_id ON media(game_id);
CREATE INDEX IF NOT EXISTS idx_media_status ON media(status);
