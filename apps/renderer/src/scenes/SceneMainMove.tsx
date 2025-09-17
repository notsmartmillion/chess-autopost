import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from 'remotion';
import { SceneMain } from '../types/timeline';
import { Board } from '../components/Board';
import { Arrow } from '../components/Arrow';
import { Heatmap } from '../components/Heatmap';
import { PinHighlight } from '../components/PinHighlight';
import { EvalBar } from '../components/EvalBar';
import { PortraitPanel } from '../components/PortraitPanel';
import { getAnimationTiming } from '../lib/audio';

interface SceneMainMoveProps {
  scene: SceneMain;
  timeline: {
    meta: {
      white: string;
      black: string;
    };
  };
}

export const SceneMainMove: React.FC<SceneMainMoveProps> = ({ scene, timeline }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  
  // Calculate animation timings based on cue times or fallback percentages
  const arrowTiming = getAnimationTiming(
    scene.durationMs,
    scene.cueTimes,
    'move',
    0.0, // Start immediately
    fps
  );
  
  const evalBarTiming = getAnimationTiming(
    scene.durationMs,
    scene.cueTimes,
    'eval',
    0.1, // Start at 10%
    fps
  );
  
  const pinTiming = getAnimationTiming(
    scene.durationMs,
    scene.cueTimes,
    'pinned',
    0.35, // Start at 35%
    fps
  );
  
  const heatmapTiming = getAnimationTiming(
    scene.durationMs,
    scene.cueTimes,
    'attacked',
    0.5, // Start at 50%
    fps
  );
  
  // Arrow animation
  const arrowOpacity = interpolate(
    frame,
    [arrowTiming.startFrame, arrowTiming.startFrame + 15],
    [0, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );
  
  // Eval bar animation
  const evalBarOpacity = interpolate(
    frame,
    [evalBarTiming.startFrame, evalBarTiming.startFrame + 20],
    [0, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );
  
  // Pin highlight animation
  const pinOpacity = interpolate(
    frame,
    [pinTiming.startFrame, pinTiming.startFrame + 10],
    [0, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );
  
  // Heatmap animation
  const heatmapOpacity = interpolate(
    frame,
    [heatmapTiming.startFrame, heatmapTiming.startFrame + 15],
    [0, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );
  
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        backgroundColor: '#1a1a1a',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
      }}
    >
      {/* Portrait Panel */}
      <div
        style={{
          position: 'absolute',
          top: 20,
          left: 20,
          right: 20,
          zIndex: 10,
        }}
      >
        <PortraitPanel
          whitePlayer={timeline.meta.white}
          blackPlayer={timeline.meta.black}
          currentPlayer={scene.player}
        />
      </div>
      
      {/* Main Board */}
      <div
        style={{
          position: 'relative',
          marginTop: 120,
        }}
      >
        <Board
          fen={scene.fen}
          size={600}
          showCoordinates={true}
        />
        
        {/* Last Move Arrow */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            opacity: arrowOpacity,
          }}
        >
          <Arrow
            from={scene.lastMoveArrow[0]}
            to={scene.lastMoveArrow[1]}
            weight="thick"
            color="#ff6b6b"
            boardSize={600}
            squareSize={75}
          />
        </div>
        
        {/* Pin Highlights */}
        {scene.pins.map((pin, index) => (
          <div
            key={`pin-${index}`}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              opacity: pinOpacity,
            }}
          >
            <PinHighlight
              pin={pin}
              boardSize={600}
              squareSize={75}
              delay={index * 2}
            />
          </div>
        ))}
        
        {/* Attack Heatmap */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            opacity: heatmapOpacity,
          }}
        >
          <Heatmap
            attacked={scene.attacked}
            boardSize={600}
            squareSize={75}
            color="#ffeb3b"
            opacity={0.3}
          />
        </div>
      </div>
      
      {/* Evaluation Bar */}
      <div
        style={{
          position: 'absolute',
          bottom: 100,
          left: '50%',
          transform: 'translateX(-50%)',
          opacity: evalBarOpacity,
        }}
      >
        <EvalBar
          target={scene.evalBarTarget}
          width={300}
          height={30}
          showValue={true}
        />
      </div>
      
      {/* Move Information */}
      <div
        style={{
          position: 'absolute',
          bottom: 50,
          left: '50%',
          transform: 'translateX(-50%)',
          color: '#fff',
          fontSize: 24,
          fontWeight: 'bold',
          textAlign: 'center',
          textShadow: '2px 2px 4px rgba(0,0,0,0.8)',
        }}
      >
        {scene.moveNumber && (
          <div>
            Move {scene.moveNumber}: {scene.move}
          </div>
        )}
      </div>
    </div>
  );
};
