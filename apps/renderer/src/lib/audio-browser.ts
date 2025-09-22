// apps/renderer/src/lib/audio-browser.ts
// Browser-safe helpers only. No 'fs', 'path', 'child_process', etc.

/**
 * Convert cue info to a frame index where an animation should start.
 * If cueTimes has a key (e.g. 'move', 'eval', 'pinned'), use that fraction of duration.
 * Otherwise fall back to a defaultPercent (0..1).
 */
export const getAnimationTiming = (
    durationMs: number,
    cueTimes: Record<string, number> | undefined,
    key: string,
    defaultPercent: number,
    fps: number
  ) => {
    const frac = Math.max(
      0,
      Math.min(1, (cueTimes?.[key] ?? defaultPercent))
    );
    const startMs = durationMs * frac;
    const startFrame = Math.round((startMs / 1000) * fps);
    return {startFrame};
  };
  