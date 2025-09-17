/**
 * YouTube Data API v3 client for uploading videos and managing metadata.
 */

import { google } from 'googleapis';
import fs from 'fs/promises';
import path from 'path';

export interface UploadOptions {
  path: string;
  title: string;
  description: string;
  tags: string[];
  privacy: 'public' | 'unlisted' | 'private';
  publishAt?: string; // ISO date string
  thumbPath?: string;
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
 * Upload video to YouTube
 */
export async function uploadVideo(options: UploadOptions): Promise<UploadResult> {
  const youtube = getYouTubeClient();
  
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
    
    // Add scheduled publish time if provided
    if (options.publishAt) {
      videoMetadata.status.publishAt = options.publishAt;
    }
    
    // Upload video
    const uploadResponse = await youtube.videos.insert({
      part: ['snippet', 'status'],
      requestBody: videoMetadata,
      media: {
        body: await fs.readFile(options.path),
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
 * Upload thumbnail for video
 */
export async function uploadThumbnail(videoId: string, thumbPath: string): Promise<void> {
  const youtube = getYouTubeClient();
  
  await youtube.thumbnails.set({
    videoId: videoId,
    media: {
      body: await fs.readFile(thumbPath),
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
  
  const response = await youtube.search.list({
    part: ['snippet'],
    forMine: true,
    type: ['video'],
    maxResults: maxResults,
    order: 'date',
  });
  
  return response.data.items || [];
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
