#!/usr/bin/env node

/**
 * YouTube uploader CLI for chess autopost
 */

import path from 'node:path';
import dotenv from 'dotenv';
// Same trap as authorize.ts: npm runs this from apps/uploader, and
// `dotenv/config` only reads the .env in the working directory. The repo's
// .env is at the root, so without this the uploader would report missing
// Google credentials on a machine that has them.
dotenv.config({ path: path.resolve(process.cwd(), '..', '..', '.env') });
import { Command } from 'commander';
import fs from 'fs/promises';
import { uploadVideo, getVideoInfo, updateVideoMetadata, listVideos, verifyChannel, fileInPlaylists } from './youtube_client';
import type { UploadOptions } from './youtube_client';
import { generateMetadata, generateShortMetadata } from './metadata';
import { generateChaptersText } from './chapters';
import type { Script } from '../renderer/src/types/script';

const program = new Command();

program
  .name('uploader')
  .description('Chess autopost YouTube uploader CLI')
  .version('1.0.0');

program
  .command('upload')
  .description('Upload video to YouTube')
  .requiredOption('-v, --video <file>', 'Video file path')
  .requiredOption('-t, --script <file>', 'Script JSON file (outputs/script.json)')
  .option('-T, --thumb <file>', 'Thumbnail file path')
  .option('-c, --captions <file>', 'SRT subtitle file path')
  .option('-p, --privacy <status>', 'Privacy status', 'unlisted')
  .option('--publish-at <date>', 'Schedule publish date (ISO format)')
  .option('--dry-run', 'Show what would be uploaded without actually uploading')
  .option('--result-json <file>', 'Write {videoId,url,status,title} here on success')
  .option('--short', 'This is a vertical Short: hook title, #Shorts, funnel description')
  .option('--full-url <url>', 'Link to the full-game video (Shorts description leads with it)')
  .action(async (options) => {
    try {
      console.log('Loading script...');
      const timelineData = await fs.readFile(options.script, 'utf-8');
      const script: Script = JSON.parse(timelineData);
      
      // Pull the channel's recent uploads for the "More videos" block. Best
      // effort: a new channel has none, and a failure here must not block a
      // finished video from being published. Shorts skip it — their one job
      // is the full-game link, and extra links dilute the funnel.
      let moreVideos: string[] = [];
      if (!options.dryRun && !options.short) {
        try {
          const recent = await listVideos(3);
          moreVideos = recent
            .filter((v: any) => v?.id?.videoId && v?.snippet?.title)
            .map((v: any) => `${v.snippet.title}
https://youtu.be/${v.id.videoId}`);
        } catch {
          console.log('(could not fetch recent videos — skipping that section)');
        }
      }

      console.log('Generating metadata...');
      const metadata = options.short
        ? generateShortMetadata(script, options.fullUrl)
        : generateMetadata(script, moreVideos);

      // Chapters make no sense in a sub-minute vertical.
      const fullDescription = options.short
        ? metadata.description
        : metadata.description + '\n\n' + generateChaptersText(script);
      
      const uploadOptions: UploadOptions = {
        path: options.video,
        title: metadata.title,
        description: fullDescription,
        tags: metadata.tags,
        privacy: options.privacy as 'public' | 'unlisted' | 'private',
        thumbPath: options.thumb,
        captionsPath: options.captions,
        publishAt: options.publishAt,
        categoryId: metadata.categoryId,
      };
      
      if (options.dryRun) {
        // A dry run exists to catch exactly this before it matters, so the
        // channel is verified here too rather than only on the real upload.
        await verifyChannel();
        console.log('\n=== DRY RUN - Would upload ===');
        console.log('Title:', uploadOptions.title);
        console.log('Description:', uploadOptions.description.substring(0, 200) + '...');
        console.log('Tags:', uploadOptions.tags.join(', '));
        console.log('Privacy:', uploadOptions.privacy);
        console.log('Video file:', uploadOptions.path);
        console.log('Thumbnail:', uploadOptions.thumbPath || 'None');
        console.log('Captions:', uploadOptions.captionsPath || 'None');
        console.log('Publish at:', uploadOptions.publishAt || 'Immediately');
        return;
      }
      
      console.log('Uploading to YouTube...');
      const result = await uploadVideo(uploadOptions);
      
      console.log('\n=== Upload Complete ===');
      console.log('Video ID:', result.videoId);
      console.log('URL:', result.url);
      console.log('Status:', result.status);

      // File it under each player's playlist. After the upload on purpose: a
      // published video with no playlist is a small loss, a lost video is not.
      const playlists = (script.meta as any)?.playlists as string[] | undefined;
      if (result.videoId && playlists?.length) {
        await fileInPlaylists(result.videoId, playlists);
      }

      // The option existed but was never implemented, so flow.py's ledger —
      // the permanent record of what this channel has published — recorded
      // every upload with a null videoId, url and title. Three videos went up
      // before anyone looked at the record and found it empty.
      if (options.resultJson) {
        await fs.writeFile(
          options.resultJson,
          JSON.stringify(
            {
              videoId: result.videoId,
              url: result.url,
              status: result.status,
              title: uploadOptions.title,
            },
            null,
            2
          ),
          'utf-8'
        );
        console.log('Result written to:', options.resultJson);
      }

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
  .requiredOption('-t, --script <file>', 'Script JSON file (outputs/script.json)')
  .option('-o, --output <file>', 'Output file for chapters')
  .action(async (options) => {
    try {
      console.log('Loading script...');
      const timelineData = await fs.readFile(options.script, 'utf-8');
      const script: Script = JSON.parse(timelineData);
      
      console.log('Generating chapters...');
      const chaptersText = generateChaptersText(script);
      
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
  .description('Generate metadata for a script')
  .requiredOption('-t, --script <file>', 'Script JSON file (outputs/script.json)')
  .option('-o, --output <file>', 'Output file for metadata')
  .option('--fetch-recent', 'Include recent channel uploads (needs OAuth creds)')
  .action(async (options) => {
    try {
      console.log('Loading script...');
      const timelineData = await fs.readFile(options.script, 'utf-8');
      const script: Script = JSON.parse(timelineData);
      
      // Pull the channel's recent uploads for the "More videos" block. Best
      // effort: a new channel has none, and a failure here must not block a
      // finished video from being published.
      let moreVideos: string[] = [];
      if (options.fetchRecent) {
        try {
          const recent = await listVideos(3);
          moreVideos = recent
            .filter((v: any) => v?.id?.videoId && v?.snippet?.title)
            .map((v: any) => `${v.snippet.title}
https://youtu.be/${v.id.videoId}`);
        } catch {
          console.log('(could not fetch recent videos — skipping that section)');
        }
      }

      console.log('Generating metadata...');
      const metadata = generateMetadata(script, moreVideos);
      
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
