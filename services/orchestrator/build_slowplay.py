"""Render the no-narration slow-play cut of a game.

The second channel's format: the bare game on a board, one move every three
seconds, players' names and the pieces they have taken — nothing else. No
engine, no LLM, no voice; the PGN alone is the whole input, so this runs in
a couple of minutes where the narrated build takes forty.

Isolation from the narrated pipeline is a design rule, not an accident:

  * the game goes to the renderer via --props, never public/script.json —
    that file belongs to whatever narrated build is in flight;
  * everything written lands under outputs/slowplay/<name>/, a tree the
    narrated build never touches;
  * no audio directories are read or cleared.

Called by build_video.py after each successful narrated render (the slow
channel mirrors the main one game for game), and standalone:

    python build_slowplay.py --pgn outputs/pgns/daily/2026-08-09_X_vs_Y.pgn
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "apps" / "renderer"
OUT = ROOT / "outputs" / "slowplay"

sys.path.insert(0, str(ROOT / "apps" / "analyzer"))

PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
               chess.ROOK: 5, chess.QUEEN: 9}
LETTER = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B",
          chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}


def _display_name(header: str) -> str:
    """"Fischer, Robert James" -> "Bobby Fischer", via the analyzer's own
    resolver so both channels spell a player the same way."""
    try:
        from chessbot_analyzer.director import full_name  # noqa: PLC0415
        return full_name(header)
    except Exception:  # noqa: BLE001
        parts = [p.strip() for p in header.split(",")]
        return f"{parts[1]} {parts[0]}" if len(parts) == 2 and parts[1] else header


def _clean(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    return v if v and not all(c in "?." for c in v) else None


def game_props(pgn_path: Path) -> Dict[str, Any]:
    with pgn_path.open(encoding="utf-8", errors="ignore") as fh:
        game = chess.pgn.read_game(fh)
    if game is None:
        raise SystemExit(f"[slowplay] no game in {pgn_path}")

    board = game.board()
    start_fen = board.fen()
    by_white: List[str] = []
    by_black: List[str] = []
    diff = 0
    plies = []
    for move in game.mainline_moves():
        prev_fen = board.fen()
        san = board.san(move)
        captured = None
        if board.is_en_passant(move):
            captured = chess.PAWN
        elif board.is_capture(move):
            captured = board.piece_type_at(move.to_square)
        mover_white = board.turn == chess.WHITE
        board.push(move)
        if captured:
            (by_white if mover_white else by_black).append(LETTER[captured])
            diff += PIECE_VALUE.get(captured, 0) * (1 if mover_white else -1)
        check_sq = (chess.square_name(board.king(board.turn))
                    if board.is_check() else None)
        plies.append({
            "san": san,
            "from": chess.square_name(move.from_square),
            "to": chess.square_name(move.to_square),
            "prevFen": prev_fen,
            "fen": board.fen(),
            "checkSquare": check_sq,
            "capturedByWhite": list(by_white),
            "capturedByBlack": list(by_black),
            "matDiff": diff,
        })

    h = game.headers
    return {
        "white": _display_name(h.get("White", "White")),
        "black": _display_name(h.get("Black", "Black")),
        "whiteElo": _clean(h.get("WhiteElo")),
        "blackElo": _clean(h.get("BlackElo")),
        "result": _clean(h.get("Result")),
        "event": _clean(h.get("Event")),
        "startFen": start_fen,
        "plies": plies,
    }


def render(props_obj: Dict[str, Any], out_mp4: Path, seconds_per_move: float) -> None:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("[slowplay] npx not found")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    props = out_mp4.parent / "props.json"
    props.write_text(
        json.dumps({"game": props_obj, "secondsPerMove": seconds_per_move},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    n = len(props_obj["plies"])
    total = 3 + n * seconds_per_move + 6
    print(f"[slowplay] rendering {n} moves, ~{total / 60:.1f} min…")
    subprocess.check_call(
        [npx, "remotion", "render", "src/index.tsx", "ChessSlowPlay",
         str(out_mp4.resolve()), "--codec=h264", "--crf=18", "--overwrite",
         f"--props={props.resolve()}"],
        cwd=str(RENDERER),
    )
    print(f"[slowplay] done -> {out_mp4}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pgn", required=True, help="PGN of the game")
    ap.add_argument("--out", default=None,
                    help="Output mp4 (default outputs/slowplay/<pgn-stem>/)")
    ap.add_argument("--seconds-per-move", type=float, default=3.0)
    args = ap.parse_args()

    pgn_path = Path(args.pgn)
    props_obj = game_props(pgn_path)
    name = pgn_path.stem
    out_mp4 = Path(args.out) if args.out else OUT / name / f"{name}-slowplay.mp4"
    render(props_obj, out_mp4, args.seconds_per_move)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
