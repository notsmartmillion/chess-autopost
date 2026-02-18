import React, {useEffect, useMemo} from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {Chess} from 'chess.js';
import type {SceneAlt} from '../types/timeline';
import {getAnimationTiming} from '../lib/audio';
import {Board} from '../components/Board'; // expects props { fen: string; arrows?: {from:string;to:string}[] }

type Props = { scene: SceneAlt };

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

export const SceneAltPreview: React.FC<Props> = ({scene}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  // 1) Seed from the PRE-MOVE branch FEN (added to SceneAlt by the timeline builder).
  const baseFen =
    typeof scene.fen === 'string' && scene.fen.trim().length > 0 ? scene.fen : undefined;

  // 2) Normalize PV (SAN) and precompute FEN snapshots while applying PV from the base position.
  //    Length will be pv.length + 1 (initial + each applied move).
  const pvFenSeq = useMemo(() => {
    const seq: {fen: string}[] = [];
    const ch = new Chess(baseFen); // undefined means start pos; otherwise seed from given FEN
    seq.push({fen: ch.fen()});
    for (const san of scene.pv?.slice(0, 3) ?? []) {
      try {
        const m = ch.move(san, {sloppy: true});
        if (!m) break;
        seq.push({fen: ch.fen()});
      } catch {
        break;
      }
    }
    return seq;
  }, [baseFen, scene.pv]);

  // 3) Decide when the PV should start revealing & how fast to advance through snapshots.
  //    We consume the frames AFTER the 'alt' cue; split evenly across snapshots.
  const totalMs = scene.durationMs ?? 1200;
  const cue = getAnimationTiming(totalMs, scene.cueTimes, 'alt', 0.08, fps);
  const framesAvailable = Math.max(1, cue.durationFrames);
  const snaps = Math.max(1, pvFenSeq.length);
  const perSnap = Math.max(1, Math.floor(framesAvailable / snaps));

  // 4) Determine which snapshot is visible at the current frame.
  const currentSnapIdx = useMemo(() => {
    if (frame < cue.startFrame) return 0;
    const progressed = frame - cue.startFrame;
    return clamp(Math.floor(progressed / perSnap), 0, pvFenSeq.length - 1);
  }, [frame, cue.startFrame, perSnap, pvFenSeq.length]);

  // Current board FEN
  const fen = pvFenSeq[currentSnapIdx]?.fen ?? baseFen ?? new Chess().fen();

  // 5) Choose the arrow for the current step (comes from timeline: scene.arrows[i] for snapshot i+1).
  //    When currentSnapIdx === 0, we’re at the base; otherwise show the (idx-1)-th arrow.
  const arrowForStep =
    currentSnapIdx > 0 ? scene.arrows?.[currentSnapIdx - 1] : undefined;

  // Convert timeline arrow (['e2','e4']) into Board prop shape if needed
  const arrows =
    arrowForStep && Array.isArray(arrowForStep) && arrowForStep.length === 2
      ? [{from: arrowForStep[0], to: arrowForStep[1]}]
      : undefined;

  // Small helper to format cp/mate nicely
  const evalBadge =
    scene.mate != null
      ? ` · #${scene.mate}`
      : scene.cp != null
        ? ` · ${(scene.cp >= 0 ? '+' : '')}${(scene.cp / 100).toFixed(2)}`
        : '';

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
      }}
    >
      {/* Floating label */}
      <div
        style={{
          position: 'absolute',
          top: 24,
          left: '50%',
          transform: 'translateX(-50%)',
          color: '#fff',
          fontFamily: 'system-ui, sans-serif',
          fontSize: 18,
          padding: '6px 10px',
          borderRadius: 10,
          border: '2px solid #ff6a3d',
          background: 'rgba(0,0,0,0.35)',
        }}
      >
        {(scene.label ?? 'Alt') + evalBadge}
      </div>

      <Board fen={fen} arrows={arrows} />
    </div>
  );
};
