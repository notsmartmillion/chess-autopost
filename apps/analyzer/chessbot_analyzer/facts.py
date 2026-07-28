"""Pass 1 of the chess video pipeline: engine-backed *fact extraction*.

This module walks a game exactly once with Stockfish and emits a rich,
JSON-serializable "fact sheet". It performs **no narration and no rendering** --
it only states what is objectively true about the game:

    * per-ply engine evaluations (always normalized to the **White** point of
      view so the eval never flips sign by side to move),
    * the engine's best move / principal variation and the runner-up
      alternatives from the position *before* each move,
    * a move-quality classification (book / brilliant / best / good /
      inaccuracy / mistake / blunder),
    * a generous bundle of positional features for every ply (pins, skewers,
      hanging pieces, forks, long slider rays, batteries, pawn structure,
      material, king safety, mobility, phase, center control),
    * short-horizon threats (forced mates, hanging material),
    * a ranked ``keyMoments`` list and a game-level ``summary``.

A later "Pass 2" narration/director stage consumes this dict to write
commentary and to place on-board highlights, so it can only ever talk about
what is extracted here -- hence the deliberately generous feature set.

Performance contract
--------------------
Each *position* is analysed exactly once. The walk analyses the position
**before** every move; the evaluation *after* move N is simply the evaluation
of the position before move N+1 (negated, because the side to move flips).
Only the final position costs one extra analysis (and even that is skipped when
the game ended in mate/stalemate).

Public API
----------
``extract_facts(pgn_text, ...) -> dict``
``save_facts(facts, path) -> None``
"""

from __future__ import annotations

import io
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import chess
import chess.pgn

from .config import settings
from .detectors import FeatureDetectors
from .utils.logging import get_logger

logger = get_logger(__name__)


__all__ = ["extract_facts", "save_facts"]


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Static piece values in centipawns (kings get a sentinel "infinite" value).
PIECE_VALUES: Dict[int, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}

#: Centipawn stand-in for "mate" when scores need to be compared numerically.
MATE_SCALE_CP = 3000

#: Thresholds (mover POV centipawn loss) for move quality.
BLUNDER_CP = 300
MISTAKE_CP = 150
INACCURACY_CP = 50

#: How much worse the 2nd best move has to be for a move to count as "only move".
ONLY_MOVE_CP = 150

#: Max number of plies kept in a stored principal variation.
PV_LIMIT = 10

CENTER_SQUARES: Tuple[int, ...] = (chess.D4, chess.D5, chess.E4, chess.E5)

_SAN_STRIP_RE = re.compile(r"[+#!?]+$")
_MOVE_NUMBER_RE = re.compile(r"\d+\s*\.(\.\.)?")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _safe(label: str, fn: Callable[[], Any], default: Any) -> Any:
    """Run ``fn`` and never let it break the run; log and fall back on error."""
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"facts: detector '{label}' failed: {exc}")
        return default


