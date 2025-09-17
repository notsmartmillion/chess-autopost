"""Stockfish engine wrapper with MultiPV analysis and caching."""

import chess
import chess.engine
import json
import hashlib
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from .config import settings
from .utils.cache import CacheManager
from .utils.logging import get_logger

logger = get_logger(__name__)


class StockfishEngine:
    """Wrapper for Stockfish UCI engine with MultiPV analysis and caching."""
    
    def __init__(self, cache_manager: Optional[CacheManager] = None):
        self.cache_manager = cache_manager or CacheManager()
        self.engine = None
        
    def __enter__(self):
        """Context manager entry."""
        self.engine = chess.engine.SimpleEngine.popen_uci(settings.STOCKFISH_PATH)
        
        # Configure engine
        self.engine.configure({
            "Threads": settings.ENGINE_THREADS,
            "Hash": settings.ENGINE_HASH_MB,
            "MultiPV": settings.ENGINE_MULTIPV
        })
        
        logger.info(f"Stockfish engine started with {settings.ENGINE_THREADS} threads, "
                   f"{settings.ENGINE_HASH_MB}MB hash, MultiPV={settings.ENGINE_MULTIPV}")
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.engine:
            self.engine.quit()
            logger.info("Stockfish engine stopped")
    
    def analyse(self, board: chess.Board) -> List[Dict[str, Any]]:
        """
        Analyze position with MultiPV and return list of principal variations.
        
        Args:
            board: Chess position to analyze
            
        Returns:
            List of dicts with keys: pv, score, depth, nodes, time
        """
        fen = board.fen()
        cache_key = self._get_cache_key(fen, settings.ENGINE_DEPTH, settings.ENGINE_MULTIPV)
        
        # Check cache first
        cached_result = self.cache_manager.get(cache_key)
        if cached_result:
            logger.debug(f"Cache hit for position analysis: {fen[:50]}...")
            return cached_result
        
        if not self.engine:
            raise RuntimeError("Engine not initialized. Use as context manager.")
        
        try:
            # Perform analysis
            info = self.engine.analyse(
                board, 
                chess.engine.Limit(depth=settings.ENGINE_DEPTH),
                multipv=settings.ENGINE_MULTIPV
            )
            
            # Convert to our format
            results = []
            for i, analysis in enumerate(info):
                result = {
                    "pv": [move.uci() for move in analysis.get("pv", [])],
                    "score": self._format_score(analysis.get("score", chess.engine.PovScore(0, chess.WHITE))),
                    "depth": analysis.get("depth", 0),
                    "nodes": analysis.get("nodes", 0),
                    "time": analysis.get("time", 0),
                    "multipv": i + 1
                }
                results.append(result)
            
            # Cache the result
            self.cache_manager.set(cache_key, results)
            logger.debug(f"Analyzed position: {fen[:50]}... -> {len(results)} PVs")
            
            return results
            
        except Exception as e:
            logger.error(f"Engine analysis failed for position {fen[:50]}...: {e}")
            raise
    
    def _get_cache_key(self, fen: str, depth: int, multipv: int) -> str:
        """Generate cache key for position analysis."""
        key_data = f"{fen}:{depth}:{multipv}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def _format_score(self, score: chess.engine.PovScore) -> Dict[str, Any]:
        """Format engine score for JSON serialization."""
        if score.is_mate():
            return {
                "type": "mate",
                "value": score.relative.mate(),
                "cp": None
            }
        else:
            return {
                "type": "cp",
                "value": score.relative.score(),
                "cp": score.relative.score()
            }
