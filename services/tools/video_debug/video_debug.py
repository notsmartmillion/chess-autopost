#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)

# Defaults
DEFAULT_INPUT = Path("apps/renderer/out/ChessVideo.mp4")
DEFAULT_OUTROOT = Path("outputs/video_debug")
TIME_RE = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2})(?:\.(\d{1,3}))?$")


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        typer.secho("ffmpeg not found in PATH. Install ffmpeg and retry.", fg=typer.colors.RED)
        raise typer.Exit(1)


def ensure_ffprobe() -> None:
    if shutil.which("ffprobe") is None:
        typer.secho("ffprobe not found in PATH (comes with ffmpeg).", fg=typer.colors.YELLOW)


def parse_time_to_seconds(t: str) -> float:
    t = t.strip()
    if t.isdigit() or re.match(r"^\d+(\.\d+)?$", t):
        return float(t)
    m = TIME_RE.match(t)
    if not m:
        raise typer.BadParameter(f"Invalid timestamp: {t}")
    hh, mm, ss, ms = m.groups()
    h = int(hh) if hh else 0
    m_ = int(mm)
    s = int(ss)
    ms_ = int(ms) if ms else 0
    return h * 3600 + m_ * 60 + s + ms_ / 1000.0


def seconds_to_hhmmss(sec: float) -> str:
    msec = int(round((sec - int(sec)) * 1000))
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{msec:03d}"


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def make_session_dir(out_dir: Optional[Path]) -> Path:
    base = out_dir or DEFAULT_OUTROOT / timestamp()
    base.mkdir(parents=True, exist_ok=True)
    (base / "frames").mkdir(exist_ok=True, parents=True)
    return base


def run(cmd: List[str], cwd: Optional[Path] = None) -> None:
    typer.secho("$ " + " ".join(cmd), fg=typer.colors.BLUE)
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        raise typer.Exit(proc.returncode)


def write_run_json(session: Path, payload: dict) -> None:
    with (session / "run.json").open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)


def record_versions() -> dict:
    def get_ver(bin_name: str) -> Optional[str]:
        try:
            out = subprocess.check_output([bin_name, "-version"], stderr=subprocess.STDOUT)
            return out.decode("utf-8", errors="ignore").splitlines()[0].strip()
        except Exception:
            return None

    return {"ffmpeg": get_ver("ffmpeg"), "ffprobe": get_ver("ffprobe")}


def resolve_input(input_path: Optional[Path]) -> Path:
    p = Path(input_path) if input_path else DEFAULT_INPUT
    if not p.exists():
        typer.secho(f"Input not found: {p}", fg=typer.colors.RED)
        raise typer.Exit(1)
    return p


@dataclass
class RunMeta:
    input: str
    session: str
    command: str
    args: dict
    versions: dict


@app.callback()
def _root():
    ensure_ffmpeg()
    ensure_ffprobe()


