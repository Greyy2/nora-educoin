import React from 'react'
import { isNum, fmtMoney, fmtNum, signClass } from '../../lib/format'

export const usd = (v) => (isNum(v) ? `${fmtMoney(v, true)} $` : '—')
export const pct = (v, d = 2) => (isNum(v) ? `${fmtNum(v, d)}%` : '—')
export const spct = (v) => (isNum(v) ? `${v > 0 ? '+' : ''}${fmtNum(v, 2)}%` : '—')
export const tone = (v) => ({ pos: 'var(--n-pos)', neg: 'var(--n-neg)', '': 'inherit' }[signClass(v)])

export function Avatar({ avatar, size = 44 }) {
  return (
    <span style={{ width: size, height: size, borderRadius: '50%', background: avatar?.color || '#3b82f6', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: size / 2, flexShrink: 0 }}>
      {avatar?.emoji || '👤'}
    </span>
  )
}

export function Stat({ label, value, color }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 600, color, whiteSpace: 'nowrap' }}>{value}</div>
    </div>
  )
}

export const cardStyle = { background: 'var(--n-surface-2)', border: '1px solid var(--n-line)', borderRadius: 12, padding: 18, textDecoration: 'none', color: 'inherit' }
