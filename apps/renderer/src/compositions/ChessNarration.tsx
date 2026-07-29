import React, {useMemo} from 'react';
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  Easing,
} from 'remotion';
import {AnimatedBoard} from '../components/AnimatedBoard';
import {
  THEME,
  PlayerRow,
  EvalColumn,
  CurrentMove,
  MoveList,
  Wordmark,
  MoveListEntry,
} from '../components/AnalysisRail';
import type {Beat, Script} from '../types/script';

export type ChessNarrationProps = {
  script?: Script | null;
  audioBase?: string;
  [key: string]: unknown;
};

const BOARD = 880;
const BOARD_X = 96;
const BOARD_Y = (1080 - BOARD) / 2;
// The eval column now lives in the gap beside the board, so the rail starts
// further right than the board's edge alone would suggest.
const RAIL_X = BOARD_X + BOARD + 84;
const RAIL_W = 1920 - RAIL_X - 96;
// Where the players panel ends and the rail below it begins. Two 96px portrait
// rows plus the panel's own padding.
const PLAYERS_BOTTOM = 40 + 276 + 24;
const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

// Chess annotation marks, in the conventional colours. Deliberately only the
// notable qualities: a badge on every move is a badge on none.
const BADGE: Record<string, {symbol: string; color: string}> = {
  brilliant: {symbol: '!!', color: '#3ddc97'},
  great: {symbol: '!', color: '#5ac8fa'},
  mistake: {symbol: '?', color: '#ff8c42'},
  blunder: {symbol: '??', color: '#ff5d5d'},
};

const displayName = (raw?: string | null): string => {
  if (!raw) return 'Unknown';
  const v = raw.trim();
  if (!v || /^[?.]+$/.test(v)) return 'Unknown';
  if (v.includes(',')) {
    const [last, first] = v.split(',');
    return `${first.trim()} ${last.trim()}`.trim();
  }
  return v;
};

/** PGN dates look like "1979.??.??" — show only the parts that are known. */
const prettyDate = (raw?: string | null): string | null => {
  if (!raw) return null;
  const v = raw.trim();
  if (!v || /^[?.]+$/.test(v)) return null;
  const [year, month, day] = v.split('.');
  const known = (part?: string) => (part && !part.includes('?') ? part : null);
  if (!known(year)) return null;
  if (!known(month)) return year;
  if (!known(day)) return `${month}.${year}`;
  return `${day}.${month}.${year}`;
};

interface Segment {
  beat: Beat;
  from: number;
  durationInFrames: number;
}

