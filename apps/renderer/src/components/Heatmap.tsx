import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from 'remotion';
import { Attacked } from '../types/timeline';

interface HeatmapProps {
  attacked: Attacked;
  boardSize?: number;
  squareSize?: number;
  color?: string;
  opacity?: number;
  delay?: number;
  duration?: number;
}

export const Heatmap: React.FC<HeatmapProps> = ({
  attacked,
  boardSize = 400,
  squareSize = 50,
  color = '#ff6b6b',
  opacity = 0.3,
  delay = 0,
  duration = 20,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  
  // Convert algebraic notation to coordinates
  const getSquareCoords = (square: string) => {
    const file = square.charCodeAt(0) - 97; // a=0, b=1, etc.
    const rank = 8 - parseInt(square[1]); // 8=0, 7=1, etc.
    return {
      x: file * squareSize,
      y: rank * squareSize,
    };
  };
  
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
  
  // Combine all attacked squares
  const allAttackedSquares = [...attacked.white, ...attacked.black];
  
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
      {allAttackedSquares.map((square, index) => {
        const coords = getSquareCoords(square);
        
        return (
          <div
            key={`${square}-${index}`}
            style={{
              position: 'absolute',
              left: coords.x,
              top: coords.y,
              width: squareSize,
              height: squareSize,
              backgroundColor: color,
              opacity: animatedOpacity,
              transition: 'opacity 0.3s ease-in-out',
            }}
          />
        );
      })}
    </div>
  );
};
