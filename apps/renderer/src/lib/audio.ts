/**
 * Audio utilities for duration calculation and alignment.
 */

import fs from 'fs/promises';
import path from 'path';

export interface AudioClip {
  sceneId: string;
  durationMs: number;
  filePath: string;
}

export interface AlignmentData {
  scene_id: string;
  words: Array<{
    word: string;
    start: number;
    end: number;
    confidence: number;
  }>;
  keywords: Record<string, number>;
}

/**
 * Get audio duration using ffprobe (requires ffmpeg)
 */
export async function getAudioDuration(filePath: string): Promise<number> {
  try {
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);
    
    const command = `ffprobe -v quiet -show_entries format=duration -of csv=p=0 "${filePath}"`;
    const { stdout } = await execAsync(command);
    
    const durationSeconds = parseFloat(stdout.trim());
    return Math.round(durationSeconds * 1000); // Convert to milliseconds
  } catch (error) {
    console.warn(`Failed to get duration for ${filePath}:`, error);
    // Fallback: estimate based on file size (rough approximation)
    const stats = await fs.stat(filePath);
    const estimatedMs = Math.max(1000, stats.size / 1000); // 1KB ≈ 1ms
    return estimatedMs;
  }
}

/**
 * Get durations for all audio clips in a directory
 */
export async function getClipDurations(audioDir: string): Promise<Record<string, number>> {
  const durations: Record<string, number> = {};
  
  try {
    const files = await fs.readdir(audioDir);
    const wavFiles = files.filter(file => file.endsWith('.wav'));
    
    for (const file of wavFiles) {
      const sceneId = path.basename(file, '.wav');
      const filePath = path.join(audioDir, file);
      
      try {
        const duration = await getAudioDuration(filePath);
        durations[sceneId] = duration;
      } catch (error) {
        console.warn(`Failed to get duration for ${file}:`, error);
        durations[sceneId] = 2000; // Default 2 seconds
      }
    }
  } catch (error) {
    console.warn(`Failed to read audio directory ${audioDir}:`, error);
  }
  
  return durations;
}

/**
 * Load alignment data from JSON file
 */
export async function loadAlignmentData(alignmentPath: string): Promise<Record<string, AlignmentData>> {
  try {
    const data = await fs.readFile(alignmentPath, 'utf-8');
    return JSON.parse(data);
  } catch (error) {
    console.warn(`Failed to load alignment data from ${alignmentPath}:`, error);
    return {};
  }
}

/**
 * Calculate scene duration with audio-driven timing
 */
export function calculateSceneDuration(
  audioDurationMs: number,
  minDuration: number = 1200,
  maxDuration: number = 2500,
  paddingMs: number = 150
): number {
  const totalDuration = audioDurationMs + paddingMs;
  return Math.max(minDuration, Math.min(maxDuration, totalDuration));
}

/**
 * Get cue time for a specific keyword
 */
export function getCueTime(
  cueTimes: Record<string, number> | undefined,
  keyword: string,
  fallbackPercent: number = 0.5
): number {
  if (cueTimes && cueTimes[keyword] !== undefined) {
    return cueTimes[keyword] * 1000; // Convert seconds to milliseconds
  }
  return fallbackPercent;
}

/**
 * Convert time in milliseconds to frame number
 */
export function timeToFrame(timeMs: number, fps: number): number {
  return Math.round((timeMs / 1000) * fps);
}

/**
 * Convert frame number to time in milliseconds
 */
export function frameToTime(frame: number, fps: number): number {
  return (frame / fps) * 1000;
}

/**
 * Get animation timing based on cue times or fallback percentages
 */
export function getAnimationTiming(
  sceneDurationMs: number,
  cueTimes: Record<string, number> | undefined,
  keyword: string,
  fallbackPercent: number = 0.5,
  fps: number = 30
): {
  startFrame: number;
  endFrame: number;
  durationFrames: number;
} {
  const cueTimeMs = getCueTime(cueTimes, keyword, fallbackPercent);
  const startFrame = timeToFrame(cueTimeMs, fps);
  const endFrame = timeToFrame(sceneDurationMs, fps);
  const durationFrames = endFrame - startFrame;
  
  return {
    startFrame: Math.max(0, startFrame),
    endFrame: Math.max(startFrame + 1, endFrame),
    durationFrames: Math.max(1, durationFrames)
  };
}

/**
 * Validate audio files exist for all scene IDs
 */
export async function validateAudioFiles(
  sceneIds: string[],
  audioDir: string
): Promise<{ valid: string[]; missing: string[] }> {
  const valid: string[] = [];
  const missing: string[] = [];
  
  for (const sceneId of sceneIds) {
    const audioPath = path.join(audioDir, `${sceneId}.wav`);
    try {
      await fs.access(audioPath);
      valid.push(sceneId);
    } catch {
      missing.push(sceneId);
    }
  }
  
  return { valid, missing };
}

/**
 * Estimate total video duration from timeline and audio
 */
export function estimateTotalDuration(
  scenes: Array<{ durationMs: number }>,
  audioDurations: Record<string, number>
): number {
  let totalMs = 0;
  
  for (const scene of scenes) {
    // Use audio duration if available, otherwise use scene duration
    const duration = audioDurations[scene.durationMs] || scene.durationMs;
    totalMs += duration;
  }
  
  return totalMs;
}