def _color_name(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def _piece_name(piece_type: Optional[int]) -> Optional[str]:
    if piece_type is None:
        return None
    return chess.piece_name(piece_type)


def _value_of(piece: Optional[chess.Piece]) -> int:
    if piece is None:
        return 0
    return PIECE_VALUES.get(piece.piece_type, 0)


def _sq(square: Optional[int]) -> Optional[str]:
    return None if square is None else chess.square_name(square)


def _score_pair(
    info: Optional[Dict[str, Any]], pov: chess.Color
) -> Tuple[Optional[int], Optional[int]]:
    """Normalize one engine info dict to ``(cp, mate)`` from ``pov``'s view.

    Accepts both the shape produced by :class:`~.engine.StockfishEngine`
    (``{"cp": ..., "mate": ...}``, already relative to the side to move) and a
    raw python-chess ``{"score": PovScore}`` entry.
    """
    if not info:
        return None, None
    if "cp" in info or "mate" in info:
        return info.get("cp"), info.get("mate")
    score = info.get("score")
    if score is None:
        return None, None
    mate = score.pov(pov).mate()
    if mate is not None:
        return None, int(mate)
    cp = score.pov(pov).score(mate_score=100000)
    return (int(cp) if cp is not None else None), None


def _to_white(
    cp: Optional[int], mate: Optional[int], turn: chess.Color
) -> Tuple[Optional[int], Optional[int]]:
    """Flip a side-to-move relative ``(cp, mate)`` pair into White's POV."""
    if turn == chess.WHITE:
        return cp, mate
    return (None if cp is None else -cp), (None if mate is None else -mate)


def _scale(cp: Optional[int], mate: Optional[int]) -> Optional[int]:
    """Collapse ``(cp, mate)`` into a single comparable centipawn number."""
    if mate is not None:
        if mate == 0:
            # Side to move is already checkmated.
            return -MATE_SCALE_CP
        sign = 1 if mate > 0 else -1
        return sign * max(MATE_SCALE_CP - (abs(mate) * 10), MATE_SCALE_CP // 2)
    if cp is None:
        return None
    return max(-MATE_SCALE_CP, min(MATE_SCALE_CP, int(cp)))


def _san_line(board: chess.Board, moves: Sequence[chess.Move], limit: int = PV_LIMIT) -> List[str]:
    """Render a move sequence as SAN from ``board``; stops at the first bad move."""
    out: List[str] = []
    tmp = board.copy(stack=False)
    for mv in list(moves)[:limit]:
        try:
            if mv not in tmp.legal_moves:
                break
            out.append(tmp.san(mv))
            tmp.push(mv)
        except Exception:  # pragma: no cover - defensive
            break
    return out


def _uci_line(moves: Sequence[chess.Move], limit: int = PV_LIMIT) -> List[str]:
    return [m.uci() for m in list(moves)[:limit]]


def _pretty_eval(cp: Optional[int], mate: Optional[int]) -> str:
    """Human-readable White-POV evaluation, e.g. ``+1.2`` or ``#-3``."""
    if mate is not None:
        return f"#{'+' if mate > 0 else '-'}{abs(mate)}"
    if cp is None:
        return "?"
    return f"{cp / 100.0:+.1f}"


# --------------------------------------------------------------------------- #
# Geometry helpers (rays)
# --------------------------------------------------------------------------- #

_ROOK_DIRS: Tuple[Tuple[int, int], ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))
_BISHOP_DIRS: Tuple[Tuple[int, int], ...] = ((1, 1), (1, -1), (-1, 1), (-1, -1))
_QUEEN_DIRS: Tuple[Tuple[int, int], ...] = _ROOK_DIRS + _BISHOP_DIRS


def _dirs_for(piece_type: int) -> Tuple[Tuple[int, int], ...]:
    if piece_type == chess.ROOK:
        return _ROOK_DIRS
    if piece_type == chess.BISHOP:
        return _BISHOP_DIRS
    if piece_type == chess.QUEEN:
        return _QUEEN_DIRS
    return ()


def _ray_to_edge(square: int, df: int, dr: int) -> List[int]:
    """All squares from ``square`` (exclusive) to the board edge along (df, dr)."""
    out: List[int] = []
    f, r = chess.square_file(square), chess.square_rank(square)
    while True:
        f += df
        r += dr
        if not (0 <= f <= 7 and 0 <= r <= 7):
            return out
        out.append(chess.square(f, r))


def _line_label(a: int, b: int) -> str:
    if chess.square_file(a) == chess.square_file(b):
        return f"{chess.FILE_NAMES[chess.square_file(a)]}-file"
    if chess.square_rank(a) == chess.square_rank(b):
        return f"rank {chess.square_rank(a) + 1}"
    return "diagonal"


# --------------------------------------------------------------------------- #
# Feature detectors
# --------------------------------------------------------------------------- #


def _detect_pins(board: chess.Board) -> List[Dict[str, Any]]:
    """Absolute pins (piece shielding its own king), enriched with piece types."""
    out: List[Dict[str, Any]] = []
    for raw in FeatureDetectors.compute_pins(board):
        sq_name = raw.get("sq")
        if not sq_name:
            continue
        pinned_sq = chess.parse_square(sq_name)
        pinned_piece = board.piece_at(pinned_sq)
        attacker_name = raw.get("attacker")
        attacker_piece = (
            board.piece_at(chess.parse_square(attacker_name)) if attacker_name else None
        )
        out.append(
            {
                "pinned": sq_name,
                "attacker": attacker_name,
                "king": raw.get("king"),
                "ray": list(raw.get("ray", [])),
                "color": _color_name(pinned_piece.color) if pinned_piece else None,
                "pinnedPiece": _piece_name(pinned_piece.piece_type) if pinned_piece else None,
                "attackerPiece": (
                    _piece_name(attacker_piece.piece_type) if attacker_piece else None
                ),
            }
        )
    return out


def _detect_skewers(board: chess.Board) -> List[Dict[str, Any]]:
    """Skewers: a slider hits a valuable enemy piece with a lesser one behind it.

    Shape mirrors :func:`_detect_pins` (``pinned`` = the front piece, ``king`` =
    the square of the piece behind it) with two extra keys, ``behind`` and
    ``behindPiece``, so consumers do not have to guess.
    """
    out: List[Dict[str, Any]] = []
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        for df, dr in _dirs_for(piece.piece_type):
            ray = _ray_to_edge(square, df, dr)
            front_idx: Optional[int] = None
            front_piece: Optional[chess.Piece] = None
            for idx, sq in enumerate(ray):
                p = board.piece_at(sq)
                if p is not None:
                    front_idx, front_piece = idx, p
                    break
            if front_piece is None or front_piece.color == piece.color:
                continue
            back_piece = None
            back_sq = None
            for sq in ray[front_idx + 1 :]:
                p = board.piece_at(sq)
                if p is not None:
                    back_piece, back_sq = p, sq
                    break
            if back_piece is None or back_piece.color == piece.color:
                continue
            if _value_of(front_piece) <= _value_of(back_piece):
                continue
            if back_piece.piece_type == chess.KING:
                # King behind == pin, already reported by _detect_pins.
                continue
            path = [chess.square_name(s) for s in ray[: ray.index(back_sq) + 1]]
            out.append(
                {
                    "pinned": chess.square_name(ray[front_idx]),
                    "attacker": chess.square_name(square),
                    "king": chess.square_name(back_sq),
                    "behind": chess.square_name(back_sq),
                    "ray": path,
                    "color": _color_name(front_piece.color),
                    "pinnedPiece": _piece_name(front_piece.piece_type),
                    "behindPiece": _piece_name(back_piece.piece_type),
                    "attackerPiece": _piece_name(piece.piece_type),
                }
            )
    return out


def _exchange_verdict(board: chess.Board, square: int) -> Optional[Dict[str, Any]]:
    """Cheap static-exchange style verdict for the piece standing on ``square``.

    Returns ``None`` when the piece looks safe, otherwise a dict with the
    attacker / defender squares and the piece value at risk.
    """
    piece = board.piece_at(square)
    if piece is None or piece.piece_type == chess.KING:
        return None
    attackers = list(board.attackers(not piece.color, square))
    if not attackers:
        return None
    defenders = list(board.attackers(piece.color, square))
    value = _value_of(piece)
    least_attacker = min(_value_of(board.piece_at(a)) for a in attackers)
    at_risk = (not defenders) or (least_attacker < value) or (len(attackers) > len(defenders))
    if not at_risk:
        return None
    return {
        "square": chess.square_name(square),
        "piece": _piece_name(piece.piece_type),
        "color": _color_name(piece.color),
        "attackers": sorted(chess.square_name(a) for a in attackers),
        "defenders": sorted(chess.square_name(d) for d in defenders),
        "value": value,
    }


def _detect_hanging(board: chess.Board) -> List[Dict[str, Any]]:
    """Pieces that are attacked more than they are defended (or by a cheaper piece)."""
    out: List[Dict[str, Any]] = []
    for square in chess.SQUARES:
        verdict = _exchange_verdict(board, square)
        if verdict is not None:
            out.append(verdict)
    return out


def _detect_forks(board: chess.Board) -> List[Dict[str, Any]]:
    """A piece simultaneously attacking 2+ enemy pieces worth a knight or more."""
    out: List[Dict[str, Any]] = []
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None:
            continue
        targets: List[Dict[str, Any]] = []
        for target_sq in board.attacks(square):
            victim = board.piece_at(target_sq)
            if victim is None or victim.color == piece.color:
                continue
            if victim.piece_type == chess.KING or _value_of(victim) >= PIECE_VALUES[chess.KNIGHT]:
                targets.append(
                    {
                        "square": chess.square_name(target_sq),
                        "piece": _piece_name(victim.piece_type),
                    }
                )
        if len(targets) >= 2:
            out.append(
                {
                    "square": chess.square_name(square),
                    "piece": _piece_name(piece.piece_type),
                    "color": _color_name(piece.color),
                    "targets": sorted(targets, key=lambda t: t["square"]),
                }
            )
    return out


def _detect_long_rays(board: chess.Board, min_length: int = 3) -> List[Dict[str, Any]]:
    """Long lines controlled by bishops / rooks / queens.

    ``ray`` is the full geometric line from the slider to the board edge,
    ``hits`` holds the first *enemy* piece standing on it (empty when a friendly
    piece blocks first), and ``open`` says whether the line is free of our own
    men up to that point.
    """
    out: List[Dict[str, Any]] = []
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        for df, dr in _dirs_for(piece.piece_type):
            ray = _ray_to_edge(square, df, dr)
            if len(ray) < min_length:
                continue
            hits: List[Dict[str, Any]] = []
            open_line = True
            for sq in ray:
                blocker = board.piece_at(sq)
                if blocker is None:
                    continue
                if blocker.color == piece.color:
                    open_line = False
                else:
                    hits.append(
                        {
                            "square": chess.square_name(sq),
                            "piece": _piece_name(blocker.piece_type),
                            "color": _color_name(blocker.color),
                        }
                    )
                break
            out.append(
                {
                    "from": chess.square_name(square),
                    "piece": _piece_name(piece.piece_type),
                    "color": _color_name(piece.color),
                    "ray": [chess.square_name(s) for s in ray],
                    "hits": hits,
                    "length": len(ray),
                    "open": open_line,
                }
            )
    return out


def _detect_batteries(board: chess.Board) -> List[Dict[str, Any]]:
    """Two friendly sliders stacked on the same file / rank / diagonal."""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            continue
        for df, dr in _dirs_for(piece.piece_type):
            for sq in _ray_to_edge(square, df, dr):
                other = board.piece_at(sq)
                if other is None:
                    continue
                if (
                    other.color == piece.color
                    and other.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN)
                    and (df, dr) in _dirs_for(other.piece_type)
                ):
                    key = (min(square, sq), max(square, sq))
                    if key not in seen:
                        seen.add(key)
                        first, second = key
                        out.append(
                            {
                                "squares": [chess.square_name(first), chess.square_name(second)],
                                "pieces": [
                                    _piece_name(board.piece_at(first).piece_type),
                                    _piece_name(board.piece_at(second).piece_type),
                                ],
                                "color": _color_name(piece.color),
                                "line": _line_label(first, second),
                            }
                        )
                break
    return out


