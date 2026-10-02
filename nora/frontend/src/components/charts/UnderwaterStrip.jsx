import React, { useMemo, useRef, useState } from 'react'
import { PAD, useWidth, xTicks, linePath, areaPath, tipPos } from './chartUtils'
import { isNum, fmtNum, dmy, my, fullDate } from '../../lib/format'

/** Dải drawdown (≤ 0) dùng chung trục x với biểu đồ NAV phía trên. */
export default function UnderwaterStrip({ dates = [], values = [], height = 110, hover, onHover }) {
  const ref = useRef(null)
  const w = useWidth(ref)
  const [local, setLocal] = useState(null)
  const active = hover !== undefined ? hover : local
  const n = dates.length
  const plotW = Math.max(10, w - PAD.l - PAD.r)
  const plotH = height - PAD.t - PAD.b
  const mn = useMemo(() => Math.min(-0.5, ...values.filter(isNum)), [values])
  const lo = Math.floor(mn)
  const X = (i) => PAD.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW)
  const Y = (v) => PAD.t + (v / (lo || -1)) * plotH
  const xs = useMemo(() => dates.map((_, i) => X(i)), [dates, plotW]) // eslint-disable-line react-hooks/exhaustive-deps
  const ys = values.map((v) => (isNum(v) ? Y(Math.min(0, v)) : null))
  const labelFn = n > 220 ? my : dmy
  function move(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.max(0, Math.min(n - 1, Math.round(((e.clientX - r.left - PAD.l) / plotW) * (n - 1))))
    setLocal(i); onHover && onHover(i)
  }
  function leave() { setLocal(null); onHover && onHover(null) }
  return (
    <div className="n-chart" ref={ref} style={{ height }}>
      {w > 0 && n > 0 && (
        <>
          <svg width={w} height={height} role="img" aria-label="Underwater: sụt giảm từ đỉnh">
            {[0, lo].map((t) => (
              <g key={t}>
                <line className="grid" x1={PAD.l} x2={PAD.l + plotW} y1={Y(t)} y2={Y(t)} />
                <text x={PAD.l - 8} y={Y(t) + 3.5} textAnchor="end">{t === 0 ? '0.0%' : `${t.toFixed(1)}%`}</text>
              </g>
            ))}
            {xTicks(n, plotW).map((i) => (
              <text key={i} x={X(i)} y={height - 8} textAnchor={i === 0 ? 'start' : 'middle'}>{labelFn(dates[i])}</text>
            ))}
            <path d={areaPath(xs, ys, Y(0))} fill="var(--n-neg)" opacity="0.14" />
            <path d={linePath(xs, ys)} fill="none" stroke="var(--n-neg)" strokeWidth="1.5" strokeLinejoin="round" />
            {active != null && active < n && <line className="cross" x1={xs[active]} x2={xs[active]} y1={PAD.t} y2={PAD.t + plotH} />}
            <rect x={PAD.l} y={PAD.t} width={plotW} height={plotH} fill="transparent" onMouseMove={move} onMouseLeave={leave} />
          </svg>
          {local != null && local < n && (
            <div className="n-tip" style={{ top: 2, ...tipPos(xs[local], w, 150) }}>
              <div className="t">{fullDate(dates[local])}</div>
              <div className="r"><span><i style={{ background: 'var(--n-neg)' }} />Drawdown</span><b>{isNum(values[local]) ? `${fmtNum(values[local])}%` : '—'}</b></div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
