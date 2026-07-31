import React from 'react';
import {AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {THEME} from './AnalysisRail';

export type Quote = {
  text: string;
  author: string;
  /** Portrait file name inside /public/portraits, or null when we have none. */
  portrait?: string | null;
};

/**
 * The intro's second card: a chess quotation over the darkened board.
 *
 * It buys the viewer a moment before the analysis starts, and it gives the
 * intro somewhere to look while the narrator is still setting the scene. The
 * text comes from a hand-checked table, never from the narration model —
 * a fabricated line under a real player's name is a different kind of mistake
 * from a wrong arrow.
 */
export const QuoteCard: React.FC<{quote: Quote; startFrame?: number}> = ({
  quote,
  startFrame = 0,
}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [startFrame, startFrame + 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });
  // A slow settle rather than a slide: the channel's whole register is quiet,
  // and anything that moves quickly here reads as a different show.
  const rise = interpolate(frame, [startFrame, startFrame + 34], [26, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

  return (
    <AbsoluteFill
      style={{
        background: 'rgba(9,12,17,0.96)',
        alignItems: 'center',
        justifyContent: 'center',
        opacity,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 64,
          padding: 60,
          transform: `translateY(${rise}px)`,
        }}
      >
        {quote.portrait && (
          <div
            style={{
              width: 330,
              height: 420,
              flexShrink: 0,
              borderRadius: 10,
              overflow: 'hidden',
              boxShadow: `0 24px 60px rgba(0,0,0,0.55), 0 0 0 1px ${THEME.panelEdge}`,
            }}
          >
            <Img
              src={staticFile(`portraits/${quote.portrait}`)}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
                // Period photographs vary wildly in tone; desaturating them
                // lets a 1950s press photo and a modern one sit together.
                filter: 'grayscale(1) contrast(1.06)',
              }}
            />
          </div>
        )}

        {/* Sized to the text, not to the screen: a flexible column left a
            short quote hugging the left of a very wide box, which read as the
            whole card being off centre. */}
        <div style={{maxWidth: 900}}>
          <div
            style={{
              fontSize: 76,
              lineHeight: 1.16,
              color: THEME.accent,
              marginBottom: -18,
              opacity: 0.5,
            }}
          >
            “
          </div>
          <div
            style={{
              fontSize: quote.text.length > 150 ? 44 : 54,
              lineHeight: 1.4,
              color: THEME.text,
              fontWeight: 300,
            }}
          >
            {quote.text}
          </div>
          <div
            style={{
              height: 3,
              width: 90,
              background: THEME.accent,
              opacity: 0.6,
              margin: '34px 0 22px',
              borderRadius: 2,
            }}
          />
          <div style={{fontSize: 32, color: THEME.muted, letterSpacing: 2}}>
            {quote.author.toUpperCase()}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
