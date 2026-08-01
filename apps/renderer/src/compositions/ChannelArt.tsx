import React from 'react';
import {AbsoluteFill} from 'remotion';
import {THEME} from '../components/AnalysisRail';

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
