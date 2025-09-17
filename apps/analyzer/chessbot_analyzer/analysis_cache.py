"""
analysis_cache.py

Runs Stockfish through a game's moves and writes per-ply rows into analysis_cache.
- Evaluates the position after each ply (post-move), so eval deltas reflect move impact.
- Stores: fen, eval_cp (White POV), multipv lines (uci, san, cp/mate), best/alt moves,
  pins and attacked squares for overlays, and basic tags ("mate", "blunder", "brilliant").
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import chess
import chess.engine
import chess.pgn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import settings
from .detectors import FeatureDetectors


@dataclass
class MultiPVEntry:
    uci: str
    san: str
    cp: Optional[int]  # centipawns from White POV (None if mate)
    mate: Optional[int]  # positive means mate in N for side to move


def _engine() -> Engine:
    return create_engine(settings.DB_URL)


def _open_stockfish() -> chess.engine.SimpleEngine:
    eng = chess.engine.SimpleEngine.popen_uci(settings.STOCKFISH_PATH)
    eng.configure(
        {
            "Threads": settings.ENGINE_THREADS,
            "Hash": settings.ENGINE_HASH_MB,
            "MultiPV": settings.ENGINE_MULTIPV,
        }
    )
    return eng


def _score_to_cp_white(score: chess.engine.PovScore) -> Tuple[Optional[int], Optional[int]]:
    """
    Return (cp, mate) from White POV. cp is None when mate is present.
    """
    mate = score.white().mate()
    if mate is not None:
        return None, mate
    cp = score.white().score(mate_score=100000)  # centipawns (approx)
    return int(cp), None


class AnalysisCacheWriter:
    """
    Analyze a game and persist per-ply analysis into analysis_cache.
    """

    def __init__(self, sa_engine: Engine | None = None) -> None:
        self.sa_engine = sa_engine or _engine()

    # ---------- Public API ----------

    def analyze_and_store(
        self,
        game_id: int,
        *,
        depth: Optional[int] = None,
        multipv: Optional[int] = None,
        truncate_existing: bool = True,
        max_plies: Optional[int] = None,
    ) -> int:
        """
        Analyze the game and write rows into analysis_cache.

        Returns: number of plies written.
        """
        depth = depth or settings.ENGINE_DEPTH
        multipv = multipv or settings.ENGINE_MULTIPV

        pgn = self._fetch_pgn(game_id)
        if not pgn:
            raise ValueError(f"Game {game_id} not found or has empty PGN.")

        game = chess.pgn.read_game(__import__("io").StringIO(pgn))
        board = game.board()

        if truncate_existing:
            self._delete_existing_rows(game_id)

        plies_written = 0
        prev_cp: Optional[int] = None

        with _open_stockfish() as sf, self.sa_engine.begin() as conn:
            limit = chess.engine.Limit(depth=depth)

            for ply_idx, move in enumerate(game.mainline_moves(), start=1):
                # apply the real move
                board.push(move)

                # analyze the resulting position (post-move)
                infos = sf.analyse(board, limit, multipv=multipv)
                # `analyse` returns a dict when multipv==1, or a list of dicts when multipv>1
                if isinstance(infos, dict):
                    infos = [infos]

                # extract scores + pv
                cp, mate = _score_to_cp_white(infos[0]["score"])

                # multipv lines (best + alts) — computed on this position
                mpv: List[MultiPVEntry] = []
                for info in infos:
                    pv = info.get("pv", [])
                    if not pv:
                        continue
                    move0: chess.Move = pv[0]
                    tmp = board.copy()
                    san = tmp.san(move0)
                    uci = move0.uci()
                    cpi, mati = _score_to_cp_white(info["score"])
                    mpv.append(MultiPVEntry(uci=uci, san=san, cp=cpi, mate=mati))

                multipv_json = [
                    {"uci": m.uci, "san": m.san, "cp": m.cp, "mate": m.mate} for m in mpv
                ]
                best_move = mpv[0].san if mpv else None
                alt_moves = [m.san for m in mpv[1:]] if len(mpv) > 1 else []

                # features for overlays on this post-move position
                pins = FeatureDetectors.compute_pins(board)
                attacked = FeatureDetectors.attacked_squares(board)

                # basic tags
                tag = None
                if mate is not None:
                    tag = "mate"
                elif prev_cp is not None:
                    diff = (cp if cp is not None else prev_cp) - prev_cp
                    if diff <= -250:
                        tag = "blunder"
                    elif diff >= 250:
                        tag = "brilliant"

                # insert row
                conn.execute(
                    text(
                        """
                        INSERT INTO analysis_cache
                          (game_id, ply, fen, multipv_json, pins_json, attacks_json,
                           best_move, alt_moves, eval_cp, tag)
                        VALUES
                          (:game_id, :ply, :fen, :multipv_json, :pins_json, :attacks_json,
                           :best_move, :alt_moves, :eval_cp, :tag)
                        """
                    ),
                    {
                        "game_id": game_id,
                        "ply": ply_idx,
                        "fen": board.fen(),
                        "multipv_json": json.dumps(multipv_json),
                        "pins_json": json.dumps(pins),
                        "attacks_json": json.dumps(attacked),
                        "best_move": best_move,
                        "alt_moves": json.dumps(alt_moves),
                        "eval_cp": cp,
                        "tag": tag,
                    },
                )

                prev_cp = cp if cp is not None else prev_cp
                plies_written += 1

                if max_plies and plies_written >= max_plies:
                    break

        return plies_written

    # ---------- Internals ----------

    def _fetch_pgn(self, game_id: int) -> Optional[str]:
        with self.sa_engine.begin() as conn:
            row = conn.execute(
                text("SELECT pgn FROM games WHERE id = :id"),
                {"id": game_id},
            ).first()
            return row[0] if row else None

    def _delete_existing_rows(self, game_id: int) -> None:
        with self.sa_engine.begin() as conn:
            conn.execute(text("DELETE FROM analysis_cache WHERE game_id = :gid"), {"gid": game_id})


