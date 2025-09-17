# apps/analyzer/chessbot_analyzer/engine.py
"""Stockfish engine wrapper with MultiPV analysis and caching (merged)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

import chess
import chess.engine

from .config import settings
from .utils.cache import CacheManager
from .utils.logging import get_logger

logger = get_logger(__name__)


class StockfishEngine:
    """
    Thin wrapper around python-chess SimpleEngine that:
      - accepts config via kwargs (path/threads/hash/multipv/depth)
      - provides context-manager lifecycle
      - caches analysis per (FEN, depth, multipv) in JSON-safe form
      - returns a normalized list[dict] with:
          {
            "pv": [chess.Move, ...],   # native for callers
            "cp": int|None,            # centipawns from POV of side-to-move
            "mate": int|None,          # mate in N (positive) from POV of side-to-move
            "depth": int, "nodes": int, "time": float, "multipv": int
          }
    """

    def __init__(
        self,
        *,
        path: Optional[str] = None,
        threads: Optional[int] = None,
        hash_mb: Optional[int] = None,
        multipv: Optional[int] = None,
        depth: Optional[int] = None,
        cache_manager: Optional[CacheManager] = None,
    ) -> None:
        self.path = path or settings.STOCKFISH_PATH
        self.threads = threads or settings.ENGINE_THREADS
        self.hash_mb = hash_mb or settings.ENGINE_HASH_MB
        self.default_multipv = multipv or settings.ENGINE_MULTIPV
        self.default_depth = depth or settings.ENGINE_DEPTH

        self.cache = cache_manager or CacheManager()
        self._eng: Optional[chess.engine.SimpleEngine] = None

    # ---------------- context manager ----------------

    def __enter__(self) -> "StockfishEngine":
        self._open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---------------- public API ----------------

    def analyse(
        self,
        board: chess.Board,
        *,
        multipv: Optional[int] = None,
        depth: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Analyse a position with MultiPV; return normalized list of entries.

        Returns list items with keys: pv (List[chess.Move]), cp, mate, depth, nodes, time, multipv.
        """
        m = multipv or self.default_multipv
        d = depth or self.default_depth

        fen = board.fen()
        cache_key = self._cache_key(fen, d, m)

        # Try cache (JSON-safe form)
        cached = self.cache.get(cache_key)
        if cached:
            logger.debug("Engine cache hit.")
            return self._json_to_native(cached)

        if self._eng is None:
            self._open()

        # Run engine
        infos = self._eng.analyse(board, chess.engine.Limit(depth=d), multipv=m)
        if isinstance(infos, dict):
            infos = [infos]

        # Normalize + build JSON-safe payload for cache
        native: List[Dict[str, Any]] = []
        cached_payload: List[Dict[str, Any]] = []

        for idx, info in enumerate(infos, start=1):
            pv_moves = info.get("pv", []) or []
            # Extract cp/mate from POV of side-to-move
            cp, mate = self._score_to_cp_mate(info.get("score"), pov=board.turn)

            # Metrics (optional in engine outputs)
            depth_out = int(info.get("depth", d) or d)
            nodes_out = int(info.get("nodes", 0) or 0)
            time_out = float(info.get("time", 0.0) or 0.0)

            # Build native
            native.append(
                {
                    "pv": pv_moves,  # List[chess.Move]
                    "cp": cp,
                    "mate": mate,
                    "depth": depth_out,
                    "nodes": nodes_out,
                    "time": time_out,
                    "multipv": idx,
                }
            )

            # Build JSON-safe cache entry
            cached_payload.append(
                {
                    "pv_uci": [m.uci() for m in pv_moves],
                    "cp": cp,
                    "mate": mate,
                    "depth": depth_out,
                    "nodes": nodes_out,
                    "time": time_out,
                    "multipv": idx,
                }
            )

        # Store in cache
        self.cache.set(cache_key, cached_payload)
        logger.debug(f"Analyzed position: depth={d} multipv={m} -> {len(native)} PVs")

        return native

    def close(self) -> None:
        if self._eng is not None:
            try:
                self._eng.quit()
                logger.info("Stockfish engine stopped")
            finally:
                self._eng = None

    # ---------------- internals ----------------

    def _open(self) -> None:
        if self._eng is not None:
            return
        logger.info(f"Starting Stockfish: {self.path} (Threads={self.threads}, Hash={self.hash_mb}MB)")
        eng = chess.engine.SimpleEngine.popen_uci(self.path)
        eng.configure(
            {
                "Threads": self.threads,
                "Hash": self.hash_mb,
                # We pass MultiPV per-call to analyse(..., multipv=?)
            }
        )
        self._eng = eng

    @staticmethod
    def _score_to_cp_mate(score_obj: Optional[chess.engine.PovScore], pov: chess.Color) -> tuple[Optional[int], Optional[int]]:
        """
        Convert a PovScore into (cp, mate) from POV of the side-to-move.
        Returns (None, mate) if mate is present; otherwise (cp, None).
        """
        if score_obj is None:
            return None, None
        mate = score_obj.pov(pov).mate()
        if mate is not None:
            return None, int(mate)
        cp = score_obj.pov(pov).score(mate_score=100000)
        return int(cp), None

    @staticmethod
    def _cache_key(fen: str, depth: int, multipv: int) -> str:
        key = f"{fen}|d={depth}|m={multipv}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _json_to_native(cached_payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for entry in cached_payload:
            pv = [chess.Move.from_uci(u) for u in entry.get("pv_uci", [])]
            out.append(
                {
                    "pv": pv,
                    "cp": entry.get("cp"),
                    "mate": entry.get("mate"),
                    "depth": entry.get("depth"),
                    "nodes": entry.get("nodes"),
                    "time": entry.get("time"),
                    "multipv": entry.get("multipv"),
                }
            )
        return out