def _pawn_structure(board: chess.Board) -> Dict[str, Dict[str, List[str]]]:
    """Isolated / doubled / passed / backward pawns for both sides."""
    result: Dict[str, Dict[str, List[str]]] = {
        "isolated": {"white": [], "black": []},
        "doubled": {"white": [], "black": []},
        "passed": {"white": [], "black": []},
        "backward": {"white": [], "black": []},
    }
    pawns = {
        chess.WHITE: sorted(board.pieces(chess.PAWN, chess.WHITE)),
        chess.BLACK: sorted(board.pieces(chess.PAWN, chess.BLACK)),
    }
    for color in (chess.WHITE, chess.BLACK):
        cname = _color_name(color)
        own = pawns[color]
        enemy = pawns[not color]
        own_files = [chess.square_file(s) for s in own]
        forward = 1 if color == chess.WHITE else -1
        for sq in own:
            f, r = chess.square_file(sq), chess.square_rank(sq)
            name = chess.square_name(sq)

            if own_files.count(f) > 1:
                result["doubled"][cname].append(name)

            if not any(abs(of - f) == 1 for of in own_files):
                result["isolated"][cname].append(name)

            blocked = False
            for esq in enemy:
                ef, er = chess.square_file(esq), chess.square_rank(esq)
                if abs(ef - f) <= 1 and ((er - r) * forward) > 0:
                    blocked = True
                    break
            if not blocked:
                result["passed"][cname].append(name)

            # Backward: no friendly pawn on an adjacent file at or behind us, and
            # the square in front is covered by an enemy pawn.
            neighbours = [s for s in own if abs(chess.square_file(s) - f) == 1]
            behind_ok = all(((chess.square_rank(s) - r) * forward) > 0 for s in neighbours)
            if neighbours and behind_ok:
                ahead_rank = r + forward
                if 0 <= ahead_rank <= 7:
                    ahead = chess.square(f, ahead_rank)
                    enemy_pawn_cover = any(
                        board.piece_at(a) is not None
                        and board.piece_at(a).piece_type == chess.PAWN
                        and board.piece_at(a).color != color
                        for a in board.attackers(not color, ahead)
                    )
                    if enemy_pawn_cover:
                        result["backward"][cname].append(name)
    return result


