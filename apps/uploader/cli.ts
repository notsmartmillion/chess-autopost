#!/usr/bin/env node

/**
 * YouTube uploader CLI for chess autopost
 */

import { Command } from 'commander';
import fs from 'fs/promises';
import path from 'path';
import { uploadVideo, UploadOptions, getVideoInfo, updateVideoMetadata } from './youtube_client';
import { generateMetadata } from './metadata';
import { generateChaptersText } from './chapters';
import { Timeline } from '../renderer/src/types/timeline';

const program = new Command();

program
  .name('uploader')
  .description('Chess autopost YouTube uploader CLI')
  .version('1.0.0');

program
  .command('upload')
  .description('Upload video to YouTube')
  .requiredOption('-v, --video <file>', 'Video file path')
  .requiredOption('-t, --timeline <file>', 'Timeline JSON file')
  .option('-t, --thumb <file>', 'Thumbnail file path')
  .option('-p, --privacy <status>', 'Privacy status', 'unlisted')
  .option('--publish-at <date>', 'Schedule publish date (ISO format)')
  .option('--dry-run', 'Show what would be uploaded without actually uploading')
  .action(async (options) => {
    try {
      console.log('Loading timeline...');
      const timelineData = await fs.readFile(options.timeline, 'utf-8');
      const timeline: Timeline = JSON.parse(timelineData);
      
      console.log('Generating metadata...');
      const metadata = generateMetadata(timeline);
      
      console.log('Generating chapters...');
      const chaptersText = generateChaptersText(timeline);
      
      // Combine description with chapters
      const fullDescription = metadata.description + '\n\n' + chaptersText;
      
      const uploadOptions: UploadOptions = {
        path: options.video,
        title: metadata.title,
        description: fullDescription,
        tags: metadata.tags,
        privacy: options.privacy as 'public' | 'unlisted' | 'private',
        thumbPath: options.thumb,
        publishAt: options.publishAt,
        categoryId: metadata.categoryId,
      };
      
      if (options.dryRun) {
        console.log('\n=== DRY RUN - Would upload ===');
        console.log('Title:', uploadOptions.title);
        console.log('Description:', uploadOptions.description.substring(0, 200) + '...');
        console.log('Tags:', uploadOptions.tags.join(', '));
        console.log('Privacy:', uploadOptions.privacy);
        console.log('Video file:', uploadOptions.path);
        console.log('Thumbnail:', uploadOptions.thumbPath || 'None');
        console.log('Publish at:', uploadOptions.publishAt || 'Immediately');
        return;
      }
      
      console.log('Uploading to YouTube...');
      const result = await uploadVideo(uploadOptions);
      
      console.log('\n=== Upload Complete ===');
      console.log('Video ID:', result.videoId);
      console.log('URL:', result.url);
      console.log('Status:', result.status);
      
    } catch (error) {
      console.error('Upload failed:', error);
      process.exit(1);
    }
  });

program
  .command('info')
  .description('Get video information')
  .requiredOption('-i, --video-id <id>', 'YouTube video ID')
  .action(async (options) => {
    try {
      console.log(`Fetching info for video: ${options.videoId}`);
      const videoInfo = await getVideoInfo(options.videoId);
      
      if (!videoInfo) {
        console.log('Video not found');
        return;
      }
      
      console.log('\n=== Video Information ===');
      console.log('Title:', videoInfo.snippet?.title);
      console.log('Description:', videoInfo.snippet?.description?.substring(0, 200) + '...');
      console.log('Channel:', videoInfo.snippet?.channelTitle);
      console.log('Published:', videoInfo.snippet?.publishedAt);
      console.log('Privacy:', videoInfo.status?.privacyStatus);
      console.log('Views:', videoInfo.statistics?.viewCount);
      console.log('Likes:', videoInfo.statistics?.likeCount);
      console.log('Comments:', videoInfo.statistics?.commentCount);
      
    } catch (error) {
      console.error('Failed to get video info:', error);
      process.exit(1);
    }
  });

program
  .command('update')
  .description('Update video metadata')
  .requiredOption('-i, --video-id <id>', 'YouTube video ID')
  .option('-t, --title <title>', 'New title')
  .option('-d, --description <description>', 'New description')
  .option('-p, --privacy <status>', 'New privacy status')
  .action(async (options) => {
    try {
      const updates: any = {};
      
      if (options.title) updates.title = options.title;
      if (options.description) updates.description = options.description;
      if (options.privacy) updates.privacy = options.privacy;
      
      if (Object.keys(updates).length === 0) {
        console.log('No updates specified');
        return;
      }
      
      console.log(`Updating video: ${options.videoId}`);
      await updateVideoMetadata(options.videoId, updates);
      
      console.log('Video updated successfully');
      
    } catch (error) {
      console.error('Update failed:', error);
      process.exit(1);
    }
  });

program
  .command('chapters')
  .description('Generate chapters for timeline')
  .requiredOption('-t, --timeline <file>', 'Timeline JSON file')
  .option('-o, --output <file>', 'Output file for chapters')
  .action(async (options) => {
    try {
      console.log('Loading timeline...');
      const timelineData = await fs.readFile(options.timeline, 'utf-8');
      const timeline: Timeline = JSON.parse(timelineData);
      
      console.log('Generating chapters...');
      const chaptersText = generateChaptersText(timeline);
      
      if (options.output) {
        await fs.writeFile(options.output, chaptersText, 'utf-8');
        console.log(`Chapters written to: ${options.output}`);
      } else {
        console.log('\n=== Generated Chapters ===');
        console.log(chaptersText);
      }
      
    } catch (error) {
      console.error('Failed to generate chapters:', error);
      process.exit(1);
    }
  });

program
  .command('metadata')
  .description('Generate metadata for timeline')
  .requiredOption('-t, --timeline <file>', 'Timeline JSON file')
  .option('-o, --output <file>', 'Output file for metadata')
  .action(async (options) => {
    try {
      console.log('Loading timeline...');
      const timelineData = await fs.readFile(options.timeline, 'utf-8');
      const timeline: Timeline = JSON.parse(timelineData);
      
      console.log('Generating metadata...');
      const metadata = generateMetadata(timeline);
      
      if (options.output) {
        await fs.writeFile(options.output, JSON.stringify(metadata, null, 2), 'utf-8');
        console.log(`Metadata written to: ${options.output}`);
      } else {
        console.log('\n=== Generated Metadata ===');
        console.log('Title:', metadata.title);
        console.log('Description:', metadata.description.substring(0, 200) + '...');
        console.log('Tags:', metadata.tags.join(', '));
        console.log('Category ID:', metadata.categoryId);
      }
      
    } catch (error) {
      console.error('Failed to generate metadata:', error);
      process.exit(1);
    }
  });

// Parse command line arguments
program.parse();
