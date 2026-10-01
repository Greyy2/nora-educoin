import React, { useMemo, useRef, useState } from 'react'
import { PAD, useWidth, niceScale, xTicks, linePath, tipPos } from './chartUtils'
import { isNum, fmtTick, fmtSigned } from '../../lib/format'

/** Quạt Monte Carlo: dải p5–p95, dải p25–p75, đường p50. y là lợi nhuận % so với vốn đầu. */
export default function FanChart({ fan, height = 260 }) {
  const ref = useRef(null)
  const w = useWidth(ref)
  const [hi, setHi] = useState(null)
  const days = fan?.days || []
  const n = days.length
  const plotW = Math.max(10, w - PAD.l - PAD.r)
  const plotH = height - PAD.t - PAD.b
  const sc = useMemo(() => {
    const all = ['p5', 'p95', 'p50'].flatMap((k) => (fan?.[k] || []).filter(isNum))
    return niceScale(Math.min(0, ...all), Math.max(0, ...all), 5)
  }, [fan])
  const dMax = days[n - 1] || 1
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
            {xTicks(n, plotW, 60).map((i) => <text key={i} x={X(i)} y={height - 8} textAnchor={i === 0 ? 'start' : 'middle'}>{days[i]}</text>)}
            <path d={band('p5', 'p95')} fill="var(--n-blue)" opacity="0.14" />
            <path d={band('p25', 'p75')} fill="var(--n-blue)" opacity="0.26" />
            <path d={linePath(xs, fan.p50.map((v) => (isNum(v) ? Y(v) : null)))} fill="none" stroke="var(--n-blue)" strokeWidth="2" strokeLinejoin="round" />
            {hi != null && (
              <g>
                <line className="cross" x1={xs[hi]} x2={xs[hi]} y1={PAD.t} y2={PAD.t + plotH} />
                <circle cx={xs[hi]} cy={Y(fan.p50[hi])} r="4" fill="var(--n-blue)" stroke="var(--n-surface)" strokeWidth="2" />
              </g>
            )}
            <rect x={PAD.l} y={PAD.t} width={plotW} height={plotH} fill="transparent" onMouseMove={move} onMouseLeave={() => setHi(null)} />
          </svg>
          {hi != null && (
            <div className="n-tip" style={{ top: PAD.t, ...tipPos(xs[hi], w, 180) }}>
              <div className="t">Ngày {days[hi]}</div>
              {[['p95', 'P95'], ['p75', 'P75'], ['p50', 'P50'], ['p25', 'P25'], ['p5', 'P5']].map(([k, l]) => (
                <div className="r" key={k}><span>{l}</span><b>{fmtSigned(fan[k][hi], 1)}%</b></div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
