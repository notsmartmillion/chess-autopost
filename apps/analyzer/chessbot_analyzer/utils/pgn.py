"""PGN utilities: read/write PGN, SAN↔UCI helpers."""

import chess
import chess.pgn
import hashlib
from typing import List, Dict, Any, Optional, Iterator
from pathlib import Path
from .logging import get_logger

logger = get_logger(__name__)


def read_pgn_file(file_path: str) -> Iterator[chess.pgn.Game]:
    """
    Read PGN file and yield games.
    
    Args:
        file_path: Path to PGN file
        
    Yields:
        Chess games from PGN file
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                yield game
    except Exception as e:
        logger.error(f"Failed to read PGN file {file_path}: {e}")
        raise


def write_pgn_file(games: List[chess.pgn.Game], file_path: str):
    """
    Write games to PGN file.
    
    Args:
        games: List of chess games
        file_path: Output file path
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            for game in games:
                print(game, file=f, end="\n\n")
        logger.info(f"Wrote {len(games)} games to {file_path}")
    except Exception as e:
        logger.error(f"Failed to write PGN file {file_path}: {e}")
        raise


def extract_game_metadata(game: chess.pgn.Game) -> Dict[str, Any]:
    """
    Extract metadata from PGN game.
    
    Args:
        game: Chess game object
        
    Returns:
        Dictionary with game metadata
    """
    headers = game.headers
    
    return {
        "white": headers.get("White", "Unknown"),
        "black": headers.get("Black", "Unknown"),
        "result": headers.get("Result", "*"),
        "date": headers.get("Date", ""),
        "event": headers.get("Event", ""),
        "site": headers.get("Site", ""),
        "eco": headers.get("ECO", ""),
        "ply_count": game.end().board().fullmove_number * 2 - (1 if game.end().board().turn == chess.WHITE else 0)
    }


def compute_moves_hash(game: chess.pgn.Game) -> str:
    """
    Compute hash for game moves to detect duplicates.
    
    Args:
        game: Chess game object
        
    Returns:
        MD5 hash of moves sequence
    """
    # Get moves in SAN format
    moves = []
    board = game.board()
    
    for move in game.mainline_moves():
        moves.append(board.san(move))
        board.push(move)
    
    # Create hash from moves sequence
    moves_str = " ".join(moves)
    return hashlib.md5(moves_str.encode()).hexdigest()


def get_game_moves_san(game: chess.pgn.Game) -> List[str]:
    """
    Get all moves in SAN format.
    
    Args:
        game: Chess game object
        
    Returns:
        List of SAN moves
    """
    moves = []
    board = game.board()
    
    for move in game.mainline_moves():
        moves.append(board.san(move))
        board.push(move)
    
    return moves


def get_game_moves_uci(game: chess.pgn.Game) -> List[str]:
    """
    Get all moves in UCI format.
    
    Args:
        game: Chess game object
        
    Returns:
        List of UCI moves
    """
    moves = []
    
    for move in game.mainline_moves():
        moves.append(move.uci())
    
    return moves


def get_position_after_move(game: chess.pgn.Game, move_number: int) -> Optional[chess.Board]:
    """
    Get position after specific move number.
    
    Args:
        game: Chess game object
        move_number: Move number (1-based)
        
    Returns:
        Board position or None if invalid move number
    """
    board = game.board()
    moves = list(game.mainline_moves())
    
    if move_number < 1 or move_number > len(moves):
        return None
    
    for i in range(move_number):
        board.push(moves[i])
    
    return board


def get_fen_after_move(game: chess.pgn.Game, move_number: int) -> Optional[str]:
    """
    Get FEN after specific move number.
    
    Args:
        game: Chess game object
        move_number: Move number (1-based)
        
    Returns:
        FEN string or None if invalid move number
    """
    board = get_position_after_move(game, move_number)
    return board.fen() if board else None


def validate_pgn_file(file_path: str) -> bool:
    """
    Validate PGN file format.
    
    Args:
        file_path: Path to PGN file
        
    Returns:
        True if valid PGN file
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Try to read first game
            game = chess.pgn.read_game(f)
            return game is not None
    except Exception:
        return False


def count_games_in_pgn(file_path: str) -> int:
    """
    Count number of games in PGN file.
    
    Args:
        file_path: Path to PGN file
        
    Returns:
        Number of games
    """
    count = 0
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            while True:
                game = chess.pgn.read_game(f)
                if game is None:
                    break
                count += 1
    except Exception as e:
        logger.error(f"Failed to count games in {file_path}: {e}")
        return 0
    
    return count
