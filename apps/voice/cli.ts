#!/usr/bin/env node

/**
 * Voice synthesis CLI for chess autopost
 */

import { Command } from 'commander';
import fs from 'fs/promises';
import path from 'path';
import { ttsBatch, VoiceLine, TTSOptions, getVoices } from './elevenlabs_client';
import { normalizeText } from './text_normalizer';

const program = new Command();

program
  .name('voice')
  .description('Chess autopost voice synthesis CLI')
  .version('1.0.0');

program
  .command('synth')
  .description('Synthesize voice lines from JSON file')
  .requiredOption('-l, --lines <file>', 'JSON file with voice lines')
  .requiredOption('-v, --voice-id <id>', 'ElevenLabs voice ID')
  .option('-o, --output <dir>', 'Output directory', './audio')
  .option('-s, --stability <number>', 'Voice stability (0-1)', '0.5')
  .option('-r, --rate <number>', 'Speech rate (0-1)', '0.5')
  .option('-c, --clarity <number>', 'Voice clarity (0-1)', '0.75')
  .option('--normalize', 'Normalize text for better pronunciation', true)
  .action(async (options) => {
    try {
      console.log('Loading voice lines...');
      const linesData = await fs.readFile(options.lines, 'utf-8');
      const lines: VoiceLine[] = JSON.parse(linesData);
      
      if (!Array.isArray(lines)) {
        throw new Error('Lines file must contain an array of voice lines');
      }
      
      console.log(`Found ${lines.length} voice lines`);
      
      // Normalize text if requested
      if (options.normalize) {
        console.log('Normalizing text...');
        lines.forEach(line => {
          line.text = normalizeText(line.text);
        });
      }
      
      const ttsOptions: TTSOptions = {
        voiceId: options.voiceId,
        stability: parseFloat(options.stability),
        rate: parseFloat(options.rate),
        clarity: parseFloat(options.clarity),
      };
      
      console.log('Starting synthesis...');
      const results = await ttsBatch(lines, ttsOptions, options.output);
      
      console.log(`Synthesis complete! Generated ${Object.keys(results).length} audio files`);
      console.log(`Output directory: ${path.resolve(options.output)}`);
      
    } catch (error) {
      console.error('Synthesis failed:', error);
      process.exit(1);
    }
  });

program
  .command('voices')
  .description('List available ElevenLabs voices')
  .action(async () => {
    try {
      console.log('Fetching available voices...');
      const voices = await getVoices();
      
      console.log(`\nFound ${voices.length} voices:\n`);
      
      voices.forEach((voice: any) => {
        console.log(`ID: ${voice.voice_id}`);
        console.log(`Name: ${voice.name}`);
        console.log(`Category: ${voice.category || 'Unknown'}`);
        console.log(`Description: ${voice.description || 'No description'}`);
        console.log('---');
      });
      
    } catch (error) {
      console.error('Failed to fetch voices:', error);
      process.exit(1);
    }
  });

program
  .command('normalize')
  .description('Normalize text file for TTS')
  .requiredOption('-i, --input <file>', 'Input text file')
  .option('-o, --output <file>', 'Output file (default: input with .normalized extension)')
  .action(async (options) => {
    try {
      console.log('Reading input file...');
      const inputText = await fs.readFile(options.input, 'utf-8');
      
      console.log('Normalizing text...');
      const normalizedText = normalizeText(inputText);
      
      const outputFile = options.output || options.input.replace(/\.[^/.]+$/, '.normalized.txt');
      
      console.log('Writing normalized text...');
      await fs.writeFile(outputFile, normalizedText, 'utf-8');
      
      console.log(`Normalized text written to: ${outputFile}`);
      
    } catch (error) {
      console.error('Normalization failed:', error);
      process.exit(1);
    }
  });

program
  .command('test')
  .description('Test voice synthesis with sample text')
  .requiredOption('-v, --voice-id <id>', 'ElevenLabs voice ID')
  .option('-t, --text <text>', 'Test text', 'Hello, this is a test of the chess autopost voice synthesis system.')
  .option('-o, --output <file>', 'Output file', './test_audio.wav')
  .action(async (options) => {
    try {
      console.log('Testing voice synthesis...');
      
      const testLine: VoiceLine = {
        id: 'test',
        text: options.text,
      };
      
      const ttsOptions: TTSOptions = {
        voiceId: options.voiceId,
        stability: 0.5,
        rate: 0.5,
        clarity: 0.75,
      };
      
      const results = await ttsBatch([testLine], ttsOptions, path.dirname(options.output));
      
      if (results.test) {
        await fs.rename(results.test, options.output);
        console.log(`Test audio saved to: ${options.output}`);
      } else {
        throw new Error('No audio generated');
      }
      
    } catch (error) {
      console.error('Test failed:', error);
      process.exit(1);
    }
  });

// Parse command line arguments
program.parse();
