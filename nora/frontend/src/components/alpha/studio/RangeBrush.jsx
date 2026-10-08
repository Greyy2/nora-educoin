import React, { useRef } from 'react'

/** Thanh chọn khoảng dưới biểu đồ: vẽ đường mini + hai tay nắm kéo được. range = [a, b] trong 0..1. */
export default function RangeBrush({ values = [], range, onChange, height = 34 }) {
  const ref = useRef(null)
  const [a, b] = range
  const W = 1000
  const vs = values.filter((v) => Number.isFinite(v))
  const lo = vs.length ? Math.min(...vs) : 0
  const hi = vs.length ? Math.max(...vs) : 1
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * W},${height - 4 - ((v - lo) / (hi - lo || 1)) * (height - 8)}`).join(' ')
  const pos = (e) => { const r = ref.current.getBoundingClientRect(); return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) }
  const drag = (mode) => (e) => {
    e.preventDefault(); e.stopPropagation()
    const start = pos(e)
    const [a0, b0] = range
    const mv = (ev) => {
      const p = pos(ev)
      if (mode === 'a') onChange([Math.min(p, b0 - 0.02), b0])
      else if (mode === 'b') onChange([a0, Math.max(p, a0 + 0.02)])
      else { const d = Math.max(-a0, Math.min(1 - b0, p - start)); onChange([a0 + d, b0 + d]) }
    }
    const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up)
  }
  return (
    <div className="se-brush" ref={ref} style={{ height }} role="group" aria-label="Chọn khoảng thời gian">
      <svg viewBox={`0 0 ${W} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        <polyline points={pts} fill="none" stroke="var(--n-ink-3)" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="se-br-mask" style={{ left: 0, width: `${a * 100}%` }} />
      <div className="se-br-mask" style={{ left: `${b * 100}%`, right: 0 }} />
      <div className="se-br-win" style={{ left: `${a * 100}%`, width: `${(b - a) * 100}%` }} onPointerDown={drag('m')}>
        <span className="h l" onPointerDown={drag('a')} /><span className="h r" onPointerDown={drag('b')} />
      </div>
    </div>
  )
}