@app.command(help="Cut a micro-clip")
def clip(
    start: str = typer.Option(..., help="Start time HH:MM:SS.mmm or seconds"),
    dur: float = typer.Option(..., help="Duration (seconds)"),
    width: int = typer.Option(960, help="Scale width (height auto)"),
    input: Optional[Path] = typer.Option(None, "--input"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir"),
):
    src = resolve_input(input)
    session = make_session_dir(out_dir)
    ss = seconds_to_hhmmss(parse_time_to_seconds(start))
    out = session / "clip.mp4"
    run(["ffmpeg", "-y", "-ss", ss, "-i", str(src), "-t", str(dur), "-vf", f"scale={width}:-1",
         "-an", "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", str(out)])
    write_run_json(session, asdict(RunMeta(str(src), str(session), "clip", {"start": start, "dur": dur, "width": width}, record_versions())))
    typer.secho(f"Wrote {out}", fg=typer.colors.GREEN)


@app.command(help="High-quality GIF using palettegen/paletteuse")
def gif(
    start: str = typer.Option(...),
    dur: float = typer.Option(...),
    width: int = typer.Option(720),
    fps: int = typer.Option(8),
    input: Optional[Path] = typer.Option(None, "--input"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir"),
):
    src = resolve_input(input)
    session = make_session_dir(out_dir)
    ss = seconds_to_hhmmss(parse_time_to_seconds(start))
    clip_tmp = session / "_gif_src.mp4"
    run(["ffmpeg", "-y", "-ss", ss, "-i", str(src), "-t", str(dur), "-an", "-vf", f"scale={width}:-1", str(clip_tmp)])
    palette = session / "palette.png"
    run(["ffmpeg", "-y", "-i", str(clip_tmp), "-vf", f"fps={fps},scale={width}:-1:flags=lanczos,palettegen", str(palette)])
    out = session / "clip.gif"
    run(["ffmpeg", "-y", "-i", str(clip_tmp), "-i", str(palette), "-lavfi", f"fps={fps},scale={width}:-1:flags=lanczos[p];[p][1:v]paletteuse", str(out)])
    write_run_json(session, asdict(RunMeta(str(src), str(session), "gif", {"start": start, "dur": dur, "width": width, "fps": fps}, record_versions())))
    typer.secho(f"Wrote {out}", fg=typer.colors.GREEN)


@app.command("frames", help="Extract frames every N seconds or via FPS")
def frames_every(
    start: Optional[str] = typer.Option(None),
    every: Optional[float] = typer.Option(None, help="Every N seconds"),
    fps: Optional[float] = typer.Option(None, help="Use FPS instead (mutually exclusive)"),
    input: Optional[Path] = typer.Option(None, "--input"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir"),
):
    if every and fps:
        raise typer.BadParameter("Use either --every or --fps, not both")
    src = resolve_input(input)
    session = make_session_dir(out_dir)
    vf = []
    if fps:
        vf.append(f"fps={fps}")
    elif every:
        vf.append(f"fps={max(0.0001, 1.0/every)}")
    else:
        vf.append("fps=1")
    pre = []
    if start:
        pre = ["-ss", seconds_to_hhmmss(parse_time_to_seconds(start))]
    out_pattern = session / "frames" / "frame_%04d.png"
    run(["ffmpeg", "-y", *pre, "-i", str(src), "-vf", ",".join(vf), "-vsync", "vfr", str(out_pattern)])
    write_run_json(session, asdict(RunMeta(str(src), str(session), "frames", {"start": start, "every": every, "fps": fps}, record_versions())))
    typer.secho(f"Wrote frames to {out_pattern.parent}", fg=typer.colors.GREEN)


@app.command("frames-at", help="Extract exact timestamps")
def frames_at(
    times: str = typer.Option(..., help="Comma-separated seconds or HH:MM:SS(.ms) list"),
    input: Optional[Path] = typer.Option(None, "--input"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir"),
):
    src = resolve_input(input)
    session = make_session_dir(out_dir)
    secs = [parse_time_to_seconds(t) for t in times.split(",")]
    select_terms = [f"eq(t\\,{t})" for t in secs]
    vf = f"select='{'+'.join(select_terms)}',setpts=N/FRAME_RATE/TB"
    tmp = session / "frame_%06d.png"
    run(["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-vsync", "vfr", str(tmp)])
    produced = sorted(tmp.parent.glob("frame_*.png"))
    for idx, p in enumerate(produced):
        t = secs[idx] if idx < len(secs) else idx
        p.rename(session / f"frame_{seconds_to_hhmmss(t).replace(':','-')}.png")
    write_run_json(session, asdict(RunMeta(str(src), str(session), "frames-at", {"times": secs}, record_versions())))
    typer.secho(f"Wrote frames to {session}", fg=typer.colors.GREEN)


@app.command("scene-detect", help="Detect scene changes; PySceneDetect if available else FFmpeg")
def scene_detect(
    threshold: float = typer.Option(0.4),
    max: int = typer.Option(20),
    input: Optional[Path] = typer.Option(None, "--input"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir"),
    use_pyscenedetect: bool = typer.Option(False),
):
    src = resolve_input(input)
    session = make_session_dir(out_dir)

    if use_pyscenedetect and shutil.which("scenedetect"):
        run(["scenedetect", "--input", str(src), "detect-content", "list-scenes", "--output", str(session), "save-images", "--num-images", str(max)])
        write_run_json(session, asdict(RunMeta(str(src), str(session), "scene-detect(pyscenedetect)", {"threshold": "auto", "max": max}, record_versions())))
        typer.secho(f"Wrote scene images to {session}", fg=typer.colors.GREEN)
        return

    out_pattern = session / "scene_%03d.png"
    run(["ffmpeg", "-y", "-i", str(src), "-vf", f"select='gt(scene\\,{threshold})'", "-vsync", "vfr", "-vframes", str(max), str(out_pattern)])
    write_run_json(session, asdict(RunMeta(str(src), str(session), "scene-detect(ffmpeg)", {"threshold": threshold, "max": max}, record_versions())))
    typer.secho(f"Wrote scenes to {session}", fg=typer.colors.GREEN)


@app.command(help="Contact sheet from a clip or video")
def contact(
    grid: str = typer.Option("5x5"),
    tile_width: int = typer.Option(320),
    from_: Optional[Path] = typer.Option(None, "--from"),
    input: Optional[Path] = typer.Option(None, "--input"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir"),
):
    src = Path(from_) if from_ else resolve_input(input)
    session = make_session_dir(out_dir)
    cols, rows = [int(x) for x in grid.lower().split("x")]
    vf = f"fps=4,scale={tile_width}:-1,tile={cols}x{rows}"
    out = session / "contact_sheet.png"
    run(["ffmpeg", "-y", "-i", str(src), "-vf", vf, str(out)])
    write_run_json(session, asdict(RunMeta(str(src), str(session), "contact", {"grid": grid, "tile_width": tile_width}, record_versions())))
    typer.secho(f"Wrote {out}", fg=typer.colors.GREEN)


@app.command(help="Redact a rectangular region with blur")
def redact(
    box: str = typer.Option(..., help="x,y,w,h"),
    blur: int = typer.Option(15),
    from_: Optional[Path] = typer.Option(None, "--from"),
    input: Optional[Path] = typer.Option(None, "--input"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir"),
):
    src = Path(from_) if from_ else resolve_input(input)
    session = make_session_dir(out_dir)
    x, y, w, h = [int(v) for v in box.split(",")]
    vf = f"boxblur=luma_radius={blur}:luma_power=3,drawbox=x={x}:y={y}:w={w}:h={h}:color=black@0:thickness=fill"
    out = session / "redacted.mp4"
    run(["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", str(out)])
    write_run_json(session, asdict(RunMeta(str(src), str(session), "redact", {"box": box, "blur": blur}, record_versions())))
    typer.secho(f"Wrote {out}", fg=typer.colors.GREEN)


@app.command(help="Preset: clip + gif + frames around a center time")
def preset(
    name: str = typer.Option(...),
    center: str = typer.Option(...),
    pre: float = typer.Option(2.0),
    post: float = typer.Option(6.0),
    width: int = typer.Option(960),
    gif_width: int = typer.Option(720),
    fps: int = typer.Option(8),
    input: Optional[Path] = typer.Option(None, "--input"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir"),
):
    src = resolve_input(input)
    session = make_session_dir(out_dir)
    c = parse_time_to_seconds(center)
    clip_start = max(0.0, c - pre)
    clip_dur = pre + post
    # clip
    clip(start=seconds_to_hhmmss(clip_start), dur=clip_dur, width=width, input=src, out_dir=session)
    # gif
    gif(start=seconds_to_hhmmss(clip_start), dur=min(6.0, clip_dur), width=gif_width, fps=fps, input=src, out_dir=session)
    # frames every 0.5s
    frames_every(start=seconds_to_hhmmss(clip_start), every=0.5, fps=None, input=src, out_dir=session)
    write_run_json(session, asdict(RunMeta(str(src), str(session), "preset", {"name": name, "center": center, "pre": pre, "post": post}, record_versions())))
    notes = session / "notes.txt"
    if not notes.exists():
        notes.write_text(f"[{name}] center={center}\n", encoding="utf-8")
    typer.secho(f"Preset complete. Session: {session}", fg=typer.colors.GREEN)


@app.command(help="Append a one-liner to notes.txt in the session dir")
def note(text: str = typer.Argument(...), out_dir: Optional[Path] = typer.Option(None, "--out-dir")):
    session = make_session_dir(out_dir)
    with (session / "notes.txt").open("a", encoding="utf-8") as fp:
        fp.write(text.strip() + "\n")
    typer.secho(f"Appended note to {session / 'notes.txt'}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()






