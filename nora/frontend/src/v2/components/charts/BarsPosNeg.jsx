import React, { useMemo, useRef, useState } from 'react'
import { PAD, useWidth, niceScale, xTicks, barPath, tipPos } from './chartUtils'
import { isNum, fmtTick, compact, dmy, my, fullDate, fmtSigned } from '../../lib/format'

/** Cột lãi/lỗ theo ngày: xanh trên đường 0, đỏ dưới đường 0 (kèm dấu +/− trong tooltip). */
export default function BarsPosNeg({ dates = [], values = [], height = 190, unit = 'USDT' }) {
  const ref = useRef(null)
  const w = useWidth(ref)
  const [hi, setHi] = useState(null)
  const n = dates.length
  const plotW = Math.max(10, w - PAD.l - PAD.r)
  const plotH = height - PAD.t - PAD.b
  const sc = useMemo(() => {
    const f = values.filter(isNum)
    return niceScale(Math.min(0, ...f), Math.max(0, ...f), 4)
  }, [values])
  const slot = plotW / Math.max(1, n)
  const bw = Math.max(1, Math.min(24, slot - 2))
  const Y = (v) => PAD.t + plotH - ((v - sc.min) / (sc.max - sc.min || 1)) * plotH
  const cx = (i) => PAD.l + slot * i + slot / 2
  const labelFn = n > 220 ? my : dmy
  function move(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.floor((e.clientX - r.left - PAD.l) / slot)
    setHi(Math.max(0, Math.min(n - 1, i)))
  }
  return (
    <div className="n-chart" ref={ref} style={{ height }}>
      {w > 0 && n > 0 && (
        <>
          <svg width={w} height={height} role="img" aria-label="Lãi/lỗ theo ngày">
            {sc.ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? 'axis' : 'grid'} x1={PAD.l} x2={PAD.l + plotW} y1={Y(t)} y2={Y(t)} />
                <text x={PAD.l - 8} y={Y(t) + 3.5} textAnchor="end">{Math.abs(t) >= 1000 ? compact(t) : fmtTick(t, sc.step)}</text>
              </g>
            ))}
            {xTicks(n, plotW, 64).map((i) => (
              <text key={i} x={cx(i)} y={height - 8} textAnchor="middle">{labelFn(dates[i])}</text>
            ))}
            {values.map((v, i) => (isNum(v) ? (
              <path key={i} d={barPath(cx(i) - bw / 2, bw, Y(0), Y(v))} fill={v >= 0 ? 'var(--n-pos)' : 'var(--n-neg)'} opacity={hi === i ? 1 : 0.85} />
            ) : null))}
            {hi != null && <line className="cross" x1={cx(hi)} x2={cx(hi)} y1={PAD.t} y2={PAD.t + plotH} />}
            <rect x={PAD.l} y={PAD.t} width={plotW} height={plotH} fill="transparent" onMouseMove={move} onMouseLeave={() => setHi(null)} />
          </svg>
          {hi != null && (
            <div className="n-tip" style={{ top: PAD.t, ...tipPos(cx(hi), w, 170) }}>
              <div className="t">{fullDate(dates[hi])}</div>
              <div className="r"><span>{values[hi] >= 0 ? '▲' : '▼'} Lãi/lỗ</span><b className={values[hi] >= 0 ? 'pos' : 'neg'}>{fmtSigned(values[hi], 2)} {unit}</b></div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
