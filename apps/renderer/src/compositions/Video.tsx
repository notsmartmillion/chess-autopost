import React, {useEffect, useMemo, useState} from 'react';
import {Audio, Sequence, staticFile, useVideoConfig, useCurrentFrame, spring, interpolate, Easing} from 'remotion';
import {EvalBar} from '../components/EvalBar';
import {PortraitPanel} from '../components/PortraitPanel';
import {Timeline, Scene} from '../types/timeline';
import {Board} from '../components/Board';
import {SceneMainMove} from '../scenes/SceneMainMove';

type Props = {
  /** Base path for audio files in /public (default: /audio) */
  audioBase?: string;
};

const SAFE_FALLBACK: Timeline = {
  meta: {white: 'White', black: 'Black'},
  scenes: [],
  totalDurationMs: 0,
};

async function loadTimelineJsonSafe(): Promise<Timeline> {
  try {
    const url = staticFile('timeline.json');
    const res = await fetch(url);
    if (!res.ok) {
      console.warn(`timeline.json not found at ${url} (${res.status})`);
      return SAFE_FALLBACK;
    }
    return (await res.json()) as Timeline;
  } catch (e) {
    console.warn('Failed to fetch timeline.json:', e);
    return SAFE_FALLBACK;
  }
}

type Durations = Record<string, number>;

async function loadDurationsSafe(): Promise<Durations> {
  try {
    const url = staticFile('audio_durations.json');
    const res = await fetch(url);
    if (!res.ok) return {};
    return (await res.json()) as Durations;
  } catch {
    return {};
  }
}

