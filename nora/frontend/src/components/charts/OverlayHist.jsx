import React, { useMemo, useRef, useState } from 'react'
import { PAD, useWidth, niceScale, barPath, tipPos } from './geometry'
import { isNum, fmtTick, fmtNum } from '../../lib/format'

/**
 * Hai phân phối chồng nhau trên cùng các bin: nhóm vào (xám) và nhóm qua (xanh).
 * Trục y là % số alpha của MỖI nhóm (để so hình dạng dù nhóm qua nhỏ hơn nhiều); tooltip có số đếm thật.
 * `a` / `b` = { bins: [{lo,hi,count}], p50, n }.
 */
export default function OverlayHist({ a, b, height = 150, xFormat = (v) => fmtNum(v, 1), unit = '', label = 'Phân phối', aLabel = 'Nhóm vào', bLabel = 'Nhóm qua' }) {
  const ref = useRef(null)
  const w = useWidth(ref)
  const [hi, setHi] = useState(null)
  const pad = { ...PAD, l: 36, r: 10, t: 8, b: 24 }
  const base = (a?.bins?.length ? a : b)?.bins || []
  const n = base.length
  const plotW = Math.max(10, w - pad.l - pad.r)
  const plotH = height - pad.t - pad.b
  const totA = useMemo(() => (a?.bins || []).reduce((s, x) => s + (x.count || 0), 0), [a])
  const totB = useMemo(() => (b?.bins || []).reduce((s, x) => s + (x.count || 0), 0), [b])
  const shareA = (i) => (totA ? ((a.bins[i]?.count || 0) / totA) * 100 : 0)
  const shareB = (i) => (totB ? ((b?.bins?.[i]?.count || 0) / totB) * 100 : 0)
  const sc = useMemo(() => {
    let m = 1
    for (let i = 0; i < n; i++) m = Math.max(m, shareA(i), shareB(i))
    return niceScale(0, m, 3)
  }, [a, b, n]) // eslint-disable-line react-hooks/exhaustive-deps
  const lo = n ? base[0].lo : 0
  const hiX = n ? base[n - 1].hi : 1
  const X = (v) => pad.l + ((v - lo) / (hiX - lo || 1)) * plotW
  const Y = (v) => pad.t + plotH - (v / (sc.max || 1)) * plotH
  const xt = useMemo(() => niceScale(lo, hiX, Math.max(2, Math.floor(plotW / 70))).ticks.filter((t) => t >= lo - 1e-9 && t <= hiX + 1e-9), [lo, hiX, plotW])
  function move(e) {
    const r = e.currentTarget.getBoundingClientRect()
    const v = lo + ((e.clientX - r.left - pad.l) / plotW) * (hiX - lo)
    const i = base.findIndex((x) => v >= x.lo && v < x.hi)
    setHi(i >= 0 ? i : null)
  }
  const med = (v) => (isNum(v) && v >= lo && v <= hiX ? <path d={`M${X(v) - 4},${pad.t + plotH + 1}h8l-4,-6z`} /> : null)
  return (
    <div className="n-chart" ref={ref} style={{ height }}>
      {w > 0 && n > 0 && (
        <>
          <svg width={w} height={height} role="img" aria-label={label}>
            {sc.ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? 'axis' : 'grid'} x1={pad.l} x2={pad.l + plotW} y1={Y(t)} y2={Y(t)} />
                <text x={pad.l - 6} y={Y(t) + 3.5} textAnchor="end">{fmtTick(t, sc.step)}%</text>
              </g>
            ))}
            {base.map((bn, i) => {
              const bw = Math.max(1, X(bn.hi) - X(bn.lo) - 2)
              return (
                <g key={i} opacity={hi == null || hi === i ? 1 : 0.55}>
                  {totA > 0 && <path d={barPath(X(bn.lo) + 1, bw, Y(0), Y(shareA(i)), Math.min(4, bw / 2))} fill="var(--n-bench)" opacity="0.5" />}
                  {totB > 0 && <path d={barPath(X(bn.lo) + 1, bw, Y(0), Y(shareB(i)), Math.min(4, bw / 2))} fill="var(--n-blue)" opacity="0.82" />}
                </g>
              )
            })}
            {xt.map((t) => <text key={t} x={X(t)} y={height - 3} textAnchor="middle">{xFormat(t)}</text>)}
            <g fill="var(--n-bench)" stroke="var(--n-surface)" strokeWidth="1">{med(a?.p50)}</g>
            <g fill="var(--n-blue)" stroke="var(--n-surface)" strokeWidth="1">{med(b?.p50)}</g>
            <rect x={pad.l} y={pad.t} width={plotW} height={plotH} fill="transparent" onMouseMove={move} onMouseLeave={() => setHi(null)} />
          </svg>
          {hi != null && (
            <div className="n-tip" style={{ top: pad.t, ...tipPos((X(base[hi].lo) + X(base[hi].hi)) / 2, w, 190) }}>
              <div className="t">{xFormat(base[hi].lo)} → {xFormat(base[hi].hi)}{unit}</div>
              <div className="r"><span><i style={{ background: 'var(--n-bench)' }} />{aLabel}</span><b>{fmtNum(a?.bins?.[hi]?.count ?? 0, 0)} · {fmtNum(shareA(hi), 1)}%</b></div>
              <div className="r"><span><i style={{ background: 'var(--n-blue)' }} />{bLabel}</span><b>{fmtNum(b?.bins?.[hi]?.count ?? 0, 0)} · {fmtNum(shareB(hi), 1)}%</b></div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
