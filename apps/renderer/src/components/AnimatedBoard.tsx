import React, { useMemo } from 'react';
import { useCurrentFrame, useVideoConfig, spring, interpolate, Easing } from 'remotion';
import { PieceSprites } from './PieceSprites';
import { Arrow } from './Arrow';

/* -------------------------------------------------------------------------- */
/*                                   Types                                    */
/* -------------------------------------------------------------------------- */

export interface BoardArrow {
  from: string;
  to: string;
  color?: string;
}

export interface BoardHighlight {
  square: string;
  color?: string;
  kind?: 'move' | 'alt' | 'danger' | 'good';
}

export interface AnimatedBoardProps {
  prevFen: string;
  fen: string;
  move?: { from: string; to: string } | null;
  moveStartFrame?: number;
  moveDurationFrames?: number;
  size?: number;
  flipped?: boolean;
  highlights?: BoardHighlight[];
  arrows?: BoardArrow[];
  checkSquare?: string | null;
  branch?: boolean;
  showCoordinates?: boolean;
  style?: React.CSSProperties;
}

/* -------------------------------------------------------------------------- */
/*                              FEN / geometry                                */
/* -------------------------------------------------------------------------- */

type PieceMap = Map<string, string>;

const FILES = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'] as const;

/** Parse the placement field of a FEN into a Map<square, pieceChar>. */
const parseFen = (fen: string): PieceMap => {
  const map: PieceMap = new Map();
  const placement = (fen ?? '').trim().split(/\s+/)[0] ?? '';
  const ranks = placement.split('/');
  for (let r = 0; r < ranks.length && r < 8; r++) {
    const row = ranks[r] ?? '';
    let file = 0;
    for (const ch of row) {
      if (ch >= '1' && ch <= '9') {
        file += parseInt(ch, 10);
      } else {
        if (file < 8) {
          const sq = `${FILES[file]}${8 - r}`;
          map.set(sq, ch);
        }
        file++;
      }
    }
  }
  return map;
};

const squareFileIndex = (sq: string) => sq.charCodeAt(0) - 97; // a -> 0
const squareRankNumber = (sq: string) => parseInt(sq.slice(1), 10); // '1'..'8'

/** Top-left pixel of a square in *display* space (accounts for flip). */
const squareToXY = (sq: string, squareSize: number, flipped: boolean) => {
  const file = squareFileIndex(sq);
  const rank = squareRankNumber(sq);
  const col = flipped ? 7 - file : file;
  const row = flipped ? rank - 1 : 8 - rank;
  return { x: col * squareSize, y: row * squareSize };
};

const isValidSquare = (sq: string | null | undefined): sq is string =>
  typeof sq === 'string' &&
  sq.length === 2 &&
  sq.charCodeAt(0) >= 97 &&
  sq.charCodeAt(0) <= 104 &&
  sq[1]! >= '1' &&
  sq[1]! <= '8';

/* -------------------------------------------------------------------------- */
/*                              Move diffing                                  */
/* -------------------------------------------------------------------------- */

interface Slide {
  piece: string; // piece as it looked in prevFen
  from: string;
  to: string;
  promotesTo?: string; // set when the arriving piece differs (promotion)
  primary: boolean;
}

interface Fading {
  piece: string;
  square: string;
}

interface Diff {
  slides: Slide[];
  captures: Fading[]; // pieces that disappear (regular capture, en passant, ...)
  appears: Fading[]; // pieces that appear without an identifiable origin
  staticSquares: string[]; // squares whose piece is untouched by the move
}

/**
 * Diff two positions. The explicit `move` is trusted as the primary slide;
 * every further difference is derived from the two maps so castling,
 * en passant and promotion all fall out of the data instead of being
 * special-cased by name.
 */
