/**
 * YouTube Data API v3 client for uploading videos and managing metadata.
 */

import { google } from 'googleapis';
import { createReadStream } from 'fs';
import fs from 'fs/promises';

export interface UploadOptions {
  path: string;
  title: string;
  description: string;
  tags: string[];
  privacy: 'public' | 'unlisted' | 'private';
  publishAt?: string; // ISO date string
  thumbPath?: string;
  captionsPath?: string;
  categoryId?: string;
  defaultLanguage?: string;
}

export interface UploadResult {
  videoId: string;
  url: string;
  status: string;
}

/**
 * Initialize YouTube API client with OAuth2
 */
function getYouTubeClient() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  const refreshToken = process.env.GOOGLE_REFRESH_TOKEN;
  
  if (!clientId || !clientSecret || !refreshToken) {
    throw new Error('Missing Google OAuth credentials. Set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REFRESH_TOKEN');
  }
  
  const oauth2Client = new google.auth.OAuth2(clientId, clientSecret);
  oauth2Client.setCredentials({ refresh_token: refreshToken });
  
  return google.youtube({ version: 'v3', auth: oauth2Client });
}

/**
 * Refuse to upload unless the token controls the channel we mean.
 *
 * A Google account can own several channels, and OAuth consent quietly
 * defaults to the personal one — so the first real upload landed on "Tom
 * Jacobson" instead of Nocturne Chess, and the only reason anyone noticed was
 * that a human asked. Unattended at three in the morning, nobody asks.
 *
 * Set YOUTUBE_CHANNEL_ID in .env to the channel that should receive videos.
 * Left unset, this only reports what it found: the check cannot be a hard
 * requirement for people who have not configured it, but it can make the
 * mistake visible in the log.
 */
export async function verifyChannel(): Promise<void> {
  const youtube = getYouTubeClient();
  const expected = process.env.YOUTUBE_CHANNEL_ID?.trim();
  const res = await youtube.channels.list({ part: ['snippet'], mine: true });
  const channel = res.data.items?.[0];
  const id = channel?.id ?? '(none)';
  const title = channel?.snippet?.title ?? '(unknown)';

  if (!expected) {
    console.warn(
      `Uploading to "${title}" (${id}). Set YOUTUBE_CHANNEL_ID in .env to ` +
        'have this verified rather than merely reported.'
    );
    return;
  }
  if (id !== expected) {
    throw new Error(
      `Refusing to upload: this token controls "${title}" (${id}), but ` +
        `YOUTUBE_CHANNEL_ID is ${expected}. Re-run "npm run authorize" and ` +
        'pick the right channel at the Google account chooser.'
    );
  }
  console.log(`Channel verified: ${title} (${id})`);
}

/**
 * Upload video to YouTube
 */
export async function uploadVideo(options: UploadOptions): Promise<UploadResult> {
  const youtube = getYouTubeClient();
  await verifyChannel();

  try {
    console.log(`Uploading video: ${options.title}`);
    
    // Prepare video metadata
    const videoMetadata = {
      snippet: {
        title: options.title,
        description: options.description,
        tags: options.tags,
        categoryId: options.categoryId || '20', // Gaming category
        defaultLanguage: options.defaultLanguage || 'en',
      },
      status: {
        privacyStatus: options.privacy,
        selfDeclaredMadeForKids: false,
      } as any,
    };
    
    // Add scheduled publish time if provided.
    // YouTube requires privacyStatus=private for scheduled publishing.
    if (options.publishAt) {
      videoMetadata.status.publishAt = options.publishAt;
      videoMetadata.status.privacyStatus = 'private';
    }

    // Upload video (stream, not Buffer — resumable and memory-safe)
    const uploadResponse = await youtube.videos.insert({
      part: ['snippet', 'status'],
      requestBody: videoMetadata,
      media: {
        body: createReadStream(options.path),
      },
    });
    
    const videoId = uploadResponse.data.id;
    if (!videoId) {
      throw new Error('No video ID returned from upload');
    }
    
    console.log(`Video uploaded successfully: ${videoId}`);
    
    // Upload thumbnail if provided
    if (options.thumbPath) {
      try {
        await uploadThumbnail(videoId, options.thumbPath);
        console.log(`Thumbnail uploaded for video: ${videoId}`);
      } catch (error) {
        console.warn(`Failed to upload thumbnail: ${error}`);
      }
    }

    // Captions, which are ours rather than YouTube's guess at the audio.
    // Non-fatal like the thumbnail: a published video with automatic captions
    // beats a failed upload, and the track can be added by hand afterwards.
    if (options.captionsPath) {
      try {
        await uploadCaptions(videoId, options.captionsPath);
        console.log(`Captions uploaded for video: ${videoId}`);
      } catch (error) {
        console.warn(`Failed to upload captions: ${error}`);
      }
    }
    
    return {
      videoId,
      url: `https://www.youtube.com/watch?v=${videoId}`,
      status: 'uploaded',
    };
    
  } catch (error) {
    console.error('Video upload failed:', error);
    throw error;
  }
}

