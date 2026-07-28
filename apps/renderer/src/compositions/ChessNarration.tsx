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
  EvalReadout,
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
const RAIL_X = BOARD_X + BOARD + 72;
const RAIL_W = 1920 - RAIL_X - 96;
const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

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
  const channel = meta.channel ?? 'Quiet Chess';

  const sideToMove: 'white' | 'black' =
    (beat.fen ?? beat.prevFen ?? START_FEN).split(' ')[1] === 'b' ? 'black' : 'white';

  // Board props come from the current beat, but the board itself is mounted
  // ONCE for the whole video. Remounting it per beat destroyed and recreated
  // all 32 piece sprites at every boundary, which is what made the pieces
  // flicker. moveStartFrame is therefore absolute, not sequence-relative.
  const boardFen = beat.fen ?? beat.prevFen ?? START_FEN;
  const boardPrevFen = beat.prevFen ?? boardFen;
  const moveStartFrame =
    (current?.from ?? 0) + Math.round(((beat.moveAtMs || 0) * fps) / 1000);

  const moveNumber = beat.ply ? Math.ceil(beat.ply / 2) : null;

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
          highlights={beat.highlights}
          arrows={beat.arrows}
          checkSquare={beat.checkSquare}
          branch={beat.branch}
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

      {/* Analysis rail */}
      <div
        style={{
          position: 'absolute',
          left: RAIL_X,
          top: BOARD_Y,
          width: RAIL_W,
          height: BOARD,
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}
      >
        <div
          style={{
            background: THEME.panel,
            border: `1px solid ${THEME.panelEdge}`,
            borderRadius: 14,
            padding: 14,
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
          }}
        >
          <PlayerRow name={black} side="black" active={sideToMove === 'black'} />
          <PlayerRow name={white} side="white" active={sideToMove === 'white'} />
        </div>

        <EvalReadout cp={beat.evalCp} changeKey={beat.id} />
        <CurrentMove beat={beat} moveNumber={moveNumber} isBlack={beat.ply ? beat.ply % 2 === 0 : false} />
        <MoveList entries={moveEntries} currentPly={beat.ply} rows={6} />
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
