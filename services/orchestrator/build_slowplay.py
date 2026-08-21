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
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
            "isCapture": captured is not None,
            "capturedByWhite": list(by_white),
            "capturedByBlack": list(by_black),
            "matDiff": diff,
        })

    h = game.headers
    date = _clean(h.get("Date")) or ""
    year = date[:4] if date[:4].isdigit() else None
    # Database collections glue a round or section digit onto the event
    # ("Lodz1", "Hastings2"); a lone digit riding directly on letters is that
    # artefact, not part of the name. Years and numbered editions keep their
    # space and are left alone.
    event = _clean(h.get("Event"))
    if event:
        event = re.sub(r"(?<=[A-Za-z])\d$", "", event)
    return {
        "white": _display_name(h.get("White", "White")),
        "black": _display_name(h.get("Black", "Black")),
        "whiteElo": _clean(h.get("WhiteElo")),
        "blackElo": _clean(h.get("BlackElo")),
        "result": _clean(h.get("Result")),
        "event": event,
        "year": year,
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


def make_thumbnail(mp4: Path) -> Optional[Path]:
    """A frame from the middle game as the thumbnail — the board with pieces
    developed and captures in the trays, rather than the opening position."""
    ff = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if not ff:
        return None
    probe = shutil.which("ffprobe") or (Path(ff).with_name("ffprobe" + Path(ff).suffix))
    try:
        dur = float(subprocess.check_output(
            [str(probe), "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(mp4)], text=True).strip())
    except Exception:  # noqa: BLE001
        dur = 0.0
    at = max(3.0, dur * 0.45)
    png = mp4.with_suffix(".png")
    try:
        subprocess.check_call(
            [ff, "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(mp4),
             "-frames:v", "1", str(png)])
        return png
    except Exception:  # noqa: BLE001
        return None


def slowplay_paths(pgn: Path) -> Tuple[Path, Path]:
    """Where build_video/flow find a game's slow-play cut and its props."""
    d = OUT / pgn.stem
    return d / f"{pgn.stem}-slowplay.mp4", d / "props.json"


def have_slowplay_creds(profile: str = "slowplay") -> bool:
    """The second channel is configured: its token AND its channel id."""
    p = profile.upper()
    return bool(os.getenv(f"GOOGLE_REFRESH_TOKEN_{p}")
                and os.getenv(f"YOUTUBE_CHANNEL_ID_{p}"))


def upload(mp4: Path, props: Path, privacy: str, full_url: Optional[str],
           profile: str = "slowplay", dry_run: bool = False) -> Dict[str, Any]:
    """Post a slow-play cut to the slow-play channel via the uploader CLI.

    Returns the uploader's result dict (videoId/url/title) or {} on a dry
    run. Raises CalledProcessError on failure — the caller decides whether
    that is fatal (it never is for the narrated video's own pipeline).
    """
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("[slowplay] npm not found")
    uploader = ROOT / "apps" / "uploader"
    thumb = mp4.with_suffix(".png")
    if not thumb.exists():
        make_thumbnail(mp4)
    result = mp4.parent / "upload.json"
    result.unlink(missing_ok=True)
    cmd = [npm, "run", "cli", "--", "upload-slowplay",
           "-v", str(mp4), "--props", str(props), "-p", privacy,
           "--channel", profile, "--result-json", str(result)]
    if thumb.exists():
        cmd += ["-T", str(thumb)]
    if full_url:
        cmd += ["--full-url", full_url]
    if dry_run:
        cmd.append("--dry-run")
    print(f"[slowplay] uploading to the '{profile}' channel ({privacy})…")
    subprocess.check_call(cmd, cwd=str(uploader))
    if result.exists():
        try:
            return json.loads(result.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pgn", required=True, help="PGN of the game")
    ap.add_argument("--out", default=None,
                    help="Output mp4 (default outputs/slowplay/<pgn-stem>/)")
    ap.add_argument("--seconds-per-move", type=float, default=4.0)
    ap.add_argument("--no-render", action="store_true",
                    help="Skip rendering (upload an existing cut)")
    ap.add_argument("--upload", action="store_true",
                    help="Post to the slow-play channel after rendering")
    ap.add_argument("--privacy", default="unlisted",
                    choices=["public", "unlisted", "private"])
    ap.add_argument("--full-url", default=None,
                    help="Narrated analysis URL on the main channel, for the description")
    ap.add_argument("--channel", default="slowplay", help="Uploader channel profile")
    ap.add_argument("--dry-run-upload", action="store_true")
    args = ap.parse_args()

    pgn_path = Path(args.pgn)
    name = pgn_path.stem
    out_mp4 = Path(args.out) if args.out else OUT / name / f"{name}-slowplay.mp4"
    props_path = out_mp4.parent / "props.json"
    if not args.no_render:
        props_obj = game_props(pgn_path)
        render(props_obj, out_mp4, args.seconds_per_move)
        make_thumbnail(out_mp4)
    if args.upload:
        if not out_mp4.exists() or not props_path.exists():
            raise SystemExit(f"[slowplay] nothing to upload at {out_mp4}")
        res = upload(out_mp4, props_path, args.privacy, args.full_url,
                     args.channel, dry_run=args.dry_run_upload)
        if res.get("url"):
            print(f"[slowplay] posted: {res['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