/**
 * Attach our own subtitle track.
 *
 * `name` is what the viewer sees in the subtitle picker; an empty string is
 * the conventional "default track" and avoids a stray label sitting next to
 * "English". isDraft=false publishes it immediately — a draft track exists but
 * is invisible, which looks identical to the upload having failed.
 */
export async function uploadCaptions(videoId: string, srtPath: string): Promise<void> {
  const youtube = getYouTubeClient();

  await youtube.captions.insert({
    part: ['snippet'],
    requestBody: {
      snippet: {
        videoId,
        language: 'en',
        name: '',
        isDraft: false,
      },
    },
    media: {
      body: createReadStream(srtPath),
    },
  });
}

/**
 * Upload thumbnail for video
 */
export async function uploadThumbnail(videoId: string, thumbPath: string): Promise<void> {
  const youtube = getYouTubeClient();
  
  await youtube.thumbnails.set({
    videoId: videoId,
    media: {
      body: createReadStream(thumbPath),
    },
  });
}

/**
 * Update video metadata
 */
export async function updateVideoMetadata(
  videoId: string,
  updates: Partial<UploadOptions>
): Promise<void> {
  const youtube = getYouTubeClient();
  
  // Get current video data
  const videoResponse = await youtube.videos.list({
    part: ['snippet', 'status'],
    id: [videoId],
  });
  
  const video = videoResponse.data.items?.[0];
  if (!video) {
    throw new Error(`Video not found: ${videoId}`);
  }
  
  // Update metadata
  const updatedVideo = {
    id: videoId,
    snippet: {
      ...video.snippet,
      ...(updates.title && { title: updates.title }),
      ...(updates.description && { description: updates.description }),
      ...(updates.tags && { tags: updates.tags }),
    },
    status: {
      ...video.status,
      ...(updates.privacy && { privacyStatus: updates.privacy }),
    },
  };
  
  await youtube.videos.update({
    part: ['snippet', 'status'],
    requestBody: updatedVideo,
  });
  
  console.log(`Video metadata updated: ${videoId}`);
}

/**
 * Delete video
 */
export async function deleteVideo(videoId: string): Promise<void> {
  const youtube = getYouTubeClient();
  
  await youtube.videos.delete({
    id: videoId,
  });
  
  console.log(`Video deleted: ${videoId}`);
}

/**
 * Get video information
 */
export async function getVideoInfo(videoId: string): Promise<any> {
  const youtube = getYouTubeClient();
  
  const response = await youtube.videos.list({
    part: ['snippet', 'status', 'statistics'],
    id: [videoId],
  });
  
  return response.data.items?.[0];
}

/**
 * List videos in channel
 */
export async function listVideos(maxResults: number = 50): Promise<any[]> {
  const youtube = getYouTubeClient();

  // Over-fetch, then keep only what a viewer can actually watch. These feed
  // the "More videos" block in every description, and `forMine` returns
  // unlisted uploads too — so a published video's own description pointed at
  // the superseded drafts it had replaced. A viewer clicking through from our
  // best Fischer render landed on the Lasker cut with "M1. Didier" still on
  // the intro card. A dead-end link is worse than no link at all.
  const response = await youtube.search.list({
    part: ['snippet'],
    forMine: true,
    type: ['video'],
    maxResults: Math.min(50, Math.max(maxResults * 5, 20)),
    order: 'date',
  });

  const items = response.data.items || [];
  const ids = items
    .map((i: any) => i?.id?.videoId)
    .filter(Boolean) as string[];
  if (!ids.length) return [];

  // search.list carries neither privacy nor duration, so ask for both.
  const details = await youtube.videos.list({
    part: ['status', 'contentDetails'],
    id: ids,
  });

  // ISO 8601 duration -> seconds, enough for PT#M#S shapes.
  const seconds = (iso: string): number => {
    const m = /PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/.exec(iso || '');
    if (!m) return 0;
    return (+(m[1] || 0)) * 3600 + (+(m[2] || 0)) * 60 + (+(m[3] || 0));
  };

  const eligible = new Set(
    (details.data.items || [])
      .filter((v: any) => {
        if (v?.status?.privacyStatus !== 'public') return false;
        // Shorts stay out of a long-form video's "More videos" block. Their
        // titles carry "#Shorts", which then appears in the description of a
        // thirteen-minute analysis and reads like a mislabel — and the pull
        // a Short is meant to exert is INTO the long game, not away from it.
        return seconds(v?.contentDetails?.duration) > 180;
      })
      .map((v: any) => v.id as string)
  );

  return items
    .filter((i: any) => eligible.has(i?.id?.videoId))
    .slice(0, maxResults);
}

