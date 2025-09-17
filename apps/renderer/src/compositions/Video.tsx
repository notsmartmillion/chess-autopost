import React from 'react';
import { Composition, useCurrentFrame, useVideoConfig } from 'remotion';
import { Timeline, Scene } from './types/timeline';
import { SceneMainMove } from '../scenes/SceneMainMove';
import { SceneAltPreview } from '../scenes/SceneAltPreview';
import { SceneReset } from '../scenes/SceneReset';
import { getClipDurations, loadAlignmentData } from '../lib/audio';

interface VideoProps {
  timeline: Timeline;
  audioDir: string;
  alignmentData?: Record<string, any>;
}

export const Video: React.FC<VideoProps> = ({ timeline, audioDir, alignmentData }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  
  // Calculate current scene based on frame
  let currentTimeMs = 0;
  let currentScene: Scene | null = null;
  let sceneStartFrame = 0;
  
  for (const scene of timeline.scenes) {
    const sceneEndFrame = sceneStartFrame + (scene.durationMs * fps / 1000);
    
    if (frame >= sceneStartFrame && frame < sceneEndFrame) {
      currentScene = scene;
      break;
    }
    
    currentTimeMs += scene.durationMs;
    sceneStartFrame = sceneEndFrame;
  }
  
  if (!currentScene) {
    // Return empty frame if no scene found
    return (
      <div
        style={{
          width: '100%',
          height: '100%',
          backgroundColor: '#1a1a1a',
        }}
      />
    );
  }
  
  // Render appropriate scene component
  switch (currentScene.type) {
    case 'main':
      return (
        <SceneMainMove
          scene={currentScene}
          timeline={timeline}
        />
      );
    
    case 'alt':
      return (
        <SceneAltPreview
          scene={currentScene}
        />
      );
    
    case 'reset':
      return (
        <SceneReset
          scene={currentScene}
        />
      );
    
    default:
      return (
        <div
          style={{
            width: '100%',
            height: '100%',
            backgroundColor: '#1a1a1a',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 24,
          }}
        >
          Unknown scene type: {currentScene.type}
        </div>
      );
  }
};

// Main video composition
export const ChessVideo: React.FC = () => {
  // This would typically load timeline and audio data
  // For now, we'll use a sample timeline
  const sampleTimeline: Timeline = {
    meta: {
      white: "Magnus Carlsen",
      black: "Hikaru Nakamura",
      date: "2023-01-15",
      event: "World Championship",
      result: "1-0",
      eco: "C42"
    },
    scenes: [
      {
        type: "main",
        id: "m1",
        fen: "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
        move: "e4",
        lastMoveArrow: ["e2", "e4"],
        evalBarTarget: 0.1,
        pins: [],
        attacked: { white: [], black: [] },
        durationMs: 2000,
        moveNumber: 1,
        player: "white"
      }
    ],
    totalDurationMs: 2000
  };
  
  return (
    <Video
      timeline={sampleTimeline}
      audioDir="./audio"
    />
  );
};

// Export composition for Remotion
export const ChessVideoComposition: React.FC = () => {
  return (
    <Composition
      id="ChessVideo"
      component={ChessVideo}
      durationInFrames={300} // 10 seconds at 30fps
      fps={30}
      width={1920}
      height={1080}
    />
  );
};
