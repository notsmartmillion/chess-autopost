/**
 * Browser-safe audio & timing utilities for the Remotion renderer.
 * - Loads timeline and measured audio durations via fetch(staticFile(...)).
 * - Provides math helpers for cue timings and frame calculations.
 *
 * NOTE: Do not use Node APIs (fs, path, child_process) in this file.
 */

import {staticFile} from 'remotion';

export type Durations = Record<string, number>;

/** Load timeline.json that build_video.py writes to /public */
export async function loadTimeline<T = any>(): Promise<T> {
  const res = await fetch(staticFile('timeline.json'));
  if (!res.ok) throw new Error(`timeline.json ${res.status}`);
  return res.json();
}

/** Load optional audio_durations.json for precise VO trimming */
export async function loadDurations(): Promise<Durations> {
  try {
    const res = await fetch(staticFile('audio_durations.json'));
    if (!res.ok) return {};
    return res.json();
  } catch {
    return {};
  }
}

/** Precompute scene segments (from frame + length in frames) */
export function computeSegments(
  scenes: {id: string; durationMs: number}[],
  fps: number
): Array<{id: string; from: number; frames: number}> {
  let cursor = 0;
  return scenes.map((s) => {
    const frames = Math.max(1, Math.round((s.durationMs * fps) / 1000));
    const out = {id: s.id, from: cursor, frames};
    cursor += frames;
    return out;
  });
}

/** Convert time (ms) <-> frame helpers */
export function timeToFrame(timeMs: number, fps: number): number {
  return Math.round((timeMs / 1000) * fps);
}

export function frameToTime(frame: number, fps: number): number {
  return (frame / fps) * 1000;
}

/**
 * Calculate a scene duration from an audio clip with padding and clamps.
 * Pure math; safe in browser.
 */
export function calculateSceneDuration(
  audioDurationMs: number,
  minDuration: number = 1200,
  maxDuration: number = 2500,
  paddingMs: number = 150
): number {
  const total = audioDurationMs + paddingMs;
  return Math.max(minDuration, Math.min(maxDuration, total));
}

/**
 * Animation timing based on cueTimes (seconds from scene start) or a
 * fallback percentage of the scene duration.
 *
 * FIXED: Previously, fallbackPercent was returned as-is and treated as ms.
 * Now we convert fallbackPercent -> ms correctly.
 */
export function getAnimationTiming(
  sceneDurationMs: number,
  cueTimes: Record<string, number> | undefined,
  keyword: string,
  fallbackPercent: number = 0.5,
  fps: number = 30
): {
  startFrame: number;
  endFrame: number;
  durationFrames: number;
} {
  // If cueTimes present, we treat value as SECONDS from scene start (pipeline convention).
  // Otherwise, fall back to a fraction of the scene duration.
  const startMs =
    cueTimes && typeof cueTimes[keyword] === 'number'
      ? cueTimes[keyword] * 1000
      : sceneDurationMs * fallbackPercent;

  const startFrame = Math.max(0, timeToFrame(startMs, fps));
  const endFrame = Math.max(startFrame + 1, timeToFrame(sceneDurationMs, fps));
  const durationFrames = Math.max(1, endFrame - startFrame);

  return {startFrame, endFrame, durationFrames};
}
