import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from 'remotion';
import { SceneMain } from '../types/timeline';
import { Board } from '../components/Board';
import { Arrow } from '../components/Arrow';
import { SquareHighlight } from '../components/SquareHighlight';
import { Heatmap } from '../components/Heatmap';
import { PinHighlight } from '../components/PinHighlight';
import { EvalBar } from '../components/EvalBar';
import { PortraitPanel } from '../components/PortraitPanel';
import { getAnimationTiming } from '../lib/audio-browser';

interface SceneMainMoveProps {
  scene: SceneMain;
  timeline: {
    meta: {
      white: string;
      black: string;
    };
  };
  showChrome?: boolean; // persistent layout can hide EvalBar/Portraits
  renderBoard?: boolean; // when false, only overlays render
}

export const SceneMainMove: React.FC<SceneMainMoveProps> = ({ scene, timeline, showChrome = true, renderBoard = true }) => {
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
  
  // Move highlight animation
  const arrowOpacity = interpolate(
    frame,
    [arrowTiming.startFrame, arrowTiming.startFrame + 8],
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
    [evalBarTiming.startFrame, evalBarTiming.startFrame + 10],
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
    [pinTiming.startFrame, pinTiming.startFrame + 6],
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
    [heatmapTiming.startFrame, heatmapTiming.startFrame + 8],
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
        backgroundColor: 'transparent',
        position: 'relative',
      }}
    >
      {/* Portrait Panel (optional) */}
      {showChrome && (
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
      )}
      
      {/* Main Board (optional when using persistent board) */}
      <div
        style={{
          position: 'relative',
          marginTop: 0,
        }}
      >
        {renderBoard && (
          <Board
            fen={scene.fen}
            size={720}
            showCoordinates={true}
          />
        )}
        
        {/* Last move squares: BEFORE (origin) + AFTER (destination) */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            opacity: arrowOpacity,
          }}
        >
          {/* Origin (before) always yellow */}
          <SquareHighlight
            square={scene.lastMoveArrow[0]}
            boardSize={720}
            squareSize={90}
            theme="yellow"
            borderWidth={3}
          />
          {/* Destination (after): red if capture, else yellow */}
          <SquareHighlight
            square={scene.lastMoveArrow[1]}
            boardSize={720}
            squareSize={90}
            theme={(scene as any).captured ? 'red' : 'yellow'}
            borderWidth={4}
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
              boardSize={720}
              squareSize={90}
              delay={index * 2}
            />
          </div>
        ))}
        
        {/* Attack Heatmap */}
        {scene.moveNumber && scene.moveNumber > 5 && (
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
              prevAttacked={(scene as any).prevAttacked}
              fen={scene.fen}
              mover={scene.player || 'white'}
              boardSize={720}
              squareSize={90}
            />
          </div>
        )}
      </div>
      
      {/* Evaluation Bar (optional, persistent layout will render its own) */}
      {showChrome && (
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
      )}
      
      {/* Move Information removed per request */}

      {/* Per-move engine tag badge at destination square (top-right of the square) */}
      {(() => {
        const tag = (scene as any).tag as string | undefined;
        const allowed = new Set(['brilliant', 'great', 'inaccuracy', 'blunder']);
        if (!tag || !allowed.has(tag)) return null;
        const to = scene.lastMoveArrow[1];
        const file = to.charCodeAt(0) - 97; // a=0
        const rank = 8 - parseInt(to[1], 10); // 8=0
        const squareSize = 90;
        const x = file * squareSize;
        const y = rank * squareSize;
        const token = tag === 'brilliant' ? '!!' : tag === 'great' ? '!' : tag === 'blunder' ? '??' : '!?';
        const bg = tag === 'brilliant' ? 'rgba(0, 199, 160, 0.95)'
                 : tag === 'great' ? 'rgba(255, 193, 7, 0.95)'
                 : tag === 'inaccuracy' ? 'rgba(255, 165, 0, 0.95)'
                 : 'rgba(220, 53, 69, 0.95)';
        return (
          <div
            style={{
              position: 'absolute',
              left: x + squareSize - 26,
              top: y + 4,
              width: 22,
              height: 22,
              borderRadius: 6,
              background: bg,
              color: '#fff',
              fontSize: 12,
              fontWeight: 900,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 2px 6px rgba(0,0,0,0.35)'
            }}
          >
            {token}
          </div>
        );
      })()}
    </div>
  );
};
