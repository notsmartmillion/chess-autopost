"""Script generator for turning scenes into concise VO lines with audio-sync considerations."""

import random
from typing import List, Dict, Any
from .timeline import Timeline, SceneMain, SceneAlt
from .utils.evals import format_evaluation, get_eval_category
from .utils.logging import get_logger

logger = get_logger(__name__)


class ScriptGenerator:
    """Generates voice-over scripts with timing considerations for audio sync."""
    
    def __init__(self):
        self.phrase_bank = self._build_phrase_bank()
    
    def from_timeline(self, timeline: Timeline) -> List[Dict[str, str]]:
        """
        Generate voice lines from timeline with audio-sync considerations.
        
        Args:
            timeline: Complete timeline with scenes
            
        Returns:
            List of voice line dictionaries with id and text
        """
        voice_lines = []
        
        for scene_dict in timeline.scenes:
            scene_type = scene_dict.get("type")
            scene_id = scene_dict.get("id")
            
            if scene_type == "main":
                text = self._generate_main_scene_script(scene_dict)
            elif scene_type == "alt":
                text = self._generate_alt_scene_script(scene_dict)
            elif scene_type == "reset":
                # Reset scenes are typically silent or have minimal audio
                continue
            else:
                logger.warning(f"Unknown scene type: {scene_type}")
                continue
            
            if text:
                voice_lines.append({
                    "id": scene_id,
                    "text": text
                })
        
        logger.info(f"Generated {len(voice_lines)} voice lines")
        return voice_lines
    
    def _generate_main_scene_script(self, scene: Dict[str, Any]) -> str:
        """Generate script for main move scene."""
        move = scene.get("move", "")
        move_number = scene.get("moveNumber", 0)
        player = scene.get("player", "")
        eval_target = scene.get("evalBarTarget", 0.0)
        pins = scene.get("pins", [])
        attacked = scene.get("attacked", {})
        
        # Build script components
        components = []
        
        # Move announcement
        if move_number <= 10:
            components.append(f"Move {move_number}: {move}")
        else:
            components.append(move)
        
        # Evaluation context
        if abs(eval_target) > 0.3:
            eval_text = self._format_eval_for_speech(eval_target)
            components.append(eval_text)
        
        # Tactical elements
        if pins:
            pin_text = self._describe_pins(pins)
            components.append(pin_text)
        
        # Attack context
        total_attacked = len(attacked.get("white", [])) + len(attacked.get("black", []))
        if total_attacked > 8:
            components.append("Tactical complexity increases")
        
        # Combine components
        if len(components) == 1:
            return components[0]
        elif len(components) == 2:
            return f"{components[0]}. {components[1]}"
        else:
            return f"{components[0]}. {components[1]}. {components[2]}"
    
    def _generate_alt_scene_script(self, scene: Dict[str, Any]) -> str:
        """Generate script for alternative move scene."""
        label = scene.get("label", "Alternative")
        cp = scene.get("cp")
        mate = scene.get("mate")
        pv = scene.get("pv", [])
        
        # Start with alternative label
        text = f"{label}:"
        
        # Add evaluation
        if mate:
            text += f" mate in {mate}"
        elif cp:
            eval_text = self._format_cp_for_speech(cp)
            text += f" {eval_text}"
        
        # Add move sequence
        if pv:
            moves = " ".join(pv[:3])  # Limit to first 3 moves
            text += f" {moves}"
        
        return text
    
    def _format_eval_for_speech(self, eval_target: float) -> str:
        """Format evaluation for natural speech."""
        if eval_target > 0.5:
            return "White has a winning advantage"
        elif eval_target > 0.3:
            return "White is better"
        elif eval_target > 0.1:
            return "White has a slight advantage"
        elif eval_target < -0.5:
            return "Black has a winning advantage"
        elif eval_target < -0.3:
            return "Black is better"
        elif eval_target < -0.1:
            return "Black has a slight advantage"
        else:
            return "The position is equal"
    
    def _format_cp_for_speech(self, cp: float) -> str:
        """Format centipawn evaluation for speech."""
        if abs(cp) < 10:
            return "equal position"
        elif abs(cp) < 50:
            return f"{'slight advantage' if cp > 0 else 'slight disadvantage'}"
        elif abs(cp) < 200:
            pawns = abs(cp) / 100
            return f"{pawns:.1f} pawn {'advantage' if cp > 0 else 'disadvantage'}"
        else:
            pawns = abs(cp) / 100
            return f"{pawns:.1f} pawn {'advantage' if cp > 0 else 'disadvantage'}"
    
    def _describe_pins(self, pins: List[Dict[str, Any]]) -> str:
        """Describe pin tactics in the position."""
        if not pins:
            return ""
        
        pin_count = len(pins)
        if pin_count == 1:
            pin = pins[0]
            piece_square = pin.get("sq", "")
            return f"The piece on {self._format_square_for_speech(piece_square)} is pinned"
        else:
            return f"Multiple pins in the position"
    
    def _format_square_for_speech(self, square: str) -> str:
        """Format square notation for natural speech."""
        if len(square) != 2:
            return square
        
        file_names = {
            'a': 'ay', 'b': 'bee', 'c': 'see', 'd': 'dee',
            'e': 'ee', 'f': 'eff', 'g': 'gee', 'h': 'aitch'
        }
        
        file = square[0].lower()
        rank = square[1]
        
        return f"{file_names.get(file, file)} {rank}"
    
    def _build_phrase_bank(self) -> Dict[str, List[str]]:
        """Build phrase bank for variety in script generation."""
        return {
            "move_intros": [
                "Now",
                "Here",
                "Next",
                "Then",
                "Following"
            ],
            "evaluations": [
                "The position is",
                "This gives",
                "This leads to",
                "Resulting in"
            ],
            "tactics": [
                "Tactical opportunity",
                "Tactical motif",
                "Tactical pattern",
                "Tactical idea"
            ],
            "advantages": [
                "advantage",
                "edge",
                "superiority",
                "initiative"
            ],
            "disadvantages": [
                "disadvantage",
                "weakness",
                "problem",
                "difficulty"
            ]
        }
    
    def _get_random_phrase(self, category: str) -> str:
        """Get random phrase from category."""
        phrases = self.phrase_bank.get(category, [])
        return random.choice(phrases) if phrases else ""
    
    def optimize_for_audio_sync(self, voice_lines: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Optimize voice lines for better audio synchronization.
        
        Args:
            voice_lines: List of voice line dictionaries
            
        Returns:
            Optimized voice lines
        """
        optimized = []
        
        for line in voice_lines:
            text = line["text"]
            
            # Ensure consistent timing cues
            optimized_text = self._add_timing_cues(text)
            
            # Optimize for natural speech rhythm
            optimized_text = self._optimize_speech_rhythm(optimized_text)
            
            optimized.append({
                "id": line["id"],
                "text": optimized_text
            })
        
        return optimized
    
    def _add_timing_cues(self, text: str) -> str:
        """Add natural pauses and timing cues to text."""
        # Add pauses after important moves
        text = text.replace("Move ", "Move... ")
        text = text.replace("takes", "takes...")
        text = text.replace("check", "check!")
        text = text.replace("mate", "mate!")
        
        return text
    
    def _optimize_speech_rhythm(self, text: str) -> str:
        """Optimize text for natural speech rhythm."""
        # Ensure proper spacing
        text = " ".join(text.split())
        
        # Add natural pauses
        if ":" in text:
            text = text.replace(":", "...")
        
        return text
