import React from 'react';

interface PieceSpritesProps {
  piece: string;
  size: number;
}

export const PieceSprites: React.FC<PieceSpritesProps> = ({ piece, size }) => {
  // Unicode chess symbols
  const pieceSymbols: Record<string, string> = {
    'K': '♔', // White King
    'Q': '♕', // White Queen
    'R': '♖', // White Rook
    'B': '♗', // White Bishop
    'N': '♘', // White Knight
    'P': '♙', // White Pawn
    'k': '♚', // Black King
    'q': '♛', // Black Queen
    'r': '♜', // Black Rook
    'b': '♝', // Black Bishop
    'n': '♞', // Black Knight
    'p': '♟', // Black Pawn
  };

  const symbol = pieceSymbols[piece] || piece;
  const isWhite = piece === piece.toUpperCase();

  return (
    <div
      style={{
        fontSize: size,
        color: isWhite ? '#ffffff' : '#000000',
        textShadow: isWhite 
          ? '1px 1px 2px rgba(0,0,0,0.8)' 
          : '1px 1px 2px rgba(255,255,255,0.8)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: size,
        height: size,
        userSelect: 'none',
      }}
    >
      {symbol}
    </div>
  );
};