const diffPositions = (prev: PieceMap, next: PieceMap, move?: { from: string; to: string } | null): Diff => {
  const slides: Slide[] = [];
  const origins = new Set<string>();
  const dests = new Set<string>();

  if (move && isValidSquare(move.from) && isValidSquare(move.to) && move.from !== move.to) {
    const moving = prev.get(move.from);
    if (moving) {
      const arrived = next.get(move.to);
      slides.push({
        piece: moving,
        from: move.from,
        to: move.to,
        // Promotion: the piece standing on the destination afterwards is not
        // the piece that left the origin square.
        promotesTo: arrived && arrived !== moving ? arrived : undefined,
        primary: true,
      });
      origins.add(move.from);
      dests.add(move.to);
    }
  }

  // Squares that lost their piece (or had it replaced) and are not the origin
  // of a slide we already know about.
  const vacated: string[] = [];
  prev.forEach((piece, sq) => {
    if (origins.has(sq)) return;
    if (next.get(sq) !== piece) vacated.push(sq);
  });

  // Squares that gained a piece and are not the destination of a known slide.
  const appeared: string[] = [];
  next.forEach((piece, sq) => {
    if (dests.has(sq)) return;
    if (prev.get(sq) !== piece) appeared.push(sq);
  });

  // Match leftovers by identical piece char -> an extra displacement.
  // In legal chess this only ever fires for the castling rook.
  const capturedSquares: string[] = [];
  const usedAppeared = new Set<string>();

  for (const fromSq of vacated) {
    const piece = prev.get(fromSq)!;
    let best: string | null = null;
    let bestDist = Infinity;
    for (const toSq of appeared) {
      if (usedAppeared.has(toSq)) continue;
      if (next.get(toSq) !== piece) continue;
      const dx = squareFileIndex(toSq) - squareFileIndex(fromSq);
      const dy = squareRankNumber(toSq) - squareRankNumber(fromSq);
      const dist = dx * dx + dy * dy;
      if (dist < bestDist) {
        bestDist = dist;
        best = toSq;
      }
    }
    if (best) {
      usedAppeared.add(best);
      origins.add(fromSq);
      dests.add(best);
      slides.push({ piece, from: fromSq, to: best, primary: false });
    } else {
      // No home to slide to: the piece was captured on this square.
      // For en passant this is the pawn's real square, not the destination.
      capturedSquares.push(fromSq);
    }
  }

  const captures: Fading[] = capturedSquares.map((sq) => ({ piece: prev.get(sq)!, square: sq }));
  const appears: Fading[] = appeared
    .filter((sq) => !usedAppeared.has(sq))
    .map((sq) => ({ piece: next.get(sq)!, square: sq }));

  const capturedSet = new Set(capturedSquares);
  const staticSquares: string[] = [];
  prev.forEach((_piece, sq) => {
    if (origins.has(sq) || capturedSet.has(sq)) return;
    staticSquares.push(sq);
  });

  return { slides, captures, appears, staticSquares };
};

/* -------------------------------------------------------------------------- */
/*                                  Colors                                    */
/* -------------------------------------------------------------------------- */

const LIGHT_SQUARE = '#cfd8e6';
const DARK_SQUARE = '#61748f';

const HIGHLIGHT_COLORS: Record<NonNullable<BoardHighlight['kind']>, string> = {
  move: 'rgba(90,200,250,.42)',
  alt: 'rgba(178,140,255,.45)',
  danger: 'rgba(255,93,93,.45)',
  good: 'rgba(61,220,151,.42)',
};

const HIGHLIGHT_BORDERS: Record<NonNullable<BoardHighlight['kind']>, string> = {
  move: 'rgba(90,200,250,.95)',
  alt: 'rgba(178,140,255,.95)',
  danger: 'rgba(255,93,93,.95)',
  good: 'rgba(61,220,151,.95)',
};

/* -------------------------------------------------------------------------- */
/*                             Rendered piece model                           */
/* -------------------------------------------------------------------------- */

interface RenderedPiece {
  key: string;
  piece: string;
  x: number; // top-left of the *square* the piece is drawn on
  y: number;
  opacity: number;
  scale: number;
  lifted?: boolean;
}

