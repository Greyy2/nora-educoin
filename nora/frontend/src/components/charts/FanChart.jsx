import React, { useMemo, useRef, useState } from 'react'
import { PAD, useWidth, niceScale, xTicks, linePath, tipPos } from './chartUtils'
import { isNum, fmtTick, fmtSigned } from '../../lib/format'

/** Quạt Monte Carlo: dải p5–p95, dải p25–p75, đường p50. y là lợi nhuận % so với vốn đầu.
 *  `overlays` (tuỳ chọn): [{ key, label, color, dash, days: [...], ret_pct: [...] }] — đường kịch bản cực xấu vẽ chồng lên quạt
 *  (trục x theo ngày thật của từng đường, có thể dài hơn chân trời của quạt). */
export default function FanChart({ fan, height = 260, overlays = [] }) {
  const ref = useRef(null)
  const w = useWidth(ref)
  const [hi, setHi] = useState(null)
  const days = fan?.days || []
  const n = days.length
  const plotW = Math.max(10, w - PAD.l - PAD.r)
  const plotH = height - PAD.t - PAD.b
  const ov = useMemo(() => (overlays || []).filter((o) => o?.days?.length > 1 && o?.ret_pct?.length === o.days.length), [overlays])
  const sc = useMemo(() => {
    const all = ['p5', 'p95', 'p50'].flatMap((k) => (fan?.[k] || []).filter(isNum)).concat(ov.flatMap((o) => o.ret_pct.filter(isNum)))
    return niceScale(Math.min(0, ...all), Math.max(0, ...all), 5)
  }, [fan, ov])
  const dMax = Math.max(days[n - 1] || 1, ...ov.map((o) => o.days[o.days.length - 1]))
  const dayTicks = useMemo(() => (ov.length ? niceScale(0, dMax, Math.max(2, Math.floor(plotW / 60))).ticks.filter((t) => t >= 0 && t <= dMax) : null), [ov, dMax, plotW])
  const OX = (d) => PAD.l + (d / dMax) * plotW
  const at = (o, d) => {   // nội suy tuyến tính giá trị đường vẽ tại ngày d (ngoài phạm vi: không có)
    if (d > o.days[o.days.length - 1]) return null
    let j = 1
    while (j < o.days.length - 1 && o.days[j] < d) j++
    const [d0, d1, v0, v1] = [o.days[j - 1], o.days[j], o.ret_pct[j - 1], o.ret_pct[j]]
    return d1 === d0 ? v1 : v0 + ((v1 - v0) * (d - d0)) / (d1 - d0)
  }
  const X = (i) => PAD.l + (days[i] / dMax) * plotW
  const Y = (v) => PAD.t + plotH - ((v - sc.min) / (sc.max - sc.min || 1)) * plotH
  const xs = days.map((_, i) => X(i))
  const band = (a, b) => {
    const top = xs.map((x, i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${Y(fan[b][i]).toFixed(1)}`).join('')
    const bot = xs.map((x, i) => `L${xs[n - 1 - i].toFixed(1)},${Y(fan[a][n - 1 - i]).toFixed(1)}`).join('')
    return `${top}${bot}Z`
  }
  function move(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const d = ((e.clientX - r.left - PAD.l) / plotW) * dMax
    let best = 0
    for (let i = 0; i < n; i++) if (Math.abs(days[i] - d) < Math.abs(days[best] - d)) best = i
    setHi(best)
  }
  return (
    <div className="n-chart" ref={ref} style={{ height }}>
      {w > 0 && n > 1 && (
        <>
          <svg width={w} height={height} role="img" aria-label="Quạt Monte Carlo của lợi nhuận tích luỹ">
            {sc.ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? 'axis' : 'grid'} x1={PAD.l} x2={PAD.l + plotW} y1={Y(t)} y2={Y(t)} />
                <text x={PAD.l - 8} y={Y(t) + 3.5} textAnchor="end">{fmtTick(t, sc.step)}%</text>
              </g>
            ))}
            {dayTicks
              ? dayTicks.map((t) => <text key={t} x={OX(t)} y={height - 8} textAnchor={t === 0 ? 'start' : 'middle'}>{t}</text>)
              : xTicks(n, plotW, 60).map((i) => <text key={i} x={X(i)} y={height - 8} textAnchor={i === 0 ? 'start' : 'middle'}>{days[i]}</text>)}
            <path d={band('p5', 'p95')} fill="var(--n-blue)" opacity="0.14" />
            <path d={band('p25', 'p75')} fill="var(--n-blue)" opacity="0.26" />
            <path d={linePath(xs, fan.p50.map((v) => (isNum(v) ? Y(v) : null)))} fill="none" stroke="var(--n-blue)" strokeWidth="2" strokeLinejoin="round" />
            {ov.map((o) => (
              <g key={o.key}>
                <path d={linePath(o.days.map(OX), o.ret_pct.map((v) => (isNum(v) ? Y(v) : null)))} fill="none" stroke={o.color} strokeWidth="1.75"
                  strokeDasharray={o.dash ? '6 4' : undefined} strokeLinejoin="round" />
                <circle cx={OX(o.days[o.days.length - 1])} cy={Y(o.ret_pct[o.ret_pct.length - 1])} r="3.5" fill={o.color} stroke="var(--n-surface)" strokeWidth="1.5" />
              </g>
            ))}
            {hi != null && (
              <g>
                <line className="cross" x1={xs[hi]} x2={xs[hi]} y1={PAD.t} y2={PAD.t + plotH} />
                <circle cx={xs[hi]} cy={Y(fan.p50[hi])} r="4" fill="var(--n-blue)" stroke="var(--n-surface)" strokeWidth="2" />
              </g>
            )}
            <rect x={PAD.l} y={PAD.t} width={plotW} height={plotH} fill="transparent" onMouseMove={move} onMouseLeave={() => setHi(null)} />
          </svg>
          {hi != null && (
            <div className="n-tip" style={{ top: PAD.t, ...tipPos(xs[hi], w, ov.length ? 250 : 180) }}>
              <div className="t">Ngày {days[hi]}</div>
              {[['p95', 'P95'], ['p75', 'P75'], ['p50', 'P50'], ['p25', 'P25'], ['p5', 'P5']].map(([k, l]) => (
                <div className="r" key={k}><span>{l}</span><b>{fmtSigned(fan[k][hi], 1)}%</b></div>
              ))}
              {ov.map((o) => { const v = at(o, days[hi]); return v == null ? null : <div className="r" key={o.key}><span style={{ color: o.color }}>{o.label}</span><b>{fmtSigned(v, 1)}%</b></div> })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
