import React, {useMemo} from 'react';
import {
  AbsoluteFill,
  Audio,
  Img,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {AnimatedBoard} from '../components/AnimatedBoard';
import {THEME} from '../components/AnalysisRail';

/**
 * The no-narration cut: the bare game, one move every few seconds, for the
 * slow-play channel. Deliberately the opposite of the narrated composition —
 * no eval bar, no arrows, no badges, no story. A board, two names, and the
 * pieces each side has taken, exactly the furniture of watching a game
 * replayed on a phone.
 *
 * Everything arrives via --props (see build_slowplay.py). This composition
 * must never read public/script.json — that file belongs to the narrated
 * build, which may be rendering at the same time on another channel's clock.
 */

export type SlowPly = {
  san: string;
  from: string;
  to: string;
  prevFen: string;
  fen: string;
  checkSquare?: string | null;
  isCapture?: boolean;
  /** Black pieces White has taken so far, as piece letters ('P','N',...). */
  capturedByWhite: string[];
  /** White pieces Black has taken so far. */
  capturedByBlack: string[];
  /** Material balance in pawns, positive = White ahead. */
  matDiff: number;
};

export type SlowPlayGame = {
  white: string;
  black: string;
  whiteElo?: string | null;
  blackElo?: string | null;
  result?: string | null;
  event?: string | null;
  startFen: string;
  plies: SlowPly[];
};

export type ChessSlowPlayProps = {
  game?: SlowPlayGame | null;
  secondsPerMove?: number;
  introSeconds?: number;
  outroSeconds?: number;
  [key: string]: unknown;
};

export const SLOWPLAY_DEFAULTS = {secondsPerMove: 3, introSeconds: 3, outroSeconds: 6};

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

/** Captured sprites read best grouped by kind, heaviest last (chess.com's order). */
const VALUE: Record<string, number> = {P: 1, N: 3, B: 3, R: 5, Q: 9};
const sortCaptures = (pieces: string[]) =>
  [...pieces].sort((a, b) => (VALUE[a] ?? 0) - (VALUE[b] ?? 0));

const RESULT_LINE: Record<string, string> = {
  '1-0': 'White wins',
  '0-1': 'Black wins',
  '1/2-1/2': 'Draw',
};

const CapturedRow: React.FC<{pieces: string[]; ofColor: 'w' | 'b'; lead: number}> = ({
  pieces,
  ofColor,
  lead,
}) => (
  // The tray sits on its own lighter chip: black sprites vanished straight
  // into the page background, and a backing only where the pieces are beats
  // lightening the whole frame.
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 2,
      minHeight: 44,
      padding: pieces.length ? '3px 12px' : 0,
      borderRadius: 10,
      background: pieces.length ? 'rgba(230, 235, 242, 0.16)' : 'transparent',
    }}
  >
    {sortCaptures(pieces).map((p, i) => (
      <Img
        key={`${p}-${i}`}
        src={staticFile(`pieces/merida/${ofColor}${p.toLowerCase()}.svg`)}
        style={{width: 36, height: 36, marginLeft: i > 0 ? -12 : 0}}
      />
    ))}
    {lead > 0 && (
      <span style={{color: THEME.text, fontSize: 26, fontWeight: 600, marginLeft: 6}}>
        +{lead}
      </span>
    )}
  </div>
);

