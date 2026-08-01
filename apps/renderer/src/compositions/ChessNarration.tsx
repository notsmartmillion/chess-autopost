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
  PlayerCard,
  EvalColumn,
  CurrentMove,
  MoveList,
  Wordmark,
  MoveListEntry,
} from '../components/AnalysisRail';
import {QuoteCard} from '../components/QuoteCard';
import {SubscribeBadge} from '../components/SubscribeBadge';
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
// The rail splits into two equal halves with no dead space: the matchup on
// top, the move panels below, together spanning exactly the board's height.
const RAIL_TOP = 40;
const RAIL_BOTTOM = BOARD_Y + BOARD;
const RAIL_GAP = 24;
const RAIL_HALF = (RAIL_BOTTOM - RAIL_TOP - RAIL_GAP) / 2;
const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

// Chess annotation marks, in the conventional colours. Deliberately only the
// notable qualities: a badge on every move is a badge on none.
const BADGE: Record<string, {symbol: string; color: string}> = {
  brilliant: {symbol: '!!', color: '#3ddc97'},
  great: {symbol: '!', color: '#5ac8fa'},
  mistake: {symbol: '?', color: '#ff8c42'},
  blunder: {symbol: '??', color: '#ff5d5d'},
};

/**
 * "Bronstein, David I" -> "David Bronstein".
 *
 * PGN headers carry middle initials and Russian patronymics, often truncated
 * ("Chistiakov, Alexander Nikolaevi"). A lone capital I renders as a bare
 * vertical stroke and gets read as a pipe character, and broadcasts say
 * "David Bronstein" anyway — so bare initials are dropped.
 */
