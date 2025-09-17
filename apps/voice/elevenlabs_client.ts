/**
 * ElevenLabs Text-to-Speech client with batch synthesis and caching.
 */

import fs from 'fs/promises';
import path from 'path';
import crypto from 'crypto';

export interface VoiceLine {
  id: string;
  text: string;
}

export interface TTSOptions {
  voiceId: string;
  stability?: number;
  rate?: number;
  clarity?: number;
}

export interface TTSResponse {
  audio: Buffer;
  duration?: number;
}

/**
 * Generate cache key for TTS request
 */
function getCacheKey(text: string, options: TTSOptions): string {
  const data = `${text}:${options.voiceId}:${options.stability}:${options.rate}:${options.clarity}`;
  return crypto.createHash('md5').update(data).digest('hex');
}

/**
 * Batch synthesize voice lines with caching and rate limiting
 */
export async function ttsBatch(
  lines: VoiceLine[],
  options: TTSOptions,
  outDir: string
): Promise<Record<string, string>> {
  const results: Record<string, string> = {};
  const cacheDir = path.join(outDir, 'cache');
  
  // Ensure directories exist
  await fs.mkdir(outDir, { recursive: true });
  await fs.mkdir(cacheDir, { recursive: true });
  
  // Process lines with rate limiting
  for (const line of lines) {
    try {
      const cacheKey = getCacheKey(line.text, options);
      const cachePath = path.join(cacheDir, `${cacheKey}.wav`);
      const outputPath = path.join(outDir, `${line.id}.wav`);
      
      // Check cache first
      try {
        await fs.access(cachePath);
        await fs.copyFile(cachePath, outputPath);
        results[line.id] = outputPath;
        console.log(`Cache hit for line: ${line.id}`);
        continue;
      } catch {
        // Cache miss, proceed with synthesis
      }
      
      // Synthesize audio
      const audioBuffer = await synthesizeText(line.text, options);
      
      // Save to cache and output
      await fs.writeFile(cachePath, audioBuffer);
      await fs.writeFile(outputPath, audioBuffer);
      
      results[line.id] = outputPath;
      console.log(`Synthesized line: ${line.id}`);
      
      // Rate limiting delay
      await new Promise(resolve => setTimeout(resolve, 100));
      
    } catch (error) {
      console.error(`Failed to synthesize line ${line.id}:`, error);
      // Continue with other lines
    }
  }
  
  return results;
}

/**
 * Synthesize single text with ElevenLabs API
 */
async function synthesizeText(text: string, options: TTSOptions): Promise<Buffer> {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) {
    throw new Error('ELEVENLABS_API_KEY environment variable not set');
  }
  
  const url = `https://api.elevenlabs.io/v1/text-to-speech/${options.voiceId}`;
  
  const requestBody = {
    text: text,
    model_id: 'eleven_monolingual_v1',
    voice_settings: {
      stability: options.stability ?? 0.5,
      similarity_boost: options.clarity ?? 0.75,
    },
  };
  
  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Accept': 'audio/mpeg',
      'Content-Type': 'application/json',
      'xi-api-key': apiKey,
    },
    body: JSON.stringify(requestBody),
  });
  
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`ElevenLabs API error: ${response.status} ${errorText}`);
  }
  
  const audioBuffer = Buffer.from(await response.arrayBuffer());
  return audioBuffer;
}

/**
 * Get available voices from ElevenLabs
 */
export async function getVoices(): Promise<any[]> {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  if (!apiKey) {
    throw new Error('ELEVENLABS_API_KEY environment variable not set');
  }
  
  const response = await fetch('https://api.elevenlabs.io/v1/voices', {
    headers: {
      'xi-api-key': apiKey,
    },
  });
  
  if (!response.ok) {
    throw new Error(`Failed to fetch voices: ${response.status}`);
  }
  
  const data = await response.json();
  return data.voices || [];
}

/**
 * Estimate duration for text (rough approximation)
 */
export function estimateDuration(text: string): number {
  // Rough estimate: 150 words per minute
  const words = text.split(/\s+/).length;
  const minutes = words / 150;
  return Math.max(1000, minutes * 60 * 1000); // Minimum 1 second
}
