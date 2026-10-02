import React from 'react'
import { isNum } from '../../lib/format'

/** Đường nhỏ không trục. Nét luôn 2px nhờ non-scaling-stroke. */
export default function Sparkline({ values = [], color = 'var(--n-accent)', area = false, className, label = 'Xu hướng' }) {
  const v = values.filter(isNum)
  if (v.length < 2) return <span className={className} style={{ color: 'var(--n-ink-3)' }}>—</span>
  const lo = Math.min(...v)
  const hi = Math.max(...v)
  const W = 100
  const H = 32
  const pts = v.map((y, i) => [(i / (v.length - 1)) * W, H - 3 - ((y - lo) / (hi - lo || 1)) * (H - 6)])
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join('')
  return (
    <svg className={className} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label} style={{ overflow: 'visible' }}>
      {area && <path d={`${d}L${W},${H}L0,${H}Z`} fill={color} opacity="0.12" />}
      <path d={d} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
