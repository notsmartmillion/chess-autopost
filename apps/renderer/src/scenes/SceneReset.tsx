import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from 'remotion';

interface SceneResetProps {
  scene: {
    id: string;
    durationMs: number;
  };
}

export const SceneReset: React.FC<SceneResetProps> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  
  // Quick flash/wipe effect
  const flashOpacity = interpolate(
    frame,
    [0, scene.durationMs * fps / 1000 / 4, scene.durationMs * fps / 1000 / 2],
    [0, 1, 0],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.inOut(Easing.cubic),
    }
  );
  
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        backgroundColor: '#1a1a1a',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Flash Effect */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: '#ffffff',
          opacity: flashOpacity,
          zIndex: 10,
        }}
      />
      
      {/* Optional: Subtle transition effect */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'linear-gradient(45deg, transparent 0%, rgba(255,255,255,0.1) 50%, transparent 100%)',
          opacity: flashOpacity * 0.5,
          zIndex: 5,
        }}
      />
    </div>
  );
};
