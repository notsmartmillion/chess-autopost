// apps/renderer/src/index.tsx
import {Composition, registerRoot, staticFile, CalculateMetadataFunction} from 'remotion';
import {ChessNarration, ChessNarrationProps} from './compositions/ChessNarration';
import {Thumbnail, ThumbnailProps} from './compositions/Thumbnail';
import type {Script} from './types/script';

const FPS = 30;

async function loadScript(): Promise<Script | null> {
  try {
    const res = await fetch(staticFile('script.json'));
    if (res.ok) return (await res.json()) as Script;
  } catch {
    // leave null; compositions render a friendly hint
  }
  return null;
}

/**
 * The script (written by the build step) is the single source of truth for
 * length: beats already carry their measured audio durations, so we can set an
 * exact composition length instead of rendering a fixed block and trimming it.
 */
const calculateMetadata: CalculateMetadataFunction<ChessNarrationProps> = async ({props}) => {
  const script = await loadScript();

  const totalMs = (script?.beats ?? []).reduce(
    (sum, beat) => sum + (beat.durationMs || 1500),
    0
  );
  const durationInFrames = totalMs > 0 ? Math.max(1, Math.round((totalMs / 1000) * FPS)) : 20 * FPS;

  return {durationInFrames, props: {...props, script}};
};

const thumbnailMetadata: CalculateMetadataFunction<ThumbnailProps> = async ({props}) => ({
  props: {...props, script: await loadScript()},
});

registerRoot(() => {
  return (
    <>
      <Composition
        id="ChessVideo"
        component={ChessNarration}
        durationInFrames={20 * FPS}
        fps={FPS}
        width={1920}
        height={1080}
        calculateMetadata={calculateMetadata}
        defaultProps={{audioBase: '/audio'}}
      />
      <Composition
        id="Thumbnail"
        component={Thumbnail}
        durationInFrames={30}
        fps={FPS}
        width={1920}
        height={1080}
        calculateMetadata={thumbnailMetadata}
        defaultProps={{}}
      />
    </>
  );
});
