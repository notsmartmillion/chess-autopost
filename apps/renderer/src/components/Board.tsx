import React from 'react';
import { useCurrentFrame, useVideoConfig } from 'remotion';
import { PieceSprites } from './PieceSprites';

interface BoardProps {
  fen: string;
  size?: number;
  showCoordinates?: boolean;
  style?: React.CSSProperties;
}

export const Board: React.FC<BoardProps> = ({ 
  fen, 
  size = 400, 
  showCoordinates = true,
  style = {}
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  
  // Parse FEN
  const [position, activeColor, castling, enPassant, halfmove, fullmove] = fen.split(' ');
  
  // Convert position to 2D array
  const board = Array(8).fill(null).map(() => Array(8).fill(null));
  let rank = 0;
  let file = 0;
  
  for (const char of position) {
    if (char === '/') {
      rank++;
      file = 0;
    } else if (char >= '1' && char <= '8') {
      file += parseInt(char);
    } else {
      board[rank][file] = char;
      file++;
    }
  }
  
  const squareSize = size / 8;
  
  return (
    <div 
      style={{
        width: size,
        height: size,
        position: 'relative',
        ...style
      }}
    >
      {/* Board squares */}
      {Array.from({ length: 8 }, (_, rank) =>
        Array.from({ length: 8 }, (_, file) => {
          const isLight = (rank + file) % 2 === 0;
          const squareName = String.fromCharCode(97 + file) + (8 - rank);
          
          return (
            <div
              key={`${rank}-${file}`}
              style={{
                position: 'absolute',
                left: file * squareSize,
                top: rank * squareSize,
                width: squareSize,
                height: squareSize,
                backgroundColor: isLight ? '#f0d9b5' : '#b58863',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {/* Coordinates */}
              {showCoordinates && (
                <>
                  {file === 0 && (
                    <div
                      style={{
                        position: 'absolute',
                        top: 2,
                        left: 2,
                        fontSize: squareSize * 0.15,
                        color: isLight ? '#b58863' : '#f0d9b5',
                        fontWeight: 'bold',
                      }}
                    >
                      {8 - rank}
                    </div>
                  )}
                  {rank === 7 && (
                    <div
                      style={{
                        position: 'absolute',
                        bottom: 2,
                        right: 2,
                        fontSize: squareSize * 0.15,
                        color: isLight ? '#b58863' : '#f0d9b5',
                        fontWeight: 'bold',
                      }}
                    >
                      {String.fromCharCode(97 + file)}
                    </div>
                  )}
                </>
              )}
              
              {/* Piece */}
              {board[rank][file] && (
                <PieceSprites
                  piece={board[rank][file]}
                  size={squareSize * 0.8}
                />
              )}
            </div>
          );
        })
      )}
    </div>
  );
};
