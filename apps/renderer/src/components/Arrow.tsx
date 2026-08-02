import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from 'remotion';

interface ArrowProps {
  from: string;
  to: string;
  weight?: 'thin' | 'thick';
  dashed?: boolean;
  label?: string;
  color?: string;
  opacity?: number;
  boardSize?: number;
  squareSize?: number;
  delay?: number;
  duration?: number;
}

export const Arrow: React.FC<ArrowProps> = ({
  from,
  to,
  weight = 'thick',
  dashed = false,
  label,
  color = '#ff6b6b',
  opacity = 1,
  boardSize = 400,
  squareSize = 50,
  delay = 0,
  duration = 30,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  
  // Convert algebraic notation to coordinates
  const getSquareCoords = (square: string) => {
    const file = square.charCodeAt(0) - 97; // a=0, b=1, etc.
    const rank = 8 - parseInt(square[1]); // 8=0, 7=1, etc.
    return {
      x: file * squareSize + squareSize / 2,
      y: rank * squareSize + squareSize / 2,
    };
  };
  
  const fromCoords = getSquareCoords(from);
  const toCoords = getSquareCoords(to);
  const fromFile = from.charCodeAt(0) - 97;
  const fromRank = parseInt(from[1], 10);
  const toFile = to.charCodeAt(0) - 97;
  const toRank = parseInt(to[1], 10);
  
  // Calculate arrow properties
  const dx = toCoords.x - fromCoords.x;
  const dy = toCoords.y - fromCoords.y;
  const length = Math.sqrt(dx * dx + dy * dy);

  // Decide if we draw straight or "L" shaped (for knight moves)
  const df = Math.abs(toFile - fromFile);
  const dr = Math.abs(toRank - fromRank);
  const isKnightMove = (df === 1 && dr === 2) || (df === 2 && dr === 1);

  // For an L-shaped arrow the head arrives along the *last* leg, so the shaft
  // direction — not the straight line between the squares — decides its angle.
  const goHorizontalLast = df > dr;
  const mid = isKnightMove
    ? goHorizontalLast
      ? { x: toCoords.x, y: fromCoords.y } // vertical first, then horizontal
      : { x: fromCoords.x, y: toCoords.y } // horizontal first, then vertical
    : fromCoords;

  const angle =
    Math.atan2(toCoords.y - mid.y, toCoords.x - mid.x) * (180 / Math.PI);

  // Stop short of the target square's centre: an arrow that runs to the middle
  // of the square buries its own head under the piece it is pointing at.
  const pullBack = (
    ax: number, ay: number, bx: number, by: number, inset: number
  ) => {
    const vx = bx - ax;
    const vy = by - ay;
    const len = Math.hypot(vx, vy) || 1;
    const k = Math.min(inset, len * 0.45) / len;
    return { x: bx - vx * k, y: by - vy * k };
  };

  const tip = pullBack(mid.x, mid.y, toCoords.x, toCoords.y, squareSize * 0.34);
  // On a straight arrow `mid` is the origin itself, so the first leg points at
  // the destination; on an L it points at the corner.
  const tailAnchor = isKnightMove ? mid : toCoords;
  const tail = pullBack(
    tailAnchor.x, tailAnchor.y, fromCoords.x, fromCoords.y, squareSize * 0.26
  );

  // Animation
  const animatedOpacity = interpolate(
    frame,
    [delay, delay + duration],
    [0, opacity],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );
  
  const strokeWidth = weight === 'thick' ? 6 : 3; // widened shafts

  // The head is built from an explicit length and half-width rather than an
  // angle, because that is what actually controls whether it reads as an
  // arrow: a head barely wider than its shaft looks like the line just
  // stopped. Sized against the square so it holds up at any board size.
  //
  // The previous version also drew the triangle between two different points
  // — barbs measured back from the pulled-back `tip`, apex at the square's
  // true centre — which stretched it into a sliver forty pixels long and
  // sixteen wide. Both ends now come from `tip`.
  const headLen = squareSize * (weight === 'thick' ? 0.21 : 0.15);
  const headHalf = squareSize * (weight === 'thick' ? 0.125 : 0.085);

  const ux = Math.cos((angle * Math.PI) / 180);
  const uy = Math.sin((angle * Math.PI) / 180);
  const baseX = tip.x - ux * headLen;
  const baseY = tip.y - uy * headLen;
  const arrowHead1X = baseX - uy * headHalf;
  const arrowHead1Y = baseY + ux * headHalf;
  const arrowHead2X = baseX + uy * headHalf;
  const arrowHead2Y = baseY - ux * headHalf;

  // The shaft stops where the head begins, less a hair so no seam shows.
  const shaftEnd = { x: baseX + ux * 1.5, y: baseY + uy * 1.5 };

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
      <svg
        width={boardSize}
        height={boardSize}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
        }}
      >
        {/* Arrow shaft */}
        {isKnightMove ? (
          // An L-shape: orthogonal from the start to the corner, then in to the
          // destination. Both legs are trimmed so the shaft clears the pieces.
          <>
            <line
              x1={tail.x}
              y1={tail.y}
              x2={mid.x}
              y2={mid.y}
              stroke={color}
              strokeWidth={strokeWidth}
              strokeOpacity={animatedOpacity}
              strokeDasharray={dashed ? '5,5' : 'none'}
              strokeLinecap="round"
            />
            <line
              x1={mid.x}
              y1={mid.y}
              x2={shaftEnd.x}
              y2={shaftEnd.y}
              stroke={color}
              strokeWidth={strokeWidth}
              strokeOpacity={animatedOpacity}
              strokeDasharray={dashed ? '5,5' : 'none'}
              strokeLinecap="round"
            />
          </>
        ) : (
          <line
            x1={tail.x}
            y1={tail.y}
            x2={shaftEnd.x}
            y2={shaftEnd.y}
            stroke={color}
            strokeWidth={strokeWidth}
            strokeOpacity={animatedOpacity}
            strokeDasharray={dashed ? '5,5' : 'none'}
            strokeLinecap="round"
          />
        )}
        
        {/* Arrow head */}
        <polygon
          points={`${tip.x},${tip.y} ${arrowHead1X},${arrowHead1Y} ${arrowHead2X},${arrowHead2Y}`}
          strokeLinejoin="round"
          fill={color}
          fillOpacity={animatedOpacity}
        />
        
        {/* Label */}
        {label && (
          <text
            x={(fromCoords.x + toCoords.x) / 2}
            y={(fromCoords.y + toCoords.y) / 2 - 10}
            textAnchor="middle"
            fill={color}
            fontSize="14"
            fontWeight="bold"
            opacity={animatedOpacity}
            style={{
              textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
            }}
          >
            {label}
          </text>
        )}
      </svg>
    </div>
  );
};