export const ChessNarration: React.FC<ChessNarrationProps> = ({
  script,
  audioBase = '/audio',
}) => {
  const {fps} = useVideoConfig();
  const frame = useCurrentFrame();

  const beats = script?.beats ?? [];
  const meta = script?.meta ?? {};

  const segments: Segment[] = useMemo(() => {
    let cursor = 0;
    return beats.map((beat) => {
      const durationInFrames = Math.max(
        1,
        Math.round(((beat.durationMs || 1500) * fps) / 1000)
      );
      const seg = {beat, from: cursor, durationInFrames};
      cursor += durationInFrames;
      return seg;
    });
  }, [beats, fps]);

  const currentIndex = useMemo(() => {
    for (let i = 0; i < segments.length; i++) {
      if (frame < segments[i].from + segments[i].durationInFrames) return i;
    }
    return Math.max(0, segments.length - 1);
  }, [frame, segments]);

  const current = segments[currentIndex] ?? null;

  // Move list is built from the main line only, so variations do not pollute it.
  const moveEntries: MoveListEntry[] = useMemo(() => {
    const byNumber = new Map<number, MoveListEntry>();
    for (const beat of beats) {
      if (beat.kind !== 'move' || !beat.ply || !beat.move) continue;
      const moveNumber = Math.ceil(beat.ply / 2);
      const entry = byNumber.get(moveNumber) ?? {moveNumber};
      if (beat.ply % 2 === 1) entry.white = beat.move.san;
      else entry.black = beat.move.san;
      byNumber.set(moveNumber, entry);
    }
    return [...byNumber.values()].sort((a, b) => a.moveNumber - b.moveNumber);
  }, [beats]);

  if (!script || beats.length === 0) {
    return (
      <AbsoluteFill
        style={{
          background: THEME.bg0,
          color: THEME.text,
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif',
          textAlign: 'center',
          padding: 48,
        }}
      >
        <div>
          <div style={{fontSize: 34, marginBottom: 14}}>No script loaded</div>
          <div style={{opacity: 0.7, fontSize: 20, lineHeight: 1.6}}>
            Run <code>python services/orchestrator/build_video.py --pgn game.pgn</code>
          </div>
        </div>
      </AbsoluteFill>
    );
  }

  const beat = current?.beat ?? beats[beats.length - 1];
  const isCard = beat.kind === 'intro' || beat.kind === 'outro';
  const white = displayName(meta.white);
  const black = displayName(meta.black);
  const eventLine = [meta.event, prettyDate(meta.date)].filter(Boolean).join(' · ');
  const channel = meta.channel ?? 'Midnight Chess';

  // Board props come from the current beat, but the board itself is mounted
  // ONCE for the whole video. Remounting it per beat destroyed and recreated
  // all 32 piece sprites at every boundary, which is what made the pieces
  // flicker. moveStartFrame is therefore absolute, not sequence-relative.
  const boardFen = beat.fen ?? beat.prevFen ?? START_FEN;
  const boardPrevFen = beat.prevFen ?? boardFen;
  const moveStartFrame =
    (current?.from ?? 0) + Math.round(((beat.moveAtMs || 0) * fps) / 1000);

  // Only the moves worth marking get a sticker on the board. "Good" and "best"
  // are most of the game — badging them would make the mark meaningless.
  const moveBadge =
    beat.move && !beat.branch && beat.tag && BADGE[beat.tag]
      ? {square: beat.move.to, ...BADGE[beat.tag]}
      : null;

  // The rail must not announce a move before the narrator does. The narration
  // builds up to its moves, so a beat can spend seconds talking before the
  // piece travels — during that time the MOVE panel, the quality tag, the move
  // list, the eval bar and the player highlight all keep describing the LAST
  // move that actually happened on screen, flipping only at this beat's cue.
  // (Recomputed every frame by nature; the scan is ~100 segments, trivial.)
  const revealed = !beat.move || frame >= moveStartFrame;
  let lastRevealed: Beat | null = null;
  if (!revealed) {
    for (const seg of segments) {
      if (!seg.beat.move) continue;
      const at = seg.from + Math.round(((seg.beat.moveAtMs || 0) * fps) / 1000);
      if (at <= frame) lastRevealed = seg.beat;
      if (seg.from > frame) break;
    }
  }
  const shownBeat = revealed ? beat : lastRevealed ?? beat;
  const shownIsMove = Boolean(shownBeat.move) && (revealed || lastRevealed !== null);
  // Before the very first reveal nothing has happened yet: empty move panel,
  // empty list, level eval — exactly what a viewer should see.
  const panelBeat = shownIsMove || !shownBeat.move
    ? shownBeat
    : {...shownBeat, move: null, tag: null, label: null, branch: false};
  const moveNumber =
    (shownIsMove || !beat.move) && shownBeat.ply ? Math.ceil(shownBeat.ply / 2) : null;
  const shownPly = shownIsMove ? shownBeat.ply : null;
  const shownEvalCp = shownIsMove || !beat.move ? shownBeat.evalCp : 0;

  // Highlight whoever played the move currently on screen. The mover is the
  // side to move in the position *before* that move — reading the post-move
  // FEN lit up the opponent. Beats with no move fall back to whoever is on
  // turn in the shown position.
  const activeSide: 'white' | 'black' = (
    shownIsMove && shownBeat.move
      ? (shownBeat.prevFen ?? START_FEN).split(' ')[1]
      : shownBeat.move
        ? // Unrevealed move with nothing shown yet: whoever is about to move.
          (shownBeat.prevFen ?? START_FEN).split(' ')[1]
        : (shownBeat.fen ?? shownBeat.prevFen ?? START_FEN).split(' ')[1]
  ) === 'b'
    ? 'black'
    : 'white';

  return (
    <AbsoluteFill
      style={{
        background: THEME.bg0,
        fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif',
      }}
    >
      {/* Depth: a soft cool glow behind the board, plus a fine grid */}
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(1100px 700px at 28% 46%, rgba(90,200,250,0.10), transparent 70%),' +
            'radial-gradient(900px 600px at 82% 70%, rgba(178,140,255,0.07), transparent 70%)',
        }}
      />
      <AbsoluteFill
        style={{
          opacity: 0.5,
          backgroundImage:
            'linear-gradient(rgba(255,255,255,0.018) 1px, transparent 1px),' +
            'linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px)',
          backgroundSize: '64px 64px',
        }}
      />

      {/* Wordmark */}
      <div style={{position: 'absolute', left: BOARD_X, top: 46}}>
        <Wordmark name={channel} />
      </div>

      {/* Board — mounted once, never remounted */}
      <div
        style={{
          position: 'absolute',
          left: BOARD_X,
          top: BOARD_Y,
          width: BOARD,
          height: BOARD,
        }}
      >
        <AnimatedBoard
          prevFen={boardPrevFen}
          fen={boardFen}
          move={beat.move ? {from: beat.move.from, to: beat.move.to} : null}
          moveStartFrame={moveStartFrame}
          moveDurationFrames={Math.round(fps * 0.4)}
          size={BOARD}
          highlights={[
            ...(beat.highlights ?? []),
            // Squares the narrator names light up on the spoken word.
            ...(beat.mentions ?? []).map((m) => ({
              square: m.square,
              kind: 'mention' as const,
              startFrame:
                (current?.from ?? 0) + Math.round((m.atMs * fps) / 1000),
            })),
          ]}
          arrows={beat.arrows}
          checkSquare={beat.checkSquare}
          branch={beat.branch}
          badge={moveBadge}
          showCoordinates
        />
      </div>

      {/* Event caption under the board */}
      {eventLine && (
        <div
          style={{
            position: 'absolute',
            left: BOARD_X,
            top: BOARD_Y + BOARD + 26,
            fontSize: 24,
            letterSpacing: 1.2,
            color: THEME.muted,
          }}
        >
          {eventLine}
        </div>
      )}

      {/* Players — top right, on the wordmark's line */}
      <div
        style={{
          position: 'absolute',
          left: RAIL_X,
          top: 40,
          width: RAIL_W,
          background: THEME.panel,
          border: `1px solid ${THEME.panelEdge}`,
          borderRadius: 14,
          padding: 14,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
        }}
      >
        <PlayerRow
          name={black}
          side="black"
          active={activeSide === 'black'}
          portrait={meta.blackPortrait}
        />
        <PlayerRow
          name={white}
          side="white"
          active={activeSide === 'white'}
          portrait={meta.whitePortrait}
        />
      </div>

      {/* Evaluation — a vertical column hugging the board */}
      <div
        style={{
          position: 'absolute',
          left: BOARD_X + BOARD + 20,
          top: BOARD_Y,
        }}
      >
        <EvalColumn cp={shownEvalCp} height={BOARD - 44} />
      </div>

      {/* Analysis rail */}
      <div
        style={{
          position: 'absolute',
          left: RAIL_X,
          top: PLAYERS_BOTTOM,
          width: RAIL_W,
          height: BOARD_Y + BOARD - PLAYERS_BOTTOM,
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}
      >
        <CurrentMove
          beat={panelBeat}
          moveNumber={moveNumber}
          isBlack={shownBeat.ply ? shownBeat.ply % 2 === 0 : false}
        />
        <MoveList entries={moveEntries} currentPly={shownPly} rows={3} />
      </div>

      {/* Intro / outro card */}
      {isCard && <TitleOverlay beat={beat} white={white} black={black} meta={meta} />}

      {/* Narration audio, one clip per beat */}
      {segments.map(({beat: b, from, durationInFrames}) =>
        b.audioFile ? (
          <Sequence
            key={`audio-${b.id}`}
            from={from}
            durationInFrames={durationInFrames}
            layout="none"
          >
            <Audio src={staticFile(`${audioBase.replace(/^\//, '')}/${b.audioFile}`)} />
          </Sequence>
        ) : null
      )}
    </AbsoluteFill>
  );
};

