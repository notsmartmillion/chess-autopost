"""Central configuration and environment parsing for chess analyzer."""

from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseSettings, validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables (.env)."""

    # -----------------------------
    # Database
    # -----------------------------
    DB_URL: str  # required (e.g., sqlite:///./chessbot.db or postgres URL)

    # -----------------------------
    # Engine (Stockfish)
    # -----------------------------
    STOCKFISH_PATH: str = "/usr/local/bin/stockfish"
    ENGINE_THREADS: int = 4
    ENGINE_HASH_MB: int = 1024
    ENGINE_DEPTH: int = 20
    ENGINE_MULTIPV: int = 4

    # Analysis / Rendering helpers
    ALT_PREVIEW_PLIES: int = 2
    ALT_MAX: int = 2
    MAX_SCENE_DURATION_MS: int = 1600

    # -----------------------------
    # Caching
    # -----------------------------
    CACHE_DIR: str = "./cache"
    ENABLE_DISK_CACHE: bool = True

    # -----------------------------
    # ElevenLabs (Voice)
    # -----------------------------
    ELEVENLABS_API_KEY: Optional[str] = None
    VOICE_ID: Optional[str] = None

    # -----------------------------
    # YouTube API (Uploader)
    # -----------------------------
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REFRESH_TOKEN: Optional[str] = None

    # -----------------------------
    # Optional Services
    # -----------------------------
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    SLACK_WEBHOOK_URL: Optional[str] = None

    # -----------------------------
    # Logging
    # -----------------------------
    LOG_LEVEL: str = "INFO"

    # -----------------------------
    # Paths
    # -----------------------------
    OUTPUT_DIR: str = "./outputs"
    AUDIO_DIR: str = "./outputs/audio"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    # ---------- Validators / Normalizers ----------

    @validator("DB_URL")
    def _strip_db_url(cls, v: str) -> str:
        # Trim whitespace; don't provide a default (keeps it required)
        return v.strip()

    @validator("DB_URL", pre=True)
    def _fallback_database_url(cls, v: Optional[str]):
        """Allow DATABASE_URL as a fallback for compatibility with existing setups."""
        if v and isinstance(v, str) and v.strip():
            return v
        env_v = os.getenv("DATABASE_URL")
        if env_v:
            return env_v
        return v

    @validator("STOCKFISH_PATH", pre=True)
    def _normalize_stockfish_path(cls, v: str) -> str:
        """
        Normalize quotes/spaces and expand env/user.
        Example Windows value in .env should be quoted:
          "C:\\Program Files\\Stockfish\\stockfish.exe"
        This removes wrapping quotes and expands env vars if present.
        """
        if not isinstance(v, str):
            return v
        vv = v.strip().strip('"').strip("'")
        # Expand %VAR% / $VAR and ~
        vv = os.path.expandvars(os.path.expanduser(vv))
        return vv

    @validator("CACHE_DIR", "OUTPUT_DIR", "AUDIO_DIR", pre=True)
    def _normalize_dirs(cls, v: str) -> str:
        if not isinstance(v, str):
            return v
        return os.path.normpath(v.strip())


# Global settings instance (will raise if required vars are missing)
settings = Settings()
