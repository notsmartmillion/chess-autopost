import React, {useMemo} from 'react';
import {useCurrentFrame, useVideoConfig, interpolate, Easing} from 'remotion';
import {Chess} from 'chess.js';
import type {SceneAlt} from '../types/timeline';
import {getAnimationTiming} from '../lib/audio-browser';
import {Board} from '../components/Board';

type Props = {scene: SceneAlt; size?: number};

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/**
 * "What could have been better" preview: steps through the engine's suggested
 * line (PV) from the branch-point position, one snapshot at a time, with an
 * arrow for each step. Rendered as an overlay covering the persistent board.
 */
export const SceneAltPreview: React.FC<Props> = ({scene, size = 720}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // Seed from the PRE-MOVE branch FEN written by the timeline builder.
  const baseFen =
    typeof scene.fen === 'string' && scene.fen.trim().length > 0 ? scene.fen : undefined;

  // Precompute FEN snapshots while applying the PV from the base position.
  const pvFenSeq = useMemo(() => {
    const seq: {fen: string}[] = [];
    const ch = new Chess(baseFen);
    seq.push({fen: ch.fen()});
    for (const san of scene.pv?.slice(0, 3) ?? []) {
      try {
        const m = ch.move(san); // chess.js v1: SAN accepted directly
        if (!m) break;
        seq.push({fen: ch.fen()});
      } catch {
        break;
      }
    }
    return seq;
  }, [baseFen, scene.pv]);

  // Reveal timing: consume frames after the 'alt' cue; split evenly across snapshots.
  const totalMs = scene.durationMs ?? 1200;
  const cue = getAnimationTiming(totalMs, scene.cueTimes, 'alt', 0.08, fps);
  const framesAvailable = Math.max(1, cue.durationFrames);
  const snaps = Math.max(1, pvFenSeq.length);
  const perSnap = Math.max(1, Math.floor(framesAvailable / snaps));

  const currentSnapIdx = useMemo(() => {
    if (frame < cue.startFrame) return 0;
    const progressed = frame - cue.startFrame;
    return clamp(Math.floor(progressed / perSnap), 0, pvFenSeq.length - 1);
  }, [frame, cue.startFrame, perSnap, pvFenSeq.length]);

  const fen = pvFenSeq[currentSnapIdx]?.fen ?? baseFen ?? new Chess().fen();

  // Arrow for the current step (scene.arrows[i] corresponds to snapshot i+1).
  const arrowForStep = currentSnapIdx > 0 ? scene.arrows?.[currentSnapIdx - 1] : scene.arrows?.[0];
  const arrows =
    arrowForStep && Array.isArray(arrowForStep) && arrowForStep.length === 2
      ? [{from: arrowForStep[0], to: arrowForStep[1]}]
      : undefined;

  const fadeIn = interpolate(frame, [0, 8], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

  const evalBadge =
    scene.mate != null
      ? ` · mate in ${Math.abs(scene.mate)}`
      : scene.cp != null
        ? ` · ${scene.cp >= 0 ? '+' : ''}${(scene.cp / 100).toFixed(1)}`
        : '';

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        opacity: fadeIn,
      }}
    >
      <Board fen={fen} size={size} showCoordinates={true} arrows={arrows} />

      {/* "Better was..." label */}
      <div
        style={{
          position: 'absolute',
          top: -54,
          left: '50%',
          transform: 'translateX(-50%)',
          whiteSpace: 'nowrap',
          color: '#fff',
          fontFamily: 'system-ui, sans-serif',
          fontSize: 22,
          fontWeight: 700,
          padding: '8px 14px',
          borderRadius: 10,
          border: '2px solid #ff6a3d',
          background: 'rgba(15, 15, 18, 0.9)',
        }}
      >
        {`Better was ${scene.pv?.[0] ?? ''}${evalBadge}`}
      </div>
    </div>
  );
};