def _material(board: chess.Board) -> Dict[str, Any]:
    """Per-side piece counts, pawn-unit balance and exchange-up flags."""
    counts: Dict[str, Dict[str, int]] = {}
    totals: Dict[chess.Color, int] = {}
    for color in (chess.WHITE, chess.BLACK):
        c: Dict[str, int] = {}
        total = 0
        for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING):
            n = len(board.pieces(pt, color))
            c[chess.piece_name(pt)] = n
            if pt != chess.KING:
                total += n * PIECE_VALUES[pt]
        counts[_color_name(color)] = c
        totals[color] = total

    w, b = counts["white"], counts["black"]
    w_minors = w["knight"] + w["bishop"]
    b_minors = b["knight"] + b["bishop"]
    return {
        "white": w,
        "black": b,
        "balancePawns": round((totals[chess.WHITE] - totals[chess.BLACK]) / 100.0, 2),
        "whiteIsUpExchange": bool(w["rook"] > b["rook"] and w_minors < b_minors),
        "blackIsUpExchange": bool(b["rook"] > w["rook"] and b_minors < w_minors),
    }


def _bishop_pair(board: chess.Board) -> Optional[str]:
    """Which side (if any) uniquely owns the bishop pair."""
    w = len(board.pieces(chess.BISHOP, chess.WHITE)) >= 2
    b = len(board.pieces(chess.BISHOP, chess.BLACK)) >= 2
    if w and not b:
        return "white"
    if b and not w:
        return "black"
    return None


def _king_safety(board: chess.Board, castled: Dict[str, bool]) -> Dict[str, Dict[str, Any]]:
    """Castling status, pawn shield size and enemy pressure near each king."""
    out: Dict[str, Dict[str, Any]] = {}
    for color in (chess.WHITE, chess.BLACK):
        cname = _color_name(color)
        king_sq = board.king(color)
        if king_sq is None:
            out[cname] = {"castled": castled.get(cname, False), "shieldPawns": 0, "attackersNearKing": 0}
            continue
        kf, kr = chess.square_file(king_sq), chess.square_rank(king_sq)
        forward = 1 if color == chess.WHITE else -1

        shield = 0
        for df in (-1, 0, 1):
            f = kf + df
            if not (0 <= f <= 7):
                continue
            for step in (1, 2):
                r = kr + forward * step
                if not (0 <= r <= 7):
                    continue
                p = board.piece_at(chess.square(f, r))
                if p is not None and p.piece_type == chess.PAWN and p.color == color:
                    shield += 1
                    break

        zone = [king_sq] + list(chess.SquareSet(chess.BB_KING_ATTACKS[king_sq]))
        attackers: set = set()
        for sq in zone:
            attackers |= set(board.attackers(not color, sq))

        out[cname] = {
            "castled": bool(castled.get(cname, False)),
            "kingSquare": chess.square_name(king_sq),
            "shieldPawns": shield,
            "attackersNearKing": len(attackers),
        }
    return out


def _mobility(board: chess.Board) -> Dict[str, int]:
    """Legal move counts for both sides (null-move trick for the idle side)."""
    stm = board.turn
    counts = {_color_name(stm): board.legal_moves.count()}
    other = not stm
    try:
        tmp = board.copy(stack=False)
        tmp.push(chess.Move.null())
        counts[_color_name(other)] = tmp.legal_moves.count()
    except Exception:  # pragma: no cover - defensive
        counts[_color_name(other)] = 0
    return {"white": counts.get("white", 0), "black": counts.get("black", 0)}


def _phase(board: chess.Board, ply: int) -> str:
    """Coarse game phase from remaining non-pawn material plus the ply count."""
    npm = 0
    queens = 0
    for color in (chess.WHITE, chess.BLACK):
        for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            n = len(board.pieces(pt, color))
            npm += n * PIECE_VALUES[pt]
            if pt == chess.QUEEN:
                queens += n
    if npm <= 1600 or (queens == 0 and npm <= 3200):
        return "endgame"
    if ply <= 20 and npm >= 5600:
        return "opening"
    return "middlegame"


def _center_control(board: chess.Board) -> Dict[str, int]:
    """How many attacks each side has on d4/d5/e4/e5."""
    return {
        "white": sum(len(board.attackers(chess.WHITE, s)) for s in CENTER_SQUARES),
        "black": sum(len(board.attackers(chess.BLACK, s)) for s in CENTER_SQUARES),
    }


def _detect_check_evasions(board: chess.Board) -> Optional[Dict[str, Any]]:
    """How the side to move may answer a check — ``None`` when not in check.

    Narration loves to assert that a king "cannot block" or "must move", and
    those claims are cheap to get wrong by eye. Enumerating the legal replies
    here means the commentary can state the fact instead of guessing at it.
    """
    if not board.is_check():
        return None

    king = board.king(board.turn)
    king_moves: List[str] = []
    blocks: List[str] = []
    captures: List[str] = []
    for move in board.legal_moves:
        san = board.san(move)
        if move.from_square == king:
            king_moves.append(san)
        elif board.is_capture(move):
            captures.append(san)
        else:
            blocks.append(san)

    return {
        "kingMoves": king_moves,
        "blocks": blocks,
        "captures": captures,
        "canBlock": bool(blocks),
        "canCapture": bool(captures),
        "onlyKingMoves": not blocks and not captures,
        "isDouble": len(board.checkers()) > 1,
        "isMate": board.is_checkmate(),
    }


