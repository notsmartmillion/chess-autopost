import React from 'react';

type Props = {
  square: string; // e.g. "e4"
  boardSize: number; // px
  squareSize: number; // px
  color?: string; // fill color
  opacity?: number; // 0..1
  borderColor?: string; // optional stroke
  borderWidth?: number; // px
  radiusPct?: number; // 0..0.5 corner rounding relative to squareSize
  style?: React.CSSProperties;
};

export const SquareHighlight: React.FC<Props> = ({
  square,
  boardSize,
  squareSize,
  color = 'rgba(255, 204, 0, 0.7)',
  opacity = 1,
  borderColor = 'rgba(255, 204, 0, 0.95)',
  borderWidth = 3,
  radiusPct = 0.18,
  style = {},
}) => {
  const file = square.charCodeAt(0) - 97; // a→0
  const rank = 8 - parseInt(square[1], 10); // 8→0
  const left = file * squareSize;
  const top = rank * squareSize;
  const radius = Math.max(2, Math.min(squareSize * radiusPct, squareSize / 2));

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: boardSize,
        height: boardSize,
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          position: 'absolute',
          left,
          top,
          width: squareSize,
          height: squareSize,
          background: color,
          opacity,
          borderRadius: radius,
          boxShadow: `inset 0 0 0 ${borderWidth}px ${borderColor}`,
          ...style,
        }}
      />
    </div>
  );
};


