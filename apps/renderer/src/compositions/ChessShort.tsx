import React, {useMemo} from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {AnimatedBoard} from '../components/AnimatedBoard';
import {THEME} from '../components/AnalysisRail';
import type {Beat, Script} from '../types/script';

export type ChessShortProps = {
  script?: Script | null;
  /** Where the beat clips live inside /public. Deliberately NOT /audio —
   *  that directory belongs to the long-form build, which may be running. */
  audioBase?: string;
  [key: string]: unknown;
};

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

const BADGE: Record<string, {symbol: string; color: string}> = {
  brilliant: {symbol: '!!', color: '#f2c14e'},
  great: {symbol: '!', color: '#f2c14e'},
  best: {symbol: '★', color: THEME.accent},
  mistake: {symbol: '?', color: THEME.bad},
  blunder: {symbol: '??', color: THEME.bad},
};

/**
 * The vertical cut: one key moment, its refutation, and a pointer to the
 * full game. Same beat model, same board, same audio discipline as the
 * landscape composition — the entire Short is one continuous TTS take, so
 * there are no seams for the voice to trip over.
 *
 * Frame 0 IS the thumbnail on the Shorts feed, so the first frame is the
 * hook card with the board already in position — never a fade from black.
 */
export const ChessShort: React.FC<ChessShortProps> = ({
  script,
  audioBase = '/audio_short',
}) => {
  const {fps} = useVideoConfig();
  const frame = useCurrentFrame();

  const beats = script?.beats ?? [];
  const meta = script?.meta ?? {};

  const segments = useMemo(() => {
    let cursor = 0;
    return beats.map((beat) => {
      const durationInFrames = Math.max(
        1,
        Math.round(((beat.durationMs || 1500) * fps) / 1000)
      );
      const seg = {beat, from: cursor, durationInFrames};
      cursor += durationInFrames;
      return seg;
    });
  }, [beats, fps]);

  const currentIndex = useMemo(() => {
    for (let i = 0; i < segments.length; i++) {
      if (frame < segments[i].from + segments[i].durationInFrames) return i;
    }
    return Math.max(0, segments.length - 1);
  }, [frame, segments]);

  const current = segments[currentIndex] ?? null;
  const beat: Beat | undefined = current?.beat;

  const white = meta.whiteFull ?? meta.white ?? 'White';
  const black = meta.blackFull ?? meta.black ?? 'Black';
  const hook = (meta as any).shortHook ?? 'One move changed everything.';

  // Board mounted ONCE, driven by the current beat — remounting per beat
  // recreates all 32 sprites and the pieces visibly flicker (the landscape
  // composition learned this the hard way).
  const boardFen = beat?.fen ?? beat?.prevFen ?? START_FEN;
  const boardPrevFen = beat?.prevFen ?? boardFen;
  const moveStartFrame =
    (current?.from ?? 0) +
    Math.round((((beat?.moveAtMs as number) || 0) * fps) / 1000);

  const badge =
    beat?.move && !beat.branch && beat.tag && BADGE[beat.tag]
      ? {square: beat.move.to, ...BADGE[beat.tag]}
      : beat?.move && beat.branch
        ? {square: beat.move.to, ...BADGE.best}
        : null;

  const BOARD = 1080;
  const isCta = beat?.kind === 'outro';
  const inVariation = Boolean(beat?.branch);

  return (
    <AbsoluteFill
      style={{
        background: THEME.bg0,
        fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif',
      }}
    >
      {/* Hook band. Present from frame 0 — it is the feed thumbnail. */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 240,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 48px',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: 58,
            fontWeight: 800,
            lineHeight: 1.12,
            color: THEME.text,
            letterSpacing: -0.5,
          }}
        >
          {hook}
        </div>
      </div>

      {/* Board, full width. */}
      <div style={{position: 'absolute', top: 250, left: 0, width: BOARD, height: BOARD}}>
        <AnimatedBoard
          prevFen={boardPrevFen}
          fen={boardFen}
          move={beat?.move ? {from: beat.move.from, to: beat.move.to} : null}
          size={BOARD}
          highlights={beat?.highlights ?? []}
          arrows={beat?.arrows ?? []}
          checkSquare={beat?.checkSquare ?? null}
          moveStartFrame={moveStartFrame}
          badge={badge}
          showCoordinates={false}
        />
        {inVariation && (
          <div
            style={{
              position: 'absolute',
              top: 14,
              left: 14,
              padding: '8px 18px',
              borderRadius: 10,
              background: `${THEME.bg0}d9`,
              border: `2px solid ${THEME.alt}`,
              color: THEME.text,
              fontSize: 34,
              fontWeight: 700,
            }}
          >
            {beat?.label ?? 'What should have happened'}
          </div>
        )}
      </div>

      {/* Rail strip: who is playing, and the move being judged. */}
      <div
        style={{
          position: 'absolute',
          top: 250 + BOARD + 26,
          left: 0,
          right: 0,
          padding: '0 48px',
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'baseline',
            gap: 16,
            color: THEME.text,
            fontSize: 40,
            fontWeight: 600,
          }}
        >
          <span>{white}</span>
          <span style={{color: THEME.muted, fontSize: 28}}>vs</span>
          <span>{black}</span>
        </div>
        {beat?.move && (
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              gap: 14,
              fontSize: 44,
              fontWeight: 800,
              color: badge?.color ?? THEME.text,
            }}
          >
            <span>{beat.move.san}</span>
            {badge && <span>{badge.symbol}</span>}
          </div>
        )}
      </div>

      {/* CTA band: fades up during the outro beat. */}
      <div
        style={{
          position: 'absolute',
          bottom: 60,
          left: 0,
          right: 0,
          textAlign: 'center',
          padding: '0 48px',
          opacity: isCta
            ? interpolate(
                frame,
                [current?.from ?? 0, (current?.from ?? 0) + 12],
                [0, 1],
                {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
              )
            : 0.75,
        }}
      >
        <div style={{fontSize: 34, color: THEME.muted}}>
          {isCta ? 'Full game on the channel' : meta.channel ?? 'Nocturne Chess'}
        </div>
      </div>

      {/* Narration audio, one clip per beat — the same discipline as the
          landscape composition. */}
      {segments.map(({beat: b, from, durationInFrames}) =>
        b.audioFile ? (
          <Sequence
            key={`audio-${b.id}`}
            from={from}
            durationInFrames={durationInFrames}
            layout="none"
          >
            <Audio
              src={staticFile(`${audioBase.replace(/^\//, '')}/${b.audioFile}`)}
            />
          </Sequence>
        ) : null
      )}
    </AbsoluteFill>
  );
};
