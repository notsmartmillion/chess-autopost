import React from 'react';
import {interpolate, Easing, useCurrentFrame} from 'remotion';
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

const QUALITY_STYLE: Record<string, {label: string; color: string}> = {
  brilliant: {label: 'BRILLIANT', color: THEME.good},
  great: {label: 'GREAT', color: THEME.good},
  best: {label: 'BEST', color: THEME.accent},
  book: {label: 'THEORY', color: THEME.muted},
  inaccuracy: {label: 'INACCURACY', color: THEME.warn},
  mistake: {label: 'MISTAKE', color: '#ff8c42'},
  blunder: {label: 'BLUNDER', color: THEME.bad},
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

export const PlayerRow: React.FC<{
  name: string;
  side: 'white' | 'black';
  active: boolean;
}> = ({name, side, active}) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 16,
      padding: '12px 14px',
      borderRadius: 10,
      background: active ? 'rgba(90,200,250,0.10)' : 'transparent',
      border: `1px solid ${active ? 'rgba(90,200,250,0.35)' : 'transparent'}`,
    }}
  >
    <div
      style={{
        width: 20,
        height: 20,
        borderRadius: '50%',
        background: side === 'white' ? '#eef2f7' : '#28313f',
        border: `2px solid ${side === 'white' ? '#c3cddb' : '#4a5769'}`,
        flexShrink: 0,
      }}
    />
    <div
      style={{
        flex: 1,
        fontSize: 34,
        color: active ? THEME.text : THEME.muted,
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
      }}
    >
      {name}
    </div>
    <div style={{fontSize: 16, letterSpacing: 2, color: THEME.muted}}>
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

  if (beat.kind === 'hold') {
    // Nothing moves during a hold — the narrator is reading the position, so
    // show the assessment rather than a stale move.
    return (
      <Panel>
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
      <Panel style={{borderColor: 'rgba(178,140,255,0.5)'}}>
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
    <Panel>
      <Label>Move</Label>
      <div style={{display: 'flex', alignItems: 'baseline', gap: 16}}>
        <div
          style={{
            fontSize: 58,
            color: THEME.text,
            fontVariantNumeric: 'tabular-nums',
            transform: `scale(${pop})`,
            transformOrigin: 'left bottom',
          }}
        >
          {moveNumber ? `${moveNumber}${isBlack ? '…' : '.'}` : ''} {san ?? '—'}
        </div>
      </div>
      {quality && (
        <div
          style={{
            display: 'inline-block',
            marginTop: 16,
            padding: '7px 16px',
            borderRadius: 8,
            fontSize: 19,
            letterSpacing: 2,
            color: quality.color,
            border: `1px solid ${quality.color}`,
            background: `${quality.color}1a`,
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
}> = ({entries, currentPly, rows = 6}) => {
  const currentMoveNumber = currentPly ? Math.ceil(currentPly / 2) : 0;
  const currentIsWhite = currentPly ? currentPly % 2 === 1 : true;

  // Keep the current move in view near the bottom of the window.
  const currentIndex = Math.max(
    0,
    entries.findIndex((e) => e.moveNumber === currentMoveNumber)
  );
  const start = Math.max(0, Math.min(currentIndex - rows + 2, entries.length - rows));
  const window = entries.slice(start, start + rows);

  return (
    <Panel style={{flex: 1, display: 'flex', flexDirection: 'column'}}>
      <Label>Moves</Label>
      <div style={{display: 'flex', flexDirection: 'column', gap: 6}}>
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
