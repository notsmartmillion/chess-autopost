import React, {useEffect, useRef} from 'react';
import { useCurrentFrame, useVideoConfig, Easing } from 'remotion';

interface EvalBarProps {
  target: number; // 0..1 (0 = black better, 1 = white better)
  width?: number;
  height?: number;
  smoothingFrames?: number; // frames to tween between values
  showValue?: boolean;
  orientation?: 'horizontal' | 'vertical';
  style?: React.CSSProperties;
  changeKey?: string; // when this changes (e.g., scene id), start a new tween
  startDelayFrames?: number; // debounce before starting tween after key change
}

export const EvalBar: React.FC<EvalBarProps> = ({
  target,
  width = 200,
  height = 20,
  smoothingFrames = 30,
  showValue = true,
  orientation = 'horizontal',
  style = {},
  changeKey,
  startDelayFrames = 8,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Smooth tween from previous value to new target, clamped to sensible range
  // Timeline provides -1..+1 (white POV). Convert to 0..1 for the bar and clamp.
  const normalizedTarget01 = (target + 1) / 2;
  const clampedTarget = Math.min(0.95, Math.max(0.05, normalizedTarget01));
  const startFrameRef = useRef<number>(0);
  const startValueRef = useRef<number>(0.5);
  const lastValueRef = useRef<number>(0.5);
  const lastTargetRef = useRef<number>(clampedTarget);
  const lastKeyRef = useRef<string | undefined>(undefined);

  // Reset tween only when the changeKey changes (scene boundary), not on tiny target jitters
  if (changeKey !== lastKeyRef.current) {
    startFrameRef.current = frame + Math.max(0, startDelayFrames);
    startValueRef.current = lastValueRef.current;
    lastTargetRef.current = clampedTarget;
    lastKeyRef.current = changeKey;
  }

  const progress = Math.min(1, Math.max(0, (frame - startFrameRef.current) / Math.max(1, smoothingFrames)));
  const eased = Easing.out(Easing.cubic)(progress);
  const animated = startValueRef.current + (lastTargetRef.current - startValueRef.current) * eased;
  lastValueRef.current = animated;

  const pct = Math.min(100, Math.max(0, animated * 100)); // 0..100 (white share)

  if (orientation === 'vertical') {
    const w = width || 24;
    const h = height || 600;
    const whiteHeight = (pct / 100) * h;
    const blackHeight = h - whiteHeight;
    return (
      <div style={{width: w, height: h, position:'relative', borderRadius: 12, overflow:'hidden', border:'2px solid #444', background:'#2c2c2c', ...style}}>
        {/* Black on top */}
        <div style={{position:'absolute', top:0, left:0, width:'100%', height:blackHeight, background:'#333'}}/>
        {/* White on bottom */}
        <div style={{position:'absolute', bottom:0, left:0, width:'100%', height:whiteHeight, background:'#e0e0e0'}}/>
        {/* Middle line */}
        <div style={{position:'absolute', left:0, top:'50%', width:'100%', height:2, background:'#fff', opacity:0.6, transform:'translateY(-50%)'}}/>
        {showValue && (
          <div style={{position:'absolute', left:'50%', bottom: whiteHeight + 8, transform:'translateX(-50%)', color:'#fff', fontSize:12}}>
            {`${pct.toFixed(0)}%`}
          </div>
        )}
      </div>
    );
  }

  // Horizontal (default)
  return (
    <div style={{width, height, position:'relative', borderRadius: height/2, overflow:'hidden', border:'2px solid #444', background:'#2c2c2c', ...style}}>
      <div style={{position:'absolute', top:0, left:0, height:'100%', width:`${100 - pct}%`, background:'#333'}}/>
      <div style={{position:'absolute', top:0, left:`${100 - pct}%`, height:'100%', width:`${pct}%`, background:'#e0e0e0'}}/>
      <div style={{position:'absolute', top:0, left:'50%', width:2, height:'100%', background:'#fff', opacity:0.6, transform:'translateX(-50%)'}}/>
      {showValue && (
        <div style={{position:'absolute', top:'50%', left:'50%', transform:'translate(-50%, -50%)', fontWeight:'bold', color:'#fff', textShadow:'1px 1px 2px #000'}}>
          {`White ${pct.toFixed(0)}%`}
        </div>
      )}
    </div>
  );
};
