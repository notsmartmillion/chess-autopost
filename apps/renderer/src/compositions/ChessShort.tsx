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
import {EvalColumn, THEME} from '../components/AnalysisRail';
import type {Beat, Script} from '../types/script';

export type ChessShortProps = {
  script?: Script | null;
  /** Where the beat clips live inside /public. Deliberately NOT /audio —
   *  that directory belongs to the long-form build, which may be running. */
  audioBase?: string;
  [key: string]: unknown;
};

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

const BADGE: Record<string, {symbol: string; color: string}> = {
  brilliant: {symbol: '!!', color: '#f2c14e'},
  great: {symbol: '!', color: '#f2c14e'},
  best: {symbol: '★', color: THEME.accent},
  mistake: {symbol: '?', color: THEME.bad},
  blunder: {symbol: '??', color: THEME.bad},
};

/**
 * The vertical cut: one key moment, its refutation, and a pointer to the
 * full game. Same beat model, same board, same audio discipline as the
 * landscape composition — the entire Short is one continuous TTS take, so
 * there are no seams for the voice to trip over.
 *
 * Frame 0 IS the thumbnail on the Shorts feed, so the first frame is the
 * hook card with the board already in position — never a fade from black.
 */
export const ChessShort: React.FC<ChessShortProps> = ({
  script,
  audioBase = '/audio_short',
}) => {
  const {fps} = useVideoConfig();
  const frame = useCurrentFrame();

  const beats = script?.beats ?? [];
  const meta = script?.meta ?? {};

  const segments = useMemo(() => {
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
  const beat: Beat | undefined = current?.beat;

  const white = meta.whiteFull ?? meta.white ?? 'White';
  const black = meta.blackFull ?? meta.black ?? 'Black';
  const hook = (meta as any).shortHook ?? 'One move changed everything.';

  // Board mounted ONCE, driven by the current beat — remounting per beat
  // recreates all 32 sprites and the pieces visibly flicker (the landscape
  // composition learned this the hard way).
  const boardFen = beat?.fen ?? beat?.prevFen ?? START_FEN;
  const boardPrevFen = beat?.prevFen ?? boardFen;
  const moveStartFrame =
    (current?.from ?? 0) +
    Math.round((((beat?.moveAtMs as number) || 0) * fps) / 1000);

  // Nothing names the move before the piece moves. The long-form learned
  // this twice — first the move panel, then the variation announcement — and
  // the first Short shipped the same spoiler: "Bd8 ★" on screen while the
  // bishop still stood on b6. Everything below gates on the same reveal.
  const revealed = !beat?.move || frame >= moveStartFrame;

  const badge = revealed
    ? beat?.move && !beat.branch && beat.tag && BADGE[beat.tag]
      ? {square: beat.move.to, ...BADGE[beat.tag]}
      : beat?.move && beat.branch
        ? {square: beat.move.to, ...BADGE.best}
        : null
    : null;

  // The eval a viewer may see: the last position whose move has actually
  // landed. Jumping AT the reveal is the drama; jumping before it is a spoiler.
  const shownEvalCp = useMemo(() => {
    let cp: number | null = null;
    for (const seg of segments) {
      if (seg.from > frame) break;
      const b = seg.beat;
      const at = seg.from + Math.round((((b.moveAtMs as number) || 0) * fps) / 1000);
      if (!b.move || at <= frame) {
        if (typeof b.evalCp === 'number') cp = b.evalCp;
      }
    }
    return cp ?? 0;
  }, [segments, frame, fps]);

  // THE PHONE CROPS THE SIDES. A 9:16 video on a 19.5:9-20:9 screen is
  // scaled to fill the height, cutting ~108 px per edge at the tightest
  // common aspect — the first posted Short lost its a-file and its whole
  // eval column to exactly this, seen on a real phone. Everything that
  // matters lives inside that safe area, with room to spare because the
  // eval column's NUMBER is wider than the column itself. YouTube's own UI
  // overlays the top ~110 px and the bottom quarter, so text clears both.
  //
  // ONE CENTRE LINE. The board and its eval column are centred as a single
  // unit, and every text row centres on the same axis. Laying the board out
  // from a left margin instead put its centre 20 px off the frame's, so the
  // names and the wordmark hung visibly right of the board they belong to.
  const BOARD = 760;
  const EVAL_W = 28;
  const EVAL_GAP = 12;
  const GROUP_W = BOARD + EVAL_GAP + EVAL_W;
  const GROUP_X = Math.round((1080 - GROUP_W) / 2);
  const SAFE_X = GROUP_X;
  const BOARD_TOP = 360;
  const isCta = beat?.kind === 'outro';
  const inVariation = Boolean(beat?.branch);

  return (
    <AbsoluteFill
      style={{
        background: THEME.bg0,
        fontFamily: 'Inter, "Segoe UI", system-ui, sans-serif',
      }}
    >
      {/* Hook band. Present from frame 0 — it is the feed thumbnail. Starts
          below the player UI's top overlay and stays inside the side-crop
          safe area. */}
      <div
        style={{
          position: 'absolute',
          top: 130,
          left: SAFE_X,
          right: SAFE_X,
          height: 210,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: 58,
            fontWeight: 800,
            lineHeight: 1.12,
            color: THEME.text,
            letterSpacing: -0.5,
          }}
        >
          {hook}
        </div>
      </div>

      {/* Board, filling the safe width beside its eval column. */}
      <div style={{position: 'absolute', top: BOARD_TOP, left: GROUP_X, width: BOARD, height: BOARD}}>
        <AnimatedBoard
          prevFen={boardPrevFen}
          fen={boardFen}
          move={beat?.move ? {from: beat.move.from, to: beat.move.to} : null}
          size={BOARD}
          highlights={beat?.highlights ?? []}
          arrows={beat?.arrows ?? []}
          checkSquare={beat?.checkSquare ?? null}
          moveStartFrame={moveStartFrame}
          badge={badge}
          showCoordinates={false}
        />
        {inVariation && (
          <div
            style={{
              position: 'absolute',
              top: 14,
              left: 14,
              padding: '8px 18px',
              borderRadius: 10,
              background: `${THEME.bg0}d9`,
              border: `2px solid ${THEME.alt}`,
              color: THEME.text,
              fontSize: 34,
              fontWeight: 700,
            }}
          >
            {/* The ribbon may say a branch has begun; the move's NAME waits
                for the piece. "Better was Bd8" before Bd8 moves is the same
                spoiler the long-form once shipped in its announcements. */}
            {revealed
              ? (beat?.label ?? 'What should have happened')
              : 'What should have happened'}
          </div>
        )}
      </div>

      {/* Eval column: the long-form's own component, vertical beside the
          board, driven by revealed positions only — the bar jumping AT the
          reveal is the drama; jumping before it was the spoiler. */}
      <div
        style={{
          position: 'absolute',
          top: BOARD_TOP,
          left: GROUP_X + BOARD + EVAL_GAP,
          width: EVAL_W,
          height: BOARD,
        }}
      >
        <EvalColumn cp={shownEvalCp} height={BOARD} width={EVAL_W} />
      </div>

      {/* Rail strip: who is playing, and the move being judged. */}
      <div
        style={{
          position: 'absolute',
          top: BOARD_TOP + BOARD + 30,
          left: SAFE_X,
          right: SAFE_X,
          display: 'flex',
          flexDirection: 'column',
          gap: 18,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'baseline',
            gap: 16,
            color: THEME.text,
            fontSize: 40,
            fontWeight: 600,
          }}
        >
          <span>{white}</span>
          <span style={{color: THEME.muted, fontSize: 28}}>vs</span>
          <span>{black}</span>
        </div>
        {/* The move row's SPACE is permanent; only its content waits for the
            reveal. YouTube samples an arbitrary frame as the Shorts feed
            thumbnail, and when this row popped in and out of the layout,
            every Short's card came out looking different — the channel grid
            read as five different designs. */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: 14,
            height: 54,
            fontSize: 44,
            fontWeight: 800,
            color: badge?.color ?? THEME.text,
          }}
        >
          {beat?.move && revealed && (
            <>
              <span>{beat.move.san}</span>
              {badge && <span>{badge.symbol}</span>}
            </>
          )}
        </div>
      </div>

      {/* Channel mark: the banner's own wordmark rather than the channel name
          set in the video's font, so a Short carries the same identity a
          viewer sees on the channel page. Cropped from the banner and
          feathered at the edges, so it melts into the background instead of
          sitting in a visible rectangle.

          Positioned from the TOP so it stays above YouTube's bottom overlay
          (caption, channel row and share bar cover roughly the last quarter
          of the screen — the first posted Short's CTA was hidden under
          them). */}
      <div
        style={{
          position: 'absolute',
          top: BOARD_TOP + BOARD + 150,
          left: 0,
          right: 0,
          display: 'flex',
          justifyContent: 'center',
          opacity: 0.92,
        }}
      >
        <Img
          src={staticFile('brand/wordmark.png')}
          style={{width: 520, height: 'auto'}}
        />
      </div>

      {/* CTA line: fades up during the outro, under the mark. */}
      <div
        style={{
          position: 'absolute',
          top: BOARD_TOP + BOARD + 320,
          left: SAFE_X,
          right: SAFE_X,
          textAlign: 'center',
          opacity: isCta
            ? interpolate(
                frame,
                [current?.from ?? 0, (current?.from ?? 0) + 12],
                [0, 1],
                {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
              )
            : 0,
        }}
      >
        <div style={{fontSize: 34, color: THEME.muted}}>
          Full game on the channel
        </div>
      </div>

      {/* Narration audio, one clip per beat — the same discipline as the
          landscape composition. */}
      {segments.map(({beat: b, from, durationInFrames}) =>
        b.audioFile ? (
          <Sequence
            key={`audio-${b.id}`}
            from={from}
            durationInFrames={durationInFrames}
            layout="none"
          >
            <Audio
              src={staticFile(`${audioBase.replace(/^\//, '')}/${b.audioFile}`)}
            />
          </Sequence>
        ) : null
      )}
    </AbsoluteFill>
  );
};