def _compute_features(
    board: chess.Board, *, ply: int, castled: Dict[str, bool]
) -> Dict[str, Any]:
    """Bundle every positional detector for a single position.

    Every detector is individually guarded: a failure yields an empty value for
    that key and a logged warning instead of killing the whole run.
    """
    return {
        "pins": _safe("pins", lambda: _detect_pins(board), []),
        "skewers": _safe("skewers", lambda: _detect_skewers(board), []),
        "hanging": _safe("hanging", lambda: _detect_hanging(board), []),
        "forks": _safe("forks", lambda: _detect_forks(board), []),
        "longRays": _safe("longRays", lambda: _detect_long_rays(board), []),
        "batteries": _safe("batteries", lambda: _detect_batteries(board), []),
        "checkSquare": _safe(
            "checkSquare",
            lambda: (_sq(board.king(board.turn)) if board.is_check() else None),
            None,
        ),
        "checkEvasions": _safe(
            "checkEvasions", lambda: _detect_check_evasions(board), None
        ),
        "pawnStructure": _safe("pawnStructure", lambda: _pawn_structure(board), {}),
        "material": _safe("material", lambda: _material(board), {}),
        "bishopPair": _safe("bishopPair", lambda: _bishop_pair(board), None),
        "kingSafety": _safe("kingSafety", lambda: _king_safety(board, castled), {}),
        "mobility": _safe("mobility", lambda: _mobility(board), {"white": 0, "black": 0}),
        "phase": _safe("phase", lambda: _phase(board, ply), "middlegame"),
        "centerControl": _safe("centerControl", lambda: _center_control(board), {}),
        "attacked": _safe(
            "attacked",
            lambda: FeatureDetectors.attacked_squares(board),
            {"white": [], "black": []},
        ),
    }


# --------------------------------------------------------------------------- #
# Threats
# --------------------------------------------------------------------------- #


def _compute_threats(
    board_after: chess.Board,
    infos_after: Optional[List[Dict[str, Any]]],
    features_after: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """What is looming in the position *after* the move (mates, loose material)."""
    threats: List[Dict[str, Any]] = []
    stm = board_after.turn

    if infos_after:
        _cp, mate = _score_pair(infos_after[0], stm)
        if mate is not None and mate != 0:
            mating_side = stm if mate > 0 else (not stm)
            threats.append(
                {
                    "type": "mate",
                    "in": abs(int(mate)),
                    "forSide": _color_name(mating_side),
                    "lineSan": _san_line(board_after, infos_after[0].get("pv") or [], limit=8),
                }
            )

    # Loose enemy material for whoever is on move.
    hanging = features_after.get("hanging") or []
    loose = [
        h
        for h in hanging
        if h.get("color") == _color_name(not stm) and int(h.get("value", 0)) >= PIECE_VALUES[chess.PAWN]
    ]
    loose.sort(key=lambda h: -int(h.get("value", 0)))
    for h in loose[:2]:
        threats.append(
            {
                "type": "win_material",
                "square": h.get("square"),
                "gain": int(h.get("value", 0)),
                "forSide": _color_name(stm),
            }
        )
    return threats


# --------------------------------------------------------------------------- #
# Sacrifice / quality classification
# --------------------------------------------------------------------------- #


def _is_sacrifice(
    board_before: chess.Board,
    move: chess.Move,
    board_after: chess.Board,
    cp_loss: Optional[int],
) -> bool:
    """True when the mover deliberately parts with material without losing eval.

    Heuristic: the moved piece lands where a cheaper enemy piece (or a superior
    attacker count) can take it, the immediate material gain does not cover the
    exposure, and the engine evaluation does not fall apart.
    """
    try:
        moved = board_before.piece_at(move.from_square)
        if moved is None or moved.piece_type == chess.KING:
            return False

        gain = 0
        if board_before.is_capture(move):
            if board_before.is_en_passant(move):
                gain = PIECE_VALUES[chess.PAWN]
            else:
                gain = _value_of(board_before.piece_at(move.to_square))

        verdict = _exchange_verdict(board_after, move.to_square)
        if verdict is None:
            return False

        landed = board_after.piece_at(move.to_square)
        risk = _value_of(landed)
        if risk - gain < PIECE_VALUES[chess.PAWN]:
            return False

        # A sacrifice implies compensation: the eval must hold up.
        if cp_loss is not None and cp_loss >= MISTAKE_CP:
            return False
        return True
    except Exception:  # pragma: no cover - defensive
        return False


def _classify_quality(
    *,
    ply: int,
    in_book: bool,
    cp_loss: Optional[int],
    played_best: bool,
    only_move: bool,
    is_sacrifice: bool,
) -> str:
    """Map cp loss / engine agreement onto the narration vocabulary."""
    if ply <= 10 and in_book:
        return "book"
    if cp_loss is not None:
        if cp_loss >= BLUNDER_CP:
            return "blunder"
        if cp_loss >= MISTAKE_CP:
            return "mistake"
        if cp_loss >= INACCURACY_CP:
            return "inaccuracy"
    if played_best and only_move:
        return "brilliant" if is_sacrifice else "best"
    return "good"


# --------------------------------------------------------------------------- #
# Opening book (optional local ECO table)
# --------------------------------------------------------------------------- #


def _eco_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "eco.tsv"


def _normalize_san(san: str) -> str:
    return _SAN_STRIP_RE.sub("", san.strip())


def _parse_book_moves(text: str) -> Tuple[str, ...]:
    """Turn ``'1. e4 c6 2. d4 d5'`` into ``('e4','c6','d4','d5')``."""
    cleaned = _MOVE_NUMBER_RE.sub(" ", text)
    tokens = [
        _normalize_san(tok)
        for tok in cleaned.replace("...", " ").split()
        if tok and tok not in ("*", "1-0", "0-1", "1/2-1/2")
    ]
    return tuple(t for t in tokens if t)


@lru_cache(maxsize=1)
def _load_eco_table() -> Tuple[Tuple[str, str, Tuple[str, ...]], ...]:
    """Load ``data/eco.tsv`` (``eco<TAB>name<TAB>pgn_moves``) if it exists.

    Returns an empty tuple when the file is absent or unreadable -- the opening
    name is optional and there are deliberately no network lookups here.
    """
    path = _eco_path()
    if not path.exists():
        logger.debug(f"facts: no ECO table at {path}; opening names disabled")
        return ()
    rows: List[Tuple[str, str, Tuple[str, ...]]] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                eco, name, moves = parts[0].strip(), parts[1].strip(), parts[2]
                san = _parse_book_moves(moves)
                if san:
                    rows.append((eco, name, san))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"facts: failed to read ECO table {path}: {exc}")
        return ()
    logger.info(f"facts: loaded {len(rows)} ECO entries from {path}")
    return tuple(rows)


