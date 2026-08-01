"""Write an SRT subtitle file from the render's own word timings.

    python services/orchestrator/make_captions.py            # outputs/captions.srt

YouTube will transcribe the video itself, but it is guessing at audio it has
never seen, and chess notation is exactly what speech recognition gets wrong:
"Bxf6" and "e4" come back as "b x f six" or "before". We already know every
word and when it was spoken — whisperx aligned each take against its own text
before the clips were sliced — so the captions can simply be *correct*, with
the notation spelled the way a chess viewer expects to read it.

That matters beyond accessibility: caption text is indexed, so a video whose
captions say "Nimzo-Indian" is findable by people searching for it, and one
whose captions say "nimzo indian defence" is not.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"

# A cue should be readable in one glance and gone before the next thought.
MAX_CHARS = 74          # two comfortable lines at YouTube's default size
MAX_SECONDS = 5.5
MAX_GAP = 0.8           # a pause this long ends the cue, wherever it falls

_A_FILE_CAPS = re.compile(r"(?<![A-Za-z0-9])A([1-8])(?![a-z0-9])")


def _fmt(t: float) -> str:
    if t < 0:
        t = 0.0
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _cased_words(text: str, aligned: List[Dict[str, Any]]) -> List[str]:
    """Recover the beat's own spelling for each aligned (lowercased) word.

    Alignment normalises: it returns "bxf6" for "Bxf6" and drops punctuation.
    The beat text is what the narrator was given, so it carries the capitals,
    the commas and the em dashes — which is what a reader wants. Falls back to
    the aligned token whenever the two drift apart.
    """
    src = text.split()
    out: List[str] = []
    i = 0
    for w in aligned:
        want = re.sub(r"[^a-z0-9]", "", (w.get("w") or "").lower())
        picked: Optional[str] = None
        # Look a little way ahead: alignment occasionally drops a token.
        for j in range(i, min(i + 4, len(src))):
            if re.sub(r"[^a-z0-9]", "", src[j].lower()) == want:
                picked = src[j]
                i = j + 1
                break
        word = picked if picked is not None else (w.get("w") or "")
        # The a-file is capitalised in the narration so the voice says "ay
        # four" rather than the article — but algebraic notation is written in
        # lower case, so the reader gets it back the conventional way.
        out.append(_A_FILE_CAPS.sub(lambda m: "a" + m.group(1), word))
    return out


def build_cues(script: Dict[str, Any], manifest: Dict[str, Any]) -> List[Tuple[float, float, str]]:
    clips = manifest.get("clips") or {}
    cues: List[Tuple[float, float, str]] = []

    at = 0.0
    cur: List[str] = []
    start: Optional[float] = None
    end = 0.0

    def flush() -> None:
        nonlocal cur, start
        if cur and start is not None:
            cues.append((start, end, " ".join(cur)))
        cur, start = [], None

    for beat in script.get("beats", []):
        dur = (beat.get("durationMs") or 0) / 1000.0
        clip = clips.get(beat["id"])
        words = (clip or {}).get("words") or []
        if words:
            spelled = _cased_words(beat.get("text") or "", words)
            for w, text in zip(words, spelled):
                ws, we = at + float(w["s"]), at + float(w["e"])
                too_long = len(" ".join(cur + [text])) > MAX_CHARS
                too_slow = start is not None and we - start > MAX_SECONDS
                after_gap = bool(cur) and ws - end > MAX_GAP
                if cur and (too_long or too_slow or after_gap):
                    flush()
                if start is None:
                    start = ws
                cur.append(text)
                end = we
                # A sentence ending is the most natural place to cut.
                if text.rstrip('"”’)').endswith((".", "!", "?")):
                    flush()
        at += dur
    flush()
    return cues


def to_srt(cues: List[Tuple[float, float, str]]) -> str:
    parts = []
    for n, (s, e, text) in enumerate(cues, 1):
        # Never let a cue outlive its successor's start, and never flash.
        e = max(e, s + 0.5)
        parts.append(f"{n}\n{_fmt(s)} --> {_fmt(e)}\n{text}\n")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="Write captions from word timings")
    ap.add_argument("--script", default=str(OUT / "script.json"))
    ap.add_argument("--manifest", default=str(OUT / "audio_manifest.json"))
    ap.add_argument("--out", default=str(OUT / "captions.srt"))
    args = ap.parse_args()

    try:
        script = json.loads(Path(args.script).read_text(encoding="utf-8"))
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[captions] cannot read inputs: {exc}")
        return 2

    cues = build_cues(script, manifest)
    if not cues:
        print("[captions] no aligned words; nothing written")
        return 1

    dest = Path(args.out)
    dest.write_text(to_srt(cues), encoding="utf-8")
    spoken = sum(e - s for s, e, _ in cues)
    print(f"[captions] {len(cues)} cues covering {spoken / 60:.1f} min -> "
          f"{dest.relative_to(ROOT) if dest.is_relative_to(ROOT) else dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
