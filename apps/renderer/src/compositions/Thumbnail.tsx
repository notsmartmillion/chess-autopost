import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {AnimatedBoard} from '../components/AnimatedBoard';
import {THEME, Wordmark} from '../components/AnalysisRail';
import type {Script} from '../types/script';

export type ThumbnailProps = {
  script?: Script | null;
  [key: string]: unknown;
};

const BOARD = 820;
const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

/**
 * "Bronstein, David I" -> "David Bronstein".
 *
 * PGN headers carry middle initials and Russian patronymics, often truncated
 * ("Chistiakov, Alexander Nikolaevi"). A lone capital I renders as a bare
 * vertical stroke and gets read as a pipe character, and broadcasts say
 * "David Bronstein" anyway — so bare initials are dropped.
 */
const displayName = (raw?: string | null): string => {
  if (!raw) return 'Unknown';
  const v = raw.trim();
  if (!v || /^[?.]+$/.test(v)) return 'Unknown';
  const [last, first] = v.includes(',') ? v.split(',') : [v, ''];
  const given = (first ?? '')
    .trim()
    .split(/\s+/)
    .filter((part) => part && !/^[A-Za-z]\.?$/.test(part))
    .join(' ');
  const surname = (last ?? '').trim();
  return (given ? `${given} ${surname}` : surname).trim() || 'Unknown';
};

const year = (raw?: string | null): string | null => {
  const m = (raw ?? '').match(/^(\d{4})/);
  return m ? m[1] : null;
};

/** One player's face, or nothing at all when we have no portrait for them. */
const ThumbFace: React.FC<{src?: string | null; accent: string}> = ({src, accent}) =>
  src ? (
    <div
      style={{
        // Large enough to still read as a face at browse size: a YouTube
        // thumbnail is shown around 360px wide, so anything under about 180px
        // here arrives as a grey smudge rather than a person.
        width: 196,
        height: 250,
        flexShrink: 0,
        borderRadius: 8,
        overflow: 'hidden',
        boxShadow: `0 12px 34px rgba(0,0,0,0.55), 0 0 0 2px ${accent}66`,
      }}
    >
      <Img
        src={staticFile(`portraits/${src}`)}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          filter: 'grayscale(1) contrast(1.08)',
        }}
      />
    </div>
  ) : null;

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

  // The model saw the whole game and writes a line specific to it. The
  // templates below are the safety net: they are generic by construction, so
  // every brilliancy the channel ever posts would otherwise carry the same
  // four words.
  let hook: string;
  if (meta.llmThumb) hook = meta.llmThumb;
  else if (hero?.tag === 'brilliant') hook = 'THE MOVE\nNOBODY SAW';
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
        <Wordmark name={meta.channel ?? 'Nocturne Chess'} />
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
            // The model's line is short but not fixed-length, and the column is
            // 872px wide. Size to the longest line so a three-word line of long
            // words shrinks instead of running off the card.
            fontSize: Math.min(
              96,
              Math.round(1560 / Math.max(...hook.split('\n').map((l) => l.length), 1))
            ),
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

        {/* Faces. A thumbnail with two people looking out of it is read as a
            contest between them; the same thumbnail with only names on it is
            read as a diagram. The portraits are already downloaded and
            licensed for the video, so this costs nothing. */}
        <div style={{display: 'flex', alignItems: 'center', gap: 26}}>
          <ThumbFace src={meta.whitePortrait} accent={accent} />
          <div style={{minWidth: 0}}>
            <div style={{fontSize: 44, color: THEME.text, lineHeight: 1.3}}>{white}</div>
            <div style={{fontSize: 26, color: THEME.muted, margin: '4px 0'}}>versus</div>
            <div style={{fontSize: 44, color: THEME.text, lineHeight: 1.3}}>{black}</div>
          </div>
          <ThumbFace src={meta.blackPortrait} accent={accent} />
        </div>

        {(meta.event || y) && (
          <div style={{fontSize: 28, color: THEME.muted, marginTop: 26, letterSpacing: 1.2}}>
            {[meta.event, y].filter(Boolean).join('  ·  ')}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};
