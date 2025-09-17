"""Timeline builder for converting engine analysis into renderer-ready timeline.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chess
import chess.pgn
from pydantic import BaseModel

from .config import settings
from .detectors import FeatureDetectors
from .utils.evals import cp_to_bar_value
from .utils.logging import get_logger

logger = get_logger(__name__)


# ------------------------------ Pydantic models ------------------------------


class Pin(BaseModel):
    sq: str
    ray: List[str]
    attacker: Optional[str] = None
    king: Optional[str] = None
    color: str  # "white" | "black"


class Attacked(BaseModel):
    white: List[str]
    black: List[str]


class SceneMain(BaseModel):
    type: str = "main"
    id: str
    fen: str
    move: str                 # SAN
    lastMoveArrow: List[str]  # [from, to]
    evalBarTarget: float
    pins: List[Pin]
    attacked: Attacked
    durationMs: int
    moveNumber: Optional[int] = None
    player: Optional[str] = None
    cueTimes: Optional[Dict[str, float]] = None


class SceneAlt(BaseModel):
    type: str = "alt"
    id: str
    label: str
    pv: List[str]             # SAN sequence shown (2–3 plies)
    arrows: List[List[str]]   # [[from,to], ...] for each preview step
    attacked: Attacked        # after last step
    cp: Optional[int] = None
    mate: Optional[int] = None
    durationMs: int = 1200
    multipv: int = 2          # which MultiPV index this corresponds to (2..N)
    cueTimes: Optional[Dict[str, float]] = None


class SceneReset(BaseModel):
    type: str = "reset"
    id: str
    durationMs: int = 200


class Timeline(BaseModel):
    meta: Dict[str, Any]
    scenes: List[Dict[str, Any]]
    totalDurationMs: int = 0


# ------------------------------ Engine adapter -------------------------------


class _EngineAdapter:
    """
    Adapter so TimelineBuilder can use either:
      - a provided engine (must implement analyse(board, multipv=?, depth=?))
      - or manage its own StockfishEngine lifecycle (open once, close at end)
    """

    def __init__(self, engine: Any | None = None) -> None:
        self._owned = engine is None
        if engine is not None:
            self._eng = engine
        else:
            # Lazy import to avoid hard dependency in tests
            from .engine import StockfishEngine  # type: ignore
            self._eng = StockfishEngine()
            # Open once for the whole build
            self._eng.__enter__()

    def analyse(self, board: chess.Board, multipv: int, depth: int) -> List[Dict[str, Any]]:
        return self._eng.analyse(board, multipv=multipv, depth=depth)

    def close(self) -> None:
        if self._owned and hasattr(self._eng, "__exit__"):
            try:
                self._eng.__exit__(None, None, None)
            except Exception:
                # Be defensive; we don't want shutdown errors to bubble up
                pass


# ------------------------------ Timeline builder -----------------------------


class TimelineBuilder:
    """Builds timeline from PGN/DB with audio-driven timing and alt-line previews."""

    def __init__(self, engine: Any | None = None, cache_manager: Any | None = None) -> None:
        self.engine = _EngineAdapter(engine)
        self.cache_manager = cache_manager

    # ----------- Public API -----------

    def from_game(self, game_id: int, audio_durations: Optional[Dict[str, int]] = None) -> Timeline:
        """
        Build timeline from database game_id (expects 'games' table with PGN + metadata).
        If you don't have DB wired yet, use `from_pgn`.
        """
        # Lazy import so tests don't require SQLAlchemy
        from sqlalchemy import create_engine, text  # type: ignore

        eng = create_engine(settings.DB_URL)
        with eng.begin() as conn:
            row = conn.execute(
                text("SELECT white, black, date, event, result, eco, pgn FROM games WHERE id = :id"),
                {"id": game_id},
            ).mappings().first()

        if not row:
            # Ensure we close the engine we may own
            self.engine.close()
            raise ValueError(f"Game {game_id} not found.")

        meta = {
            "white": row["white"],
            "black": row["black"],
            "date": str(row["date"]) if row["date"] else None,
            "event": row["event"],
            "result": row["result"],
            "eco": row["eco"],
        }

        try:
            timeline = self.from_pgn(row["pgn"], meta=meta, audio_durations=audio_durations)
        finally:
            # Close engine if we own it
            self.engine.close()
        return timeline

    def from_pgn(
        self,
        pgn_text: str,
        *,
        meta: Optional[Dict[str, Any]] = None,
        audio_durations: Optional[Dict[str, int]] = None,
        alt_preview_plies: int = 2,
        alt_max: int = 2,
        depth: Optional[int] = None,
        multipv: Optional[int] = None,
    ) -> Timeline:
        """
        Build a timeline from a raw PGN string. This path is great for tests and ad-hoc runs.
        """
        depth = depth or settings.ENGINE_DEPTH
        multipv = multipv or settings.ENGINE_MULTIPV

        game = chess.pgn.read_game(io := __import__("io").StringIO(pgn_text))
        if game is None:
            self.engine.close()
            raise ValueError("Empty or invalid PGN provided.")

        # Meta fallbacks from headers
        headers = game.headers
        meta = meta or {
            "white": headers.get("White"),
            "black": headers.get("Black"),
            "date": headers.get("Date"),
            "event": headers.get("Event"),
            "result": headers.get("Result"),
            "eco": headers.get("ECO"),
        }

        scenes: List[Dict[str, Any]] = []
        total_ms = 0

        board = game.board()
        try:
            for ply_idx, move in enumerate(game.mainline_moves(), start=1):
                # Pre-move snapshot (for alt-lines; this is the choice point)
                board_before = board.copy()

                # SAN of the actual move from the pre-move board
                san_move = board.san(move)

                # Apply the real move (post-move position for main scene)
                board.push(move)

                # Last move arrow
                last_arrow = [
                    chess.square_name(move.from_square),
                    chess.square_name(move.to_square),
                ]

                # Engine analysis on *post-move* position for eval bar
                infos_post = self.engine.analyse(board, multipv=multipv, depth=depth)
                best_cp_post, _best_mate_post = self._extract_cp_mate(infos_post[0], pov=board.turn)

                # Build main scene
                main_id = f"m{ply_idx}"
                main_duration = self._duration_for(main_id, audio_durations)
                pins_models = self._pin_models(board)
                attacked_model = Attacked(**FeatureDetectors.attacked_squares(board))
                main_scene = SceneMain(
                    id=main_id,
                    fen=board.fen(),
                    move=san_move,
                    lastMoveArrow=last_arrow,
                    evalBarTarget=cp_to_bar_value(best_cp_post or 0),
                    pins=pins_models,
                    attacked=attacked_model,
                    durationMs=main_duration,
                    moveNumber=(ply_idx + 1) // 2 if board.turn == chess.BLACK else (ply_idx // 2 + 1),
                    player="white" if (ply_idx % 2 == 1) else "black",
                )
                scenes.append(main_scene.dict())
                total_ms += main_duration

                # Alt previews: analyse on the *pre-move* position (side-to-move's choice)
                infos_pre = self.engine.analyse(board_before, multipv=multipv, depth=depth)

                # Skip PV #1 (best); take #2.. up to alt_max
                for alt_idx, info in enumerate(infos_pre[1:alt_max + 1], start=2):
                    alt_id = f"{main_id}_alt{alt_idx}"
                    alt_scene = self._build_alt_scene(
                        alt_id,
                        board_before,
                        info,
                        preview_plies=alt_preview_plies,
                        label=f"Alt #{alt_idx - 1}",
                        multipv_index=alt_idx,
                        audio_durations=audio_durations,
                    )
                    scenes.append(alt_scene.dict())
                    total_ms += alt_scene.durationMs

                    reset_id = f"{main_id}_reset{alt_idx}"
                    reset_scene = SceneReset(
                        id=reset_id,
                        durationMs=self._duration_for(reset_id, audio_durations, 200),
                    )
                    scenes.append(reset_scene.dict())
                    total_ms += reset_scene.durationMs
        finally:
            # Close engine if we own it
            self.engine.close()

        tl = Timeline(meta=meta, scenes=scenes, totalDurationMs=total_ms)
        logger.info(f"Built timeline with {len(scenes)} scenes, total {total_ms} ms")
        return tl

    def save(self, timeline: Timeline, path: str) -> None:
        """Save timeline to JSON file."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(timeline.dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"Timeline saved to {path}")

    def load_audio_durations(self, audio_dir: str) -> Dict[str, int]:
        """Load audio durations from directory (placeholder: treats all as 2000ms)."""
        durations: Dict[str, int] = {}
        p = Path(audio_dir)
        if not p.exists():
            logger.warning(f"Audio directory not found: {audio_dir}")
            return durations
        for wav in p.glob("*.wav"):
            durations[wav.stem] = 2000  # TODO: read real duration via ffprobe
        return durations

    def apply_alignment_data(self, timeline: Timeline, alignment_file: str) -> Timeline:
        """Apply word-level alignment cue times to scenes (optional)."""
        try:
            with open(alignment_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for scene in timeline.scenes:
                sid = scene["id"]
                if sid in data:
                    scene["cueTimes"] = data[sid].get("keywords", {})
            logger.info(f"Applied alignment data from {alignment_file}")
        except Exception as e:
            logger.warning(f"Failed to load alignment data: {e}")
        return timeline

    # ----------- Helpers -----------

    def _duration_for(
        self,
        scene_id: str,
        audio_durations: Optional[Dict[str, int]],
        default_ms: int = 2000,
        min_ms: int = 1200,
        max_ms: int = 2500,
    ) -> int:
        if audio_durations and scene_id in audio_durations:
            ms = audio_durations[scene_id] + 150
            return max(min_ms, min(max_ms, ms))
        return default_ms

    def _extract_cp_mate(self, info: Dict[str, Any], pov: chess.Color) -> Tuple[Optional[int], Optional[int]]:
        """
        Normalize analysis info to (cp, mate) from POV of the side-to-move.
        Supports either {"cp": int, "mate": Optional[int]} or {"score": PovScore}.
        """
        if "cp" in info or "mate" in info:
            return info.get("cp"), info.get("mate")
        score = info.get("score")
        if score is None:
            return None, None
        # score is a chess.engine.PovScore
        mate = score.pov(pov).mate()
        if mate is not None:
            return None, mate
        cp = score.pov(pov).score(mate_score=100000)
        return int(cp), None

    def _pin_models(self, board: chess.Board) -> List[Pin]:
        """Convert detector pins to Pin models and add color."""
        raw = FeatureDetectors.compute_pins(board)
        pins: List[Pin] = []
        for p in raw:
            sq = p.get("sq")
            piece = board.piece_at(chess.parse_square(sq)) if sq else None
            color = "white" if (piece and piece.color == chess.WHITE) else "black"
            pins.append(Pin(sq=sq, ray=p.get("ray", []), attacker=p.get("attacker"), king=p.get("king"), color=color))
        return pins

    def _build_alt_scene(
        self,
        scene_id: str,
        root_board: chess.Board,
        info: Dict[str, Any],
        *,
        preview_plies: int,
        label: str,
        multipv_index: int,
        audio_durations: Optional[Dict[str, int]],
    ) -> SceneAlt:
        """Construct an 'alt' scene by simulating first N plies of the PV from the root position."""
        pv_moves: List[chess.Move] = info.get("pv", []) or []
        # Limit to requested preview plies
        pv_moves = pv_moves[:preview_plies]

        tmp = root_board.copy()
        arrows: List[List[str]] = []
        pv_san: List[str] = []

        for mv in pv_moves:
            san = tmp.san(mv)
            pv_san.append(san)
            arrows.append([chess.square_name(mv.from_square), chess.square_name(mv.to_square)])
            tmp.push(mv)

        attacked_model = Attacked(**FeatureDetectors.attacked_squares(tmp))
        cp, mate = self._extract_cp_mate(info, pov=root_board.turn)
        duration = self._duration_for(scene_id, audio_durations, default_ms=1200)

        return SceneAlt(
            id=scene_id,
            label=label,
            pv=pv_san,
            arrows=arrows,
            attacked=attacked_model,
            cp=cp,
            mate=mate,
            durationMs=duration,
            multipv=multipv_index,
        )