/**
 * File a video under each named playlist, creating the playlist if needed.
 *
 * A back catalogue nobody can browse is a back catalogue nobody watches: the
 * established channels in this genre organise everything by player, which is
 * how a viewer who liked one Fischer game finds the other six. Doing it at
 * upload time means the structure exists from the first video rather than
 * being retrofitted over hundreds.
 *
 * Which playlists a game belongs in is decided by the director (meta
 * .playlists), not here — the same table that resolves "Fischer, Robert
 * James" into "Bobby Fischer" for the title names the playlist, so the
 * channel cannot end up with both a "Bobby Fischer" and a "Fischer" list.
 *
 * Best effort throughout: a finished video must never fail to publish
 * because a playlist call did.
 */
/**
 * Playlists this process has created, by title.
 *
 * playlists.list does not report a playlist the instant it exists, so a run
 * that files two videos under the same player looked it up, failed to find
 * what it had just made, and created a second "Paul Keres". Remembering our
 * own writes covers the window the listing does not.
 */
const CREATED_PLAYLISTS = new Map<string, string>();

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function fileInPlaylists(
  videoId: string,
  names: string[]
): Promise<void> {
  if (!names?.length) return;
  const youtube = getYouTubeClient();

  const existing = new Map<string, string>(CREATED_PLAYLISTS);
  let pageToken: string | undefined;
  do {
    const res = await youtube.playlists.list({
      part: ['snippet'],
      mine: true,
      maxResults: 50,
      pageToken,
    });
    for (const p of res.data.items ?? []) {
      if (p.snippet?.title && p.id && !existing.has(p.snippet.title)) {
        existing.set(p.snippet.title, p.id);
      }
    }
    pageToken = res.data.nextPageToken ?? undefined;
  } while (pageToken);

  for (const name of names) {
    try {
      let playlistId = existing.get(name);
      if (!playlistId) {
        const created = await youtube.playlists.insert({
          part: ['snippet', 'status'],
          requestBody: {
            snippet: {
              title: name,
              description:
                `Games of ${name}, narrated calmly and checked against ` +
                `Stockfish. New game daily on Nocturne Chess.`,
            },
            status: { privacyStatus: 'public' },
          },
        });
        playlistId = created.data.id ?? undefined;
        if (!playlistId) continue;
        existing.set(name, playlistId);
        CREATED_PLAYLISTS.set(name, playlistId);
        console.log(`Created playlist: ${name}`);
      }

      // A just-created playlist reports "cannot be found" for a few seconds
      // before it can take items. The first backfill created nine playlists
      // and filled none of them for exactly this reason, and reported each
      // failure as a shrug. Wait for it instead.
      let filed = false;
      for (let attempt = 1; attempt <= 5 && !filed; attempt++) {
        try {
          // Re-running a build must not stack duplicates of the same video.
          const items = await youtube.playlistItems.list({
            part: ['contentDetails'],
            playlistId,
            maxResults: 50,
          });
          if ((items.data.items ?? []).some(
            (i) => i.contentDetails?.videoId === videoId
          )) {
            console.log(`Already in playlist: ${name}`);
            filed = true;
            break;
          }
          await youtube.playlistItems.insert({
            part: ['snippet'],
            requestBody: {
              snippet: {
                playlistId,
                resourceId: { kind: 'youtube#video', videoId },
              },
            },
          });
          console.log(`Added to playlist: ${name}`);
          filed = true;
        } catch (error: any) {
          const msg = String(error?.message ?? error);
          if (attempt === 5 || !/cannot be found|not found|404/i.test(msg)) {
            throw error;
          }
          await sleep(1500 * attempt);
        }
      }
    } catch (error: any) {
      // Google API errors often carry their substance in errors[0].reason
      // ("quotaExceeded") while message is empty — which is how a night of
      // failures logged as `skipped: ` and said nothing.
      const reason =
        error?.errors?.[0]?.reason ??
        error?.response?.data?.error?.errors?.[0]?.reason ??
        error?.code ??
        error?.message ??
        String(error);
      console.log(`(playlist "${name}" skipped: ${reason})`);
    }
  }
}

/**
 * Add chapters to video description
 */
export async function addChaptersToDescription(
  videoId: string,
  chapters: Array<{ time: string; title: string }>
): Promise<void> {
  const videoInfo = await getVideoInfo(videoId);
  if (!videoInfo) {
    throw new Error(`Video not found: ${videoId}`);
  }
  
  const currentDescription = videoInfo.snippet.description || '';
  const chapterText = chapters
    .map(chapter => `${chapter.time} ${chapter.title}`)
    .join('\n');
  
  const newDescription = currentDescription + '\n\nChapters:\n' + chapterText;
  
  await updateVideoMetadata(videoId, { description: newDescription });
}
