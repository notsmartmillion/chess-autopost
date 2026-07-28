import React, {useMemo} from 'react';
import {Audio, Sequence, staticFile, useVideoConfig, useCurrentFrame, interpolate, Easing} from 'remotion';
import {EvalBar} from '../components/EvalBar';
import {PortraitPanel} from '../components/PortraitPanel';
import {Timeline, Scene, SceneMain, SceneAlt} from '../types/timeline';
import {Board} from '../components/Board';
import {SceneMainMove} from '../scenes/SceneMainMove';
import {SceneAltPreview} from '../scenes/SceneAltPreview';
import {SceneReset} from '../scenes/SceneReset';

export type Durations = Record<string, number>;

export type ChessVideoProps = {
  /** Base path for audio files in /public (default: /audio) */
  audioBase?: string;
  /** Injected by calculateMetadata in index.tsx */
  timeline?: Timeline | null;
  durations?: Durations | null;
};

const SAFE_FALLBACK: Timeline = {
  meta: {white: 'White', black: 'Black'},
  scenes: [],
  totalDurationMs: 0,
};

const BOARD_SIZE = 720;

type Seg = {
  scene: Scene;
  from: number;
  durationInFrames: number;
  /** FEN of the most recent main scene at/before this segment (post-move position) */
  baseFen: string | null;
  /** Eval + id of the most recent main scene, for the persistent eval bar */
  lastMainEval: number;
  lastMainId: string;
};

