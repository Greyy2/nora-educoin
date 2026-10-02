import React, { useMemo, useRef, useState } from 'react'
import { PAD, useWidth, niceScale, xTicks, linePath, areaPath, tipPos } from './chartUtils'
import { isNum, fmtTick, dmy, my, fullDate } from '../../lib/format'

/**
 * Đường / vùng theo thời gian, dependency-free.
 * series: [{ key, label, values, color, dashed?, area? }]  (đường đầu có thể có area)
 * hover/onHover: chỉ số đang trỏ, dùng chung giữa các biểu đồ cùng trục x (vd. NAV + Underwater).
 */
export default function AreaLine({
  dates = [], series = [], height = 240, valueFormat, refLines = [], hover, onHover,
  yDomain, xLabels = true, label = 'Biểu đồ đường',
}) {
  const ref = useRef(null)
  const w = useWidth(ref)
  const [local, setLocal] = useState(null)
  const active = hover !== undefined ? hover : local
  const n = dates.length
  const plotW = Math.max(10, w - PAD.l - PAD.r)
  const plotH = height - PAD.t - (xLabels ? PAD.b : 8)

  const sc = useMemo(() => {
    let lo = Infinity
    let hi = -Infinity
    series.forEach((s) => s.values.forEach((v) => { if (isNum(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v) } }))
    refLines.forEach((r) => { lo = Math.min(lo, r.y); hi = Math.max(hi, r.y) })
    if (yDomain) { lo = yDomain[0] ?? lo; hi = yDomain[1] ?? hi }
    if (!Number.isFinite(lo)) { lo = 0; hi = 1 }
    return niceScale(lo, hi, Math.max(2, Math.round(plotH / 42)))
  }, [series, refLines, yDomain, plotH])

  const X = (i) => PAD.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW)
  const Y = (v) => PAD.t + plotH - ((v - sc.min) / (sc.max - sc.min || 1)) * plotH
  const xs = useMemo(() => dates.map((_, i) => X(i)), [dates, plotW]) // eslint-disable-line react-hooks/exhaustive-deps
  const fmtV = valueFormat || ((v) => fmtTick(v, sc.step))
  const labelFn = n > 220 ? my : dmy

  function move(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX - r.left - PAD.l
    const i = Math.max(0, Math.min(n - 1, Math.round((mx / plotW) * (n - 1))))
    setLocal(i)
    onHover && onHover(i)
  }
  function leave() { setLocal(null); onHover && onHover(null) }

  return (
    <div className="n-chart" ref={ref} style={{ height }}>
      {w > 0 && n > 0 && (
        <>
          <svg width={w} height={height} role="img" aria-label={label}>
            {sc.ticks.map((t) => (
              <g key={t}>
                <line className="grid" x1={PAD.l} x2={PAD.l + plotW} y1={Y(t)} y2={Y(t)} />
                <text x={PAD.l - 8} y={Y(t) + 3.5} textAnchor="end">{fmtTick(t, sc.step)}</text>
              </g>
            ))}
            {xLabels && xTicks(n, plotW).map((i) => (
              <text key={i} x={X(i)} y={height - 8} textAnchor={i === 0 ? 'start' : 'middle'}>{labelFn(dates[i])}</text>
            ))}
            {refLines.map((r) => (
              <g key={r.y}>
                <line x1={PAD.l} x2={PAD.l + plotW} y1={Y(r.y)} y2={Y(r.y)} stroke="var(--n-ink-3)" strokeWidth="1" strokeDasharray="4 4" />
                {r.label && <text x={PAD.l + plotW - 2} y={Y(r.y) - 4} textAnchor="end">{r.label}</text>}
              </g>
            ))}
            {series.map((s, si) => {
              const ys = s.values.map((v) => (isNum(v) ? Y(v) : null))
              return (
                <g key={s.key}>
                  {s.area && <path d={areaPath(xs, ys, PAD.t + plotH)} fill={s.color} opacity="0.11" />}
                  <path d={linePath(xs, ys)} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
                    strokeDasharray={s.dashed ? '5 4' : undefined} />
                  {(() => {
                    let last = ys.length - 1
                    while (last >= 0 && ys[last] == null) last--
                    return last >= 0 && si === 0 ? <circle cx={xs[last]} cy={ys[last]} r="4" fill={s.color} stroke="var(--n-surface)" strokeWidth="2" /> : null
                  })()}
                </g>
              )
            })}
            {active != null && active < n && (
              <g>
                <line className="cross" x1={xs[active]} x2={xs[active]} y1={PAD.t} y2={PAD.t + plotH} />
                {series.map((s) => (isNum(s.values[active])
                  ? <circle key={s.key} cx={xs[active]} cy={Y(s.values[active])} r="4" fill={s.color} stroke="var(--n-surface)" strokeWidth="2" /> : null))}
              </g>
            )}
            <rect x={PAD.l} y={PAD.t} width={plotW} height={plotH} fill="transparent" onMouseMove={move} onMouseLeave={leave} />
          </svg>
          {local != null && local < n && (
            <div className="n-tip" style={{ top: PAD.t + 4, ...tipPos(xs[local], w) }}>
              <div className="t">{fullDate(dates[local])}</div>
              {series.map((s) => (
                <div className="r" key={s.key}><span><i style={{ background: s.color }} />{s.label}</span><b>{isNum(s.values[local]) ? fmtV(s.values[local]) : '—'}</b></div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