const TitleOverlay: React.FC<{
  beat: Beat;
  white: string;
  black: string;
  meta: Script['meta'];
}> = ({beat, white, black, meta}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 12], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

  const isOutro = beat.kind === 'outro';
  const subtitle = isOutro
    ? meta.result && meta.result !== '*'
      ? `Result  ${meta.result}`
      : undefined
    : [meta.event, prettyDate(meta.date)].filter(Boolean).join('  ·  ') || undefined;

  return (
    <AbsoluteFill
      style={{
        background: 'rgba(9,12,17,0.90)',
        alignItems: 'center',
        justifyContent: 'center',
        opacity,
      }}
    >
      <div style={{textAlign: 'center', color: THEME.text, padding: 60}}>
        {isOutro ? (
          <div style={{fontSize: 78, letterSpacing: 1}}>Thanks for watching</div>
        ) : (
          <>
            <div style={{fontSize: 30, letterSpacing: 7, color: THEME.accent, marginBottom: 30}}>
              GAME OF THE DAY
            </div>
            <div style={{fontSize: 82, lineHeight: 1.18}}>{white}</div>
            <div style={{fontSize: 34, color: THEME.muted, margin: '14px 0'}}>versus</div>
            <div style={{fontSize: 82, lineHeight: 1.18}}>{black}</div>
          </>
        )}
        {subtitle && (
          <div style={{fontSize: 32, color: THEME.muted, marginTop: 34, letterSpacing: 1.5}}>
            {subtitle}
          </div>
        )}
        {!isOutro && meta.opening?.name && (
          <div style={{fontSize: 27, color: '#5c6878', marginTop: 12}}>{meta.opening.name}</div>
        )}
      </div>
    </AbsoluteFill>
  );
};