export const ChessVideo: React.FC<ChessVideoProps> = ({
  audioBase = '/audio',
  timeline: timelineProp,
  durations: durationsProp,
}) => {
  const {fps} = useVideoConfig();
  const frame = useCurrentFrame();

  const timeline = timelineProp ?? SAFE_FALLBACK;
  const durations = durationsProp ?? {};

  const introMs = timeline.meta?.introMs ?? 0;
  const outroMs = timeline.meta?.outroMs ?? 0;
  const introFrames = Math.round((introMs / 1000) * fps);
  const outroFrames = Math.round((outroMs / 1000) * fps);

  // Single pass over ALL scenes (main + alt + reset) with one global cursor,
  // offset by the intro. This keeps board, overlays, audio and eval bar in
  // exactly the same coordinate system.
  const segments: Seg[] = useMemo(() => {
    let cursor = introFrames;
    let baseFen: string | null = null;
    let lastMainEval = 0;
    let lastMainId = 'start';
    const out: Seg[] = [];
    for (const s of timeline.scenes ?? []) {
      const frames = Math.max(1, Math.round(((s.durationMs ?? 0) * fps) / 1000));
      if (s.type === 'main') {
        baseFen = s.fen;
        lastMainEval = s.evalBarTarget ?? 0;
        lastMainId = s.id;
      }
      out.push({scene: s, from: cursor, durationInFrames: frames, baseFen, lastMainEval, lastMainId});
      cursor += frames;
    }
    return out;
  }, [timeline, fps, introFrames]);

  const totalSceneFrames = segments.length
    ? segments[segments.length - 1].from + segments[segments.length - 1].durationInFrames
    : introFrames;
  const outroStart = totalSceneFrames;

  const noData = (timeline.scenes ?? []).length === 0;

  // Current segment at this frame (for the persistent board + eval bar).
  const current = useMemo(() => {
    for (const seg of segments) {
      if (frame < seg.from + seg.durationInFrames) return seg;
    }
    return segments[segments.length - 1] ?? null;
  }, [frame, segments]);

  const mainSegments = useMemo(
    () => segments.filter((seg): seg is Seg & {scene: SceneMain} => seg.scene.type === 'main'),
    [segments]
  );

  // Previous main scene for each main scene id (for heatmap diffing).
  const prevAttackedById = useMemo(() => {
    const map: Record<string, SceneMain['attacked'] | undefined> = {};
    for (let i = 0; i < mainSegments.length; i++) {
      map[mainSegments[i].scene.id] = i > 0 ? mainSegments[i - 1].scene.attacked : undefined;
    }
    return map;
  }, [mainSegments]);

  const white = timeline.meta?.white ?? 'White';
  const black = timeline.meta?.black ?? 'Black';

  // Intro/outro fades
  const inIntro = frame < introFrames;
  const inOutro = frame >= outroStart;

  const currentScene = current?.scene ?? null;
  const boardFen =
    currentScene?.type === 'main'
      ? currentScene.fen
      : current?.baseFen ?? null;

  const currentMain: SceneMain | null =
    currentScene?.type === 'main' ? currentScene : null;

  // Move caption: show the move being played (or the line being previewed)
  const caption = useMemo(() => {
    if (!currentScene) return null;
    if (currentScene.type === 'main') {
      const s = currentScene;
      const n = s.moveNumber ? `${s.moveNumber}${s.player === 'black' ? '…' : '.'}` : '';
      return `${n} ${s.move}`;
    }
    if (currentScene.type === 'alt') {
      const s = currentScene as SceneAlt;
      return `Engine line: ${s.pv?.slice(0, 3).join(' ') ?? ''}`;
    }
    return null;
  }, [currentScene]);

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        backgroundColor: '#1a1a1a',
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {/* Persistent chrome */}
      {!noData && !inIntro && !inOutro && (
        <div style={{position: 'absolute', top: 16, left: 16, right: 16}}>
          <PortraitPanel
            whitePlayer={white}
            blackPlayer={black}
            currentPlayer={currentMain?.player}
          />
        </div>
      )}

      {/* Board container (stable) */}
      <div style={{position: 'relative', width: BOARD_SIZE, height: BOARD_SIZE}}>
        {/* Persistent board driven by the current segment's base FEN */}
        {!noData && boardFen && !inIntro && !inOutro && (
          <Board fen={boardFen} size={BOARD_SIZE} showCoordinates={true} />
        )}

        {!noData &&
          segments.map(({scene, from, durationInFrames}) => {
            const hasAudio = Boolean(durations[scene.id]);
            const audioSrc = staticFile(`${audioBase}/${scene.id}.wav`);
            const endAt = hasAudio
              ? Math.min(durationInFrames, Math.max(1, Math.round((durations[scene.id] / 1000) * fps)))
              : durationInFrames;

            return (
              <React.Fragment key={scene.id}>
                <Sequence from={from} durationInFrames={durationInFrames}>
                  {scene.type === 'main' && (
                    <SceneMainMove
                      scene={{
                        ...scene,
                        prevAttacked: prevAttackedById[scene.id],
                        captured: Boolean(scene.captured),
                      } as SceneMain}
                      timeline={{meta: {white, black}}}
                      showChrome={false}
                      renderBoard={false}
                    />
                  )}
                  {scene.type === 'alt' && <SceneAltPreview scene={scene} size={BOARD_SIZE} />}
                  {scene.type === 'reset' && <SceneReset scene={scene} />}
                </Sequence>

                {hasAudio && (
                  <Sequence from={from} durationInFrames={endAt}>
                    <Audio src={audioSrc} endAt={endAt} />
                  </Sequence>
                )}
              </React.Fragment>
            );
          })}
      </div>

      {/* Persistent vertical eval bar to the right of board */}
      {!noData && !inIntro && !inOutro && (
        <div style={{marginLeft: 12}}>
          <EvalBar
            target={current?.lastMainEval ?? 0}
            orientation="vertical"
            width={36}
            height={BOARD_SIZE}
            smoothingFrames={90}
            startDelayFrames={6}
            showValue={false}
            changeKey={current?.lastMainId ?? 'start'}
          />
        </div>
      )}

      {/* Move caption under the board */}
      {!noData && caption && !inIntro && !inOutro && (
        <div
          style={{
            position: 'absolute',
            bottom: 40,
            left: '50%',
            transform: 'translateX(-50%)',
            color: '#fff',
            fontFamily: 'system-ui, sans-serif',
            fontSize: 30,
            fontWeight: 700,
            letterSpacing: 0.5,
            padding: '8px 20px',
            borderRadius: 12,
            background: 'rgba(0,0,0,0.55)',
          }}
        >
          {caption}
        </div>
      )}

      {/* Intro card + narration */}
      {introFrames > 0 && (
        <Sequence from={0} durationInFrames={introFrames}>
          <IntroOutroCard
            title={`${white} vs ${black}`}
            subtitle={[timeline.meta?.event, timeline.meta?.date].filter(Boolean).join(' · ') || undefined}
            fadeFrames={Math.min(15, Math.floor(introFrames / 3))}
            totalFrames={introFrames}
          />
          <Audio src={staticFile(`${audioBase}/intro.wav`)} />
        </Sequence>
      )}

      {/* Outro card + narration */}
      {outroFrames > 0 && (
        <Sequence from={outroStart} durationInFrames={outroFrames}>
          <IntroOutroCard
            title="Thanks for watching"
            subtitle={timeline.meta?.result ? `Result: ${timeline.meta.result}` : undefined}
            fadeFrames={Math.min(15, Math.floor(outroFrames / 3))}
            totalFrames={outroFrames}
          />
          <Audio src={staticFile(`${audioBase}/outro.wav`)} />
        </Sequence>
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

const IntroOutroCard: React.FC<{
  title: string;
  subtitle?: string;
  fadeFrames: number;
  totalFrames: number;
}> = ({title, subtitle, fadeFrames, totalFrames}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [0, fadeFrames, Math.max(fadeFrames + 1, totalFrames - fadeFrames), totalFrames],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)}
  );
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background: '#0f0f12',
        color: 'white',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'system-ui, Segoe UI, sans-serif',
        letterSpacing: 0.3,
        opacity,
        zIndex: 20,
      }}
    >
      <div style={{textAlign: 'center'}}>
        <div style={{fontSize: 64, fontWeight: 800, marginBottom: 18}}>{title}</div>
        {subtitle && <div style={{fontSize: 28, opacity: 0.8}}>{subtitle}</div>}
      </div>
    </div>
  );
};
