// apps/renderer/src/index.tsx
import {Composition, registerRoot} from 'remotion';
import {ChessVideo} from './compositions/Video';

// We cannot read timeline.json here (browser bundle), so we register
// a composition with a safe "max" duration. We'll render exactly the
// needed frames by passing --frame-range from the orchestrator.
const FPS = 30;
// 5 minutes max; orchestrator will constrain with --frame-range.
const MAX_DURATION_FRAMES = 5 * 60 * FPS;

registerRoot(() => {
  return (
    <>
      <Composition
        id="ChessVideo"
        component={ChessVideo}
        durationInFrames={MAX_DURATION_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
        // The component will load /timeline.json at runtime via staticFile()+fetch
        defaultProps={{
          audioBase: '/audio',
        }}
      />
    </>
  );
});
