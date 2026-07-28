"""One-time voice setup for the local Qwen3-TTS backend.

Run this once to create the channel's narrator voice, then never again — the
result is a short reference clip that every future video is cloned from, so the
voice stays identical across the whole channel.

    # audition the built-in presets
    python services/orchestrator/voice_design.py --list
    python services/orchestrator/voice_design.py --preset velvet

    # or describe your own
    python services/orchestrator/voice_design.py --describe "a warm, low female voice..."

The chosen clip is written to storage/voice/narrator.wav and its transcript to
storage/voice/narrator.txt. Point VOICE_REF_AUDIO at it and set TTS_BACKEND=qwen.

Why *design* a voice instead of cloning one:
Qwen can clone any voice from three seconds of audio, which makes it trivially
easy to clone a real person off YouTube. Don't. A real person's voice is
protected by right-of-publicity law in most US states (and specifically by
statutes like Tennessee's ELVIS Act), so a cloned celebrity narrator is a
lawsuit and a channel strike waiting to happen. A designed voice belongs to
nobody, so it is yours to monetize.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VOICE_DIR = ROOT / "storage" / "voice"

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# The audition line — long enough to judge tone, and representative of what the
# narrator actually says all day.
AUDITION_TEXT = (
    "Before we see what happened, take in this position. Black is a little "
    "better here, but nothing is decided yet, and the move that comes next "
    "changes everything."
)

# Voice descriptions, written for a calm chess-analysis channel. Qwen's
# VoiceDesign model takes free-form English, so treat these as starting points
# and edit the wording — small changes to the adjectives matter a lot.
PRESETS = {
    "velvet": (
        "A warm, sultry female voice in a low register. Smooth and unhurried, "
        "with a soft breathy quality and gentle downward inflections. Intimate, "
        "close-miked, like late-night radio. Relaxed pace, never rushed."
    ),
    "smoke": (
        "A husky, smoky female voice, low and a little raspy. Confident and "
        "knowing, with a slow, deliberate delivery and long relaxed vowels. "
        "Mature and self-assured rather than girlish."
    ),
    "hush": (
        "A very soft, breathy female voice, close and quiet as if speaking near "
        "the microphone. Calm, soothing, ASMR-adjacent, with a slow tempo and "
        "minimal pitch variation. Gentle and warm."
    ),
    "poised": (
        "An elegant, composed female voice with a warm mid-low register and "
        "crisp diction. Measured and articulate, quietly authoritative, with a "
        "subtle warmth underneath. Documentary narrator quality."
    ),
    "ember": (
        "A rich, velvety female voice with a dark, resonant tone. Slow and "
        "deliberate, with a slight vocal fry at the end of phrases. Alluring "
        "but never theatrical — understated and grown-up."
    ),
}


def build_model(model_id: str):
    import torch
    from qwen_tts import Qwen3TTSModel

    # flash-attention-2 frequently fails to build on Windows; sdpa is the safe
    # default and the speed difference is irrelevant for ~110 short lines.
    attn = os.getenv("QWEN_ATTN", "sdpa")
    device = os.getenv("QWEN_DEVICE", "cuda:0")
    print(f"[voice] loading {model_id} on {device} (attn={attn})…")
    return Qwen3TTSModel.from_pretrained(
        model_id,
        device_map=device,
        dtype=torch.bfloat16,
        attn_implementation=attn,
    )


def design(instruct: str, out_path: Path, text: str = AUDITION_TEXT) -> Path:
    import soundfile as sf

    model = build_model(
        os.getenv("QWEN_DESIGN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    )
    wavs, sr = model.generate_voice_design(
        text=text,
        language="English",
        instruct=instruct,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), wavs[0], sr)
    out_path.with_suffix(".txt").write_text(text, encoding="utf-8")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Design the channel's narrator voice")
    ap.add_argument("--preset", choices=sorted(PRESETS), help="Use a built-in description")
    ap.add_argument("--describe", help="Your own free-form voice description")
    ap.add_argument("--text", default=AUDITION_TEXT, help="Line to speak in the audition")
    ap.add_argument("--all", action="store_true", help="Render every preset for comparison")
    ap.add_argument("--list", action="store_true", help="Show the presets and exit")
    ap.add_argument(
        "--out",
        default=str(VOICE_DIR / "narrator.wav"),
        help="Where to write the reference clip",
    )
    args = ap.parse_args()

    if args.list:
        for name, desc in PRESETS.items():
            print(f"\n--- {name} ---\n{desc}")
        print("\nAudition one:  --preset velvet")
        print("Compare all :  --all   (writes storage/voice/audition_*.wav)")
        return 0

    if args.all:
        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        for name, desc in PRESETS.items():
            path = VOICE_DIR / f"audition_{name}.wav"
            print(f"[voice] rendering '{name}'…")
            design(desc, path, args.text)
            print(f"        -> {path}")
        print("\nListen to them, then re-run with --preset <name> to make it the narrator.")
        return 0

    instruct = args.describe or (PRESETS[args.preset] if args.preset else None)
    if not instruct:
        print("Pick one: --preset <name>, --describe \"...\", --all, or --list")
        return 2

    out = Path(args.out)
    design(instruct, out, args.text)
    print(f"\n[ok] narrator voice written to {out}")
    print(f"[ok] reference transcript at {out.with_suffix('.txt')}")
    print("\nNow set these in .env:")
    print("  TTS_BACKEND=qwen")
    print(f"  VOICE_REF_AUDIO={out}")
    print(f"  VOICE_REF_TEXT={out.with_suffix('.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
