"""Feature detection for chess positions: pins, attacks, move tags."""

import chess
from typing import List, Dict, Any, Optional, Tuple
from .utils.logging import get_logger

logger = get_logger(__name__)


class FeatureDetectors:
    """Static methods for detecting chess position features."""
    
    @staticmethod
    def compute_pins(board: chess.Board) -> List[Dict[str, Any]]:
        """
        Compute all pins in the position.
        
        Args:
            board: Chess position
            
        Returns:
            List of pin dictionaries with keys: sq, ray, attacker, king
        """
        pins = []
        
        # Check pins for both colors
        for color in [chess.WHITE, chess.BLACK]:
            king_square = board.king(color)
            if king_square is None:
                continue
                
            # Check each square for pins
            for square in chess.SQUARES:
                piece = board.piece_at(square)
                if piece is None or piece.color != color:
                    continue
                    
                if board.is_pinned(color, square):
                    # Find the pinning piece and ray
                    pinner, ray = FeatureDetectors._find_pin_details(board, square, king_square, color)
                    if pinner is not None:
                        pins.append({
                            "sq": chess.square_name(square),
                            "ray": [chess.square_name(sq) for sq in ray],
                            "attacker": chess.square_name(pinner),
                            "king": chess.square_name(king_square),
                            "color": "white" if color else "black"
                        })
        
        logger.debug(f"Found {len(pins)} pins in position")
        return pins
    
    @staticmethod
    def attacked_squares(board: chess.Board) -> Dict[str, List[str]]:
        """
        Compute all attacked squares by each color.
        
        Args:
            board: Chess position
            
        Returns:
            Dict with 'white' and 'black' keys containing lists of attacked squares
        """
        attacked = {"white": [], "black": []}
        
        for color in [chess.WHITE, chess.BLACK]:
            color_name = "white" if color else "black"
            
            for square in chess.SQUARES:
                if board.is_attacked_by(color, square):
                    attacked[color_name].append(chess.square_name(square))
        
        logger.debug(f"Attacked squares - White: {len(attacked['white'])}, Black: {len(attacked['black'])}")
        return attacked
    
    @staticmethod
    def tag_move(eval_before: int, eval_after: int) -> Optional[str]:
        """
        Tag a move based on evaluation change.
        
        Args:
            eval_before: Centipawn evaluation before move
            eval_after: Centipawn evaluation after move
            
        Returns:
            Move tag or None
        """
        eval_diff = eval_after - eval_before
        
        # Blunder thresholds (in centipawns)
        if abs(eval_diff) >= 300:  # 3 pawns
            return "blunder"
        elif abs(eval_diff) >= 200:  # 2 pawns
            return "mistake"
        elif abs(eval_diff) >= 100:  # 1 pawn
            return "inaccuracy"
        elif abs(eval_diff) >= 50:  # 0.5 pawns
            return "good"
        elif abs(eval_diff) >= 200 and eval_diff > 0:  # Large improvement
            return "brilliant"
        elif abs(eval_diff) >= 100 and eval_diff > 0:  # Good improvement
            return "excellent"
        
        return None
    
    @staticmethod
    def _find_pin_details(board: chess.Board, pinned_square: int, king_square: int, color: bool) -> Tuple[Optional[int], List[int]]:
        """
        Find the pinning piece and the ray between pinned piece and king.
        
        Args:
            board: Chess position
            pinned_square: Square of pinned piece
            king_square: Square of king
            pinned_color: Color of pinned piece
            
        Returns:
            Tuple of (pinning_square, ray_squares)
        """
        # Get direction from king to pinned piece
        king_file, king_rank = chess.square_file(king_square), chess.square_rank(king_square)
        pinned_file, pinned_rank = chess.square_file(pinned_square), chess.square_rank(pinned_square)
        
        file_diff = pinned_file - king_file
        rank_diff = pinned_rank - king_rank
        
        # Normalize direction
        if file_diff != 0:
            file_diff = file_diff // abs(file_diff)
        if rank_diff != 0:
            rank_diff = rank_diff // abs(rank_diff)
        
        # Search along the ray for the pinning piece
        ray = []
        current_file, current_rank = king_file + file_diff, king_rank + rank_diff
        
        while 0 <= current_file <= 7 and 0 <= current_rank <= 7:
            current_square = chess.square(current_file, current_rank)
            ray.append(current_square)
            
            piece = board.piece_at(current_square)
            if piece is not None:
                # Found a piece
                if piece.color != color:
                    # This is the pinning piece
                    return current_square, ray
                else:
                    # This is another piece of the same color, not a pin
                    return None, []
            
            current_file += file_diff
            current_rank += rank_diff
        
        return None, ray
    
    @staticmethod
    def detect_sacrifices(board: chess.Board, move: chess.Move, eval_before: int, eval_after: int) -> Optional[str]:
        """
        Detect if a move is a sacrifice based on material and evaluation.
        
        Args:
            board: Position before move
            move: The move played
            eval_before: Evaluation before move
            eval_after: Evaluation after move
            
        Returns:
            Sacrifice type or None
        """
        # Get piece values
        piece_values = {
            chess.PAWN: 100,
            chess.KNIGHT: 320,
            chess.BISHOP: 330,
            chess.ROOK: 500,
            chess.QUEEN: 900,
            chess.KING: 20000
        }
        
        moved_piece = board.piece_at(move.from_square)
        captured_piece = board.piece_at(move.to_square)
        
        if moved_piece is None:
            return None
        
        # Calculate material change
        material_lost = piece_values.get(moved_piece.piece_type, 0)
        material_gained = piece_values.get(captured_piece.piece_type, 0) if captured_piece else 0
        net_material = material_gained - material_lost
        
        # Check if it's a sacrifice (losing material but gaining positionally)
        if net_material < -100 and eval_after > eval_before + 200:
            if net_material <= -500:  # Queen or Rook sacrifice
                return "queen_sacrifice" if net_material <= -800 else "rook_sacrifice"
            elif net_material <= -300:  # Minor piece sacrifice
                return "minor_sacrifice"
            else:  # Pawn sacrifice
                return "pawn_sacrifice"
        
        return None
