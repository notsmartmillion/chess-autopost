"""Daily end-to-end orchestrator: fetch game -> analyze/narrate/render -> upload.

Run from repo root (venv active or via wrapper scripts):
    python services/orchestrator/flow.py            # full daily run
    python services/orchestrator/flow.py --no-upload
    python services/orchestrator/flow.py --pgn path/to/game.pgn   # skip fetching

Design goals:
- Zero required credentials for video creation (Lichess public API + local TTS).
- Upload runs only when Google OAuth env vars are present; otherwise it is
  skipped with a clear message, and the video stays in apps/renderer/out/.
- Never posts the same game twice (state file with move-hashes).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import subprocess
import shutil
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

# Windows consoles default to cp1252; make unicode-safe before any printing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
PGN_DAILY_DIR = OUT / "pgns" / "daily"
# Durable state lives OUTSIDE outputs/ deliberately. outputs/ is disposable
# build output and is gitignored wholesale; used_games.json is the only thing
# stopping the channel re-publishing a game it has already posted, so losing it
# is the worst failure mode in the system. state/ is version-controlled.
STATE_DIR = ROOT / "state"
STATE_FILE = STATE_DIR / "used_games.json"
LEGACY_STATE_FILE = OUT / "state" / "used_games.json"
LEDGER_FILE = STATE_DIR / "published.json"
VIDEO_ARCHIVE = OUT / "videos"
LOG_DIR = OUT / "logs"
VIDEO_PATH = ROOT / "apps" / "renderer" / "out" / "video.mp4"
THUMBNAIL_PATH = ROOT / "apps" / "renderer" / "out" / "thumbnail.png"

sys.path.insert(0, str(ROOT / "services" / "orchestrator"))

# Default pool of very active, strong Lichess players (public games, no API key
# needed). Override with DAILY_LICHESS_PLAYERS="user1,user2" in .env.
DEFAULT_PLAYERS = [
    "Zhigalko_Sergei",
    "nihalsarin2004",
    "RebeccaHarris",
    "penguingim1",
    "DrNykterstein",
]


def _load_dotenv() -> None:
    """Minimal .env loader so this script works without python-dotenv."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


# ------------------------------ Game selection ------------------------------


def _moves_hash(pgn: str) -> str:
    """Stable hash of the game's mainline moves (ignores headers/whitespace)."""
    import chess.pgn

    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return hashlib.md5(pgn.encode("utf-8")).hexdigest()
    ucis = " ".join(m.uci() for m in game.mainline_moves())
    return hashlib.md5(ucis.encode("utf-8")).hexdigest()


def _migrate_state() -> None:
    """Move state from the old outputs/ location, once."""
    if LEGACY_STATE_FILE.exists() and not STATE_FILE.exists():
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            LEGACY_STATE_FILE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        LEGACY_STATE_FILE.unlink()
        log(f"migrated dedupe state -> {STATE_FILE.relative_to(ROOT)}")


def _load_used() -> Dict[str, str]:
    _migrate_state()
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _mark_used(h: str, note: str) -> None:
    used = _load_used()
    used[h] = note
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(used, indent=2, sort_keys=True), encoding="utf-8")