def _match_opening(san_moves: Sequence[str]) -> Tuple[Optional[str], Optional[str], int]:
    """Longest-prefix match of the game against the local ECO table.

    Returns ``(eco, name, book_ply)`` where ``book_ply`` is the number of plies
    that are still theory (0 when nothing matched).
    """
    table = _load_eco_table()
    if not table:
        return None, None, 0
    normalized = [_normalize_san(s) for s in san_moves]
    best: Tuple[Optional[str], Optional[str], int] = (None, None, 0)
    for eco, name, book in table:
        n = len(book)
        if n <= best[2] or n > len(normalized):
            continue
        if tuple(normalized[:n]) == book:
            best = (eco, name, n)
    return best


# --------------------------------------------------------------------------- #
# Engine adapter
# --------------------------------------------------------------------------- #


class _EngineAdapter:
    """Use an injected engine, or own a :class:`StockfishEngine` for the run.

    Mirrors ``timeline._EngineAdapter`` so tests can pass a fake engine that
    only implements ``analyse(board, multipv=..., depth=...)``.
    """

    def __init__(self, engine: Any | None = None) -> None:
        self._owned = engine is None
        if engine is not None:
            self._eng = engine
        else:
            from .engine import StockfishEngine  # lazy: tests need no Stockfish

            self._eng = StockfishEngine()
            self._eng.__enter__()

    def analyse(self, board: chess.Board, multipv: int, depth: int) -> List[Dict[str, Any]]:
        infos = self._eng.analyse(board, multipv=multipv, depth=depth)
        if isinstance(infos, dict):  # pragma: no cover - defensive
            return [infos]
        return list(infos or [])

    def close(self) -> None:
        if self._owned and hasattr(self._eng, "__exit__"):
            try:
                self._eng.__exit__(None, None, None)
            except Exception:  # pragma: no cover - defensive
                pass


# --------------------------------------------------------------------------- #
# Key moments
# --------------------------------------------------------------------------- #

_QUALITY_SCORES = {
    "blunder": 8.0,
    "brilliant": 9.0,
    "mistake": 5.5,
    "inaccuracy": 3.0,
}


