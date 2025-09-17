"""FEN utilities and last move arrow helpers."""

import chess
from typing import Optional, Tuple, List


def get_last_move_arrow(board: chess.Board, move: chess.Move) -> Tuple[str, str]:
    """
    Get last move arrow coordinates from a move.
    
    Args:
        board: Chess position
        move: The move to get arrow for
        
    Returns:
        Tuple of (from_square, to_square) as algebraic notation
    """
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)
    return from_sq, to_sq


def san_to_uci(san: str, board: chess.Board) -> Optional[str]:
    """
    Convert SAN move to UCI format.
    
    Args:
        san: Standard Algebraic Notation move
        board: Current position
        
    Returns:
        UCI move string or None if invalid
    """
    try:
        move = board.parse_san(san)
        return move.uci()
    except ValueError:
        return None


def uci_to_san(uci: str, board: chess.Board) -> Optional[str]:
    """
    Convert UCI move to SAN format.
    
    Args:
        uci: UCI move string
        board: Current position
        
    Returns:
        SAN move string or None if invalid
    """
    try:
        move = chess.Move.from_uci(uci)
        if move in board.legal_moves:
            return board.san(move)
    except ValueError:
        pass
    return None


def get_piece_at_square(fen: str, square: str) -> Optional[str]:
    """
    Get piece at specific square from FEN.
    
    Args:
        fen: FEN string
        square: Square in algebraic notation (e.g., "e4")
        
    Returns:
        Piece symbol or None
    """
    try:
        board = chess.Board(fen)
        sq = chess.parse_square(square)
        piece = board.piece_at(sq)
        return piece.symbol() if piece else None
    except (ValueError, AttributeError):
        return None


def is_check(fen: str) -> bool:
    """Check if position is in check."""
    try:
        board = chess.Board(fen)
        return board.is_check()
    except ValueError:
        return False


def is_checkmate(fen: str) -> bool:
    """Check if position is checkmate."""
    try:
        board = chess.Board(fen)
        return board.is_checkmate()
    except ValueError:
        return False


def is_stalemate(fen: str) -> bool:
    """Check if position is stalemate."""
    try:
        board = chess.Board(fen)
        return board.is_stalemate()
    except ValueError:
        return False


def get_legal_moves(fen: str) -> List[str]:
    """
    Get all legal moves in UCI format.
    
    Args:
        fen: FEN string
        
    Returns:
        List of UCI move strings
    """
    try:
        board = chess.Board(fen)
        return [move.uci() for move in board.legal_moves]
    except ValueError:
        return []


def get_legal_moves_san(fen: str) -> List[str]:
    """
    Get all legal moves in SAN format.
    
    Args:
        fen: FEN string
        
    Returns:
        List of SAN move strings
    """
    try:
        board = chess.Board(fen)
        return [board.san(move) for move in board.legal_moves]
    except ValueError:
        return []


def get_turn_color(fen: str) -> Optional[str]:
    """
    Get whose turn it is from FEN.
    
    Args:
        fen: FEN string
        
    Returns:
        "white" or "black" or None if invalid FEN
    """
    try:
        board = chess.Board(fen)
        return "white" if board.turn else "black"
    except ValueError:
        return None


def get_castling_rights(fen: str) -> dict:
    """
    Get castling rights from FEN.
    
    Args:
        fen: FEN string
        
    Returns:
        Dict with castling rights
    """
    try:
        board = chess.Board(fen)
        return {
            "white_kingside": board.has_kingside_castling_rights(chess.WHITE),
            "white_queenside": board.has_queenside_castling_rights(chess.WHITE),
            "black_kingside": board.has_kingside_castling_rights(chess.BLACK),
            "black_queenside": board.has_queenside_castling_rights(chess.BLACK)
        }
    except ValueError:
        return {
            "white_kingside": False,
            "white_queenside": False,
            "black_kingside": False,
            "black_queenside": False
        }
