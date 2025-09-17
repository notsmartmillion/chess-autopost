"""Timeline builder for converting engine analysis into renderer-ready timeline.json."""

import json
import chess
import chess.pgn
from typing import List, Dict, Any, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from .config import settings
from .engine import StockfishEngine
from .detectors import FeatureDetectors
from .utils.pgn import get_position_after_move, get_fen_after_move
from .utils.evals import cp_to_bar_value, format_evaluation
from .utils.fen import get_last_move_arrow
from .utils.logging import get_logger

logger = get_logger(__name__)


class Pin(BaseModel):
    sq: str
    ray: List[str]
    attacker: Optional[str] = None
    king: Optional[str] = None
    color: str


class Attacked(BaseModel):
    white: List[str]
    black: List[str]


class SceneMain(BaseModel):
    type: str = "main"
    id: str
    fen: str
    move: str
    lastMoveArrow: List[str]
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
    pv: List[str]
    arrows: List[List[str]]
    attacked: Attacked
    cp: Optional[float] = None
    mate: Optional[int] = None
    durationMs: int
    multipv: int
    cueTimes: Optional[Dict[str, float]] = None


class SceneReset(BaseModel):
    type: str = "reset"
    id: str
    durationMs: int


class Timeline(BaseModel):
    meta: Dict[str, Any]
    scenes: List[Dict[str, Any]]
    totalDurationMs: int = 0


