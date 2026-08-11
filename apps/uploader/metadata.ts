/**
 * Generate YouTube title, description, and tags from the narration script.
 *
 * Where possible these reuse what the narration model already produced — it saw
 * the whole game, so its title and hook beat anything assembled from PGN
 * headers. Everything falls back to generated text when no LLM key is set.
 */

import type { Script } from '../renderer/src/types/script';

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

/** "1-0" is jargon above the fold; say who won and keep the notation. */
function readableResult(raw: string | null | undefined): string | undefined {
  const r = clean(raw);
  if (!r || r === '*') return undefined;
  if (r === '1-0') return '1-0 (White wins)';
  if (r === '0-1') return '0-1 (Black wins)';
  if (r.startsWith('1/2')) return '½-½ (Draw)';
  return r;
}

/**
 * Build the full YouTube description, to the channel's fixed template.
 *
 * The shape is deliberately identical on every video — the same section
 * order, the same standing copy — so the channel reads as one series rather
 * than a hundred one-offs. Only four things vary: the opening sentences, the
 * game details, the photo credits, and the chapters the CLI appends.
 *
 * Order matters: only the first ~150 characters show above the fold, so the
 * game-specific hook leads and the housekeeping trails.
 */
export function generateDescription(script: Script, moreVideos: string[] = []): string {
  const white = displayName(script.meta.white) ?? 'White';
  const black = displayName(script.meta.black) ?? 'Black';
  const event = clean(script.meta.event);
  const year = parseYear(script.meta.date);
  const result = readableResult(script.meta.result);
  // A bare ECO code means nothing to most viewers, so an unnamed opening is
  // left out of the listing entirely rather than printed as "Opening: D41".
  const openingName = clean(script.meta.opening?.name);
  const openingCode = clean(script.meta.opening?.eco) ?? clean(script.meta.eco);
  const opening = openingName
    ? openingCode
      ? `${openingName} (${openingCode})`
      : openingName
    : undefined;
  const channel = clean(script.meta.channel) ?? 'Nocturne Chess';
  const l = links();

  const blocks: string[] = [];

  // 1. The only genuinely unique paragraph, and the only part most viewers
  // ever read. The narration model wrote it, having seen the whole game.
  const hook = clean(script.meta.llmHook);
  blocks.push(
    hook ??
      `${white} against ${black}${event ? ` at ${event}` : ''}${year ? `, ${year}` : ''}. ` +
        'A full move-by-move breakdown, including the moments where the game turned ' +
        'and what the engine would have played instead.'
  );

  blocks.push(
    `In this episode of ${channel}, experience a remarkable game presented with ` +
      'calm narration, atmospheric sound and clear strategic storytelling.'
  );

  // 2. The game at a glance. Lines whose value is unknown are omitted rather
  // than printed with a placeholder — a PGN with no Event is common, and
  // "Event: ?" looks like a bug to a viewer.
  const facts = [`White: ${white}`, `Black: ${black}`];
  if (event) facts.push(`Event: ${event}`);
  if (year) facts.push(`Year: ${year}`);
  if (opening) facts.push(`Opening: ${opening}`);
  if (result) facts.push(`Result: ${result}`);
  blocks.push(['♟ GAME DETAILS', '', ...facts].join('\n'));

  blocks.push(
    `${channel} presents relaxing narrations of memorable games from chess ` +
      'history, with original commentary, board animation, sound design and editing.'
  );

  blocks.push(
    [
      'Subscribe for:',
      '• Calm narrated chess games',
      '• Historic chess masterpieces',
      '• Brilliant attacks and sacrifices',
      '• Strategic explanations',
      '• Relaxing late-night chess',
    ].join('\n')
  );

  // 3. Calls to action, each omitted entirely when its link is unset.
  const cta: string[] = [];
  if (l.playChess) cta.push(`Play chess free: ${l.playChess}`);
  if (l.support) cta.push(`Support the channel: ${l.support}`);
  if (l.channel) cta.push(`More games like this: ${l.channel}`);
  if (cta.length) blocks.push(cta.join('\n'));

  // 4. Related videos, when the uploader was able to fetch them.
  if (moreVideos.length > 0) {
    blocks.push(['More videos:', ...moreVideos].join('\n'));
  }

  // 5. Housekeeping. The disclosure must stay if any link above is an affiliate
  // link — that is an FTC requirement, not a stylistic choice.
  //
  // Photo credits used to be listed here, block by block, for every Commons
  // portrait whose licence asked for attribution. Removed by decision: the
  // block ate a third of the description on a two-player game and pushed the
  // links people actually click below the fold. The credits are still recorded
  // in the script's meta.portraitCredits, so nothing is lost if the sourcing
  // is revisited — the intention is to move to portraits that carry no
  // attribution obligation at all rather than to publish uncredited CC BY-SA.
  if (l.affiliateDisclosure) blocks.push(l.affiliateDisclosure);
  if (l.contact) blocks.push(`Contact: ${l.contact}`);
  blocks.push(hashtags(script).join(' '));

  return blocks.join('\n\n');
}

/**
 * A small, relevant hashtag set. YouTube surfaces only the first three above
 * the title, so the channel's own three lead and the game-specific ones
 * follow — the brand tag is the one worth owning.
 */
function hashtags(script: Script): string[] {
  const channel = (clean(script.meta.channel) ?? 'Nocturne Chess').replace(/[^A-Za-z0-9]/g, '');
  const tags = ['#Chess', '#ChessGames', `#${channel}`];
  for (const name of [displayName(script.meta.white), displayName(script.meta.black)]) {
    const surname = name?.split(' ').pop();
    if (surname && /^[A-Za-z]{3,}$/.test(surname)) tags.push(`#${surname}`);
  }
  if (script.beats.some((b) => b.tag === 'brilliant')) tags.push('#BrilliantMove');
  if (script.beats.some((b) => b.tag === 'blunder')) tags.push('#Blunder');
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

/**
 * Metadata for a vertical Short.
 *
 * A Short is a funnel, not a listing: the title is the hook plus the names
 * (never "Player vs Player, Event Year" — nobody in the Shorts feed is
 * searching), and the description's FIRST line is the full-game link,
 * because that click is the entire point of posting Shorts at all.
 * Classification is automatic from aspect ratio; #Shorts in title and tags
 * is the supporting signal.
 */
export function generateShortMetadata(script: Script, fullUrl?: string): VideoMetadata {
  const meta = script.meta ?? {};
  const white = clean(meta.whiteFull) ?? clean(meta.white) ?? 'White';
  const black = clean(meta.blackFull) ?? clean(meta.black) ?? 'Black';
  const hook = clean((meta as any).shortHook) ?? 'One move changed everything.';

  let title = `${hook} ${white} vs ${black} #Shorts`;
  if (title.length > 100) {
    title = `${hook} #Shorts`;
  }

  const blocks: string[] = [];
  if (fullUrl) {
    blocks.push(`Full game, move by move: ${fullUrl}`);
  }
  const fullTitle = clean((meta as any).shortOf);
  if (fullTitle) {
    blocks.push(`From: ${fullTitle}`);
  }
  blocks.push(
    `${clean(meta.channel) ?? 'Nocturne Chess'} — memorable games from chess ` +
      'history, narrated calmly and checked against Stockfish. New game daily.'
  );

  const tags = [
    'Shorts', 'chess', 'chess shorts', white, black,
    'brilliant move', 'chess history', 'chess tactics',
  ].filter((t) => t && t.length <= 30);

  return {
    title,
    description: blocks.join('\n\n'),
    tags: [...new Set(tags)],
    categoryId: getCategoryId(),
  };
}
