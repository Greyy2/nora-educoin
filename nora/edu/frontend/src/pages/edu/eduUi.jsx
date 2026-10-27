import React from 'react'
import { isNum, fmtMoney, fmtNum, signClass } from '../../lib/format'

export const usd = (v) => (isNum(v) ? `${fmtMoney(v, true)} $` : '—')
export const pct = (v, d = 2) => (isNum(v) ? `${fmtNum(v, d)}%` : '—')
export const spct = (v) => (isNum(v) ? `${v > 0 ? '+' : ''}${fmtNum(v, 2)}%` : '—')
export const tone = (v) => ({ pos: 'var(--n-pos)', neg: 'var(--n-neg)', '': 'inherit' }[signClass(v)])

export function Avatar({ avatar, size = 44 }) {
  return (
    <span style={{
      width: size,
      height: size,
      borderRadius: '50%',
      background: avatar?.color || '#6366F1',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontSize: Math.round(size / 2.2),
      flexShrink: 0,
      boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)',
      border: '2px solid var(--n-surface)',
      userSelect: 'none',
    }}>
      {avatar?.emoji || '👤'}
    </span>
  )
}

export function Stat({ label, value, color }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)', marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 16, fontWeight: 700, color: color || 'var(--n-ink)', whiteSpace: 'nowrap', letterSpacing: '-0.01em' }}>{value}</div>
    </div>
  )
}

export const cardStyle = {
  background: 'var(--n-surface)',
  border: '1px solid var(--n-line)',
  borderRadius: 16,
  padding: '22px 24px',
  boxShadow: 'var(--n-shadow)',
  textDecoration: 'none',
  color: 'inherit',
}