def _load_ledger() -> List[Dict]:
    if LEDGER_FILE.exists():
        try:
            return json.loads(LEDGER_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def record_publication(entry: Dict) -> None:
    """Append to the permanent record of what this pipeline produced.

    Keyed by archive filename so re-running the same day updates that row
    rather than appending a duplicate.
    """
    ledger = [e for e in _load_ledger() if e.get("archive") != entry.get("archive")]
    ledger.append(entry)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LEDGER_FILE.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def _newest_library_copy() -> Optional[Path]:
    """The per-game copy build_video just filed, if it is genuinely this run's.

    Matched by content size against the render on disk rather than by name:
    the folder is named after the players, and this function has only the PGN
    path, so a name match would be a second implementation of the same rule.
    """
    if not VIDEO_ARCHIVE.exists() or not VIDEO_PATH.exists():
        return None
    size = VIDEO_PATH.stat().st_size
    for mp4 in VIDEO_ARCHIVE.glob("*/*.mp4"):
        try:
            if mp4.stat().st_size == size:
                return mp4
        except OSError:
            continue
    return None


def archive_video(pgn_path: Path) -> Optional[Path]:
    """Keep a copy of the render that tomorrow's build cannot overwrite.

    Remotion writes out/video.mp4 with --overwrite, so without a copy the next
    day's run destroys today's video — which matters when an upload fails.

    build_video.py now files each render in its own folder under
    outputs/videos/, which serves the same purpose. When it has already done
    so, this stands down rather than leaving a second, differently-named copy
    of every game loose in the library.
    """
    if not VIDEO_PATH.exists():
        return None
    newest = _newest_library_copy()
    if newest is not None:
        return newest
    VIDEO_ARCHIVE.mkdir(parents=True, exist_ok=True)
    dest = VIDEO_ARCHIVE / f"{pgn_path.stem}.mp4"
    try:
        shutil.copy2(VIDEO_PATH, dest)
        if THUMBNAIL_PATH.exists():
            shutil.copy2(THUMBNAIL_PATH, dest.with_suffix(".png"))
        return dest
    except OSError as exc:
        log(f"could not archive video: {exc}")
        return None


def _score_game(meta: Dict, pgn: str) -> float:
    """Heuristic 'watchability' score: decisive, mid-length, high-rated."""
    score = 0.0
    result = (meta.get("result") or "").strip()
    if result in ("1-0", "0-1"):
        score += 30
    elif result == "1/2-1/2":
        score -= 10

    # Length is the one input the writing cannot manufacture. The director
    # pulls the script toward eight minutes, but it can only stretch what the
    # game gives it: a 30-ply miniature has nothing to say for that long, and
    # padding it would trade watch time for duration. So the pool prefers
    # games with the material to fill the slot honestly.
    ply = meta.get("ply_count") or 0
    if 60 <= ply <= 120:
        score += 35
    elif 40 <= ply < 60:
        score += 25
    elif 24 <= ply < 40 or 120 < ply <= 160:
        score += 10
    elif ply < 16:
        score -= 50  # too short to narrate

    # Prefer rated/high-elo games when headers carry Elo info
    import re

    elos = [int(m) for m in re.findall(r'\[(?:White|Black)Elo "(\d+)"\]', pgn)]
    if elos:
        score += min(20.0, (sum(elos) / len(elos)) / 150.0)

    # A sprinkle of randomness so the same player pool doesn't always
    # produce the same pick order.
    score += random.uniform(0, 5)
    return score


def _save_pick(pgn: str, headers: Dict, moves_hash: str, note: str) -> Path:
    PGN_DAILY_DIR.mkdir(parents=True, exist_ok=True)
    white = (headers.get("White") or "W").split(",")[0].strip()
    black = (headers.get("Black") or "B").split(",")[0].strip()
    raw = f"{date.today().isoformat()}_{white}_vs_{black}.pgn"
    name = "".join(c for c in raw if c.isalnum() or c in "._-")
    dest = PGN_DAILY_DIR / name
    dest.write_text(pgn, encoding="utf-8")
    _mark_used(moves_hash, note or name)
    return dest


def fetch_classic_game() -> Optional[Path]:
    """Primary source: a famous game from a world-champion collection."""
    from ingest.classics_fetch import LEGENDS, pick_game  # type: ignore

    used = set(_load_used().keys())
    players_env = os.getenv("DAILY_LEGENDS", "")
    pool = [p.strip() for p in players_env.split(",") if p.strip()] or list(LEGENDS)
    random.shuffle(pool)

    for player in pool[:4]:
        try:
            log(f"looking for an unused classic from {player}…")
            pick = pick_game(player, exclude_hashes=used, hash_fn=_moves_hash)
        except Exception as exc:
            log(f"  {player}: {exc}")
            continue
        if not pick:
            continue
        headers = pick["headers"]
        dest = _save_pick(pick["pgn"], headers, pick["hash"] or _moves_hash(pick["pgn"]), player)
        log(
            f"selected: {headers.get('White')} vs {headers.get('Black')} "
            f"({headers.get('Result')}, {pick['plies']} plies, {headers.get('Event')} "
            f"{headers.get('Date')}) -> {dest.name}"
        )
        return dest
    return None


def fetch_lichess_game(limit_per_player: int = 15) -> Optional[Path]:
    """Secondary source: a recent online game from a strong player."""
    from ingest.lichess_fetch import fetch_lichess_games  # type: ignore

    players_env = os.getenv("DAILY_LICHESS_PLAYERS", "")
    players = [p.strip() for p in players_env.split(",") if p.strip()] or list(DEFAULT_PLAYERS)
    random.shuffle(players)

    used = _load_used()
    candidates: List[Dict] = []

    for i, user in enumerate(players[:2]):
        try:
            if i > 0:
                import time

                time.sleep(3)  # courtesy delay between users
            log(f"fetching recent games for lichess user '{user}'…")
            games = fetch_lichess_games(username=user, limit=limit_per_player, rated_only=True)
        except Exception as e:
            log(f"  fetch failed for {user}: {e}")
            continue
        for g in games:
            h = _moves_hash(g["pgn"])
            if h in used:
                continue
            g["hash"] = h
            g["score"] = _score_game(g.get("meta") or {}, g["pgn"])
            candidates.append(g)
        if len(candidates) >= 10:
            break

    if not candidates:
        return None

    best = max(candidates, key=lambda g: g["score"])
    meta = best.get("meta") or {}
    headers = {"White": meta.get("white"), "Black": meta.get("black")}
    dest = _save_pick(best["pgn"], headers, best["hash"], "lichess")
    log(
        f"selected: {meta.get('white')} vs {meta.get('black')} "
        f"({meta.get('result')}, {meta.get('ply_count')} plies) -> {dest.name}"
    )
    return dest


def fetch_daily_game() -> Optional[Path]:
    """Pick today's game: classic masterpiece first, online game as a backup."""
    source = os.getenv("DAILY_SOURCE", "classics").lower()

    order = [fetch_classic_game, fetch_lichess_game]
    if source == "lichess":
        order.reverse()

    for fn in order:
        try:
            picked = fn()
        except Exception as exc:
            log(f"  source {fn.__name__} failed: {exc}")
            continue
        if picked:
            return picked

    log("no fresh game from any source; falling back to an unused local PGN…")
    return _fallback_local_pgn(_load_used())


def _fallback_local_pgn(used: Dict[str, str]) -> Optional[Path]:
    for base in (OUT / "pgns" / "lichess", OUT / "pgns" / "chesscom", OUT / "pgns"):
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.pgn")):
            try:
                pgn = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            h = _moves_hash(pgn)
            if h not in used:
                _mark_used(h, p.name)
                log(f"using local PGN {p}")
                return p
    return None


# ------------------------------ Pipeline steps ------------------------------


def build_video(pgn_path: Path, tts: str, extra: Optional[List[str]] = None) -> None:
    """facts -> director -> voice -> render, via build_video.py in this venv."""
    cmd = [
        sys.executable,
        str(ROOT / "services" / "orchestrator" / "build_video.py"),
        "--pgn",
        str(pgn_path),
        "--tts",
        tts,
    ]
    cmd.extend(extra or [])
    log("building video (facts -> script -> voice -> render)…")
    subprocess.check_call(cmd, cwd=str(ROOT))


# Backends that produce the channel's actual narrator voice. Anything else is
# a fallback that kept an unattended run alive, not something to publish.
VOICE_BACKENDS = {"ttsapi", "qwen", "elevenlabs"}


def voice_backend_used() -> Optional[str]:
    """Which TTS backend actually produced the audio, per the manifest."""
    return (_audio_manifest() or {}).get("backend")


def _audio_manifest() -> Optional[Dict]:
    manifest = OUT / "audio_manifest.json"
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def have_upload_creds() -> bool:
    return all(
        os.getenv(k)
        for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
    )


def upload_video(privacy: str, dry_run: bool = False) -> Optional[Dict]:
    """Upload and return the uploader's result, or None if it did not run."""
    uploader_dir = ROOT / "apps" / "uploader"
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        log("npm not found; skipping upload")
        return None
    if not (uploader_dir / "node_modules").exists():
        log("installing uploader dependencies (first run)…")
        subprocess.check_call([npm, "install", "--no-audit", "--no-fund"], cwd=str(uploader_dir))

    result_path = OUT / "upload_result.json"
    if result_path.exists():
        result_path.unlink()

    cmd = [
        npm, "run", "cli", "--",
        "upload",
        "-v", str(VIDEO_PATH),
        "-t", str(OUT / "script.json"),
        "-p", privacy,
        "--result-json", str(result_path),
    ]
    if THUMBNAIL_PATH.exists():
        cmd += ["-T", str(THUMBNAIL_PATH)]
    # Our own subtitle track, built from the render's word timings. It lives
    # beside the library copy rather than in outputs/, since that is the file
    # that survives tomorrow's build.
    captions = _newest_library_copy()
    if captions is not None and captions.with_suffix(".srt").exists():
        cmd += ["-c", str(captions.with_suffix(".srt"))]
    if dry_run:
        cmd.append("--dry-run")
    log("uploading to YouTube…")
    subprocess.check_call(cmd, cwd=str(uploader_dir))

    if result_path.exists():
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def notify(text: str) -> None:
    url = os.getenv("SLACK_WEBHOOK_URL")
    if not url:
        return
    try:
        import requests

        requests.post(url, json={"text": text}, timeout=15)
    except Exception as e:
        log(f"slack notify failed: {e}")


# ------------------------------ Main ------------------------------


def main() -> int:
    _load_dotenv()

    ap = argparse.ArgumentParser(description="Daily chess video pipeline")
    ap.add_argument("--pgn", type=str, default=None, help="Use this PGN instead of fetching")
    ap.add_argument("--no-upload", action="store_true", help="Skip the YouTube upload step")
    ap.add_argument("--dry-run-upload", action="store_true", help="Run uploader in dry-run mode")
    ap.add_argument(
        "--tts",
        choices=["auto", "ttsapi", "qwen", "elevenlabs", "local", "silent"],
        default=os.getenv("TTS_BACKEND", "auto"),
    )
    ap.add_argument("--depth", type=int, default=None, help="Stockfish depth override")
    ap.add_argument("--no-llm", action="store_true", help="Skip LLM narration polish")
    ap.add_argument("--privacy", default=os.getenv("YOUTUBE_PRIVACY", "unlisted"),
                    choices=["public", "unlisted", "private"])
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 1) Pick today's game
    if args.pgn:
        pgn_path = Path(args.pgn)
        if not pgn_path.is_absolute():
            pgn_path = ROOT / pgn_path
        if not pgn_path.exists():
            log(f"PGN not found: {pgn_path}")
            return 2
    else:
        pgn_path = fetch_daily_game()
        if pgn_path is None:
            log("ERROR: no game available (network down and no unused local PGNs)")
            notify("Chess autopost: FAILED — no game available today.")
            return 1

    # 2) facts -> script -> voice -> render
    extra: List[str] = []
    if args.depth:
        extra += ["--depth", str(args.depth)]
    if args.no_llm:
        extra.append("--no-llm")
    try:
        build_video(pgn_path, tts=args.tts, extra=extra)
    except subprocess.CalledProcessError as e:
        log(f"ERROR: build/render failed with exit code {e.returncode}")
        notify(f"Chess autopost: FAILED at build/render ({pgn_path.name}).")
        return e.returncode

    if not VIDEO_PATH.exists():
        log("ERROR: render reported success but video.mp4 is missing")
        return 1
    size_mb = VIDEO_PATH.stat().st_size / 1e6
    log(f"video ready: {VIDEO_PATH} ({size_mb:.1f} MB)")

    # Archive before uploading. If the upload fails, tomorrow's render would
    # otherwise overwrite this file and the video would be gone.
    archived = archive_video(pgn_path)
    if archived:
        log(f"archived -> {archived.relative_to(ROOT)}")

    manifest = _audio_manifest() or {}
    backend = manifest.get("backend")
    script_meta = {}
    try:
        script_meta = json.loads(
            (OUT / "script.json").read_text(encoding="utf-8")
        ).get("meta", {})
    except (OSError, ValueError):
        pass
    entry: Dict = {
        "date": date.today().isoformat(),
        "pgn": pgn_path.name,
        "archive": archived.name if archived else None,
        "sizeMb": round(size_mb, 1),
        # Backend alone could not tell you which of thirteen profiles spoke, nor
        # whether the narration was written or templated — both decide whether a
        # render is publishable, so the ledger records them.
        "voice": backend,
        "voiceProfile": manifest.get("voice"),
        "narration": script_meta.get("narration"),
        "title": script_meta.get("llmTitle"),
        "status": "rendered",
    }

    # The voice layer degrades rather than dying, so a run survives the TTS
    # service being down — but the resulting SAPI narration is not something to
    # put on the channel. Keep the render, refuse the upload.
    if args.tts in VOICE_BACKENDS or (args.tts == "auto" and os.getenv("TTS_VOICE", "").strip()):
        if backend not in VOICE_BACKENDS:
            log(f"ERROR: asked for '{args.tts}' but audio came from '{backend}' — "
                "not uploading a fallback-voice render")
            notify(f"Chess autopost: rendered with fallback voice '{backend}'; upload held.")
            entry["status"] = "held_fallback_voice"
            record_publication(entry)
            return 1

    # 3) Upload (optional)
    if args.no_upload:
        log("upload skipped (--no-upload)")
        entry["status"] = "not_uploaded"
        record_publication(entry)
    elif not have_upload_creds():
        log("upload skipped: GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN not set in .env")
        log(f"the finished video is at: {VIDEO_PATH}")
        entry["status"] = "no_credentials"
        record_publication(entry)
    else:
        try:
            result = upload_video(args.privacy, dry_run=args.dry_run_upload) or {}
            entry.update(
                status="uploaded",
                videoId=result.get("videoId"),
                url=result.get("url"),
                title=result.get("title"),
                privacy=args.privacy,
            )
            record_publication(entry)
            if result.get("url"):
                log(f"published: {result['url']}")
            notify(f"Chess autopost: uploaded daily video ({pgn_path.name}).")
        except subprocess.CalledProcessError as e:
            log(f"ERROR: upload failed with exit code {e.returncode}")
            # Record the failure so the archived video can be retried later.
            entry.update(status="upload_failed", exitCode=e.returncode)
            record_publication(entry)
            notify(f"Chess autopost: render OK but upload FAILED ({pgn_path.name}).")
            return e.returncode

    log("daily pipeline complete ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
