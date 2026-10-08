import React, { useMemo, useRef, useState } from 'react'
import { PAD, useWidth, niceScale, barPath, tipPos } from './geometry'
import { isNum, fmtTick } from '../../lib/format'

/**
 * Histogram từ bins [{lo,hi,count}].
 * colorOf(bin) -> màu; marker: {x, label} vẽ vạch dọc (VaR / ngưỡng phá sản).
 */
export default function Histogram({ bins = [], height = 190, colorOf, marker, xFormat = (v) => String(v), unit = '', label = 'Phân phối' }) {
  const ref = useRef(null)
  const w = useWidth(ref)
  const [hi, setHi] = useState(null)
  const pad = { ...PAD, l: 40 }
  const plotW = Math.max(10, w - pad.l - pad.r)
  const plotH = height - pad.t - pad.b
  const sc = useMemo(() => niceScale(0, Math.max(1, ...bins.map((b) => b.count || 0)), 4), [bins])
  const n = bins.length
  const lo = n ? bins[0].lo : 0
  const hiX = n ? bins[n - 1].hi : 1
  const X = (v) => pad.l + ((v - lo) / (hiX - lo || 1)) * plotW
  const Y = (v) => pad.t + plotH - (v / (sc.max || 1)) * plotH
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(plotW / 56))))
  function move(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const v = lo + ((e.clientX - r.left - pad.l) / plotW) * (hiX - lo)
    const i = bins.findIndex((b) => v >= b.lo && v < b.hi)
    setHi(i >= 0 ? i : null)
  }
  return (
    <div className="n-chart" ref={ref} style={{ height }}>
      {w > 0 && n > 0 && (
        <>
          <svg width={w} height={height} role="img" aria-label={label}>
            {sc.ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? 'axis' : 'grid'} x1={pad.l} x2={pad.l + plotW} y1={Y(t)} y2={Y(t)} />
                <text x={pad.l - 8} y={Y(t) + 3.5} textAnchor="end">{fmtTick(t, sc.step)}</text>
              </g>
            ))}
            {bins.map((b, i) => {
              const bw = Math.max(1, X(b.hi) - X(b.lo) - 2)
              return <path key={i} d={barPath(X(b.lo) + 1, bw, Y(0), Y(b.count || 0))} fill={colorOf ? colorOf(b) : 'var(--n-teal)'} opacity={hi === i ? 1 : 0.88} />
            })}
            {bins.map((b, i) => (i % every === 0 ? <text key={`x${i}`} x={X(b.lo)} y={height - 8} textAnchor="middle">{xFormat(b.lo)}</text> : null))}
            {marker && isNum(marker.x) && marker.x >= lo && marker.x <= hiX && (
              <g>
                <line x1={X(marker.x)} x2={X(marker.x)} y1={pad.t} y2={pad.t + plotH} stroke="var(--n-neg)" strokeWidth="1.5" strokeDasharray="4 3" />
                {marker.label && <text x={X(marker.x) + 4} y={pad.t + 10} style={{ fill: 'var(--n-ink-2)' }}>{marker.label}</text>}
              </g>
            )}
            <rect x={pad.l} y={pad.t} width={plotW} height={plotH} fill="transparent" onMouseMove={move} onMouseLeave={() => setHi(null)} />
          </svg>
          {hi != null && (
            <div className="n-tip" style={{ top: pad.t, ...tipPos((X(bins[hi].lo) + X(bins[hi].hi)) / 2, w, 170) }}>
              <div className="t">{xFormat(bins[hi].lo)} → {xFormat(bins[hi].hi)}{unit}</div>
              <div className="r"><span>Số quan sát</span><b>{bins[hi].count}</b></div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