const displayName = (raw?: string | null): string => {
  if (!raw) return 'Unknown';
  const v = raw.trim();
  if (!v || /^[?.]+$/.test(v)) return 'Unknown';
  const [last, first] = v.includes(',') ? v.split(',') : [v, ''];
  const given = (first ?? '')
    .trim()
    .split(/\s+/)
    .filter((part) => part && !/^[A-Za-z]\.?$/.test(part))
    .join(' ');
  const surname = (last ?? '').trim();
  return (given ? `${given} ${surname}` : surname).trim() || 'Unknown';
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

  // The last intro beat is the one that carries the quotation.
  const lastIntroId = useMemo(() => {
    const intros = beats.filter((b) => b.kind === 'intro');
    return intros.length ? intros[intros.length - 1].id : null;
  }, [beats]);

  // The subscribe badge is permanent once the game starts. Timed showings
  // were tried twice and the channel's own maker missed them both times; the
  // badge is not clickable anyway (baked pixels never are — YouTube's
  // branding watermark is the clickable one), so it works as a standing
  // reminder or not at all. It waits out the intro cards rather than float
  // over the quotation, then stays to the end.
  const subscribeFrom: number = useMemo(() => {
    const firstGame = segments.find((s) => s.beat.kind !== 'intro');
    return firstGame ? firstGame.from : Math.round(fps * 10);
  }, [segments, fps]);
  const totalFrames = segments.length
    ? segments[segments.length - 1].from + segments[segments.length - 1].durationInFrames
    : 0;

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
  const channel = meta.channel ?? 'Nocturne Chess';

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

  // The rail must never run ahead of the narrator, and never fall behind the
  // game either. It always describes the last REAL move the viewer has seen
  // land — so it holds steady through the seconds a beat spends talking before
  // its piece travels, through a variation, and through the hold and resume
  // beats on either side of one, which carry no move of their own.
  // (Recomputed per frame by nature; the scan is ~100 segments, trivial.)
  // The winner is only named once the last move has been played. Marking a
  // card gold any earlier would tell the viewer the result while they are
  // still watching the game find it.
  const lastMoveSeg = [...segments].reverse().find((s) => s.beat.move && !s.beat.branch);
  const gameOver = Boolean(
    lastMoveSeg &&
      frame >= lastMoveSeg.from +
        Math.round(((lastMoveSeg.beat.moveAtMs || 0) * fps) / 1000) +
        Math.round(fps * 0.6)
  );

  const revealed = !beat.move || frame >= moveStartFrame;
  let lastReal: Beat | null = null;
  for (const seg of segments) {
    if (seg.from > frame) break;
    const bt = seg.beat;
    // Variation moves never happened, so they must not enter the game record.
    if (!bt.move || bt.branch) continue;
    const at = seg.from + Math.round(((bt.moveAtMs || 0) * fps) / 1000);
    if (at <= frame) lastReal = bt;
  }

  // A variation shows its own card; a hold keeps its "reading the position"
  // card. Otherwise: this beat's move once it has landed, else the game so far.
  const railBeat: Beat | null =
    beat.branch || beat.kind === 'hold'
      ? beat
      : beat.move && revealed
        ? beat
        : lastReal;

  // Before the first move lands there is genuinely nothing to report.
  const panelBeat: Beat =
    railBeat ?? {...beat, move: null, tag: null, label: null, branch: false};
  const numberFrom = railBeat?.move && !railBeat.branch ? railBeat : lastReal;
  const moveNumber = numberFrom?.ply ? Math.ceil(numberFrom.ply / 2) : null;
  const shownPly = lastReal?.ply ?? null;
  const shownEvalCp = (beat.branch ? beat.evalCp : railBeat?.evalCp) ?? 0;

  // Highlight whoever played the move on screen — the side to move in the
  // position *before* it. Reading the post-move FEN lit up the opponent.
  const sideSource = railBeat ?? beat;
  const activeSide: 'white' | 'black' = (
    sideSource.move
      ? (sideSource.prevFen ?? START_FEN).split(' ')[1]
      : (sideSource.fen ?? sideSource.prevFen ?? START_FEN).split(' ')[1]
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

      {/* Players — two cards side by side filling the rail's upper half */}
      <div
        style={{
          position: 'absolute',
          left: RAIL_X,
          top: RAIL_TOP,
          width: RAIL_W,
          height: RAIL_HALF,
          display: 'flex',
          gap: 16,
        }}
      >
        <PlayerCard
          name={black}
          side="black"
          active={activeSide === 'black'}
          portrait={meta.blackPortrait}
          won={gameOver && meta.outcome?.winner === 'black'}
        />
        <PlayerCard
          name={white}
          side="white"
          active={activeSide === 'white'}
          portrait={meta.whitePortrait}
          won={gameOver && meta.outcome?.winner === 'white'}
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

      {/* Move panels — splitting the rail's lower half between them, so the
          column ends level with the board and holds no dead space. */}
      <div
        style={{
          position: 'absolute',
          left: RAIL_X,
          top: RAIL_TOP + RAIL_HALF + RAIL_GAP,
          width: RAIL_W,
          height: RAIL_HALF,
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}
      >
        <CurrentMove
          beat={panelBeat}
          moveNumber={moveNumber}
          isBlack={numberFrom?.ply ? numberFrom.ply % 2 === 0 : false}
        />
        <MoveList entries={moveEntries} currentPly={shownPly} rows={3} />
      </div>

      {/* Intro / outro card. The intro may own its whole beat, but the outro
          narrates the FINAL POSITION — why the loser stopped, what the game
          hinged on — and the viewer should be looking at that board while
          hearing it. The card fades in only for the sign-off at the end. */}
      {isCard &&
        (() => {
          const segFrom = current?.from ?? 0;
          const segDur = current?.durationInFrames ?? 1;
          // The last intro beat hands over to the quotation: the pairing has
          // already been read out by then, so leaving the same names up is
          // dead air with a picture attached.
          if (meta.quote && beat.id === lastIntroId) {
            return <QuoteCard quote={meta.quote} startFrame={segFrom} />;
          }
          const cardAt =
            beat.kind === 'outro'
              ? segFrom +
                Math.max(Math.round(segDur * 0.55), segDur - Math.round(fps * 8))
              : 0;
          if (frame < cardAt) return null;
          return (
            <TitleOverlay
              beat={beat}
              white={white}
              black={black}
              meta={meta}
              startFrame={cardAt}
            />
          );
        })()}

      {/* Subscribe prompt, twice: once the viewer is invested in the game,
          and again under the sign-off. Never during the intro cards, which
          are already carrying text. */}
      {totalFrames > subscribeFrom && (
        <SubscribeBadge
          startFrame={subscribeFrom}
          holdFrames={totalFrames - subscribeFrom}
        />
      )}

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
  /** Absolute frame the card begins fading in — 0 for the intro. */
  startFrame?: number;
}> = ({beat, white, black, meta, startFrame = 0}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [startFrame, startFrame + 18], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

  const isOutro = beat.kind === 'outro';
  // "Result 0-1" tells a viewer who won and nothing about how. The fact sheet
  // works out whether the king was mated or a hand was shaken, so say that.
  const outcome = meta.outcome;
  const subtitle = isOutro
    ? outcome?.text || (meta.result && meta.result !== '*' ? `Result  ${meta.result}` : undefined)
    : [meta.event, prettyDate(meta.date)].filter(Boolean).join('  ·  ') || undefined;

  return (
    <AbsoluteFill
      style={{
        // Denser for the outro than the intro: the move panel used to read
        // straight through the line naming how the game ended.
        background: isOutro ? 'rgba(9,12,17,0.965)' : 'rgba(9,12,17,0.90)',
        alignItems: 'center',
        justifyContent: 'center',
        opacity,
      }}
    >
      <div style={{textAlign: 'center', color: THEME.text, padding: 60}}>
        {isOutro ? (
          <>
            {outcome?.winner && (
              <div
                style={{
                  fontSize: 68,
                  lineHeight: 1.15,
                  letterSpacing: 3,
                  color: '#f2c14e',
                }}
              >
                {(outcome.winner === 'white' ? white : black).toUpperCase()} WINS
              </div>
            )}
            {/* How it ended belongs with the result, not below the sign-off. */}
            {subtitle && (
              <div style={{fontSize: 36, marginTop: 16, letterSpacing: 1.5, opacity: 0.85}}>
                {subtitle}
              </div>
            )}
            <div style={{fontSize: 46, letterSpacing: 1, marginTop: 44, opacity: 0.8}}>
              Thanks for watching
            </div>
          </>
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
        {subtitle && !isOutro && (
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
