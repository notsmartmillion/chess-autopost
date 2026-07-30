/**
 * Generate YouTube title, description, and tags from the narration script.
 *
 * Where possible these reuse what the narration model already produced — it saw
 * the whole game, so its title and hook beat anything assembled from PGN
 * headers. Everything falls back to generated text when no LLM key is set.
 */

import type { Script } from '../renderer/src/types/script';

/** Attribution for a Commons portrait whose licence requires credit. */
export interface PortraitCredit {
  player?: string;
  licence?: string;
  author?: string;
  url?: string;
}

export interface VideoMetadata {
  title: string;
  description: string;
  tags: string[];
  categoryId: string;
}

/** PGN uses "?" / "????.??.??" for unknown header values — treat those as absent. */
function clean(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const v = value.trim();
  if (!v || /^[?.]+$/.test(v)) return undefined;
  return v;
}

/** PGN stores names surname-first ("Tal, Mihail"); people read "Mihail Tal". */
/**
 * "Bronstein, David I" -> "David Bronstein". Bare initials are dropped, as
 * they are on screen and in the narration: nobody searches YouTube for
 * "David I Bronstein", so a tag carrying the initial matches nothing.
 */
function displayName(value: string | null | undefined): string | undefined {
  const v = clean(value);
  if (!v) return undefined;
  const [last, first] = v.includes(',') ? v.split(',') : [v, ''];
  const given = (first ?? '')
    .trim()
    .split(/\s+/)
    .filter((part) => part && !/^[A-Za-z]\.?$/.test(part))
    .join(' ');
  const surname = (last ?? '').trim();
  return (given ? `${given} ${surname}` : surname).trim() || undefined;
}

function parseYear(date: string | null | undefined): string {
  const d = clean(date);
  if (!d) return '';
  const m = d.match(/^(\d{4})/);
  return m ? m[1] : '';
}

export function generateTitle(script: Script): string {
  // The narration model saw the whole game, so its title is almost always
  // better than one assembled from headers. Fall back when it is absent.
  const llm = clean(script.meta.llmTitle);
  if (llm) return llm.slice(0, 100);

  const white = displayName(script.meta.white) ?? 'White';
  const black = displayName(script.meta.black) ?? 'Black';
  const event = clean(script.meta.event);
  const year = parseYear(script.meta.date);

  const parts = [`${white} vs ${black}`, event || 'Chess Game Analysis'];
  if (year) parts.push(year);
  return parts.join(' - ');
}

/** Optional links, configured via .env — each is omitted entirely when unset. */
function links() {
  return {
    playChess: clean(process.env.LINK_PLAY_CHESS),
    support: clean(process.env.LINK_SUPPORT),
    channel: clean(process.env.LINK_CHANNEL),
    contact: clean(process.env.CONTACT_EMAIL),
    affiliateDisclosure: clean(process.env.AFFILIATE_DISCLOSURE),
  };
}

/**
 * Build the full YouTube description.
 *
 * Order matters: only the first ~150 characters show above the fold, so the
 * hook leads and the housekeeping trails. Chapters are appended by the CLI,
 * which owns the timings.
 */
export function generateDescription(script: Script, moreVideos: string[] = []): string {
  const white = displayName(script.meta.white) ?? 'White';
  const black = displayName(script.meta.black) ?? 'Black';
  const event = clean(script.meta.event);
  const year = parseYear(script.meta.date);
  const result = clean(script.meta.result);
  const opening = clean(script.meta.opening?.name) ?? clean(script.meta.eco);
  const l = links();

  const blocks: string[] = [];

  // 1. Hook — the only part most viewers ever read.
  const hook = clean(script.meta.llmHook);
  blocks.push(
    hook ??
      `${white} against ${black}${event ? ` at ${event}` : ''}${year ? `, ${year}` : ''}. ` +
        'A full move-by-move breakdown, including the moments where the game turned ' +
        'and what the engine would have played instead.'
  );

  // 2. The game at a glance.
  const facts = [`White: ${white}`, `Black: ${black}`];
  if (event || year) facts.push(`Event: ${[event, year].filter(Boolean).join(', ')}`);
  if (opening) facts.push(`Opening: ${opening}`);
  if (result && result !== '*') facts.push(`Result: ${result}`);
  blocks.push(facts.join('\n'));

  // 3. What the viewer gets.
  const highlights = extractHighlights(script);
  if (highlights.length > 0) {
    blocks.push(['In this video:', ...highlights.map((h) => `• ${h}`)].join('\n'));
  }

  // 4. Calls to action.
  const cta: string[] = [];
  if (l.playChess) cta.push(`Play chess free: ${l.playChess}`);
  if (l.support) cta.push(`Support the channel: ${l.support}`);
  if (l.channel) cta.push(`More games like this: ${l.channel}`);
  if (cta.length) blocks.push(cta.join('\n'));

  blocks.push('Like and subscribe if you enjoyed this one — it genuinely helps the channel.');

  // 5. Related videos, when the uploader was able to fetch them.
  if (moreVideos.length > 0) {
    blocks.push(['More videos:', ...moreVideos].join('\n'));
  }

  // 6. Housekeeping. The disclosure must stay if any link above is an affiliate
  // link — that is an FTC requirement, not a stylistic choice. Photo credits
  // are the same kind of obligation: the portraits come from Wikimedia
  // Commons, and a CC BY-SA licence is only honoured if the credit travels
  // with the image.
  const credits = (script.meta as {portraitCredits?: PortraitCredit[]}).portraitCredits;
  if (credits?.length) {
    blocks.push(
      [
        'Player photographs:',
        ...credits.map((c) =>
          `• ${c.player} — ${c.author || 'unknown author'}, ${c.licence || 'see source'}` +
          `${c.url ? ` (${c.url})` : ''}`
        ),
        'via Wikimedia Commons.',
      ].join('\n')
    );
  }
  if (l.affiliateDisclosure) blocks.push(l.affiliateDisclosure);
  if (l.contact) blocks.push(`Contact: ${l.contact}`);
  blocks.push(hashtags(script).join(' '));

  return blocks.join('\n\n');
}

