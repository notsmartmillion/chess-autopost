import React from 'react';
import {AbsoluteFill} from 'remotion';
import {AnimatedBoard} from '../components/AnimatedBoard';
import {THEME, Wordmark} from '../components/AnalysisRail';
import type {Script} from '../types/script';

export type ThumbnailProps = {
  script?: Script | null;
  [key: string]: unknown;
};

const BOARD = 820;
const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

const displayName = (raw?: string | null): string => {
  if (!raw) return 'Unknown';
  const v = raw.trim();
  if (!v || /^[?.]+$/.test(v)) return 'Unknown';
  if (v.includes(',')) {
    const [last, first] = v.split(',');
    return `${first.trim()} ${last.trim()}`.trim();
  }
  return v;
};

const year = (raw?: string | null): string | null => {
  const m = (raw ?? '').match(/^(\d{4})/);
  return m ? m[1] : null;
};

/**
 * YouTube thumbnail in the Analysis Deck style: the game's most dramatic
 * position on the left, a bold hook and the pairing on the right.
 */
export const Thumbnail: React.FC<ThumbnailProps> = ({script}) => {
  const beats = script?.beats ?? [];
  const meta = script?.meta ?? {};

  const moves = beats.filter((b) => b.kind === 'move');

  // Prefer an explicitly tagged moment, but never depend on one: at shallow
  // engine depth a game can legitimately contain no blunders or brilliancies.
  const priority = ['brilliant', 'blunder', 'great', 'mistake'];
  let hero = moves.find((b) => b.tag === priority[0]);
  for (const tag of priority.slice(1)) {
    if (hero) break;
    hero = moves.find((b) => b.tag === tag);
  }

  // Fall back to the biggest evaluation swing — the turning point of the game.
  let swingPawns = 0;
  if (!hero && moves.length > 1) {
    let best = moves[0];
    let bestDelta = 0;
    for (let i = 1; i < moves.length; i++) {
      const delta = Math.abs((moves[i].evalCp ?? 0) - (moves[i - 1].evalCp ?? 0));
      if (delta > bestDelta) {
        bestDelta = delta;
        best = moves[i];
      }
    }
    hero = best;
    swingPawns = bestDelta / 100;
  }
  if (!hero) hero = moves[moves.length - 1];

  const fen = hero?.fen ?? START_FEN;
  const white = displayName(meta.white);
  const black = displayName(meta.black);
  const y = year(meta.date);
  const winner =
    meta.result === '1-0' ? white : meta.result === '0-1' ? black : null;

  let hook: string;
  if (hero?.tag === 'brilliant') hook = 'THE MOVE\nNOBODY SAW';
  else if (hero?.tag === 'blunder') hook = 'THE MOVE\nTHAT LOST IT';
  else if (hero?.tag === 'great') hook = 'THE IDEA THAT\nDECIDED IT';
  else if (hero?.tag === 'mistake') hook = 'THE MISTAKE\nTHAT COST IT';
  else if (swingPawns >= 2) hook = 'THE MOMENT\nIT ALL TURNED';
  else if (winner) hook = `HOW ${winner.split(' ').pop()?.toUpperCase()}\nWON THIS`;
  else hook = 'A GAME WORTH\nSEEING';

  const accent =
    hero?.tag === 'blunder' || hero?.tag === 'mistake' ? THEME.bad : THEME.accent;

  return (
    <AbsoluteFill style={{background: THEME.bg0, fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif'}}>
      <AbsoluteFill
        style={{
          background:
            `radial-gradient(900px 640px at 24% 50%, ${accent}22, transparent 70%),` +
            'radial-gradient(800px 600px at 88% 76%, rgba(178,140,255,0.10), transparent 70%)',
        }}
      />

      <div style={{position: 'absolute', left: 74, top: 44}}>
        <Wordmark name={meta.channel ?? 'Midnight Chess'} />
      </div>

      <div
        style={{
          position: 'absolute',
          left: 74,
          top: (1080 - BOARD) / 2 + 26,
          width: BOARD,
          height: BOARD,
          boxShadow: `0 24px 70px rgba(0,0,0,0.6), 0 0 0 1px ${THEME.panelEdge}`,
          borderRadius: 8,
          overflow: 'hidden',
        }}
      >
        <AnimatedBoard
          prevFen={fen}
          fen={fen}
          move={null}
          size={BOARD}
          highlights={hero?.highlights ?? []}
          arrows={hero?.arrows ?? []}
          checkSquare={hero?.checkSquare ?? null}
          moveStartFrame={0}
          showCoordinates={false}
        />
      </div>

      <div
        style={{
          position: 'absolute',
          left: 74 + BOARD + 80,
          top: 250,
          width: 1920 - (74 + BOARD + 80) - 74,
        }}
      >
        <div
          style={{
            fontSize: 96,
            lineHeight: 1.06,
            fontWeight: 800,
            letterSpacing: -1,
            color: THEME.text,
            whiteSpace: 'pre-line',
          }}
        >
          {hook}
        </div>
        <div style={{height: 8, width: 150, background: accent, margin: '38px 0 34px', borderRadius: 4}} />
        <div style={{fontSize: 46, color: THEME.text, lineHeight: 1.35}}>{white}</div>
        <div style={{fontSize: 30, color: THEME.muted, margin: '6px 0'}}>versus</div>
        <div style={{fontSize: 46, color: THEME.text, lineHeight: 1.35}}>{black}</div>
        {(meta.event || y) && (
          <div style={{fontSize: 28, color: THEME.muted, marginTop: 26, letterSpacing: 1.2}}>
            {[meta.event, y].filter(Boolean).join('  ·  ')}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
