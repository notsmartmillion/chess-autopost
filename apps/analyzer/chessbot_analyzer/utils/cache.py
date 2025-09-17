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
    
    def __init__(self, cache_dir: str = "./cache", db_path: Optional[str] = None):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Use in-memory SQLite for simple caching
        self.db_path = db_path or ":memory:"
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database for caching."""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
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
