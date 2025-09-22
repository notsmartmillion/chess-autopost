import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, Easing } from 'remotion';
import { SceneAlt } from '../types/timeline';
import { Board } from '../components/Board';
import { Arrow } from '../components/Arrow';
import { Heatmap } from '../components/Heatmap';
import { getAnimationTiming } from '../lib/audio-browser';

interface SceneAltPreviewProps {
  scene: SceneAlt;
  baseFen?: string; // parent main scene's fen for now
}

export const SceneAltPreview: React.FC<SceneAltPreviewProps> = ({ scene, baseFen }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const labelTiming = getAnimationTiming(scene.durationMs, scene.cueTimes, 'alt', 0.0, fps);
  const arrowTiming = getAnimationTiming(scene.durationMs, scene.cueTimes, 'arrow', 0.1, fps);
  const heatmapTiming = getAnimationTiming(scene.durationMs, scene.cueTimes, 'attacked', 0.3, fps);

  const labelOpacity = interpolate(frame, [labelTiming.startFrame, labelTiming.startFrame + 10], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic),
  });
  const arrowOpacity = interpolate(frame, [arrowTiming.startFrame, arrowTiming.startFrame + 15], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic),
  });
  const heatmapOpacity = interpolate(frame, [heatmapTiming.startFrame, heatmapTiming.startFrame + 10], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic),
  });

  const fen = baseFen ?? "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
  const cpText = typeof scene.cp === 'number' ? `${scene.cp >= 0 ? '+' : ''}${(scene.cp/100).toFixed(2)}` : null;

  return (
    <div style={{width:'100%',height:'100%',backgroundColor:'#1a1a1a',display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',position:'relative'}}>
      {/* Label */}
      <div style={{
        position:'absolute', top:50, left:'50%', transform:'translateX(-50%)',
        color:'#fff', fontSize:28, fontWeight:'bold', textAlign:'center',
        textShadow:'2px 2px 4px rgba(0,0,0,0.8)', opacity:labelOpacity,
        backgroundColor:'rgba(0,0,0,0.7)', padding:'10px 20px', borderRadius:10, border:'2px solid #ff6b6b'
      }}>
        {scene.label}
        {cpText && <div style={{ fontSize: 18, marginTop: 5 }}>{cpText}</div>}
        {!cpText && scene.mate && <div style={{ fontSize: 18, marginTop: 5 }}>Mate in {scene.mate}</div>}
      </div>

      {/* Board + arrows + heatmap */}
      <div style={{position:'relative', marginTop:120}}>
        <Board fen={fen} size={500} showCoordinates />
        {scene.arrows.map((arrow, index) => (
          <div key={`alt-arrow-${index}`} style={{position:'absolute', top:0, left:0, opacity:arrowOpacity}}>
            <Arrow from={arrow[0]} to={arrow[1]} weight="thin" dashed color="#4CAF50" boardSize={500} squareSize={62.5} delay={index * 3}/>
          </div>
        ))}
        <div style={{position:'absolute', top:0, left:0, opacity:heatmapOpacity}}>
          <Heatmap attacked={scene.attacked} boardSize={500} squareSize={62.5} color="#4CAF50" opacity={0.2} />
        </div>
      </div>

      {/* PV text */}
      <div style={{
        position:'absolute', bottom:50, left:'50%', transform:'translateX(-50%)',
        color:'#fff', fontSize:18, textAlign:'center', textShadow:'1px 1px 2px rgba(0,0,0,0.8)',
        opacity:labelOpacity, backgroundColor:'rgba(0,0,0,0.7)', padding:'10px 15px', borderRadius:5
      }}>
        {scene.pv.slice(0, 3).join(' ')}{scene.pv.length > 3 && '...'}
      </div>
    </div>
  );
};
