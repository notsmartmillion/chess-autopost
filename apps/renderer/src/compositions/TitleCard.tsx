import React from 'react';

export const TitleCard: React.FC<{
  title: string;
  subtitle?: string;
}> = ({title, subtitle}) => {
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        background: '#0f0f12',
        color: 'white',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'system-ui, Segoe UI, sans-serif',
        letterSpacing: 0.3,
      }}
    >
      <div style={{textAlign: 'center'}}>
        <div style={{fontSize: 64, fontWeight: 800, marginBottom: 18}}>{title}</div>
        {subtitle && <div style={{fontSize: 28, opacity: 0.8}}>{subtitle}</div>}
      </div>
    </div>
  );
};