class TimelineBuilder:
    """Builds timeline from game analysis with audio-driven timing."""
    
    def __init__(self, cache_manager=None):
        self.cache_manager = cache_manager
        self.engine = None
        
    def from_game(self, game_id: int, audio_durations: Optional[Dict[str, int]] = None) -> Timeline:
        """
        Build timeline from game ID with audio-driven timing.
        
        Args:
            game_id: Database game ID
            audio_durations: Optional dict of scene_id -> duration_ms from audio files
            
        Returns:
            Complete timeline ready for rendering
        """
        # TODO: Load game from database
        # For now, we'll create a sample timeline
        logger.info(f"Building timeline for game {game_id}")
        
        # Sample game data (replace with database query)
        meta = {
            "white": "Magnus Carlsen",
            "black": "Hikaru Nakamura", 
            "date": "2023-01-15",
            "event": "World Championship",
            "result": "1-0",
            "eco": "C42"
        }
        
        scenes = []
        current_time_ms = 0
        
        # Sample moves (replace with actual game analysis)
        sample_moves = [
            {"move": "e4", "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1", "eval": 0.1},
            {"move": "e5", "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2", "eval": 0.0},
            {"move": "Nf3", "fen": "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKBNR b KQkq - 1 2", "eval": 0.2},
        ]
        
        for i, move_data in enumerate(sample_moves):
            move_number = i + 1
            player = "white" if i % 2 == 0 else "black"
            scene_id = f"m{move_number}"
            
            # Create main scene
            main_scene = self._create_main_scene(
                scene_id, move_data, move_number, player, audio_durations
            )
            scenes.append(main_scene)
            current_time_ms += main_scene.durationMs
            
            # Add alternative scenes for interesting moves
            if i > 0:  # Skip first move
                alt_scenes = self._create_alt_scenes(
                    scene_id, move_data, audio_durations
                )
                scenes.extend(alt_scenes)
                current_time_ms += sum(scene.durationMs for scene in alt_scenes)
                
                # Add reset scene
                reset_scene = self._create_reset_scene(f"r{move_number}", audio_durations)
                scenes.append(reset_scene)
                current_time_ms += reset_scene.durationMs
        
        timeline = Timeline(
            meta=meta,
            scenes=[scene.dict() for scene in scenes],
            totalDurationMs=current_time_ms
        )
        
        logger.info(f"Timeline built: {len(scenes)} scenes, {current_time_ms}ms total")
        return timeline
    
    def _create_main_scene(self, scene_id: str, move_data: Dict, move_number: int, 
                          player: str, audio_durations: Optional[Dict[str, int]]) -> SceneMain:
        """Create main move scene."""
        board = chess.Board(move_data["fen"])
        
        # Get last move arrow (simplified)
        last_move_arrow = ["e2", "e4"] if move_number == 1 else ["d7", "d5"]
        
        # Calculate evaluation bar target
        eval_target = cp_to_bar_value(int(move_data["eval"] * 100))
        
        # Detect features
        pins = self._detect_pins(board)
        attacked = self._detect_attacked_squares(board)
        
        # Calculate duration
        duration_ms = self._calculate_scene_duration(scene_id, audio_durations)
        
        return SceneMain(
            id=scene_id,
            fen=move_data["fen"],
            move=move_data["move"],
            lastMoveArrow=last_move_arrow,
            evalBarTarget=eval_target,
            pins=pins,
            attacked=attacked,
            durationMs=duration_ms,
            moveNumber=move_number,
            player=player
        )
    
    def _create_alt_scenes(self, scene_id: str, move_data: Dict, 
                          audio_durations: Optional[Dict[str, int]]) -> List[SceneAlt]:
        """Create alternative move scenes."""
        alt_scenes = []
        
        # Sample alternative moves
        alt_moves = [
            {"move": "d4", "eval": 0.1, "multipv": 2},
            {"move": "c4", "eval": -0.1, "multipv": 3}
        ]
        
        for alt_move in alt_moves:
            alt_scene_id = f"{scene_id}_alt{alt_move['multipv']}"
            
            # Calculate duration
            duration_ms = self._calculate_scene_duration(alt_scene_id, audio_durations)
            
            alt_scene = SceneAlt(
                id=alt_scene_id,
                label=f"Alt #{alt_move['multipv'] - 1}",
                pv=[alt_move["move"], "Nf6", "Nc3"],
                arrows=[["d2", "d4"]],  # Simplified
                attacked=Attacked(white=[], black=[]),
                cp=alt_move["eval"] * 100,
                durationMs=duration_ms,
                multipv=alt_move["multipv"]
            )
            alt_scenes.append(alt_scene)
        
        return alt_scenes
    
    def _create_reset_scene(self, scene_id: str, audio_durations: Optional[Dict[str, int]]) -> SceneReset:
        """Create reset scene."""
        duration_ms = self._calculate_scene_duration(scene_id, audio_durations, default_ms=200)
        
        return SceneReset(
            id=scene_id,
            durationMs=duration_ms
        )
    
    def _detect_pins(self, board: chess.Board) -> List[Pin]:
        """Detect pins in position."""
        pins_data = FeatureDetectors.compute_pins(board)
        return [Pin(**pin) for pin in pins_data]
    
    def _detect_attacked_squares(self, board: chess.Board) -> Attacked:
        """Detect attacked squares."""
        attacked_data = FeatureDetectors.attacked_squares(board)
        return Attacked(**attacked_data)
    
    def _calculate_scene_duration(self, scene_id: str, audio_durations: Optional[Dict[str, int]], 
                                 default_ms: int = 2000) -> int:
        """Calculate scene duration based on audio or default."""
        if audio_durations and scene_id in audio_durations:
            # Use audio duration with padding
            audio_ms = audio_durations[scene_id]
            return max(1200, min(2500, audio_ms + 150))
        else:
            return default_ms
    
    def save(self, timeline: Timeline, path: str) -> None:
        """Save timeline to JSON file."""
        with open(path, 'w') as f:
            json.dump(timeline.dict(), f, indent=2)
        logger.info(f"Timeline saved to {path}")
    
    def load_audio_durations(self, audio_dir: str) -> Dict[str, int]:
        """Load audio durations from directory."""
        durations = {}
        audio_path = Path(audio_dir)
        
        if not audio_path.exists():
            logger.warning(f"Audio directory not found: {audio_dir}")
            return durations
        
        for wav_file in audio_path.glob("*.wav"):
            scene_id = wav_file.stem
            # TODO: Use ffprobe to get actual duration
            durations[scene_id] = 2000  # Default 2 seconds
        
        logger.info(f"Loaded {len(durations)} audio durations")
        return durations
    
    def apply_alignment_data(self, timeline: Timeline, alignment_file: str) -> Timeline:
        """Apply word-level alignment data to timeline."""
        try:
            with open(alignment_file, 'r') as f:
                alignment_data = json.load(f)
            
            # Update scenes with cue times
            for scene_dict in timeline.scenes:
                scene_id = scene_dict["id"]
                if scene_id in alignment_data:
                    scene_dict["cueTimes"] = alignment_data[scene_id].get("keywords", {})
            
            logger.info(f"Applied alignment data from {alignment_file}")
            
        except Exception as e:
            logger.warning(f"Failed to load alignment data: {e}")
        
        return timeline