/* -------------------------------------------------------------------------- */
/*                                 Component                                  */
/* -------------------------------------------------------------------------- */

export const AnimatedBoard: React.FC<AnimatedBoardProps> = ({
  prevFen,
  fen,
  move,
  moveStartFrame = 0,
  moveDurationFrames = 10,
  size = 760,
  flipped = false,
  highlights,
  arrows,
  checkSquare,
  branch = false,
  showCoordinates = true,
  style = {},
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const squareSize = size / 8;
  const pieceSize = squareSize * 0.88;
  const pieceOffset = (squareSize - pieceSize) / 2;

  const prevMap = useMemo(() => parseFen(prevFen), [prevFen]);
  const nextMap = useMemo(() => parseFen(fen), [fen]);
  const diff = useMemo(() => diffPositions(prevMap, nextMap, move), [prevMap, nextMap, move]);

  const duration = Math.max(1, moveDurationFrames);
  const localFrame = frame - moveStartFrame;

  // Snappy, overdamped spring: reaches the target without overshooting it.
  const rawProgress = spring({
    frame: localFrame,
    fps,
    config: { damping: 200, stiffness: 120, mass: 0.6 },
    durationInFrames: duration,
  });
  const progress = localFrame <= 0 ? 0 : localFrame >= duration ? 1 : Math.min(1, Math.max(0, rawProgress));

  const animating = localFrame > 0 && localFrame < duration && (diff.slides.length > 0 || diff.captures.length > 0 || diff.appears.length > 0);

  /* ------------------------------- pieces -------------------------------- */

  const pieces: RenderedPiece[] = useMemo(() => {
    const out: RenderedPiece[] = [];

    // Outside the animation window we render the exact source position, so
    // prevFen / fen are always shown pixel-faithfully.
    if (localFrame <= 0) {
      prevMap.forEach((piece, sq) => {
        const { x, y } = squareToXY(sq, squareSize, flipped);
        out.push({ key: `s-${sq}`, piece, x, y, opacity: 1, scale: 1 });
      });
      return out;
    }
    if (localFrame >= duration) {
      nextMap.forEach((piece, sq) => {
        const { x, y } = squareToXY(sq, squareSize, flipped);
        out.push({ key: `s-${sq}`, piece, x, y, opacity: 1, scale: 1 });
      });
      return out;
    }

    const p = progress;

    // Untouched pieces.
    for (const sq of diff.staticSquares) {
      const piece = prevMap.get(sq)!;
      const { x, y } = squareToXY(sq, squareSize, flipped);
      out.push({ key: `s-${sq}`, piece, x, y, opacity: 1, scale: 1 });
    }

    // Captured pieces: fade + shrink over the first ~60% of the motion.
    const capOpacity = interpolate(p, [0, 0.6], [1, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.quad),
    });
    const capScale = interpolate(p, [0, 0.6], [1, 0.85], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    for (const cap of diff.captures) {
      const { x, y } = squareToXY(cap.square, squareSize, flipped);
      out.push({ key: `c-${cap.square}`, piece: cap.piece, x, y, opacity: capOpacity, scale: capScale });
    }

    // Sliding pieces (mover + castling rook).
    for (const slide of diff.slides) {
      const a = squareToXY(slide.from, squareSize, flipped);
      const b = squareToXY(slide.to, squareSize, flipped);
      const x = a.x + (b.x - a.x) * p;
      const y = a.y + (b.y - a.y) * p;

      if (slide.promotesTo) {
        // Cross-fade the pawn into the promoted piece around ~70% of the slide.
        const outOpacity = interpolate(p, [0.6, 0.8], [1, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        const inOpacity = interpolate(p, [0.6, 0.8], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        const inScale = interpolate(p, [0.6, 0.8], [0.8, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        out.push({
          key: `m-${slide.from}-${slide.to}-a`,
          piece: slide.piece,
          x,
          y,
          opacity: outOpacity,
          scale: 1,
          lifted: true,
        });
        out.push({
          key: `m-${slide.from}-${slide.to}-b`,
          piece: slide.promotesTo,
          x,
          y,
          opacity: inOpacity,
          scale: inScale,
          lifted: true,
        });
      } else {
        out.push({
          key: `m-${slide.from}-${slide.to}`,
          piece: slide.piece,
          x,
          y,
          opacity: 1,
          scale: 1,
          lifted: slide.primary,
        });
      }
    }

    // Anything that materialised without a traceable origin simply fades in.
    const appearOpacity = interpolate(p, [0.4, 1], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    for (const app of diff.appears) {
      const { x, y } = squareToXY(app.square, squareSize, flipped);
      out.push({ key: `a-${app.square}`, piece: app.piece, x, y, opacity: appearOpacity, scale: 1 });
    }

    return out;
  }, [diff, prevMap, nextMap, localFrame, duration, progress, squareSize, flipped]);

  /* ------------------------------ overlays ------------------------------- */

  // Highlights and arrows never hard-cut in.
  //
  // They also must not arrive *early*. A beat can spend several seconds talking
  // before its move is played, and lighting the from/to squares during that time
  // announces the move before the narrator does. Fade them in with the piece.
  const highlightOpacity = interpolate(
    frame,
    move ? [moveStartFrame, moveStartFrame + 5] : [0, 5],
    [0, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );

  // The check only exists once the piece has landed, so the glow waits for it.
  const checkOpacity = interpolate(
    frame,
    move ? [moveStartFrame + duration, moveStartFrame + duration + 8] : [0, 8],
    [0, 1],
    {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
      easing: Easing.out(Easing.cubic),
    }
  );

  const squares = useMemo(() => {
    const cells: { key: string; x: number; y: number; light: boolean; file: string; rank: number; col: number; row: number }[] = [];
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const fileIdx = flipped ? 7 - col : col;
        const rankNum = flipped ? row + 1 : 8 - row;
        cells.push({
          key: `${FILES[fileIdx]}${rankNum}`,
          x: col * squareSize,
          y: row * squareSize,
          light: (fileIdx + rankNum) % 2 === 0,
          file: FILES[fileIdx]!,
          rank: rankNum,
          col,
          row,
        });
      }
    }
    return cells;
  }, [squareSize, flipped]);

  const coordFontSize = Math.max(10, squareSize * 0.16);

  return (
    <div
      style={{
        position: 'relative',
        width: size,
        height: size,
        overflow: 'hidden',
        boxShadow: '0 10px 40px rgba(0,0,0,0.35)',
        filter: branch ? 'saturate(0.82)' : undefined,
        ...style,
      }}
    >
      {/* ---------------------------- squares ---------------------------- */}
      <div style={{ position: 'absolute', inset: 0, width: size, height: size }}>
        {squares.map((cell) => (
          <div
            key={`sq-${cell.key}`}
            style={{
              position: 'absolute',
              left: cell.x,
              top: cell.y,
              width: squareSize,
              height: squareSize,
              backgroundColor: cell.light ? LIGHT_SQUARE : DARK_SQUARE,
            }}
          >
            {showCoordinates && cell.col === 0 && (
              <div
                style={{
                  position: 'absolute',
                  top: squareSize * 0.03,
                  left: squareSize * 0.04,
                  fontSize: coordFontSize,
                  lineHeight: 1,
                  fontWeight: 700,
                  color: cell.light ? DARK_SQUARE : LIGHT_SQUARE,
                  opacity: 0.9,
                  userSelect: 'none',
                }}
              >
                {cell.rank}
              </div>
            )}
            {showCoordinates && cell.row === 7 && (
              <div
                style={{
                  position: 'absolute',
                  bottom: squareSize * 0.03,
                  right: squareSize * 0.06,
                  fontSize: coordFontSize,
                  lineHeight: 1,
                  fontWeight: 700,
                  color: cell.light ? DARK_SQUARE : LIGHT_SQUARE,
                  opacity: 0.9,
                  userSelect: 'none',
                }}
              >
                {cell.file}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* --------------------- highlights (under pieces) ------------------ */}
      <div style={{ position: 'absolute', inset: 0, width: size, height: size, pointerEvents: 'none' }}>
        {highlights?.map((h, i) => {
          if (!isValidSquare(h.square)) return null;
          const kind = h.kind ?? 'move';
          const fill = h.color ?? HIGHLIGHT_COLORS[kind];
          const border = h.color ?? HIGHLIGHT_BORDERS[kind];
          const { x, y } = squareToXY(h.square, squareSize, flipped);
          return (
            <div
              key={`hl-${h.square}-${kind}-${i}`}
              style={{
                position: 'absolute',
                left: x,
                top: y,
                width: squareSize,
                height: squareSize,
                background: fill,
                opacity: highlightOpacity,
                borderRadius: Math.max(2, squareSize * 0.1),
                boxShadow: `inset 0 0 0 ${Math.max(2, squareSize * 0.035)}px ${border}`,
              }}
            />
          );
        })}

        {/* ------------------------ check glow ---------------------------- */}
        {isValidSquare(checkSquare) &&
          (() => {
            const { x, y } = squareToXY(checkSquare, squareSize, flipped);
            const pad = squareSize * 0.35;
            return (
              <div
                style={{
                  position: 'absolute',
                  left: x - pad,
                  top: y - pad,
                  width: squareSize + pad * 2,
                  height: squareSize + pad * 2,
                  opacity: checkOpacity,
                  background:
                    'radial-gradient(circle at 50% 50%, rgba(255,40,40,0.85) 0%, rgba(220,53,69,0.55) 32%, rgba(220,53,69,0.18) 58%, rgba(220,53,69,0) 72%)',
                }}
              />
            );
          })()}
      </div>

      {/* ----------------------------- pieces ---------------------------- */}
      <div style={{ position: 'absolute', inset: 0, width: size, height: size, pointerEvents: 'none' }}>
        {pieces.map((p) => (
          <div
            key={p.key}
            style={{
              position: 'absolute',
              left: p.x + pieceOffset,
              top: p.y + pieceOffset,
              width: pieceSize,
              height: pieceSize,
              opacity: p.opacity,
              transform: p.scale === 1 ? undefined : `scale(${p.scale})`,
              transformOrigin: 'center center',
              filter: p.lifted && animating ? 'drop-shadow(0 6px 10px rgba(0,0,0,0.35))' : undefined,
              willChange: 'transform, opacity',
            }}
          >
            <PieceSprites piece={p.piece} size={pieceSize} />
          </div>
        ))}
      </div>

      {/* ------------------- arrows (above the pieces) ------------------- */}
      {arrows && arrows.length > 0 && (
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: 0,
            width: size,
            height: size,
            pointerEvents: 'none',
            // Arrow.tsx computes its own unflipped coordinates; a 180° turn of
            // the whole layer maps every square onto its flipped counterpart.
            transform: flipped ? 'rotate(180deg)' : undefined,
          }}
        >
          {arrows.map((a, i) =>
            isValidSquare(a.from) && isValidSquare(a.to) ? (
              <Arrow
                key={`ar-${a.from}-${a.to}-${i}`}
                from={a.from}
                to={a.to}
                color={a.color ?? '#5ac8fa'}
                boardSize={size}
                squareSize={squareSize}
                // An arrow describes the position the move creates, so it is
                // drawn once the piece has arrived — never before it.
                delay={move ? moveStartFrame + duration : 0}
                duration={6}
              />
            ) : null
          )}
        </div>
      )}

      {/* --------------------------- branch chrome ----------------------- */}
      {branch && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            width: size,
            height: size,
            pointerEvents: 'none',
            background: 'rgba(10,8,20,0.18)',
            boxShadow: 'inset 0 0 0 3px #b28cff',
          }}
        />
      )}
    </div>
  );
};

export default AnimatedBoard;
