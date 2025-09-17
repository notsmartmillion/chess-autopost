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
  
  // Calculate arrow properties
  const dx = toCoords.x - fromCoords.x;
  const dy = toCoords.y - fromCoords.y;
  const length = Math.sqrt(dx * dx + dy * dy);
  const angle = Math.atan2(dy, dx) * (180 / Math.PI);
  
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
  
  const strokeWidth = weight === 'thick' ? 4 : 2;
  const arrowHeadSize = weight === 'thick' ? 12 : 8;
  
  // Arrow head points
  const arrowHeadAngle1 = angle - 30;
  const arrowHeadAngle2 = angle + 30;
  const arrowHead1X = toCoords.x - arrowHeadSize * Math.cos(arrowHeadAngle1 * Math.PI / 180);
  const arrowHead1Y = toCoords.y - arrowHeadSize * Math.sin(arrowHeadAngle1 * Math.PI / 180);
  const arrowHead2X = toCoords.x - arrowHeadSize * Math.cos(arrowHeadAngle2 * Math.PI / 180);
  const arrowHead2Y = toCoords.y - arrowHeadSize * Math.sin(arrowHeadAngle2 * Math.PI / 180);
  
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
        {/* Arrow line */}
        <line
          x1={fromCoords.x}
          y1={fromCoords.y}
          x2={toCoords.x}
          y2={toCoords.y}
          stroke={color}
          strokeWidth={strokeWidth}
          strokeOpacity={animatedOpacity}
          strokeDasharray={dashed ? '5,5' : 'none'}
          strokeLinecap="round"
        />
        
        {/* Arrow head */}
        <polygon
          points={`${toCoords.x},${toCoords.y} ${arrowHead1X},${arrowHead1Y} ${arrowHead2X},${arrowHead2Y}`}
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
