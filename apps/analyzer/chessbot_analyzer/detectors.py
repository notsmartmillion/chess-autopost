# chessbot_analyzer/detectors.py
from __future__ import annotations

import typing as t
import chess


def _sign(x: int) -> int:
    return (x > 0) - (x < 0)


def _square_step(start: int, df: int, dr: int) -> int | None:
    """
    Step one square from `start` by file delta df and rank delta dr.
    Returns new square or None if off-board.
    """
    f = chess.square_file(start) + df
    r = chess.square_rank(start) + dr
    if 0 <= f <= 7 and 0 <= r <= 7:
        return chess.square(f, r)
    return None


def _unit_direction(a: int, b: int) -> tuple[int, int] | None:
    """
    If a->b are aligned on a rook or bishop ray, return unit step (df, dr).
    Else return None.
    """
    df = chess.square_file(b) - chess.square_file(a)
    dr = chess.square_rank(b) - chess.square_rank(a)
    if df == 0 and dr == 0:
        return None
    # rook directions
    if df == 0:
        return (0, _sign(dr))
    if dr == 0:
        return (_sign(df), 0)
    # bishop directions
    if abs(df) == abs(dr):
        return (_sign(df), _sign(dr))
    return None


def _first_piece_along(board: chess.Board, start: int, df: int, dr: int) -> int | None:
    """
    From `start`, walk in step (df,dr) until a piece is found or board edge.
    Returns that square or None if none found.
    """
    sq = start
    while True:
        sq = _square_step(sq, df, dr)
        if sq is None:
            return None
        if board.piece_at(sq):
            return sq


def _is_valid_pin_attacker(piece: chess.Piece, df: int, dr: int) -> bool:
    """
    Given the direction from king -> pinned piece, determine what attacker type is valid
    (rook/queen for orthogonal; bishop/queen for diagonal).
    We don't check color here; just sliding type suitability.
    """
    if df == 0 or dr == 0:
        # rook/queen
        return piece.piece_type in (chess.ROOK, chess.QUEEN)
    # diagonal
    return piece.piece_type in (chess.BISHOP, chess.QUEEN)


def _ray_squares_exclusive(board: chess.Board, attacker: int, king: int) -> list[str]:
    """
    Squares strictly between attacker and king, moving from the attacker towards the king.
    (Used to draw a neat path; you'll typically include these plus the king.)
    """
    step = _unit_direction(attacker, king)
    if step is None:
        return []
    df, dr = step
    cur = attacker
    ray: list[str] = []
    while True:
        cur = _square_step(cur, df, dr)
        if cur is None or cur == king:
            break
        ray.append(chess.square_name(cur))
    return ray


class FeatureDetectors:
    @staticmethod
    def compute_pins(board: chess.Board) -> list[dict[str, t.Any]]:
        """
        Return full pin descriptors for the side to move *and* the opponent:
          [
            {
              "sq": "e3",                # pinned piece square
              "attacker": "c5",          # enemy sliding piece delivering the pin
              "king": "g1",              # king of the pinned piece
              "ray": ["d4","e3","f2","g1"]  # path from just in front of attacker to the king (inclusive of pin+king, exclusive of attacker)
            },
            ...
          ]
        Notes:
        - We rely on board.is_pinned(color, sq) to find pinned pieces.
        - Then we walk *away from the king* to locate the first enemy sliding piece on that line.
        """
        pins: list[dict[str, t.Any]] = []

        for color in (chess.WHITE, chess.BLACK):
            king_sq = board.king(color)
            if king_sq is None:
                continue

            # Scan all own pieces; identify ones flagged as pinned by python-chess.
            for sq in chess.SQUARES:
                piece = board.piece_at(sq)
                if not piece or piece.color != color:
                    continue
                if not board.is_pinned(color, sq):
                    continue

                # Determine the unit direction from king -> pinned piece.
                step = _unit_direction(king_sq, sq)
                if step is None:
                    # Shouldn't happen for a true pin, but be defensive.
                    pins.append({"sq": chess.square_name(sq), "king": chess.square_name(king_sq)})
                    continue
                df, dr = step

                # Search from the pinned piece outward *away from the king* to find the attacker.
                attacker_sq = _first_piece_along(board, sq, df, dr)
                if attacker_sq is None:
                    pins.append({"sq": chess.square_name(sq), "king": chess.square_name(king_sq)})
                    continue

                attacker_piece = board.piece_at(attacker_sq)
                if (
                    attacker_piece
                    and attacker_piece.color != color
                    and _is_valid_pin_attacker(attacker_piece, df, dr)
                ):
                    # Build ray from attacker towards the king (exclusive of attacker, inclusive through king).
                    ray_between = _ray_squares_exclusive(board, attacker_sq, king_sq)
                    # Ensure the pinned square and king are included (renderer expects them).
                    if chess.square_name(sq) not in ray_between:
                        # Insert it in the correct place if python-chess returned a weird alignment (very unlikely)
                        # By construction, the pinned square lies on this ray.
                        pass
                    ray_full = ray_between + [chess.square_name(king_sq)]

                    pins.append(
                        {
                            "sq": chess.square_name(sq),
                            "attacker": chess.square_name(attacker_sq),
                            "king": chess.square_name(king_sq),
                            "ray": ray_full,
                        }
                    )
                else:
                    # Fallback minimal info if something is off.
                    pins.append({"sq": chess.square_name(sq), "king": chess.square_name(king_sq)})

        return pins

    @staticmethod
    def attacked_squares(board: chess.Board) -> dict[str, list[str]]:
        """
        Squares currently attacked by each side, as algebraic strings.
        Useful for heatmaps/overlays.
        """
        return {
            "white": [
                chess.square_name(s)
                for s in chess.SQUARES
                if board.is_attacked_by(chess.WHITE, s)
            ],
            "black": [
                chess.square_name(s)
                for s in chess.SQUARES
                if board.is_attacked_by(chess.BLACK, s)
            ],
        }
