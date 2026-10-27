import React, { useEffect, useMemo, useRef, useState } from 'react'
import { PAD, useWidth, xTicks, linePath, areaPath, tipPos } from './geometry'
import { isNum, fmtNum, fmtPct, dmy, my, fullDate } from '../../lib/format'

/** Dải drawdown (≤ 0) dùng chung trục x với biểu đồ NAV phía trên. */
export default function UnderwaterStrip({
  dates = [], values = [], height = 110, hover, onHover, marks = [],
  zoomRange = [0, 1], onZoom,
}) {
  const ref = useRef(null)
  const rectRef = useRef(null)
  const w = useWidth(ref)
  const [local, setLocal] = useState(null)
  const active = hover !== undefined ? hover : local
  const n = dates.length
  const plotW = Math.max(10, w - PAD.l - PAD.r)
  const plotH = height - PAD.t - PAD.b

  useEffect(() => {
    const el = rectRef.current
    if (!el || !onZoom) return undefined
    const wheelHandler = (e) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const mx = Math.max(0, Math.min(plotW, e.clientX - r.left))
      const ratio = plotW > 0 ? mx / plotW : 0.5
      const [r0, r1] = zoomRange || [0, 1]
      const curSpan = Math.max(0.01, r1 - r0)
      const factor = e.deltaY < 0 ? 0.8 : 1.25
      const minSpan = Math.max(0.01, 5 / Math.max(n, 100))
      const newSpan = Math.min(1.0, Math.max(minSpan, curSpan * factor))
      const cursor = r0 + ratio * curSpan
      let newR0 = cursor - ratio * newSpan
      let newR1 = newR0 + newSpan
      if (newR0 < 0) {
        newR0 = 0
        newR1 = Math.min(1.0, newSpan)
      }
      if (newR1 > 1.0) {
        newR1 = 1.0
        newR0 = Math.max(0.0, 1.0 - newSpan)
      }
      onZoom([newR0, newR1])
    }
    el.addEventListener('wheel', wheelHandler, { passive: false })
    return () => el.removeEventListener('wheel', wheelHandler)
  }, [onZoom, zoomRange, plotW, n])

  const handleKeyDown = (e) => {
    if (!onZoom) return
    const [r0, r1] = zoomRange || [0, 1]
    const curSpan = Math.max(0.01, r1 - r0)
    if (e.key === '+' || e.key === '=') {
      e.preventDefault()
      const newSpan = Math.max(0.01, curSpan * 0.8)
      const center = (r0 + r1) / 2
      onZoom([Math.max(0, center - newSpan / 2), Math.min(1, center + newSpan / 2)])
    } else if (e.key === '-' || e.key === '_') {
      e.preventDefault()
      const newSpan = Math.min(1.0, curSpan * 1.25)
      const center = (r0 + r1) / 2
      onZoom([Math.max(0, center - newSpan / 2), Math.min(1, center + newSpan / 2)])
    } else if (e.key === '0') {
      e.preventDefault()
      onZoom([0, 1])
    }
  }

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
                <text x={PAD.l - 8} y={Y(t) + 3.5} textAnchor="end">{fmtPct(t, 1)}</text>
              </g>
            ))}
            {xTicks(n, plotW).map((i) => (
              <text key={i} x={X(i)} y={height - 8} textAnchor={i === 0 ? 'start' : 'middle'}>{labelFn(dates[i])}</text>
            ))}
            {marks.filter((m) => m.i >= 0 && m.i < n).map((m) => (
              <line key={`m${m.i}`} x1={xs[m.i]} x2={xs[m.i]} y1={PAD.t} y2={PAD.t + plotH} stroke="var(--n-ink-3)" strokeWidth="1" strokeDasharray="4 4" />
            ))}
            <path d={areaPath(xs, ys, Y(0))} fill="var(--n-neg)" opacity="0.14" />
            <path d={linePath(xs, ys)} fill="none" stroke="var(--n-neg)" strokeWidth="1.5" strokeLinejoin="round" />
            {active != null && active < n && <line className="cross" x1={xs[active]} x2={xs[active]} y1={PAD.t} y2={PAD.t + plotH} />}
            <rect
              ref={rectRef}
              x={PAD.l}
              y={PAD.t}
              width={plotW}
              height={plotH}
              fill="transparent"
              tabIndex={0}
              role="region"
              aria-label="Khu vực tương tác biểu đồ Drawdown (cuộn chuột để zoom, 0 để đặt lại)"
              onMouseMove={move}
              onMouseLeave={leave}
              onKeyDown={handleKeyDown}
              style={{ outline: 'none', cursor: onZoom ? 'crosshair' : 'default' }}
            />
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
