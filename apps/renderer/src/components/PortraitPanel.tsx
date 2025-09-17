import React from 'react';

interface PortraitPanelProps {
  whitePlayer: string;
  blackPlayer: string;
  whitePortrait?: string;
  blackPortrait?: string;
  currentPlayer?: 'white' | 'black';
  style?: React.CSSProperties;
}

export const PortraitPanel: React.FC<PortraitPanelProps> = ({
  whitePlayer,
  blackPlayer,
  whitePortrait,
  blackPortrait,
  currentPlayer,
  style = {},
}) => {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '20px',
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        borderRadius: '10px',
        ...style,
      }}
    >
      {/* Black player (left) */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          opacity: currentPlayer === 'black' ? 1 : 0.6,
          transform: currentPlayer === 'black' ? 'scale(1.05)' : 'scale(1)',
          transition: 'all 0.3s ease-in-out',
        }}
      >
        <div
          style={{
            width: 80,
            height: 80,
            borderRadius: '50%',
            backgroundColor: '#2c2c2c',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 10,
            border: currentPlayer === 'black' ? '3px solid #ff6b6b' : '3px solid transparent',
            overflow: 'hidden',
          }}
        >
          {blackPortrait ? (
            <img
              src={blackPortrait}
              alt={blackPlayer}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
              }}
            />
          ) : (
            <div
              style={{
                fontSize: 24,
                color: '#fff',
                fontWeight: 'bold',
              }}
            >
              ♚
            </div>
          )}
        </div>
        <div
          style={{
            color: '#fff',
            fontSize: 16,
            fontWeight: 'bold',
            textAlign: 'center',
            maxWidth: 120,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {blackPlayer}
        </div>
        <div
          style={{
            color: '#ccc',
            fontSize: 12,
            textAlign: 'center',
          }}
        >
          Black
        </div>
      </div>
      
      {/* VS indicator */}
      <div
        style={{
          color: '#fff',
          fontSize: 18,
          fontWeight: 'bold',
          margin: '0 20px',
        }}
      >
        VS
      </div>
      
      {/* White player (right) */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          opacity: currentPlayer === 'white' ? 1 : 0.6,
          transform: currentPlayer === 'white' ? 'scale(1.05)' : 'scale(1)',
          transition: 'all 0.3s ease-in-out',
        }}
      >
        <div
          style={{
            width: 80,
            height: 80,
            borderRadius: '50%',
            backgroundColor: '#2c2c2c',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 10,
            border: currentPlayer === 'white' ? '3px solid #ff6b6b' : '3px solid transparent',
            overflow: 'hidden',
          }}
        >
          {whitePortrait ? (
            <img
              src={whitePortrait}
              alt={whitePlayer}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'cover',
              }}
            />
          ) : (
            <div
              style={{
                fontSize: 24,
                color: '#fff',
                fontWeight: 'bold',
              }}
            >
              ♔
            </div>
          )}
        </div>
        <div
          style={{
            color: '#fff',
            fontSize: 16,
            fontWeight: 'bold',
            textAlign: 'center',
            maxWidth: 120,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {whitePlayer}
        </div>
        <div
          style={{
            color: '#ccc',
            fontSize: 12,
            textAlign: 'center',
          }}
        >
          White
        </div>
      </div>
    </div>
  );
};
