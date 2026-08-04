import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {AnimatedBoard} from '../components/AnimatedBoard';
import {THEME} from '../components/AnalysisRail';
import type {Script} from '../types/script';

export type ThumbnailProps = {
  script?: Script | null;
  [key: string]: unknown;
};

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

/**
 * The channel's thumbnail, built from three findings rather than taste.
 *
 * ONE FACE, NOT TWO. Seven players in the classics pool have no portrait at
 * all, and two of the last three games hit one — the pool pairs a famous
 * player against an obscure opponent, so a two-portrait layout shows a grey
 * silhouette about half the time. Showing only the player we actually have,
 * preferring the famous one, removes the failure rather than styling it.
 *
 * A BIGGER BOARD. The old design gave the board 820 of 1920 pixels, so at the
 * ~360px a browsing viewer actually sees, each piece was about fourteen pixels
 * — a texture, not a position. The board now runs full height.
 *
 * LESS TEXT. The old card carried a headline, both names, "versus" and an
 * event line. At browse size that is four things competing to be unread.
 */

/** The one player worth showing: whoever we have a face for, famous first. */
const FAMOUS = new Set([
  'tal', 'fischer', 'kasparov', 'carlsen', 'capablanca', 'alekhine', 'lasker',
  'botvinnik', 'karpov', 'spassky', 'petrosian', 'morphy', 'rubinstein',
  'keres', 'smyslov', 'bronstein', 'kramnik', 'anand', 'nimzowitsch',
]);

const surnameKey = (raw?: string | null): string => {
  const v = (raw ?? '').trim();
  if (!v) return '';
  const first = v.includes(',') ? v.split(',')[0] : v.split(/\s+/).pop() ?? '';
  return first.toLowerCase().replace(/[^a-z]/g, '');
};

const displayName = (raw?: string | null): string => {
  if (!raw) return 'Unknown';
  const v = raw.trim();
  if (!v || /^[?.]+$/.test(v)) return 'Unknown';
  const [last, first] = v.includes(',') ? v.split(',') : [v, ''];
  const given = (first ?? '')
    .trim()
    .split(/\s+/)
    .filter((p) => p && !/^[A-Za-z]{1,2}\.?$/.test(p))
    .filter((p) => !/(?:vich|evich|ovich|aevi|ievi)$/i.test(p))
    .filter((p) => !/\d/.test(p)); // "Didier, M1." — scanning debris
  const surname = (last ?? '').trim();
  return (given[0] ? `${given[0]} ${surname}` : surname).trim() || 'Unknown';
};

const year = (raw?: string | null): string | null => {
  const m = (raw ?? '').match(/^(\d{4})/);
  return m ? m[1] : null;
};

