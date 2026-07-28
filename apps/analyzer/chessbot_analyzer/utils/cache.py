"""Simple disk and database cache for engine results."""

import json
import os
import sqlite3
from typing import Any, Optional, Dict
from pathlib import Path
from .logging import get_logger

logger = get_logger(__name__)


class CacheManager:
    """Manages caching of engine analysis results."""
    
    def __init__(self, cache_dir: Optional[str] = None, db_path: Optional[str] = None):
        # Engine analysis is the most expensive step in the pipeline, so the
        # cache must survive between runs. An in-memory database made every
        # re-render pay full Stockfish cost again.
        settings_dir = os.getenv("CACHE_DIR") or "./cache"
        self.cache_dir = Path(cache_dir or settings_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        if db_path is None:
            enabled = (os.getenv("ENABLE_DISK_CACHE", "true") or "").strip().lower()
            use_disk = enabled not in ("0", "false", "no")
            db_path = str(self.cache_dir / "engine_cache.sqlite") if use_disk else ":memory:"

        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database for caching."""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Durable enough for a cache, and much faster for the write-heavy
        # analysis pass.
        if self.db_path != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.commit()
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value by key."""
        try:
            cursor = self.conn.execute("SELECT value FROM cache WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        except Exception as e:
            logger.warning(f"Cache get failed for key {key}: {e}")
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Set cached value with optional TTL."""
        try:
            json_value = json.dumps(value)
            self.conn.execute(
                "INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)",
                (key, json_value)
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"Cache set failed for key {key}: {e}")
    
    def clear(self):
        """Clear all cached values."""
        try:
            self.conn.execute("DELETE FROM cache")
            self.conn.commit()
            logger.info("Cache cleared")
        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")
    
    def close(self):
        """Close database connection."""
        if hasattr(self, 'conn'):
            self.conn.close()
