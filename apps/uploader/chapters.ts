/**
 * Generate YouTube chapters from the narration beat script.
 *
 * Chapters are derived from the same beats that drive the video, so the
 * timestamps are exact rather than estimated: each beat carries the measured
 * duration of its narration clip.
 */

import type { Beat, Script } from '../renderer/src/types/script';

export interface Chapter {
  time: string; // "0:00" / "12:34"
  title: string;
}

/** YouTube requires the first chapter at 0:00 and at least three chapters. */
export function generateChapters(script: Script): Chapter[] {
  const chapters: Chapter[] = [{ time: formatTime(0), title: 'Introduction' }];

  let cursorMs = 0;
  let lastChapterMs = 0;
  let phase: 'opening' | 'middlegame' | 'endgame' = 'opening';

  // Never place two chapters closer than this — YouTube renders them unusably.
  const MIN_GAP_MS = 25_000;

  for (const beat of script.beats) {
    const startMs = cursorMs;
    cursorMs += beat.durationMs || 0;

    if (beat.kind === 'intro' || beat.kind === 'outro') continue;

    const moveNumber = beat.ply ? Math.ceil(beat.ply / 2) : 0;

    // Phase transitions.
    if (phase === 'opening' && moveNumber >= 12) {
      phase = 'middlegame';
      if (startMs - lastChapterMs >= MIN_GAP_MS) {
        chapters.push({ time: formatTime(startMs), title: 'Middlegame' });
        lastChapterMs = startMs;
      }
      continue;
    }
    if (phase === 'middlegame' && moveNumber >= 32) {
      phase = 'endgame';
      if (startMs - lastChapterMs >= MIN_GAP_MS) {
        chapters.push({ time: formatTime(startMs), title: 'Endgame' });
        lastChapterMs = startMs;
      }
      continue;
    }

    // Notable moments get their own chapter.
    const title = notableTitle(beat, moveNumber);
    if (title && startMs - lastChapterMs >= MIN_GAP_MS) {
      chapters.push({ time: formatTime(startMs), title });
      lastChapterMs = startMs;
    }
  }

  if (cursorMs > 0) {
    chapters.push({ time: formatTime(Math.max(0, cursorMs - 8000)), title: 'Final thoughts' });
  }
  return chapters;
}

function notableTitle(beat: Beat, moveNumber: number): string | null {
  const move = beat.move?.san;
  const prefix = moveNumber ? `Move ${moveNumber}` : 'Key moment';

  if (beat.kind === 'variation') {
    return beat.label ? `${prefix}: ${beat.label}` : null;
  }
  switch (beat.tag) {
    case 'blunder':
      return `${prefix}: the losing mistake${move ? ` (${move})` : ''}`;
    case 'mistake':
      return `${prefix}: a costly error${move ? ` (${move})` : ''}`;
    case 'brilliant':
      return `${prefix}: brilliancy${move ? ` (${move})` : ''}`;
    case 'great':
      return `${prefix}: the key idea${move ? ` (${move})` : ''}`;
    default:
      return null;
  }
}

/** Format milliseconds as YouTube chapter time. */
export function formatTime(timeMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(timeMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

export function generateChaptersText(script: Script): string {
  const chapters = generateChapters(script);
  if (chapters.length < 3) {
    // Below three chapters YouTube ignores them entirely; emit nothing.
    return '';
  }
  return ['Chapters:', ...chapters.map((c) => `${c.time} ${c.title}`)].join('\n');
}
