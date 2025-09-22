import React, {useEffect, useMemo, useState} from 'react';
import {Audio, Sequence, staticFile, useVideoConfig} from 'remotion';
import {Timeline, Scene} from '../types/timeline';
import {SceneMainMove} from '../scenes/SceneMainMove';
import {SceneAltPreview} from '../scenes/SceneAltPreview';
import {SceneReset} from '../scenes/SceneReset';

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

  return (
    <div style={{width: '100%', height: '100%', backgroundColor: '#1a1a1a', position: 'relative'}}>
      {/* Scenes */}
      {!noData &&
        segments.map(({scene, from, durationInFrames}) => {
          const audioSrc = staticFile(`${audioBase}/${scene.id}.wav`);

          // Trim audio to measured duration if available, never exceeding the scene bounds
          const endAt =
            scene.type !== 'reset' && durations[scene.id]
              ? Math.min(
                  durationInFrames,
                  Math.max(1, Math.round((durations[scene.id] / 1000) * fps))
                )
              : durationInFrames;

          return (
            <React.Fragment key={scene.id}>
              <Sequence from={from} durationInFrames={durationInFrames}>
                {scene.type === 'main' && <SceneMainMove scene={scene} timeline={timeline} />}
                {scene.type === 'alt' && <SceneAltPreview scene={scene} />}
                {scene.type === 'reset' && <SceneReset scene={scene} />}
              </Sequence>

              {scene.type !== 'reset' && (
                <Sequence from={from} durationInFrames={endAt}>
                  <Audio src={audioSrc} endAt={endAt} />
                </Sequence>
              )}
            </React.Fragment>
          );
        })}

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
