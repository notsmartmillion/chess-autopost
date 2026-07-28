import React, {useMemo} from 'react';
import {Img, staticFile} from 'remotion';

interface PieceSpritesProps {
  piece: string;
  size: number;
}

/**
 * A single chess piece.
 *
 * Uses Remotion's <Img> rather than a plain <img>: Remotion delays capturing a
 * frame until every <Img> has finished loading. With a bare <img> the renderer
 * can screenshot before the SVG has decoded, which is what made pieces flicker
 * during and after each move.
 */
export const PieceSprites: React.FC<PieceSpritesProps> = ({piece, size}) => {
  // Merida SVGs live in apps/renderer/public/pieces/merida/{w,b}{k,q,r,b,n,p}.svg
  const spritePath = useMemo(() => {
    const isWhite = piece === piece.toUpperCase();
    const code = piece.toLowerCase();
    return staticFile(`pieces/merida/${isWhite ? 'w' : 'b'}${code}.svg`);
  }, [piece]);

  return (
    <Img
      src={spritePath}
      alt={piece}
      style={{
        display: 'block',
        width: size,
        height: size,
        userSelect: 'none',
        pointerEvents: 'none',
      }}
    />
  );
};
