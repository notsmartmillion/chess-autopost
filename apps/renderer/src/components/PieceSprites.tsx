import React, {useMemo, useState} from 'react';
import {staticFile} from 'remotion';

interface PieceSpritesProps {
  piece: string;
  size: number;
}

export const PieceSprites: React.FC<PieceSpritesProps> = ({ piece, size }) => {
  // Preferred theme: Merida SVGs placed under apps/renderer/public/pieces/merida/
  // Filenames: wk.svg, wq.svg, wr.svg, wb.svg, wn.svg, wp.svg, bk.svg, bq.svg, br.svg, bb.svg, bn.svg, bp.svg
  const [fallback, setFallback] = useState(false);

  const spritePath = useMemo(() => {
    const isWhite = piece === piece.toUpperCase();
    const code = piece.toLowerCase(); // k,q,r,b,n,p
    const name = `${isWhite ? 'w' : 'b'}${code}`;
    // Remotion serves files from apps/renderer/public under the "/public" prefix via staticFile()
    return staticFile(`pieces/merida/${name}.svg`);
  }, [piece]);

  // Unicode fallback if SVG missing
  const unicode: Record<string, string> = {
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
  };
  const sym = piece === piece.toUpperCase()
    ? { 'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙' }[piece] || piece
    : unicode[piece] || piece;

  if (fallback) {
    const isWhite = piece === piece.toUpperCase();
    return (
      <div style={{
        fontSize: size,
        color: isWhite ? '#ffffff' : '#000000',
        textShadow: isWhite ? '1px 1px 2px rgba(0,0,0,0.8)' : '1px 1px 2px rgba(255,255,255,0.8)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        width: size, height: size, userSelect: 'none',
      }}>{sym}</div>
    );
  }

  return (
    <img
      src={spritePath}
      alt={piece}
      width={size}
      height={size}
      style={{
        display: 'block',
        width: size,
        height: size,
        imageRendering: 'crisp-edges',
        userSelect: 'none',
        pointerEvents: 'none',
      }}
      onError={() => setFallback(true)}
    />
  );
};
