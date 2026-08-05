"""Render the channel's current thumbnail for a game, standalone.

    python services/orchestrator/make_thumbnail.py --pgn outputs/pgns/daily/x.pgn
    python services/orchestrator/make_thumbnail.py --script outputs/videos/G/G.json

Videos published before a design change keep the thumbnail they were born
with, and a channel whose front page mixes two templates looks like two
channels. Re-rendering the whole video to fix a picture costs forty minutes
and, worse, a new video id — losing the views and watch history the old one
had earned. This regenerates just the image.

Deliberately touches none of the shared build state: not outputs/facts.json,
not outputs/script.json, and not renderer/public/script.json. Those belong to
whatever build is running, and a daily pipeline is often running. The script
is handed to Remotion through --props instead.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "apps" / "renderer"
PUB = RENDERER / "public"

sys.path.insert(0, str(ROOT / "apps" / "analyzer"))
sys.path.insert(0, str(ROOT / "services" / "orchestrator"))


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def attach_portraits(script: Dict[str, Any]) -> None:
    """Same wiring build_video does: cache the faces, then point at them."""
    meta = script.setdefault("meta", {})
    try:
        import portraits_fetch  # noqa: PLC0415

        portraits_fetch.ensure(meta.get("white"), meta.get("black"))
    except Exception as exc:  # noqa: BLE001
        print(f"[portraits] skipped ({exc})")
    for side, key in (("white", "whitePortrait"), ("black", "blackPortrait")):
        name = (meta.get(side) or "").split(",")[0].strip().lower()
        if not name:
            continue
        for ext in ("jpg", "jpeg", "png", "webp"):
            if (PUB / "portraits" / f"{name}.{ext}").exists():
                meta[key] = f"{name}.{ext}"
                break


def script_from_pgn(pgn_path: Path, use_llm: bool, depth: Optional[int]) -> Dict[str, Any]:
    from chessbot_analyzer.facts import extract_facts  # noqa: PLC0415
    from chessbot_analyzer.director import build_script  # noqa: PLC0415

    pgn = pgn_path.read_text(encoding="utf-8", errors="ignore")
    print(f"[facts] analysing {pgn_path.name}…")
    facts = extract_facts(pgn, depth=depth)
    print(f"[facts] {len(facts.get('plies') or [])} plies")
    # The overlay line is model-written, and it is most of what makes the card
    # read as ours — so the LLM is on by default even though nothing else here
    # needs it.
    return build_script(
        facts,
        channel_name=os.getenv("CHANNEL_NAME", "Nocturne Chess"),
        use_llm=use_llm,
    )


def render(script: Dict[str, Any], out_path: Path) -> int:
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not (npm and npx):
        print("[thumb] npm/npx not found")
        return 2
    if not (RENDERER / "node_modules").exists():
        subprocess.check_call([npm, "install", "--no-audit", "--no-fund"],
                              cwd=str(RENDERER))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="thumbprops-"))
    props = tmp / "props.json"
    props.write_text(json.dumps({"script": script}, ensure_ascii=False),
                     encoding="utf-8")
    try:
        subprocess.check_call(
            [npx, "remotion", "still", "src/index.tsx", "Thumbnail",
             str(out_path.resolve()), "--frame=12", "--overwrite",
             f"--props={props.resolve()}"],
            cwd=str(RENDERER),
        )
    except subprocess.CalledProcessError as exc:
        print(f"[thumb] render failed ({exc.returncode})")
        return exc.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    meta = script.get("meta") or {}
    print(f"[thumb] {meta.get('whiteFull')} vs {meta.get('blackFull')} "
          f"-> {out_path}")
    print(f"[thumb] overlay: {(meta.get('llmThumb') or '(template)')!r}")
    return 0


def main() -> int:
    _load_dotenv()
    ap = argparse.ArgumentParser(description="Render one thumbnail, standalone")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pgn", help="Rebuild the script from this PGN")
    src.add_argument("--script", help="Use an existing script.json")
    ap.add_argument("--out", required=True, help="Where to write the PNG")
    ap.add_argument("--no-llm", action="store_true",
                    help="Skip the model-written overlay line")
    ap.add_argument("--depth", type=int, default=None)
    args = ap.parse_args()

    if args.script:
        script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    else:
        pgn = Path(args.pgn)
        if not pgn.is_absolute():
            pgn = ROOT / pgn
        script = script_from_pgn(pgn, use_llm=not args.no_llm, depth=args.depth)

    attach_portraits(script)
    return render(script, Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
