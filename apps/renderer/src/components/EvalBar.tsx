import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from 'remotion';

interface EvalBarProps {
  target: number; // -1 to 1
  width?: number;
  height?: number;
  delay?: number;
  duration?: number;
  showValue?: boolean;
  style?: React.CSSProperties;
}

export const EvalBar: React.FC<EvalBarProps> = ({
  target,
  width = 200,
  height = 20,
  delay = 0,
  duration = 30,
  showValue = true,
  style = {},
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  
  // Animate to target value
  const animatedValue = interpolate(
    frame,
    [delay, delay + duration],
    [0, target],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );
  
  // Convert to percentage (0-100)
  const percentage = Math.abs(animatedValue) * 100;
  const isPositive = animatedValue >= 0;
  
  // Color based on evaluation
  const getBarColor = (value: number) => {
    if (Math.abs(value) < 0.1) return '#4CAF50'; // Equal
    if (Math.abs(value) < 0.3) return '#8BC34A'; // Slight advantage
    if (Math.abs(value) < 0.6) return '#FFC107'; // Advantage
    return '#FF5722'; // Winning
  };
  
  const barColor = getBarColor(animatedValue);
  
  // Format evaluation text
  const formatEval = (value: number) => {
    if (Math.abs(value) < 0.01) return '0.0';
    const pawns = value * 10; // Rough conversion to pawns
    return `${value > 0 ? '+' : ''}${pawns.toFixed(1)}`;
  };
  
  return (
    <div
      style={{
        width,
        height,
        backgroundColor: '#2c2c2c',
        borderRadius: height / 2,
        position: 'relative',
        overflow: 'hidden',
        border: '2px solid #444',
        ...style,
      }}
    >
      {/* Background gradient */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'linear-gradient(90deg, #2c2c2c 0%, #4c4c4c 50%, #2c2c2c 100%)',
        }}
      />
      
      {/* Evaluation bar */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          width: `${percentage}%`,
          backgroundColor: barColor,
          borderRadius: height / 2,
          transition: 'all 0.3s ease-in-out',
          boxShadow: `0 0 ${height * 0.5}px ${barColor}`,
          left: isPositive ? '50%' : `${50 - percentage}%`,
        }}
      />
      
      {/* Center line */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: '50%',
          width: 2,
          height: '100%',
          backgroundColor: '#fff',
          transform: 'translateX(-50%)',
          opacity: 0.7,
        }}
      />
      
      {/* Evaluation text */}
      {showValue && (
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            color: '#fff',
            fontSize: height * 0.6,
            fontWeight: 'bold',
            textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
            zIndex: 1,
          }}
        >
          {formatEval(animatedValue)}
        </div>
      )}
      
      {/* Side labels */}
      <div
        style={{
          position: 'absolute',
          top: '50%',
          left: 5,
          transform: 'translateY(-50%)',
          color: '#fff',
          fontSize: height * 0.4,
          fontWeight: 'bold',
          textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
        }}
      >
        Black
      </div>
      <div
        style={{
          position: 'absolute',
          top: '50%',
          right: 5,
          transform: 'translateY(-50%)',
          color: '#fff',
          fontSize: height * 0.4,
          fontWeight: 'bold',
          textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
        }}
      >
        White
      </div>
    </div>
  );
};