export const ChessVideo: React.FC<Props> = ({audioBase = '/audio'}) => {
  const {fps} = useVideoConfig();
  const [timeline, setTimeline] = useState<Timeline>(SAFE_FALLBACK);
  const [durations, setDurations] = useState<Durations>({});

  // Load timeline once; stay graceful if it's missing
  useEffect(() => {
    let cancelled = false;
    loadTimelineJsonSafe().then((t) => {
      if (!cancelled) setTimeline(t);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Load measured audio durations (optional)
  useEffect(() => {
    let cancelled = false;
    loadDurationsSafe().then((d) => {
      if (!cancelled) setDurations(d);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Always compute segments, even with empty scenes, so hooks order is stable
  const segments = useMemo(() => {
    let cursor = 0;
    const scenes = timeline?.scenes ?? [];
    return scenes.map((s) => {
      const frames = Math.max(1, Math.round(((s.durationMs ?? 0) * fps) / 1000));
      const seg = {scene: s as Scene, from: cursor, durationInFrames: frames};
      cursor += frames;
      return seg;
    });
  }, [timeline, fps]);

  const noData = !timeline || (timeline.scenes ?? []).length === 0;
  
  // Only main scenes for this pass (visual + audio)
  const mainSegments = useMemo(() => segments.filter((seg) => (seg.scene as any).type === 'main'), [segments]);
  const frame = useCurrentFrame();
  const { currentSegId, currentEvalTarget, currentFromFrame, currentDurationFrames, prevEvalTarget } = useMemo(() => {
    let cursor = 0;
    for (let i = 0; i < mainSegments.length; i++) {
      const seg = mainSegments[i];
      const end = cursor + seg.durationInFrames;
      if (frame < end) {
        return {
          currentSegId: (seg.scene as any).id as string,
          currentEvalTarget: (((seg.scene as any).evalBarTarget as number) ?? 0) as number,
          currentFromFrame: cursor,
          currentDurationFrames: seg.durationInFrames,
          prevEvalTarget: i > 0 ? (((mainSegments[i-1].scene as any).evalBarTarget as number) ?? 0) : 0,
        };
      }
      cursor = end;
    }
    const last = mainSegments[mainSegments.length - 1]?.scene as any;
    return {
      currentSegId: (last?.id as string) ?? 'end',
      currentEvalTarget: (last?.evalBarTarget as number) ?? 0,
      currentFromFrame: 0,
      currentDurationFrames: 1,
      prevEvalTarget: 0,
    };
  }, [frame, mainSegments]);

  // Smooth the eval transition from previous -> current using a gentle spring
  const relFrame = Math.max(0, frame - (currentFromFrame ?? 0));
  const deadBand = 0.015;
  const quantize = (v: number, step = 0.02) => Math.round(v / step) * step;
  const fromEval = quantize(Math.max(-1, Math.min(1, prevEvalTarget ?? 0)));
  const toEvalRaw = Math.max(-1, Math.min(1, currentEvalTarget ?? 0));
  const toEval = quantize(toEvalRaw);
  const targetEval = Math.abs(toEval - fromEval) < deadBand ? fromEval : toEval;
  const prog = spring({
    frame: relFrame,
    fps,
    config: { damping: 200, stiffness: 80, mass: 0.9 },
    durationInFrames: Math.max(10, currentDurationFrames ?? 10),
  });
  const eased = Easing.inOut(Easing.cubic)(prog);
  const smoothedEval = interpolate(eased, [0, 1], [fromEval, targetEval]); // -1..+1

  return (
    <div style={{width: '100%', height: '100%', backgroundColor: '#1a1a1a', position: 'relative', display:'flex', alignItems:'center', justifyContent:'center'}}>
      {/* Persistent chrome */}
      {!noData && (
        <div style={{position:'absolute', top: 16, left: 16, right: 16}}>
          <PortraitPanel whitePlayer={(timeline.meta as any).white} blackPlayer={(timeline.meta as any).black} currentPlayer={undefined} />
        </div>
      )}

      {/* Board container (stable) */}
      <div style={{position:'relative', width: 720, height: 720}}>
        {/* Persistent board driven by the current scene's FEN */}
        {!noData && (() => {
          // Determine current FEN based on frame
          let cursor = 0;
          for (let i = 0; i < mainSegments.length; i++) {
            const seg = mainSegments[i];
            const end = cursor + seg.durationInFrames;
            if (frame < end) {
              return <Board fen={(seg.scene as any).fen} size={720} showCoordinates={true} />;
            }
            cursor = end;
          }
          const last = mainSegments[mainSegments.length - 1];
          return last ? <Board fen={(last.scene as any).fen} size={720} showCoordinates={true} /> : null;
        })()}

        {!noData &&
          mainSegments.map(({scene, from, durationInFrames}) => {
            const audioSrc = staticFile(`${audioBase}/${scene.id}.wav`);

            const endAt =
              durations[scene.id]
                ? Math.min(
                    durationInFrames,
                    Math.max(1, Math.round((durations[scene.id] / 1000) * fps))
                  )
                : durationInFrames;

            return (
              <React.Fragment key={scene.id}>
                <Sequence from={from} durationInFrames={durationInFrames}>
                  {/* Render overlays only; board is persistent */}
                  <SceneMainMove
                    scene={{
                      ...(scene as any),
                      prevAttacked: (mainSegments.find((s) => s.from + s.durationInFrames === from)?.scene as any)?.attacked,
                      captured: Boolean((scene as any).captured),
                    }}
                    timeline={timeline}
                    showChrome={false}
                    renderBoard={false}
                  />
                </Sequence>

                {durations[scene.id] && (
                  <Sequence from={from} durationInFrames={endAt}>
                    <Audio src={audioSrc} endAt={endAt} />
                  </Sequence>
                )}
              </React.Fragment>
            );
          })}
      </div>

      {/* Persistent vertical eval bar to the right of board */}
      {!noData && (
        <div style={{marginLeft: 12}}>
          {/* changeKey is the current main scene id at the current frame for stable, per-move tweening */}
          <EvalBar target={currentEvalTarget} orientation="vertical" width={36} height={720} smoothingFrames={90} startDelayFrames={6} showValue={false} changeKey={currentSegId} />
        </div>
      )}
      

      {/* Friendly overlay when timeline.json is missing */}
      {noData && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontFamily: 'system-ui, sans-serif',
            textAlign: 'center',
            padding: 24,
          }}
        >
          <div>
            <div style={{fontSize: 28, marginBottom: 10}}>No timeline loaded</div>
            <div style={{opacity: 0.8, lineHeight: 1.5}}>
              Run:
              <pre style={{marginTop: 10, background: '#222', padding: 12, borderRadius: 8}}>
                python services/orchestrator/build_video.py
              </pre>
              This will write <code>apps/renderer/public/timeline.json</code> and{' '}
              <code>apps/renderer/public/audio/*.wav</code>. Then refresh this page.
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
