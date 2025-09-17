"""Central configuration and environment parsing for chess analyzer."""

from pydantic import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database
    DB_URL: str
    
    # Engine configuration
    STOCKFISH_PATH: str = "/usr/local/bin/stockfish"
    ENGINE_THREADS: int = 4
    ENGINE_HASH_MB: int = 1024
    ENGINE_DEPTH: int = 20
    ENGINE_MULTIPV: int = 4
    
    # Analysis settings
    ALT_PREVIEW_PLIES: int = 2
    MAX_SCENE_DURATION_MS: int = 1600
    
    # Cache settings
    CACHE_DIR: str = "./cache"
    ENABLE_DISK_CACHE: bool = True
    
    # ElevenLabs
    ELEVENLABS_API_KEY: Optional[str] = None
    
    # YouTube
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REFRESH_TOKEN: Optional[str] = None
    
    # Optional services
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    SLACK_WEBHOOK_URL: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings()
