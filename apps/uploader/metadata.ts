/**
 * Generate YouTube metadata from chess game information.
 */

import { Timeline } from '../renderer/src/types/timeline';

export interface VideoMetadata {
  title: string;
  description: string;
  tags: string[];
  categoryId: string;
}

/**
 * Generate video title from timeline metadata
 */
export function generateTitle(timeline: Timeline): string {
  const { white, black, event, date } = timeline.meta;
  
  // Extract year from date
  const year = date ? new Date(date).getFullYear() : '';
  
  // Create title variations
  const titleVariations = [
    `${white} vs ${black} - ${event || 'Chess Game'} ${year}`,
    `${white} vs ${black} - Epic Chess Battle ${year}`,
    `Chess Masterclass: ${white} vs ${black} ${year}`,
    `${white} vs ${black} - Brilliant Chess Game ${year}`,
    `Amazing Chess: ${white} vs ${black} ${year}`,
  ];
  
  // Return first variation (could be randomized)
  return titleVariations[0];
}

/**
 * Generate video description from timeline metadata
 */
export function generateDescription(timeline: Timeline): string {
  const { white, black, event, date, result, eco } = timeline.meta;
  
  let description = `Chess game between ${white} (White) and ${black} (Black)`;
  
  if (event) {
    description += ` from ${event}`;
  }
  
  if (date) {
    const gameDate = new Date(date).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
    description += ` played on ${gameDate}`;
  }
  
  if (result) {
    description += `\nResult: ${result}`;
  }
  
  if (eco) {
    description += `\nOpening: ${eco}`;
  }
  
  // Add analysis highlights
  const highlights = extractHighlights(timeline);
  if (highlights.length > 0) {
    description += '\n\nKey moments:';
    highlights.forEach(highlight => {
      description += `\n• ${highlight}`;
    });
  }
  
  // Add standard footer
  description += '\n\n---';
  description += '\n🎯 Subscribe for daily chess analysis!';
  description += '\n📚 Learn from the masters with detailed move-by-move commentary';
  description += '\n🔥 Watch more chess content: [Channel Link]';
  description += '\n\n#Chess #ChessAnalysis #ChessGame #ChessMaster #ChessStrategy';
  
  return description;
}

/**
 * Generate relevant tags for the video
 */
export function generateTags(timeline: Timeline): string[] {
  const { white, black, event, eco } = timeline.meta;
  const tags = new Set<string>();
  
  // Basic chess tags
  tags.add('Chess');
  tags.add('Chess Analysis');
  tags.add('Chess Game');
  tags.add('Chess Strategy');
  tags.add('Chess Master');
  tags.add('Chess Tutorial');
  
  // Player names
  if (white) tags.add(white);
  if (black) tags.add(black);
  
  // Event tags
  if (event) {
    tags.add(event);
    if (event.toLowerCase().includes('world')) tags.add('World Chess Championship');
    if (event.toLowerCase().includes('candidates')) tags.add('Candidates Tournament');
    if (event.toLowerCase().includes('olympiad')) tags.add('Chess Olympiad');
  }
  
  // Opening tags
  if (eco) {
    tags.add(eco);
    if (eco.startsWith('A')) tags.add('Flank Openings');
    if (eco.startsWith('B')) tags.add('Semi-Open Games');
    if (eco.startsWith('C')) tags.add('Open Games');
    if (eco.startsWith('D')) tags.add('Closed Games');
    if (eco.startsWith('E')) tags.add('Indian Defenses');
  }
  
  // Analysis tags
  const highlights = extractHighlights(timeline);
  highlights.forEach(highlight => {
    if (highlight.toLowerCase().includes('sacrifice')) tags.add('Chess Sacrifice');
    if (highlight.toLowerCase().includes('tactic')) tags.add('Chess Tactics');
    if (highlight.toLowerCase().includes('endgame')) tags.add('Chess Endgame');
    if (highlight.toLowerCase().includes('opening')) tags.add('Chess Opening');
    if (highlight.toLowerCase().includes('middlegame')) tags.add('Chess Middlegame');
  });
  
  // Convert to array and limit to 15 tags (YouTube limit)
  return Array.from(tags).slice(0, 15);
}

/**
 * Extract highlights from timeline for description
 */
function extractHighlights(timeline: Timeline): string[] {
  const highlights: string[] = [];
  
  timeline.scenes.forEach(scene => {
    if (scene.type === 'main') {
      // Check for interesting moves
      if (scene.pins && scene.pins.length > 0) {
        highlights.push('Pin tactics and tactical motifs');
      }
      
      // Check for evaluation swings
      if (Math.abs(scene.evalBarTarget) > 0.5) {
        const advantage = scene.evalBarTarget > 0 ? 'White' : 'Black';
        highlights.push(`${advantage} gains significant advantage`);
      }
    }
  });
  
  // Remove duplicates and limit
  return [...new Set(highlights)].slice(0, 5);
}

/**
 * Generate category ID for YouTube
 */
export function getCategoryId(): string {
  return '20'; // Gaming category
}

/**
 * Generate complete metadata object
 */
export function generateMetadata(timeline: Timeline): VideoMetadata {
  return {
    title: generateTitle(timeline),
    description: generateDescription(timeline),
    tags: generateTags(timeline),
    categoryId: getCategoryId(),
  };
}
