import React, {useMemo} from 'react';
import { useCurrentFrame } from 'remotion';
import { Attacked } from '../types/timeline';

interface HeatmapProps {
  attacked: Attacked;
  prevAttacked?: Attacked;
  fen: string; // to know which squares contain pieces
  mover: 'white' | 'black'; // side that just moved
  boardSize?: number;
  squareSize?: number;
}

export const Heatmap: React.FC<HeatmapProps> = ({
  attacked,
  prevAttacked,
  fen,
  mover,
  boardSize = 400,
  squareSize = 50,
}) => {
  const frame = useCurrentFrame();
  
  // Parse FEN to see which squares have pieces
  const { occupiedAll, occupiedWhite, occupiedBlack } = useMemo(() => {
    const pos = fen.split(' ')[0] || '';
    const occ = new Set<string>();
    const occW = new Set<string>();
    const occB = new Set<string>();
    let rank = 0, file = 0;
    for (const ch of pos) {
      if (ch === '/') { rank++; file = 0; continue; }
      if (ch >= '1' && ch <= '8') { file += parseInt(ch); continue; }
      const sq = String.fromCharCode(97 + file) + (8 - rank);
      occ.add(sq);
      if (ch === ch.toUpperCase()) occW.add(sq); else occB.add(sq);
      file++;
    }
    return { occupiedAll: occ, occupiedWhite: occW, occupiedBlack: occB };
  }, [fen]);

  // Convert algebraic notation to coordinates
  const getSquareCoords = (square: string) => {
    const file = square.charCodeAt(0) - 97; // a=0, b=1, etc.
    const rank = 8 - parseInt(square[1]); // 8=0, 7=1, etc.
    return {
      x: file * squareSize,
      y: rank * squareSize,
    };
  };
  
  // No internal animation; parent controls opacity via wrapping style.
  const globalOpacity = 1;
  
  // Build sets
  const whiteAttacks = new Set((attacked.white || []).filter((sq) => /^[a-h][1-8]$/.test(sq)));
  const blackAttacks = new Set((attacked.black || []).filter((sq) => /^[a-h][1-8]$/.test(sq)));

  const prevWhite = new Set((prevAttacked?.white || []).filter((sq) => /^[a-h][1-8]$/.test(sq)));
  const prevBlack = new Set((prevAttacked?.black || []).filter((sq) => /^[a-h][1-8]$/.test(sq)));

  // Newly attacked squares compared to previous frame
  const newly = new Set<string>();
  if (mover === 'white') {
    for (const sq of whiteAttacks) if (!prevWhite.has(sq)) newly.add(sq);
  } else {
    for (const sq of blackAttacks) if (!prevBlack.has(sq)) newly.add(sq);
  }

  // Select a single most-relevant threatened square: prefer center and only opponent-occupied
  const candidates = Array.from(newly).filter((sq) =>
    mover === 'white' ? occupiedBlack.has(sq) : occupiedWhite.has(sq)
  );
  const scoreSq = (sq: string) => {
    const file = sq.charCodeAt(0) - 97; // 0..7
    const center = Math.abs(3.5 - file);
    return -center; // closer to center is better
  };
  const top = candidates.sort((a, b) => scoreSq(b) - scoreSq(a))[0];
  const threatenedRed = top ? [top] : [];

  // Defended: if the threatened square is also defended by the same color, show blue fill under it
  const defendedBlue = threatenedRed.filter((sq) => mover === 'white' ? blackAttacks.has(sq) : whiteAttacks.has(sq));
  
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: boardSize,
        height: boardSize,
        pointerEvents: 'none',
      }}
    >
      {defendedBlue.map((sq, i) => {
        const c = getSquareCoords(sq);
        return (
          <div
            key={`def-${sq}-${i}`}
            style={{
              position: 'absolute',
              left: c.x,
              top: c.y,
              width: squareSize,
              height: squareSize,
              backgroundColor: 'rgba(66, 135, 245, 0.25)',
              opacity: globalOpacity,
            }}
          />
        );
      })}
      {threatenedRed.map((sq, i) => {
        const c = getSquareCoords(sq);
        return (
          <div
            key={`thr-${sq}-${i}`}
            style={{
              position: 'absolute',
              left: c.x,
              top: c.y,
              width: squareSize,
              height: squareSize,
              boxShadow: 'inset 0 0 0 3px rgba(255, 99, 71, 0.8)',
              opacity: globalOpacity,
            }}
          />
        );
      })}
    </div>
  );
};
