export type BeatKind = 'intro' | 'move' | 'variation' | 'resume' | 'hold' | 'outro';

export interface BeatMove {
  from: string;
  to: string;
  san: string;
}

export interface BeatHighlight {
  square: string;
  kind?: 'move' | 'alt' | 'danger' | 'good';
  color?: string;
}

export interface BeatArrow {
  from: string;
  to: string;
  color?: string;
}

export interface Beat {
  id: string;
  kind: BeatKind;
  text: string;
  prevFen: string | null;
  fen: string | null;
  move: BeatMove | null;
  branch: boolean;
  label: string | null;
  highlights: BeatHighlight[];
  arrows: BeatArrow[];
  checkSquare: string | null;
  evalCp: number | null;
  tag: string | null;
  ply: number | null;
  moveCueWords: string[];
  /** Roughly how many spoken words this beat should get — sets its pacing. */
  targetWords?: number;

  /** Filled in by the build step from the audio manifest. */
  durationMs: number;
  /** Milliseconds into the beat when the piece should start moving. */
  moveAtMs: number;
  /** File name inside /public/audio, e.g. "b0007.mp3". Null when silent. */
  audioFile: string | null;
  /** Squares the narrator names ("the knight on d3"), verified against the
   *  position and timed to the spoken word. */
  mentions?: {square: string; atMs: number}[];
  /** Breath group — beats sharing a para are one continuous TTS take. */
  para?: number;
}

export interface ScriptMeta {
  white?: string | null;
  black?: string | null;
  date?: string | null;
  event?: string | null;
  site?: string | null;
  result?: string | null;
  eco?: string | null;
  channel?: string | null;
  narration?: 'llm' | 'template';
  opening?: { eco?: string | null; name?: string | null } | null;
  whitePortrait?: string | null;
  /** Full names resolved by the director — the one source of truth. */
  whiteFull?: string | null;
  blackFull?: string | null;
  blackPortrait?: string | null;
  supportText?: string | null;
  /** Title + description hook written by the narration model. */
  llmTitle?: string | null;
  llmHook?: string | null;
  /** Short overlay line for the thumbnail, written by the narration model. */
  llmThumb?: string | null;
  /** Intro quotation. Hand-checked table, never model-written. */
  quote?: {text: string; author: string; portrait?: string | null} | null;
  /** How the game ended — derived from the final position, not just Result. */
  outcome?: {
    type: 'checkmate' | 'resignation' | 'stalemate' | 'insufficient' |
          'repetition' | 'draw' | 'timeout' | 'abandoned' | 'unknown';
    winner?: 'white' | 'black' | null;
    text?: string;
  } | null;
}

export interface Script {
  meta: ScriptMeta;
  beats: Beat[];
}
