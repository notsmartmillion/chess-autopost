// apps/renderer/src/lib/audio-browser.ts
// Browser-safe helpers only. No 'fs', 'path', 'child_process', etc.

export interface AnimationTiming {
  startFrame: number;
  endFrame: number;
  durationFrames: number;
}

/**
 * Convert cue info to frame timings for an animation.
 *
 * Cue values are FRACTIONS of the scene duration (0..1) — this is the single
 * convention across the pipeline (build_video.py writes fractions). If the
 * key is missing, fall back to `defaultPercent`.
 */
export const getAnimationTiming = (
  durationMs: number,
  cueTimes: Record<string, number> | undefined,
  key: string,
  defaultPercent: number,
  fps: number
): AnimationTiming => {
  const frac = Math.max(0, Math.min(1, cueTimes?.[key] ?? defaultPercent));
  const startFrame = Math.round(((durationMs * frac) / 1000) * fps);
  const endFrame = Math.max(startFrame + 1, Math.round((durationMs / 1000) * fps));
  return {startFrame, endFrame, durationFrames: endFrame - startFrame};
};