export const Thumbnail: React.FC<ThumbnailProps> = ({script}) => {
  const beats = script?.beats ?? [];
  const meta = script?.meta ?? {};
  const moves = beats.filter((b) => b.kind === 'move');

  // The position worth showing: the sharpest tagged moment, else the biggest
  // evaluation swing, else the finish.
  const priority = ['brilliant', 'blunder', 'great', 'mistake'];
  let hero = moves.find((b) => b.tag === priority[0]);
  for (const tag of priority.slice(1)) {
    if (hero) break;
    hero = moves.find((b) => b.tag === tag);
  }
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
  }
  if (!hero) hero = moves[moves.length - 1];

  // Which single face. Prefer the one the audience recognises; fall back to
  // whichever we have; accept that sometimes we have neither.
  const white = {raw: meta.white, portrait: meta.whitePortrait, key: surnameKey(meta.white)};
  const black = {raw: meta.black, portrait: meta.blackPortrait, key: surnameKey(meta.black)};
  const candidates = [white, black].filter((p) => p.portrait);
  const star =
    candidates.find((p) => FAMOUS.has(p.key)) ??
    candidates.find((p) => surnameKey(meta.outcome?.winner === 'white' ? meta.white : meta.black) === p.key) ??
    candidates[0];

  const accent =
    hero?.tag === 'blunder' || hero?.tag === 'mistake' ? THEME.bad :
    hero?.tag === 'brilliant' || hero?.tag === 'great' ? '#f2c14e' :
    THEME.accent;

  const hookRaw = meta.llmThumb ??
    (hero?.tag === 'brilliant' ? 'THE MOVE\nNOBODY SAW'
      : hero?.tag === 'blunder' ? 'THE MOVE\nTHAT LOST IT'
      : 'A GAME WORTH\nSEEING');
  const hook = hookRaw;

  // With a face the board takes the left two-thirds; without one it runs
  // wider and the text grows, because a thumbnail must never show the grey
  // silhouette that a missing portrait used to produce.
  const hasFace = Boolean(star?.portrait);
  const BOARD = 1080;
  const boardX = 0;
  const faceW = 620;
  // Resolved by the director, so the thumbnail cannot disagree with the title
  // about whether he is Bobby or Robert James.
  const whiteName = meta.whiteFull ?? displayName(meta.white);
  const blackName = meta.blackFull ?? displayName(meta.black);

  return (
    <AbsoluteFill style={{background: THEME.bg0, fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif'}}>
      <AbsoluteFill
        style={{
          background:
            `radial-gradient(900px 700px at 20% 50%, ${accent}20, transparent 70%),` +
            'radial-gradient(900px 700px at 85% 60%, rgba(178,140,255,0.10), transparent 70%)',
        }}
      />

      {/* Board, full height and flush left. Brightened relative to the video:
          a dark board on YouTube's dark grid recedes, and the thumbnail's only
          job is to be seen in that grid. */}
      <div
        style={{
          position: 'absolute',
          left: boardX,
          top: 0,
          width: BOARD,
          height: BOARD,
          filter: 'brightness(1.14) saturate(1.06)',
          boxShadow: '24px 0 60px rgba(0,0,0,0.55)',
        }}
      >
        <AnimatedBoard
          prevFen={hero?.prevFen ?? hero?.fen ?? START_FEN}
          fen={hero?.fen ?? START_FEN}
          move={hero?.move ? {from: hero.move.from, to: hero.move.to} : null}
          size={BOARD}
          highlights={hero?.highlights ?? []}
          arrows={hero?.arrows ?? []}
          checkSquare={hero?.checkSquare ?? null}
          moveStartFrame={0}
          showCoordinates={false}
        />
      </div>

      {/* One portrait, full height, bled off the right edge. */}
      {hasFace && (
        <div
          style={{
            position: 'absolute',
            right: 0,
            top: 0,
            width: faceW,
            height: 1080,
            overflow: 'hidden',
          }}
        >
          <Img
            src={staticFile(`portraits/${star!.portrait}`)}
            style={{
              width: '100%',
              height: '100%',
              objectFit: 'cover',
              objectPosition: 'center 22%',
              filter: 'grayscale(1) contrast(1.12) brightness(1.05)',
            }}
          />
          {/* Feather the inner edge so the face joins the board rather than
              sitting in a box beside it. */}
          <AbsoluteFill
            style={{
              // Wide and dark on purpose: the headline is laid over this, and
              // white text on a face is unreadable at browse size however big
              // its shadow.
              background:
                `linear-gradient(90deg, ${THEME.bg0} 0%, ${THEME.bg0}f2 32%, ` +
                `${THEME.bg0}a6 56%, transparent 78%)`,
            }}
          />
        </div>
      )}

      <div
        style={{
          position: 'absolute',
          left: hasFace ? BOARD + 46 : BOARD + 70,
          right: hasFace ? 300 : 90,
          top: 0,
          height: 1080,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          gap: 26,
          zIndex: 2,
        }}
      >
        <div
          style={{
            fontSize: Math.min(
              hasFace ? 76 : 104,
              Math.round((hasFace ? 1150 : 1900) / Math.max(...hook.split('\n').map((l) => l.length), 1))
            ),
            lineHeight: 1.04,
            fontWeight: 800,
            letterSpacing: -1,
            color: THEME.text,
            whiteSpace: 'pre-line',
            textShadow: '0 6px 30px rgba(0,0,0,0.85)',
          }}
        >
          {hook}
        </div>
        <div style={{height: 7, width: 120, background: accent, borderRadius: 4}} />
        <div
          style={{
            fontSize: 36,
            color: THEME.text,
            lineHeight: 1.32,
            textShadow: '0 4px 22px rgba(0,0,0,0.9)',
          }}
        >
          {/* Stacked, not wrapped: "Karl Juhnke vs Boris / Spassky" breaks a
              name across lines, which reads as a mistake. */}
          <div>{whiteName}</div>
          <div style={{fontSize: 25, color: THEME.muted, margin: '3px 0'}}>versus</div>
          <div>{blackName}</div>
        </div>
        {year(meta.date) && (
          <div style={{fontSize: 30, color: THEME.muted, letterSpacing: 2}}>
            {year(meta.date)}
          </div>
        )}
      </div>

      {/* The mark alone, not the wordmark. YouTube prints the channel name
          under every thumbnail already, so spelling it out here spends pixels
          on something the viewer is being told anyway — and the full lockup
          was wide enough to sit across a piece in the corner. */}
      <div
        style={{
          position: 'absolute',
          left: 22,
          top: 20,
          zIndex: 3,
          width: 56,
          height: 56,
          borderRadius: 15,
          background: `linear-gradient(135deg, ${THEME.accent}, ${THEME.alt})`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 36,
          color: THEME.bg0,
          lineHeight: 1,
          boxShadow: '0 6px 20px rgba(0,0,0,0.6)',
        }}
      >
        ♞
      </div>
    </AbsoluteFill>
  );
};
