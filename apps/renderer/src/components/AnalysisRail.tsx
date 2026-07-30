import React from 'react';
import {Img, interpolate, Easing, staticFile, useCurrentFrame} from 'remotion';
import type {Beat} from '../types/script';

export const THEME = {
  bg0: '#0b0e13',
  panel: '#141922',
  panelEdge: '#212a38',
  text: '#e6ebf2',
  muted: '#8b97a8',
  accent: '#5ac8fa',
  alt: '#b28cff',
  good: '#3ddc97',
  warn: '#ffb020',
  bad: '#ff5d5d',
} as const;

// Glyphs are the annotation language every chess audience already reads, so the
// badge says "??" and the label underneath says what that means.
const QUALITY_STYLE: Record<
  string,
  {label: string; color: string; glyph: string}
> = {
  brilliant: {label: 'BRILLIANT', color: THEME.good, glyph: '!!'},
  great: {label: 'GREAT', color: THEME.good, glyph: '!'},
  best: {label: 'BEST', color: THEME.accent, glyph: '★'},
  book: {label: 'THEORY', color: THEME.muted, glyph: '≡'},
  inaccuracy: {label: 'INACCURACY', color: THEME.warn, glyph: '?!'},
  mistake: {label: 'MISTAKE', color: '#ff8c42', glyph: '?'},
  blunder: {label: 'BLUNDER', color: THEME.bad, glyph: '??'},
};

const Panel: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({
  children,
  style,
}) => (
  <div
    style={{
      background: THEME.panel,
      border: `1px solid ${THEME.panelEdge}`,
      borderRadius: 14,
      padding: '22px 26px',
      ...style,
    }}
  >
    {children}
  </div>
);

const Label: React.FC<{children: React.ReactNode}> = ({children}) => (
  <div
    style={{
      fontSize: 17,
      letterSpacing: 2.4,
      color: THEME.muted,
      textTransform: 'uppercase',
      marginBottom: 14,
    }}
  >
    {children}
  </div>
);

const PORTRAIT = 96;

/** Neutral bust used when we have no photo of a player — every game renders. */
const PortraitPlaceholder: React.FC<{side: 'white' | 'black'}> = ({side}) => (
  <svg
    width="100%"
    height="100%"
    viewBox="0 0 96 96"
    preserveAspectRatio="xMidYMid slice"
    aria-hidden
  >
    <rect width="96" height="96" fill={side === 'white' ? '#2a323f' : '#1b222c'} />
    <circle cx="48" cy="37" r="16" fill="#5d6b7f" />
    <path d="M16 96c0-17.7 14.3-32 32-32s32 14.3 32 32z" fill="#5d6b7f" />
  </svg>
);

/**
 * One player, as a card. Two of these sit side by side above the move, so the
 * pairing reads as a matchup rather than a list.
 */
