// apps/renderer/src/index.tsx
import {Composition, registerRoot, staticFile, CalculateMetadataFunction} from 'remotion';
import {ChessNarration, ChessNarrationProps} from './compositions/ChessNarration';
import {Thumbnail, ThumbnailProps} from './compositions/Thumbnail';
import {ChannelWatermark, ChannelBanner} from './compositions/ChannelArt';
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

/**
 * A script passed in props wins over the synced one.
 *
 * The thumbnail used to be renderable only for whatever build happened to own
 * public/script.json, so regenerating one for an already-published video meant
 * overwriting that file — which races any render in flight. Accepting the
 * script directly makes "give this old video the current thumbnail" a safe,
 * standalone operation.
 */
const thumbnailMetadata: CalculateMetadataFunction<ThumbnailProps> = async ({props}) => ({
  props: {...props, script: (props.script as Script | null) ?? (await loadScript())},
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
        id="ChannelWatermark"
        component={ChannelWatermark}
        durationInFrames={1}
        fps={FPS}
        width={150}
        height={150}
      />
      <Composition
        id="ChannelBanner"
        component={ChannelBanner}
        durationInFrames={1}
        fps={FPS}
        width={2048}
        height={1152}
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
