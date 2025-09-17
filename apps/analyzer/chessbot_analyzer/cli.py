"""CLI for chess analyzer with audio-sync pipeline."""

import typer
import json
from pathlib import Path
from typing import Optional
from .config import settings
from .timeline import TimelineBuilder
from .scripting import ScriptGenerator
from .utils.logging import setup_logging, get_logger

app = typer.Typer()
logger = get_logger(__name__)


@app.command()
def ingest(
    source: str = typer.Option(..., help="Data source: lichess, chesscom, twic, manual"),
    path: str = typer.Option(..., help="Path to PGN file or data source"),
    output_dir: str = typer.Option("./outputs", help="Output directory")
):
    """Ingest games from various sources into database."""
    logger.info(f"Ingesting games from {source}: {path}")
    
    # TODO: Implement actual ingestion
    # For now, just create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    typer.echo(f"Games ingested from {source} to {output_dir}")


@app.command()
def select(
    strategy: str = typer.Option("anniversary-or-topscore", help="Selection strategy"),
    output_file: str = typer.Option("game_id.txt", help="Output file for selected game ID")
):
    """Select today's game for analysis."""
    logger.info(f"Selecting game with strategy: {strategy}")
    
    # TODO: Implement actual game selection
    # For now, return a sample game ID
    game_id = 123
    
    with open(output_file, 'w') as f:
        f.write(str(game_id))
    
    typer.echo(f"Selected game ID: {game_id}")


@app.command()
def analyse(
    game_id: int = typer.Option(..., help="Game ID to analyze"),
    out: str = typer.Option("timeline.json", help="Output timeline file"),
    audio_dir: Optional[str] = typer.Option(None, help="Audio directory for duration calculation"),
    alignment_file: Optional[str] = typer.Option(None, help="Alignment data file")
):
    """Analyze game and generate timeline with audio-sync."""
    logger.info(f"Analyzing game {game_id}")
    
    # Initialize timeline builder
    builder = TimelineBuilder()
    
    # Load audio durations if available
    audio_durations = None
    if audio_dir:
        audio_durations = builder.load_audio_durations(audio_dir)
        logger.info(f"Loaded {len(audio_durations)} audio durations")
    
    # Build timeline
    timeline = builder.from_game(game_id, audio_durations)
    
    # Apply alignment data if available
    if alignment_file and Path(alignment_file).exists():
        timeline = builder.apply_alignment_data(timeline, alignment_file)
        logger.info("Applied alignment data")
    
    # Save timeline
    builder.save(timeline, out)
    
    typer.echo(f"Timeline generated: {out}")
    typer.echo(f"Total duration: {timeline.totalDurationMs}ms")
    typer.echo(f"Scenes: {len(timeline.scenes)}")


@app.command()
def script(
    timeline: str = typer.Option(..., help="Timeline JSON file"),
    out: str = typer.Option("lines.json", help="Output voice lines file"),
    optimize: bool = typer.Option(True, help="Optimize for audio sync")
):
    """Generate voice script from timeline."""
    logger.info(f"Generating script from {timeline}")
    
    # Load timeline
    with open(timeline, 'r') as f:
        timeline_data = json.load(f)
    
    timeline_obj = Timeline(**timeline_data)
    
    # Generate script
    generator = ScriptGenerator()
    voice_lines = generator.from_timeline(timeline_obj)
    
    # Optimize for audio sync if requested
    if optimize:
        voice_lines = generator.optimize_for_audio_sync(voice_lines)
        logger.info("Optimized script for audio sync")
    
    # Save voice lines
    with open(out, 'w') as f:
        json.dump(voice_lines, f, indent=2)
    
    typer.echo(f"Voice script generated: {out}")
    typer.echo(f"Voice lines: {len(voice_lines)}")


@app.command()
def pipeline(
    game_id: int = typer.Option(..., help="Game ID to process"),
    output_dir: str = typer.Option("./outputs", help="Output directory"),
    audio_dir: Optional[str] = typer.Option(None, help="Audio directory"),
    alignment_file: Optional[str] = typer.Option(None, help="Alignment data file")
):
    """Run complete analysis pipeline with audio-sync."""
    logger.info(f"Running complete pipeline for game {game_id}")
    
    # Ensure output directory exists
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Step 1: Analyze game and generate timeline
    timeline_file = Path(output_dir) / "timeline.json"
    typer.echo("Step 1: Analyzing game...")
    
    builder = TimelineBuilder()
    audio_durations = None
    if audio_dir:
        audio_durations = builder.load_audio_durations(audio_dir)
    
    timeline = builder.from_game(game_id, audio_durations)
    
    if alignment_file and Path(alignment_file).exists():
        timeline = builder.apply_alignment_data(timeline, alignment_file)
    
    builder.save(timeline, str(timeline_file))
    
    # Step 2: Generate voice script
    lines_file = Path(output_dir) / "lines.json"
    typer.echo("Step 2: Generating voice script...")
    
    generator = ScriptGenerator()
    voice_lines = generator.from_timeline(timeline)
    voice_lines = generator.optimize_for_audio_sync(voice_lines)
    
    with open(lines_file, 'w') as f:
        json.dump(voice_lines, f, indent=2)
    
    # Step 3: Generate summary
    typer.echo("Step 3: Pipeline complete!")
    typer.echo(f"Timeline: {timeline_file}")
    typer.echo(f"Voice lines: {lines_file}")
    typer.echo(f"Total duration: {timeline.totalDurationMs}ms")
    typer.echo(f"Scenes: {len(timeline.scenes)}")
    typer.echo(f"Voice lines: {len(voice_lines)}")
    
    # Next steps
    typer.echo("\nNext steps:")
    typer.echo(f"1. Generate audio: voice synth --lines {lines_file} --voice-id VOICE_ID --out {audio_dir or './audio'}")
    if not alignment_file:
        typer.echo(f"2. Align audio: voice align --lines {lines_file} --audio-dir {audio_dir or './audio'} --output alignment.json")
    typer.echo(f"3. Render video: renderer render --timeline {timeline_file} --audio-dir {audio_dir or './audio'}")


@app.command()
def config():
    """Show current configuration."""
    typer.echo("Current configuration:")
    typer.echo(f"Database URL: {settings.DB_URL}")
    typer.echo(f"Stockfish path: {settings.STOCKFISH_PATH}")
    typer.echo(f"Engine threads: {settings.ENGINE_THREADS}")
    typer.echo(f"Engine hash: {settings.ENGINE_HASH_MB}MB")
    typer.echo(f"Engine depth: {settings.ENGINE_DEPTH}")
    typer.echo(f"Engine MultiPV: {settings.ENGINE_MULTIPV}")
    typer.echo(f"Alt preview plies: {settings.ALT_PREVIEW_PLIES}")
    typer.echo(f"Max scene duration: {settings.MAX_SCENE_DURATION_MS}ms")


if __name__ == "__main__":
    setup_logging()
    app()