export const PlayerCard: React.FC<{
  name: string;
  side: 'white' | 'black';
  active: boolean;
  portrait?: string | null;
}> = ({name, side, active, portrait}) => (
  <div
    style={{
      flex: 1,
      minWidth: 0,
      background: active ? 'rgba(90,200,250,0.07)' : THEME.panel,
      border: `1px solid ${active ? 'rgba(90,200,250,0.45)' : THEME.panelEdge}`,
      borderRadius: 14,
      padding: '18px 16px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 12,
    }}
  >
    <div
      style={{
        // The portrait takes whatever height the card has to give, so the
        // matchup half of the rail is faces, not padding.
        flex: 1,
        minHeight: 0,
        width: '100%',
        borderRadius: 12,
        overflow: 'hidden',
        background: '#1b222c',
        // Grayscale keeps mismatched press photos from fighting the palette;
        // the side to move comes up to full strength.
        filter: active ? 'grayscale(1) contrast(1.05)' : 'grayscale(1) brightness(0.68)',
        boxShadow: `inset 0 0 0 2px ${active ? 'rgba(90,200,250,0.55)' : THEME.panelEdge}`,
      }}
    >
      {portrait ? (
        <Img
          src={staticFile(`portraits/${portrait}`)}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      ) : (
        <PortraitPlaceholder side={side} />
      )}
    </div>
    <div
      style={{
        fontSize: 27,
        lineHeight: 1.18,
        textAlign: 'center',
        color: active ? THEME.text : THEME.muted,
        // Long names wrap rather than being cut: "Robert James Fischer" has to
        // fit a half-width card without an ellipsis eating the surname. The
        // block is two lines tall whether or not it needs them, so a wrapping
        // name cannot steal height from its portrait and leave the two cards
        // holding different-sized faces.
        overflowWrap: 'anywhere',
        height: 27 * 1.18 * 2,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      {name}
    </div>
    <div
      style={{
        fontSize: 15,
        letterSpacing: 2.4,
        color: active ? THEME.accent : THEME.muted,
        marginTop: 'auto',
      }}
    >
      {side.toUpperCase()}
    </div>
  </div>
);

/** Horizontal eval bar with a numeric readout, White-positive. */
export const EvalReadout: React.FC<{cp: number | null; changeKey: string}> = ({cp}) => {
  const value = cp ?? 0;
  const pawns = value / 100;
  const ratio = Math.max(0.02, Math.min(0.98, 0.5 + Math.tanh(value / 400) / 2));

  const text =
    Math.abs(pawns) < 0.05 ? '0.0' : `${pawns > 0 ? '+' : '−'}${Math.abs(pawns).toFixed(1)}`;
  const tone = Math.abs(pawns) < 0.5 ? THEME.muted : pawns > 0 ? THEME.text : THEME.accent;

  return (
    <Panel>
      <Label>Evaluation</Label>
      <div style={{display: 'flex', alignItems: 'center', gap: 20}}>
        <div
          style={{
            flex: 1,
            height: 22,
            borderRadius: 11,
            overflow: 'hidden',
            background: '#28313f',
            display: 'flex',
          }}
        >
          {/* White's share grows from the left */}
          <div style={{width: `${ratio * 100}%`, background: '#eef2f7'}} />
          <div style={{flex: 1, background: '#28313f'}} />
        </div>
        <div
          style={{
            fontSize: 40,
            fontVariantNumeric: 'tabular-nums',
            color: tone,
            minWidth: 108,
            textAlign: 'right',
          }}
        >
          {text}
        </div>
      </div>
    </Panel>
  );
};

/**
 * Vertical evaluation column that stands beside the board.
 *
 * White's share fills from the bottom, so the bar reads the same way the board
 * does — White below, Black above — and the number sits at whichever end the
 * advantage is, out of the board's way.
 */
export const EvalColumn: React.FC<{
  cp: number | null;
  height: number;
  width?: number;
}> = ({cp, height, width = 26}) => {
  const value = cp ?? 0;
  const pawns = value / 100;
  const ratio = Math.max(0.02, Math.min(0.98, 0.5 + Math.tanh(value / 400) / 2));
  const text =
    Math.abs(pawns) < 0.05 ? '0.0' : `${pawns > 0 ? '+' : '−'}${Math.abs(pawns).toFixed(1)}`;
  const whiteLeads = pawns >= 0;

  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', height}}>
      <div
        style={{
          position: 'relative',
          width,
          flex: 1,
          borderRadius: width / 2,
          overflow: 'hidden',
          background: '#28313f',
          border: `1px solid ${THEME.panelEdge}`,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-end',
        }}
      >
        <div style={{height: `${ratio * 100}%`, background: '#eef2f7', width: '100%'}} />
        {/* Midpoint tick: the eye needs a reference for "equal". */}
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: 0,
            width: '100%',
            height: 1,
            background: 'rgba(255,255,255,0.22)',
          }}
        />
      </div>
      <div
        style={{
          marginTop: 10,
          fontSize: 26,
          fontVariantNumeric: 'tabular-nums',
          color: whiteLeads ? THEME.text : THEME.accent,
        }}
      >
        {text}
      </div>
    </div>
  );
};

