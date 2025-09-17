/**
 * Generate YouTube chapters from timeline scenes.
 */

import { Timeline, Scene } from '../renderer/src/types/timeline';

export interface Chapter {
  time: string; // Format: "0:00" or "1:23"
  title: string;
}

/**
 * Generate chapters from timeline scenes
 */
export function generateChapters(timeline: Timeline): Chapter[] {
  const chapters: Chapter[] = [];
  let currentTimeMs = 0;
  
  // Add opening chapter
  chapters.push({
    time: formatTime(0),
    title: 'Opening',
  });
  
  let moveCount = 0;
  let inMiddlegame = false;
  let inEndgame = false;
  
  timeline.scenes.forEach((scene, index) => {
    if (scene.type === 'main') {
      moveCount++;
      
      // Determine game phase
      if (moveCount >= 10 && moveCount <= 30 && !inMiddlegame) {
        inMiddlegame = true;
        chapters.push({
          time: formatTime(currentTimeMs),
          title: 'Middlegame',
        });
      } else if (moveCount > 30 && !inEndgame) {
        inEndgame = true;
        chapters.push({
          time: formatTime(currentTimeMs),
          title: 'Endgame',
        });
      }
      
      // Add move-specific chapters for interesting moves
      if (isInterestingMove(scene)) {
        const moveNumber = Math.ceil(moveCount / 2);
        const player = moveCount % 2 === 1 ? 'White' : 'Black';
        const moveTitle = generateMoveTitle(scene, moveNumber, player);
        
        chapters.push({
          time: formatTime(currentTimeMs),
          title: moveTitle,
        });
      }
    }
    
    currentTimeMs += scene.durationMs;
  });
  
  // Add conclusion chapter
  chapters.push({
    time: formatTime(currentTimeMs),
    title: 'Conclusion',
  });
  
  return chapters;
}

/**
 * Check if a move is interesting enough for a chapter
 */
function isInterestingMove(scene: Scene): boolean {
  if (scene.type !== 'main') return false;
  
  // Check for pins
  if (scene.pins && scene.pins.length > 0) {
    return true;
  }
  
  // Check for significant evaluation changes
  if (Math.abs(scene.evalBarTarget) > 0.3) {
    return true;
  }
  
  // Check for many attacked squares (tactical position)
  const totalAttacked = scene.attacked.white.length + scene.attacked.black.length;
  if (totalAttacked > 8) {
    return true;
  }
  
  return false;
}

/**
 * Generate title for interesting move
 */
function generateMoveTitle(scene: Scene, moveNumber: number, player: string): string {
  const titles: string[] = [];
  
  // Add move number and player
  titles.push(`Move ${moveNumber} (${player})`);
  
  // Add tactical elements
  if (scene.pins && scene.pins.length > 0) {
    titles.push('Pin Tactics');
  }
  
  // Add evaluation context
  if (Math.abs(scene.evalBarTarget) > 0.5) {
    const advantage = scene.evalBarTarget > 0 ? 'White Advantage' : 'Black Advantage';
    titles.push(advantage);
  }
  
  // Add tactical complexity
  const totalAttacked = scene.attacked.white.length + scene.attacked.black.length;
  if (totalAttacked > 10) {
    titles.push('Tactical Complexity');
  }
  
  return titles.join(' - ');
}

/**
 * Format time in milliseconds to YouTube chapter format
 */
function formatTime(timeMs: number): string {
  const totalSeconds = Math.floor(timeMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

/**
 * Generate chapters text for video description
 */
export function generateChaptersText(timeline: Timeline): string {
  const chapters = generateChapters(timeline);
  
  let chaptersText = 'Chapters:\n';
  chapters.forEach(chapter => {
    chaptersText += `${chapter.time} ${chapter.title}\n`;
  });
  
  return chaptersText;
}

/**
 * Generate chapters with enhanced titles based on game analysis
 */
export function generateEnhancedChapters(timeline: Timeline): Chapter[] {
  const chapters = generateChapters(timeline);
  
  // Enhance chapter titles with more descriptive text
  return chapters.map(chapter => {
    let enhancedTitle = chapter.title;
    
    // Enhance opening chapter
    if (chapter.title === 'Opening') {
      const eco = timeline.meta.eco;
      if (eco) {
        enhancedTitle = `Opening: ${eco}`;
      } else {
        enhancedTitle = 'Opening Moves';
      }
    }
    
    // Enhance middlegame chapter
    if (chapter.title === 'Middlegame') {
      enhancedTitle = 'Middlegame Tactics';
    }
    
    // Enhance endgame chapter
    if (chapter.title === 'Endgame') {
      enhancedTitle = 'Endgame Technique';
    }
    
    // Enhance conclusion chapter
    if (chapter.title === 'Conclusion') {
      const result = timeline.meta.result;
      if (result) {
        enhancedTitle = `Game Conclusion (${result})`;
      } else {
        enhancedTitle = 'Game Conclusion';
      }
    }
    
    return {
      time: chapter.time,
      title: enhancedTitle,
    };
  });
}
