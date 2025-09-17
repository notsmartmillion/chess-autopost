"""
Audio alignment system for word-level synchronization with chess moves.
Uses whisperX for forced alignment to get precise word timestamps.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import whisperx
import torch
import logging

logger = logging.getLogger(__name__)


class AudioAligner:
    """Forced alignment system for precise word-level timing."""
    
    def __init__(self, model_name: str = "base", device: str = "auto"):
        """
        Initialize the aligner with a Whisper model.
        
        Args:
            model_name: Whisper model size (tiny, base, small, medium, large)
            device: Device to use (auto, cpu, cuda)
        """
        self.model_name = model_name
        self.device = device if device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.align_model = None
        self.align_metadata = None
        
    def load_models(self):
        """Load Whisper and alignment models."""
        if self.model is None:
            logger.info(f"Loading Whisper model: {self.model_name}")
            self.model = whisperx.load_model(self.model_name, device=self.device)
            
        if self.align_model is None:
            logger.info("Loading alignment model")
            self.align_model, self.align_metadata = whisperx.load_align_model(
                language_code="en", device=self.device
            )
    
    def align_audio(self, audio_path: str, text: str) -> List[Dict]:
        """
        Align audio with text to get word-level timestamps.
        
        Args:
            audio_path: Path to audio file
            text: Text to align with
            
        Returns:
            List of word dictionaries with start, end, word, confidence
        """
        self.load_models()
        
        try:
            # Transcribe audio
            logger.info(f"Transcribing audio: {audio_path}")
            result = self.model.transcribe(audio_path)
            
            # Align with text
            logger.info("Aligning transcription with text")
            aligned_result = whisperx.align(
                result["segments"], 
                self.align_model, 
                self.align_metadata, 
                audio_path, 
                self.device
            )
            
            # Extract word-level timestamps
            words = []
            for segment in aligned_result["segments"]:
                for word_info in segment.get("words", []):
                    words.append({
                        "word": word_info["word"].strip(),
                        "start": word_info["start"],
                        "end": word_info["end"],
                        "confidence": word_info.get("score", 0.0)
                    })
            
            logger.info(f"Aligned {len(words)} words")
            return words
            
        except Exception as e:
            logger.error(f"Alignment failed for {audio_path}: {e}")
            return []
    
    def extract_keywords(self, words: List[Dict], keywords: List[str]) -> Dict[str, float]:
        """
        Extract timestamps for specific keywords.
        
        Args:
            words: List of aligned words
            keywords: Keywords to find timestamps for
            
        Returns:
            Dictionary mapping keywords to start times
        """
        keyword_times = {}
        
        for word_info in words:
            word = word_info["word"].lower().strip(".,!?")
            
            # Check for exact matches
            if word in [kw.lower() for kw in keywords]:
                keyword_times[word] = word_info["start"]
                continue
            
            # Check for partial matches (e.g., "pinned" in "unpinned")
            for keyword in keywords:
                if keyword.lower() in word:
                    keyword_times[keyword.lower()] = word_info["start"]
                    break
        
        return keyword_times
    
    def align_scene(self, scene_id: str, audio_path: str, text: str, 
                   keywords: Optional[List[str]] = None) -> Dict:
        """
        Align a single scene's audio with its text.
        
        Args:
            scene_id: Scene identifier
            audio_path: Path to audio file
            text: Scene text
            keywords: Keywords to extract timestamps for
            
        Returns:
            Dictionary with alignment data
        """
        if not Path(audio_path).exists():
            logger.warning(f"Audio file not found: {audio_path}")
            return {"scene_id": scene_id, "words": [], "keywords": {}}
        
        words = self.align_audio(audio_path, text)
        
        result = {
            "scene_id": scene_id,
            "words": words,
            "keywords": {}
        }
        
        if keywords:
            result["keywords"] = self.extract_keywords(words, keywords)
        
        return result


def align_voice_lines(lines_file: str, audio_dir: str, output_file: str, 
                     keywords: Optional[List[str]] = None):
    """
    Align all voice lines and save results.
    
    Args:
        lines_file: JSON file with voice lines
        audio_dir: Directory containing audio files
        output_file: Output file for alignment data
        keywords: Keywords to extract timestamps for
    """
    aligner = AudioAligner()
    
    # Load voice lines
    with open(lines_file, 'r') as f:
        lines = json.load(f)
    
    alignments = {}
    
    for line in lines:
        scene_id = line["id"]
        text = line["text"]
        audio_path = Path(audio_dir) / f"{scene_id}.wav"
        
        logger.info(f"Aligning scene: {scene_id}")
        alignment = aligner.align_scene(scene_id, str(audio_path), text, keywords)
        alignments[scene_id] = alignment
    
    # Save alignment data
    with open(output_file, 'w') as f:
        json.dump(alignments, f, indent=2)
    
    logger.info(f"Alignment data saved to: {output_file}")


def get_chess_keywords() -> List[str]:
    """Get common chess keywords for alignment."""
    return [
        "pin", "pinned", "pins",
        "fork", "forks", "forked",
        "skewer", "skewers", "skewered",
        "sacrifice", "sacrifices", "sacrificed",
        "check", "checkmate", "mate",
        "capture", "captures", "captured", "takes",
        "castle", "castles", "castling",
        "promotion", "promotes", "promoted",
        "discovered", "discovery",
        "double", "triple",
        "attack", "attacks", "attacking",
        "defend", "defends", "defending",
        "threat", "threats", "threatening",
        "tactic", "tactics", "tactical",
        "strategy", "strategic",
        "opening", "middlegame", "endgame",
        "advantage", "disadvantage",
        "equal", "position",
        "best", "better", "worse", "worst",
        "brilliant", "excellent", "good",
        "blunder", "mistake", "inaccuracy",
        "white", "black",
        "king", "queen", "rook", "bishop", "knight", "pawn"
    ]


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Align voice lines with audio")
    parser.add_argument("--lines", required=True, help="Voice lines JSON file")
    parser.add_argument("--audio-dir", required=True, help="Audio directory")
    parser.add_argument("--output", required=True, help="Output alignment file")
    parser.add_argument("--keywords", nargs="*", help="Keywords to extract")
    parser.add_argument("--model", default="base", help="Whisper model size")
    
    args = parser.parse_args()
    
    keywords = args.keywords or get_chess_keywords()
    
    align_voice_lines(args.lines, args.audio_dir, args.output, keywords)
