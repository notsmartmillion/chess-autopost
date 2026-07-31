import React from 'react';
import {Easing, interpolate, useCurrentFrame} from 'remotion';
import {THEME} from './AnalysisRail';

/**
 * A subscribe prompt, in the channel's own palette.
 *
 * Deliberately not a copy of YouTube's button. Reproducing their mark is
 * governed by their brand guidelines, and a saturated red pill would fight
 * everything else on screen anyway — this channel's whole look is quiet.
 *
 * It also does not sit there permanently. A badge that never leaves stops
 * being read after ten seconds; one that arrives, waits, and goes is noticed
 * every time. It appears twice: once after the viewer has settled into the
 * game, and once more over the sign-off.
 */
export const SubscribeBadge: React.FC<{
  /** Absolute frame the badge begins its entrance. */
  startFrame: number;
  /** How long it stays fully visible, in frames, excluding the fades. */
  holdFrames: number;
}> = ({startFrame, holdFrames}) => {
  const frame = useCurrentFrame();
  const FADE = 18;
  const end = startFrame + FADE + holdFrames + FADE;
  if (frame < startFrame || frame > end) return null;

  const opacity = interpolate(
    frame,
    [startFrame, startFrame + FADE, end - FADE, end],
    [0, 1, 1, 0],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.inOut(Easing.cubic)}
  );
  const slide = interpolate(frame, [startFrame, startFrame + FADE], [22, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

  return (
    <div
      style={{
        position: 'absolute',
        // The strip along the top, between the wordmark and the player cards:
        // the one place on the layout that is empty in every frame of every
        // video, so nothing has to move aside to make room. Right edge aligned
        // to the board's, which is a line the eye already follows.
        right: 1920 - (96 + 880),
        top: 30,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '18px 30px',
        borderRadius: 999,
        background: 'rgba(16,21,29,0.92)',
        border: `1px solid ${THEME.accent}55`,
        boxShadow: '0 18px 44px rgba(0,0,0,0.5)',
        opacity,
        transform: `translateY(${slide}px)`,
      }}
    >
      {/* A play glyph rather than any platform's logo. */}
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 999,
          background: THEME.accent,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: 0,
            height: 0,
            marginLeft: 4,
            borderLeft: `12px solid ${THEME.bg0}`,
            borderTop: '8px solid transparent',
            borderBottom: '8px solid transparent',
          }}
        />
      </div>
      <div
        style={{
          fontSize: 27,
          letterSpacing: 3.5,
          color: THEME.text,
          fontWeight: 600,
        }}
      >
        SUBSCRIBE
      </div>
    </div>
  );
};