/** A small, relevant hashtag set — YouTube only surfaces the first three. */
function hashtags(script: Script): string[] {
  const tags = ['#chess', '#chessgame', '#chessanalysis'];
  for (const name of [displayName(script.meta.white), displayName(script.meta.black)]) {
    const surname = name?.split(' ').pop();
    if (surname && /^[A-Za-z]{3,}$/.test(surname)) tags.push(`#${surname.toLowerCase()}`);
  }
  if (script.beats.some((b) => b.tag === 'brilliant')) tags.push('#brilliantmove');
  if (script.beats.some((b) => b.tag === 'blunder')) tags.push('#blunder');
  return tags.slice(0, 6);
}

export function generateTags(script: Script): string[] {
  const white = displayName(script.meta.white);
  const black = displayName(script.meta.black);
  const event = clean(script.meta.event);
  const eco = clean(script.meta.eco);
  const opening = clean(script.meta.opening?.name);
  const tags = new Set<string>();

  tags.add('Chess');
  tags.add('Chess Analysis');
  tags.add('Chess Game');
  tags.add('Chess Strategy');
  tags.add('Chess Tactics');

  if (white) tags.add(white);
  if (black) tags.add(black);

  if (event) {
    tags.add(event);
    if (event.toLowerCase().includes('world')) tags.add('World Chess Championship');
    if (event.toLowerCase().includes('candidates')) tags.add('Candidates Tournament');
    if (event.toLowerCase().includes('olympiad')) tags.add('Chess Olympiad');
  }

  if (opening) tags.add(opening);
  if (eco) {
    tags.add(eco);
    if (eco.startsWith('A')) tags.add('Flank Openings');
    if (eco.startsWith('B')) tags.add('Semi-Open Games');
    if (eco.startsWith('C')) tags.add('Open Games');
    if (eco.startsWith('D')) tags.add('Closed Games');
    if (eco.startsWith('E')) tags.add('Indian Defenses');
  }

  for (const highlight of extractHighlights(script)) {
    const h = highlight.toLowerCase();
    if (h.includes('sacrifice')) tags.add('Chess Sacrifice');
    if (h.includes('brilliant')) tags.add('Brilliant Move');
    if (h.includes('mistake')) tags.add('Chess Blunder');
  }

  // YouTube splits tags on commas, so a tag containing one becomes two junk
  // tags. Strip them, drop empties, then cap the list.
  return Array.from(tags)
    .map((t) => t.replace(/,/g, ' ').replace(/\s+/g, ' ').trim())
    .filter((t) => t.length > 0)
    .slice(0, 15);
}

function extractHighlights(script: Script): string[] {
  const highlights: string[] = [];

  for (const beat of script.beats) {
    switch (beat.tag) {
      case 'blunder':
        highlights.push('The mistake that decides the game');
        break;
      case 'brilliant':
        highlights.push('A brilliant sacrifice');
        break;
      case 'great':
        highlights.push('The key idea behind the win');
        break;
      default:
        break;
    }
    if (beat.kind === 'variation') {
      highlights.push('What the engine would have played instead');
    }
    if (beat.checkSquare) {
      highlights.push('Sharp attacking play against the king');
    }
  }

  return [...new Set(highlights)].slice(0, 5);
}

export function getCategoryId(): string {
  return '20'; // Gaming
}

export function generateMetadata(script: Script, moreVideos: string[] = []): VideoMetadata {
  return {
    title: generateTitle(script),
    description: generateDescription(script, moreVideos),
    tags: generateTags(script),
    categoryId: getCategoryId(),
  };
}
