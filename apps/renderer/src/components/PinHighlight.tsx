import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from 'remotion';
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
  
  // Animation
  const animatedGlowOpacity = interpolate(
    frame,
    [delay, delay + duration],
    [0, glowOpacity],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );
  
  const animatedRayOpacity = interpolate(
    frame,
    [delay + 10, delay + duration],
    [0, rayOpacity],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );
  
  const pinnedCoords = getSquareCoords(pin.sq);
  
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
      {/* Glow effect on pinned piece */}
      <div
        style={{
          position: 'absolute',
          left: pinnedCoords.x - squareSize / 2,
          top: pinnedCoords.y - squareSize / 2,
          width: squareSize,
          height: squareSize,
          borderRadius: '50%',
          backgroundColor: glowColor,
          opacity: animatedGlowOpacity,
          boxShadow: `0 0 ${squareSize * 0.3}px ${glowColor}`,
          animation: 'pulse 1s ease-in-out infinite alternate',
        }}
      />
      
      {/* Ray to king */}
      {pin.ray && pin.ray.length > 0 && (
        <svg
          width={boardSize}
          height={boardSize}
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
          }}
        >
          {pin.ray.map((raySquare, index) => {
            const rayCoords = getSquareCoords(raySquare);
            
            return (
              <circle
                key={`ray-${index}`}
                cx={rayCoords.x}
                cy={rayCoords.y}
                r={squareSize * 0.1}
                fill={rayColor}
                opacity={animatedRayOpacity * (1 - index * 0.1)}
              />
            );
          })}
          
          {/* Line connecting pinned piece to king */}
          {pin.king && (
            <line
              x1={pinnedCoords.x}
              y1={pinnedCoords.y}
              x2={getSquareCoords(pin.king).x}
              y2={getSquareCoords(pin.king).y}
              stroke={rayColor}
              strokeWidth={2}
              strokeOpacity={animatedRayOpacity}
              strokeDasharray="3,3"
            />
          )}
        </svg>
      )}
      
      <style jsx>{`
        @keyframes pulse {
          0% {
            transform: scale(1);
            opacity: ${animatedGlowOpacity};
          }
          100% {
            transform: scale(1.1);
            opacity: ${animatedGlowOpacity * 0.7};
          }
        }
      `}</style>
    </div>
  );
};