export const CurrentMove: React.FC<{
  beat: Beat;
  moveNumber: number | null;
  isBlack?: boolean;
}> = ({beat, moveNumber, isBlack = false}) => {
  const frame = useCurrentFrame();
  const quality = beat.tag ? QUALITY_STYLE[beat.tag] : undefined;
  const san = beat.move?.san;

  const pop = interpolate(frame % 100000, [0, 6], [0.94, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.out(Easing.cubic),
  });

  // Every branch stretches: the panel owns half of the rail's lower section,
  // and its content sits centred in that space instead of above a void.
  const fill: React.CSSProperties = {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
  };

  if (beat.kind === 'hold') {
    // Nothing moves during a hold — the narrator is reading the position, so
    // show the assessment rather than a stale move.
    return (
      <Panel style={fill}>
        <Label>Reading the position</Label>
        <div style={{fontSize: 34, color: THEME.text, lineHeight: 1.25}}>
          {moveNumber ? `After move ${moveNumber}` : 'Taking stock'}
        </div>
        <div style={{fontSize: 22, color: THEME.muted, marginTop: 10}}>
          What both sides are playing for
        </div>
      </Panel>
    );
  }

  if (beat.branch) {
    return (
      <Panel style={{...fill, borderColor: 'rgba(178,140,255,0.5)'}}>
        <Label>Variation</Label>
        <div style={{fontSize: 42, color: THEME.alt, lineHeight: 1.2}}>
          {beat.label ?? 'Alternative line'}
        </div>
        <div style={{fontSize: 24, color: THEME.muted, marginTop: 10}}>
          Not played in the game
        </div>
      </Panel>
    );
  }

  return (
    <Panel style={fill}>
      <Label>Move</Label>
      {/* The badge rides the move's top-right corner, the way annotation
          symbols sit beside a move everywhere else in chess. */}
      <div style={{display: 'inline-flex', alignItems: 'flex-start', gap: 10}}>
        <div
          style={{
            fontSize: 58,
            color: THEME.text,
            fontVariantNumeric: 'tabular-nums',
            transform: `scale(${pop})`,
            transformOrigin: 'left bottom',
            lineHeight: 1.05,
          }}
        >
          {moveNumber ? `${moveNumber}${isBlack ? '…' : '.'}` : ''} {san ?? '—'}
        </div>
        {quality && (
          <div
            style={{
              marginTop: 2,
              minWidth: 46,
              height: 46,
              padding: '0 10px',
              borderRadius: 23,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 26,
              fontWeight: 700,
              color: '#0b0e13',
              background: quality.color,
              boxShadow: `0 0 0 4px ${quality.color}33`,
              transform: `scale(${pop})`,
              transformOrigin: 'left top',
            }}
          >
            {quality.glyph}
          </div>
        )}
      </div>
      {quality && (
        <div
          style={{
            marginTop: 12,
            fontSize: 18,
            letterSpacing: 2.4,
            color: quality.color,
          }}
        >
          {quality.label}
        </div>
      )}
    </Panel>
  );
};

export interface MoveListEntry {
  moveNumber: number;
  white?: string;
  black?: string;
}

/** Compact scrolling move list; the current move is highlighted. */
export const MoveList: React.FC<{
  entries: MoveListEntry[];
  currentPly: number | null;
  rows?: number;
}> = ({entries, currentPly, rows = 3}) => {
  const currentMoveNumber = currentPly ? Math.ceil(currentPly / 2) : 0;
  const currentIsWhite = currentPly ? currentPly % 2 === 1 : true;

  // Only ever show what has actually been played. Windowing over the whole game
  // put the next few moves on screen, so the viewer could read the continuation
  // before the narrator reached it.
  const played = entries
    .filter((e) => e.moveNumber <= currentMoveNumber)
    .map((e) =>
      e.moveNumber === currentMoveNumber && currentIsWhite ? {...e, black: undefined} : e
    );
  const window = played.slice(Math.max(0, played.length - rows));

  return (
    <Panel style={{flex: 1, display: 'flex', flexDirection: 'column'}}>
      <Label>Moves</Label>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          flex: 1,
          justifyContent: 'space-evenly',
        }}
      >
        {window.map((entry) => {
          const isCurrentRow = entry.moveNumber === currentMoveNumber;
          return (
            <div
              key={entry.moveNumber}
              style={{
                display: 'grid',
                gridTemplateColumns: '62px 1fr 1fr',
                alignItems: 'center',
                fontSize: 27,
                fontVariantNumeric: 'tabular-nums',
                color: THEME.muted,
                padding: '3px 0',
              }}
            >
              <span style={{color: '#5c6878'}}>{entry.moveNumber}.</span>
              <span
                style={{
                  color: isCurrentRow && currentIsWhite ? THEME.accent : THEME.text,
                  opacity: entry.white ? 1 : 0.25,
                }}
              >
                {entry.white ?? '·'}
              </span>
              <span
                style={{
                  color: isCurrentRow && !currentIsWhite ? THEME.accent : THEME.text,
                  opacity: entry.black ? 1 : 0.25,
                }}
              >
                {entry.black ?? '·'}
              </span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
};

export const Wordmark: React.FC<{name: string}> = ({name}) => (
  <div style={{display: 'flex', alignItems: 'center', gap: 14}}>
    <div
      style={{
        width: 34,
        height: 34,
        borderRadius: 9,
        background: `linear-gradient(135deg, ${THEME.accent}, ${THEME.alt})`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 22,
        color: '#0b0e13',
      }}
    >
      ♞
    </div>
    <div style={{fontSize: 25, letterSpacing: 4, color: THEME.text, textTransform: 'uppercase'}}>
      {name}
    </div>
  </div>
);