export const ChessSlowPlay: React.FC<ChessSlowPlayProps> = ({
  game,
  secondsPerMove = SLOWPLAY_DEFAULTS.secondsPerMove,
  introSeconds = SLOWPLAY_DEFAULTS.introSeconds,
  outroSeconds = SLOWPLAY_DEFAULTS.outroSeconds,
}) => {
  const {fps, durationInFrames} = useVideoConfig();
  const frame = useCurrentFrame();

  const plies = game?.plies ?? [];
  const introFrames = Math.round(introSeconds * fps);
  const moveFrames = Math.max(1, Math.round(secondsPerMove * fps));

  // The ply whose move has begun; -1 during the intro hold.
  const currentIndex = useMemo(() => {
    const i = Math.floor((frame - introFrames) / moveFrames);
    return Math.max(-1, Math.min(i, plies.length - 1));
  }, [frame, introFrames, moveFrames, plies.length]);

  const ply = currentIndex >= 0 ? plies[currentIndex] : null;
  const moveStartFrame = introFrames + currentIndex * moveFrames;

  const captures = ply ?? {capturedByWhite: [], capturedByBlack: [], matDiff: 0};
  const whiteLead = Math.max(0, captures.matDiff);
  const blackLead = Math.max(0, -captures.matDiff);

  const BOARD = 880;
  const BOARD_X = Math.round((1920 - BOARD) / 2);
  const BOARD_Y = Math.round((1080 - BOARD) / 2);

  const gameOverAt = introFrames + plies.length * moveFrames;
  const showResult = frame >= gameOverAt && Boolean(game?.result && RESULT_LINE[game.result]);
  const resultOpacity = interpolate(
    frame,
    [gameOverAt, gameOverAt + Math.round(0.5 * fps)],
    [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
  );

  const nameRow = (
    name: string,
    elo: string | null | undefined,
    pieces: string[],
    ofColor: 'w' | 'b',
    lead: number
  ) => (
    <div
      style={{
        position: 'absolute',
        left: BOARD_X,
        width: BOARD,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        color: THEME.text,
        fontSize: 34,
        fontWeight: 600,
      }}
    >
      <span>
        {name}
        {elo ? <span style={{color: THEME.muted, fontWeight: 400}}> ({elo})</span> : null}
      </span>
      <CapturedRow pieces={pieces} ofColor={ofColor} lead={lead} />
    </div>
  );

  return (
    <AbsoluteFill
      style={{
        // Lighter than the narrated build's bg0 on purpose: black captured
        // sprites were unreadable against #0b0e13.
        background: '#1d2430',
        fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif',
      }}
    >
      {/* Black on top, White below — the seat the viewer occupies. Captured
          sprites are the OPPONENT's colour: next to Black's name go the white
          pieces Black has taken. */}
      <div style={{position: 'absolute', top: BOARD_Y - 62, left: 0, right: 0}}>
        {nameRow(game?.black ?? 'Black', game?.blackElo, captures.capturedByBlack, 'w', blackLead)}
      </div>

      <div style={{position: 'absolute', top: BOARD_Y, left: BOARD_X, width: BOARD, height: BOARD}}>
        <AnimatedBoard
          prevFen={ply?.prevFen ?? game?.startFen ?? START_FEN}
          fen={ply?.fen ?? game?.startFen ?? START_FEN}
          move={ply ? {from: ply.from, to: ply.to} : null}
          moveStartFrame={moveStartFrame}
          size={BOARD}
          checkSquare={ply?.checkSquare ?? null}
          showCoordinates
        />
      </div>

      <div style={{position: 'absolute', top: BOARD_Y + BOARD + 26, left: 0, right: 0}}>
        {nameRow(game?.white ?? 'White', game?.whiteElo, captures.capturedByWhite, 'b', whiteLead)}
      </div>

      {/* The move sounds: a knock when a piece lands, the heavier two-contact
          knock when it lands on another. Timed to moveStartFrame, the same
          instant the animation begins. */}
      {plies.map((p, i) => (
        <Sequence
          key={`sfx-${i}`}
          from={introFrames + i * moveFrames}
          durationInFrames={Math.min(moveFrames, Math.round(0.4 * fps))}
          layout="none"
        >
          <Audio src={staticFile(p.isCapture ? 'sfx/capture.wav' : 'sfx/move.wav')} />
        </Sequence>
      ))}

      {/* The game's end: the result, quietly, over the final position. */}
      {showResult && (
        <div
          style={{
            position: 'absolute',
            top: BOARD_Y + BOARD / 2 - 60,
            left: 0,
            right: 0,
            textAlign: 'center',
            opacity: resultOpacity,
          }}
        >
          <div
            style={{
              display: 'inline-block',
              padding: '22px 54px',
              borderRadius: 16,
              background: `${THEME.bg0}e6`,
              border: `2px solid ${THEME.panelEdge}`,
            }}
          >
            <div style={{fontSize: 62, fontWeight: 800, color: THEME.text}}>
              {game?.result}
            </div>
            <div style={{fontSize: 30, color: THEME.muted, marginTop: 6}}>
              {RESULT_LINE[game?.result ?? ''] ?? ''}
            </div>
          </div>
        </div>
      )}
    </AbsoluteFill>
  );
};
