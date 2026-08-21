import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';
import {THEME} from '../components/AnalysisRail';

/* ------------------------------------------------------------------------ */
/*  Just the Moves — the slow-play channel's art                             */
/* ------------------------------------------------------------------------ */

// The slow-play composition's own palette, so the channel page matches the
// thumbnails sitting on it: lifted slate background, the board's two square
// tones, and the merida knight that stands on every video's board.
const JTM = {
  bg: '#262421',
  light: '#f0d9b5',
  dark: '#b58863',
  text: '#f3ede4',
  muted: '#b3a89a',
};

/** A fragment of board — cols x rows squares — with a knight over it. */
const BoardMark: React.FC<{cols: number; rows: number; square: number; knight: number; radius?: number}> = ({
  cols,
  rows,
  square,
  knight,
  radius = 0.08,
}) => {
  const w = cols * square;
  const h = rows * square;
  const cells = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      cells.push(
        <div
          key={`${r}-${c}`}
          style={{
            position: 'absolute',
            left: c * square,
            top: r * square,
            width: square,
            height: square,
            background: (r + c) % 2 === 0 ? JTM.light : JTM.dark,
          }}
        />
      );
    }
  }
  return (
    <div
      style={{
        position: 'relative',
        width: w,
        height: h,
        borderRadius: Math.round(w * radius),
        overflow: 'hidden',
        boxShadow: '0 18px 50px rgba(0,0,0,0.45)',
      }}
    >
      {cells}
      <Img
        src={staticFile('pieces/merida/bn.svg')}
        style={{
          position: 'absolute',
          width: knight,
          height: knight,
          left: (w - knight) / 2,
          top: (h - knight) / 2,
          filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.35))',
        }}
      />
    </div>
  );
};

/**
 * Avatar — 800x800, shown as a circle everywhere. The mark alone: a 2x2 board
 * fragment with the knight over it. No words — at 48 px they would be noise.
 */
export const JtmAvatar: React.FC = () => (
  <AbsoluteFill style={{background: JTM.bg, alignItems: 'center', justifyContent: 'center'}}>
    <BoardMark cols={2} rows={2} square={215} knight={330} radius={0.09} />
  </AbsoluteFill>
);

/**
 * Banner — 2048x1152, safe strip 1235x338 in the centre. Mark left, name
 * right, tagline under it; a faint oversized board fades across the rest for
 * desktop, where the whole canvas shows.
 */
export const JtmBanner: React.FC = () => {
  const big = 128;
  const ghost = [];
  for (let r = 0; r < 9; r++) {
    for (let c = 0; c < 16; c++) {
      if ((r + c) % 2 === 0) continue;
      ghost.push(
        <div
          key={`${r}-${c}`}
          style={{
            position: 'absolute',
            left: c * big,
            top: r * big,
            width: big,
            height: big,
            background: 'rgba(214, 221, 232, 0.035)',
          }}
        />
      );
    }
  }
  return (
    <AbsoluteFill style={{background: JTM.bg, fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif'}}>
      <AbsoluteFill style={{opacity: 1}}>{ghost}</AbsoluteFill>
      <AbsoluteFill
        style={{
          background:
            `radial-gradient(900px 520px at 50% 50%, rgba(29,36,48,0) 0%, rgba(29,36,48,0.6) 70%, ${JTM.bg} 100%)`,
        }}
      />
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
        <div
          style={{
            width: 1235,
            height: 338,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 54,
          }}
        >
          <BoardMark cols={3} rows={2} square={118} knight={190} radius={0.05} />
          <div style={{display: 'flex', flexDirection: 'column', gap: 14}}>
            <div
              style={{
                fontSize: 118,
                fontWeight: 800,
                letterSpacing: -2,
                lineHeight: 1,
                color: JTM.text,
              }}
            >
              Just the Moves
            </div>
            <div style={{fontSize: 36, letterSpacing: 5, color: JTM.muted, textTransform: 'uppercase'}}>
              Full chess games · No commentary
            </div>
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/**
 * The channel's own artwork, built from the same mark and palette the videos
 * use.
 *
 * Made here rather than in a design tool for one reason: the knight glyph, the
 * gradient and the background are read from THEME, so if the video's look ever
 * changes, re-rendering these keeps the channel page from drifting out of step
 * with the thing it is advertising.
 */

const KNIGHT = '♞';

/**
 * Watermark — the small overlay in the player's corner. On YouTube this is the
 * one genuinely clickable subscribe control, so it is the mark alone at high
 * contrast: at 150px over arbitrary video frames, anything with text in it
 * turns to mush.
 */
export const ChannelWatermark: React.FC = () => (
  <AbsoluteFill
    style={{
      background: 'transparent',
      alignItems: 'center',
      justifyContent: 'center',
    }}
  >
    <div
      style={{
        width: 132,
        height: 132,
        borderRadius: 34,
        background: `linear-gradient(135deg, ${THEME.accent}, ${THEME.alt})`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        // A dark ring keeps the mark legible over a light chessboard, which is
        // exactly what it will usually be sitting on.
        boxShadow: `0 0 0 6px ${THEME.bg0}`,
        fontSize: 86,
        color: THEME.bg0,
        lineHeight: 1,
      }}
    >
      {KNIGHT}
    </div>
  </AbsoluteFill>
);

/**
 * Banner — 2048x1152, but only the middle 1235x338 is safe on every device.
 * Everything that must be read lives inside that strip; the rest is atmosphere
 * for desktop.
 */
export const ChannelBanner: React.FC = () => (
  <AbsoluteFill style={{background: THEME.bg0, fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif'}}>
    <AbsoluteFill
      style={{
        background:
          `radial-gradient(1200px 700px at 30% 45%, ${THEME.accent}1f, transparent 70%),` +
          `radial-gradient(1000px 620px at 74% 62%, ${THEME.alt}18, transparent 70%)`,
      }}
    />
    <AbsoluteFill
      style={{
        opacity: 0.5,
        backgroundImage:
          'linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),' +
          'linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)',
        backgroundSize: '96px 96px',
      }}
    />

    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center'}}>
      {/* The safe strip. Nothing outside this is guaranteed to be seen. */}
      <div
        style={{
          width: 1235,
          height: 338,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 26,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', gap: 30}}>
          <div
            style={{
              width: 96,
              height: 96,
              borderRadius: 24,
              background: `linear-gradient(135deg, ${THEME.accent}, ${THEME.alt})`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 62,
              color: THEME.bg0,
              lineHeight: 1,
            }}
          >
            {KNIGHT}
          </div>
          <div
            style={{
              fontSize: 92,
              letterSpacing: 16,
              color: THEME.text,
              textTransform: 'uppercase',
              fontWeight: 300,
            }}
          >
            Nocturne Chess
          </div>
        </div>
        <div style={{fontSize: 33, letterSpacing: 6, color: THEME.muted, textTransform: 'uppercase'}}>
          Great games, quietly told · New game daily
        </div>
      </div>
    </AbsoluteFill>
  </AbsoluteFill>
);
