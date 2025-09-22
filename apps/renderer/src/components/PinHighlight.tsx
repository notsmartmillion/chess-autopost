import React from 'react';
import { useCurrentFrame, interpolate, Easing } from 'remotion';
import { Pin } from '../types/timeline';

interface PinHighlightProps {
  pin: Pin;
  boardSize?: number;
  squareSize?: number;
  glowColor?: string;
  rayColor?: string;
  glowOpacity?: number;
  rayOpacity?: number;
  delay?: number;
  duration?: number;
}

export const PinHighlight: React.FC<PinHighlightProps> = ({
  pin,
  boardSize = 400,
  squareSize = 50,
  glowColor = '#ffeb3b',
  rayColor = '#ff9800',
  glowOpacity = 0.6,
  rayOpacity = 0.4,
  delay = 0,
  duration = 25,
}) => {
  const frame = useCurrentFrame();

  const toXY = (sq: string) => {
    const file = sq.charCodeAt(0) - 97;
    const rank = 8 - parseInt(sq[1], 10);
    return {x: file * squareSize + squareSize/2, y: rank * squareSize + squareSize/2};
  };

  const glowAlpha = interpolate(frame, [delay, delay + duration], [0, glowOpacity], {
    extrapolateLeft: 'clamp', extrapolateRight:'clamp', easing: Easing.out(Easing.cubic),
  });
  const rayAlpha = interpolate(frame, [delay + 10, delay + duration], [0, rayOpacity], {
    extrapolateLeft: 'clamp', extrapolateRight:'clamp', easing: Easing.out(Easing.cubic),
  });
  const scale = interpolate(frame, [delay, delay + duration], [0.9, 1.05], {
    extrapolateLeft: 'clamp', extrapolateRight:'clamp', easing: Easing.out(Easing.cubic),
  });

  const pinned = toXY(pin.sq);

  return (
    <div style={{position:'absolute', inset:0, width:boardSize, height:boardSize, pointerEvents:'none'}}>
      {/* Glow */}
      <div
        style={{
          position:'absolute',
          left: pinned.x - squareSize/2,
          top: pinned.y - squareSize/2,
          width: squareSize,
          height: squareSize,
          borderRadius:'50%',
          backgroundColor: glowColor,
          opacity: glowAlpha,
          transform: `scale(${scale})`,
          boxShadow: `0 0 ${squareSize * 0.35}px ${glowColor}`,
        }}
      />
      {/* Ray + breadcrumbs */}
      {pin.ray?.length ? (
        <svg width={boardSize} height={boardSize} style={{position:'absolute', inset:0}}>
          {pin.ray.map((sq, i) => {
            const p = toXY(sq);
            return <circle key={sq+i} cx={p.x} cy={p.y} r={squareSize*0.1} fill={rayColor} opacity={rayAlpha * (1 - i*0.1)} />;
          })}
          {pin.king && (
            <line
              x1={pinned.x} y1={pinned.y} x2={toXY(pin.king).x} y2={toXY(pin.king).y}
              stroke={rayColor} strokeWidth={2} strokeDasharray="3 3" strokeOpacity={rayAlpha}
            />
          )}
        </svg>
      ) : null}
    </div>
  );
};