def _build_key_moments(plies: List[Dict[str, Any]], book_ply: int) -> List[Dict[str, Any]]:
    """Rank plies by narrative interest; at most one moment per ply."""
    best_per_ply: Dict[int, Dict[str, Any]] = {}

    def offer(ply: int, kind: str, score: float, note: str) -> None:
        current = best_per_ply.get(ply)
        if current is None or score > current["score"]:
            best_per_ply[ply] = {
                "ply": ply,
                "kind": kind,
                "score": round(float(score), 2),
                "note": note,
            }

    prev_forks = 0
    prev_pins = 0
    deviation_flagged = False

    for p in plies:
        ply = p["ply"]
        side = p["side"].capitalize()
        move_no = p["moveNumber"]
        san = p["san"]
        quality = p.get("quality")
        cp_loss = p.get("cpLoss")
        features = p.get("features") or {}
        before_txt = _pretty_eval(p.get("evalBeforeCp"), p.get("mateBefore"))
        after_txt = _pretty_eval(p.get("evalAfterCp"), p.get("mateAfter"))

        if quality == "blunder":
            offer(
                ply,
                "blunder",
                min(10.0, 8.0 + (cp_loss or 0) / 500.0),
                f"{side} blunders with {move_no}. {san}"
                + (f" (-{(cp_loss or 0) / 100:.1f} pawns, {before_txt} to {after_txt})."),
            )
        elif quality == "brilliant":
            offer(
                ply,
                "brilliant",
                9.5,
                f"{side} finds the brilliant {move_no}. {san} - the only move that works.",
            )
        elif quality == "mistake":
            offer(
                ply,
                "mistake",
                5.5 + min(1.5, (cp_loss or 0) / 300.0),
                f"{side} errs with {move_no}. {san}; the eval slides from {before_txt} to {after_txt}.",
            )
        elif quality == "inaccuracy":
            offer(ply, "inaccuracy", 3.0, f"{side} is imprecise with {move_no}. {san}.")

        if p.get("isMate"):
            offer(ply, "checkmate", 9.8, f"{move_no}. {san} is checkmate - {side} wins.")
        elif p.get("isStalemate"):
            offer(ply, "stalemate", 7.0, f"{move_no}. {san} leaves the position stalemated.")

        if p.get("isSacrifice"):
            offer(
                ply,
                "sacrifice",
                7.5,
                f"{side} offers material with {move_no}. {san} and the engine still likes it ({after_txt}).",
            )

        before = p.get("evalBeforeCp")
        after = p.get("evalAfterCp")
        if before is not None and after is not None:
            swing = abs(after - before)
            if swing >= 200:
                offer(
                    ply,
                    "swing",
                    min(9.0, 4.0 + swing / 300.0),
                    f"Big swing on {move_no}. {san}: {before_txt} to {after_txt}.",
                )

        if p.get("mateBefore") and not p.get("mateAfter"):
            mover_is_white = p["side"] == "white"
            mate_for_mover = (p["mateBefore"] > 0) == mover_is_white
            if mate_for_mover:
                offer(
                    ply,
                    "missed_mate",
                    8.5,
                    f"{side} had a forced mate but played {move_no}. {san}.",
                )

        n_forks = len(features.get("forks") or [])
        n_pins = len(features.get("pins") or [])
        if n_forks > prev_forks:
            offer(ply, "fork", 5.0, f"{move_no}. {san} sets up a fork.")
        if n_pins > prev_pins:
            offer(ply, "pin", 4.0, f"{move_no}. {san} creates a pin.")
        prev_forks, prev_pins = n_forks, n_pins

        if book_ply and not deviation_flagged and ply == book_ply + 1:
            deviation_flagged = True
            offer(ply, "out_of_book", 4.5, f"{move_no}. {san} leaves known theory.")

    moments = sorted(best_per_ply.values(), key=lambda m: (-m["score"], m["ply"]))
    return moments[:30]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def extract_facts(
    pgn_text: str,
    *,
    engine: Any | None = None,
    depth: Optional[int] = None,
    multipv: Optional[int] = None,
    max_plies: Optional[int] = None,
    progress: bool = True,
) -> Dict[str, Any]:
    """Walk a game once with the engine and return a JSON-serializable fact sheet.

    Args:
        pgn_text: Raw PGN of a single game (only the mainline is followed).
        engine: Optional pre-built engine implementing
            ``analyse(board, multipv=..., depth=...)``. When ``None`` a
            :class:`~.engine.StockfishEngine` is created, opened and closed here.
        depth: Search depth per position (defaults to ``settings.ENGINE_DEPTH``).
        multipv: Number of principal variations per position (defaults to
            ``settings.ENGINE_MULTIPV``). PVs 2..N become ``alternatives``.
        max_plies: Analyse at most this many plies of the mainline.
        progress: Print a one-line progress indicator to stderr every 10 plies.

    Returns:
        A dict with ``meta``, ``opening``, ``plies``, ``keyMoments`` and
        ``summary`` keys. Every value is plain JSON data -- no ``chess.Move`` or
        ``chess.Board`` objects leak out.

    Raises:
        ValueError: if the PGN is empty or cannot be parsed.
    """
    depth = int(depth or settings.ENGINE_DEPTH)
    multipv = int(multipv or settings.ENGINE_MULTIPV)

    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Empty or invalid PGN provided.")

    headers = game.headers
    moves: List[chess.Move] = list(game.mainline_moves())
    if max_plies is not None:
        moves = moves[: max(0, int(max_plies))]

    board = game.board()

    # SAN list up front (cheap) so the opening matcher can run before the walk.
    san_moves: List[str] = _safe(
        "sanList", lambda: _san_line(board, moves, limit=max(1, len(moves))), []
    )
    eco_match, opening_name, book_ply = _safe(
        "openingMatch", lambda: _match_opening(san_moves), (None, None, 0)
    )

    adapter = _EngineAdapter(engine)
    plies: List[Dict[str, Any]] = []
    castled = {"white": False, "black": False}
    total = len(moves)

    try:
        infos_before: Optional[List[Dict[str, Any]]] = (
            adapter.analyse(board, multipv=multipv, depth=depth) if total else None
        )

        for idx, move in enumerate(moves):
            ply = idx + 1
            board_before = board.copy(stack=False)
            mover = board_before.turn

            san = board_before.san(move)
            moved_piece = board_before.piece_at(move.from_square)
            is_capture = board_before.is_capture(move)
            if is_capture:
                captured_piece = (
                    chess.piece_name(chess.PAWN)
                    if board_before.is_en_passant(move)
                    else _piece_name(
                        board_before.piece_at(move.to_square).piece_type
                        if board_before.piece_at(move.to_square)
                        else None
                    )
                )
            else:
                captured_piece = None

            is_castle = None
            if board_before.is_castling(move):
                is_castle = (
                    "kingside" if board_before.is_kingside_castling(move) else "queenside"
                )
                castled[_color_name(mover)] = True

            fen_before = board_before.fen()
            board.push(move)
            fen_after = board.fen()

            terminal = board.is_checkmate() or board.is_stalemate() or board.is_insufficient_material()

            # ---- evaluations ------------------------------------------------
            cp_b_stm, mate_b_stm = _score_pair(infos_before[0] if infos_before else None, mover)
            eval_before_cp, mate_before = _to_white(cp_b_stm, mate_b_stm, mover)

            if terminal:
                infos_after: Optional[List[Dict[str, Any]]] = None
                if board.is_checkmate():
                    # Side to move is mated -> mover delivered mate.
                    eval_after_cp, mate_after = None, 0
                    after_scale_mover: Optional[int] = MATE_SCALE_CP
                else:
                    eval_after_cp, mate_after = 0, None
                    after_scale_mover = 0
            else:
                infos_after = adapter.analyse(board, multipv=multipv, depth=depth)
                cp_a_stm, mate_a_stm = _score_pair(infos_after[0] if infos_after else None, board.turn)
                eval_after_cp, mate_after = _to_white(cp_a_stm, mate_a_stm, board.turn)
                opp_scale = _scale(cp_a_stm, mate_a_stm)
                after_scale_mover = None if opp_scale is None else -opp_scale

            before_scale = _scale(cp_b_stm, mate_b_stm)

            # ---- best move / alternatives ----------------------------------
            best_pv: List[chess.Move] = (
                list(infos_before[0].get("pv") or []) if infos_before else []
            )
            played_best = bool(best_pv) and best_pv[0] == move
            best_pv_san = _san_line(board_before, best_pv)
            best_pv_uci = _uci_line(best_pv)

            alternatives: List[Dict[str, Any]] = []
            only_move = False
            if infos_before and len(infos_before) > 1:
                cp2, mate2 = _score_pair(infos_before[1], mover)
                scale2 = _scale(cp2, mate2)
                if before_scale is not None and scale2 is not None:
                    only_move = (before_scale - scale2) >= ONLY_MOVE_CP
                for rank, info in enumerate(infos_before[1:], start=2):
                    alt_pv: List[chess.Move] = list(info.get("pv") or [])
                    if not alt_pv:
                        continue
                    alt_cp, alt_mate = _score_pair(info, mover)
                    alt_cp_white, alt_mate_white = _to_white(alt_cp, alt_mate, mover)
                    alt_pv_san = _san_line(board_before, alt_pv)
                    alternatives.append(
                        {
                            "rank": rank,
                            "san": alt_pv_san[0] if alt_pv_san else None,
                            "uci": alt_pv[0].uci(),
                            "pvSan": alt_pv_san,
                            "pvUci": _uci_line(alt_pv),
                            # cp/mate are from the MOVER's point of view here;
                            # cpWhite/mateWhite mirror the White-POV convention.
                            "cp": alt_cp,
                            "mate": alt_mate,
                            "cpWhite": alt_cp_white,
                            "mateWhite": alt_mate_white,
                        }
                    )

            # ---- cp loss / quality ------------------------------------------
            cp_loss_raw: Optional[int] = None
            if before_scale is not None and after_scale_mover is not None:
                cp_loss_raw = max(0, int(before_scale - after_scale_mover))
            cp_loss = 0 if played_best else cp_loss_raw

            is_sacrifice = _safe(
                "sacrifice", lambda: _is_sacrifice(board_before, move, board, cp_loss), False
            )

            in_book = (ply <= book_ply) if book_ply else (cp_loss is None or cp_loss < INACCURACY_CP)
            quality = _classify_quality(
                ply=ply,
                in_book=in_book,
                cp_loss=cp_loss,
                played_best=played_best,
                only_move=only_move,
                is_sacrifice=bool(is_sacrifice),
            )

            # ---- features & threats -----------------------------------------
            features = _compute_features(board, ply=ply, castled=dict(castled))
            threats = _safe(
                "threats", lambda: _compute_threats(board, infos_after, features), []
            )

            plies.append(
                {
                    "ply": ply,
                    "moveNumber": (ply + 1) // 2,
                    "side": _color_name(mover),
                    "san": san,
                    "uci": move.uci(),
                    "from": chess.square_name(move.from_square),
                    "to": chess.square_name(move.to_square),
                    "pieceType": _piece_name(moved_piece.piece_type) if moved_piece else None,
                    "fenBefore": fen_before,
                    "fenAfter": fen_after,
                    "isCapture": bool(is_capture),
                    "capturedPiece": captured_piece,
                    "isCheck": bool(board.is_check()),
                    "isMate": bool(board.is_checkmate()),
                    "isStalemate": bool(board.is_stalemate()),
                    "isCastle": is_castle,
                    "promotion": _piece_name(move.promotion) if move.promotion else None,
                    "evalBeforeCp": eval_before_cp,
                    "evalAfterCp": eval_after_cp,
                    "mateBefore": mate_before,
                    "mateAfter": mate_after,
                    "cpLoss": cp_loss,
                    "cpLossRaw": cp_loss_raw,
                    "playedBest": bool(played_best),
                    "isSacrifice": bool(is_sacrifice),
                    "quality": quality,
                    "bestMoveSan": best_pv_san[0] if best_pv_san else None,
                    "bestMoveUci": best_pv_uci[0] if best_pv_uci else None,
                    "bestPvSan": best_pv_san,
                    "bestPvUci": best_pv_uci,
                    "alternatives": alternatives,
                    "features": features,
                    "threats": threats,
                }
            )

            infos_before = infos_after

            if progress and (ply % 10 == 0 or ply == total):
                print(
                    f"\r[facts] analysed ply {ply}/{total}", end="", file=sys.stderr, flush=True
                )

            if terminal:
                break
    finally:
        adapter.close()
        if progress and total:
            print("", file=sys.stderr, flush=True)

    key_moments = _safe("keyMoments", lambda: _build_key_moments(plies, book_ply), [])

    meta = {
        "white": headers.get("White") or None,
        "black": headers.get("Black") or None,
        "date": headers.get("Date") or None,
        "event": headers.get("Event") or None,
        "site": headers.get("Site") or None,
        "result": headers.get("Result") or None,
        "eco": headers.get("ECO") or None,
        "whiteElo": headers.get("WhiteElo") or None,
        "blackElo": headers.get("BlackElo") or None,
        "timeControl": headers.get("TimeControl") or None,
        "plyCount": len(plies),
    }

    opening = {
        "eco": eco_match or (headers.get("ECO") or None),
        "name": opening_name,
    }

    result = meta["result"]
    biggest_swing_ply: Optional[int] = None
    biggest_swing = 0
    for p in plies:
        b, a = p.get("evalBeforeCp"), p.get("evalAfterCp")
        if b is None or a is None:
            continue
        swing = abs(a - b)
        if swing > biggest_swing:
            biggest_swing, biggest_swing_ply = swing, p["ply"]

    summary = {
        "result": result,
        "plyCount": len(plies),
        "decisive": result in ("1-0", "0-1"),
        "biggestSwingPly": biggest_swing_ply,
        "blunders": [p["ply"] for p in plies if p["quality"] == "blunder"],
        "brilliancies": [p["ply"] for p in plies if p["quality"] == "brilliant"],
        "sacrifices": [p["ply"] for p in plies if p["isSacrifice"]],
        "mistakes": [p["ply"] for p in plies if p["quality"] == "mistake"],
        "inaccuracies": [p["ply"] for p in plies if p["quality"] == "inaccuracy"],
        "bookPlies": book_ply,
    }

    logger.info(
        f"facts: extracted {len(plies)} plies, {len(key_moments)} key moments "
        f"(depth={depth}, multipv={multipv})"
    )

    return {
        "meta": meta,
        "opening": opening,
        "plies": plies,
        "keyMoments": key_moments,
        "summary": summary,
    }


def save_facts(facts: Dict[str, Any], path: str | Path) -> None:
    """Write a fact sheet to ``path`` as pretty-printed UTF-8 JSON.

    Parent directories are created automatically.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(facts, fh, indent=2, ensure_ascii=False)
    logger.info(f"facts: saved fact sheet to {p}")
