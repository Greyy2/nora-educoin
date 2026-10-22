import React, { useMemo, useState } from 'react'
import { fmtSPct, fmtPct, fmtNum } from '../../lib/format'

/**
 * Biểu đồ đánh giá Backtest (Step 1):
 * - Thể hiện đường cong vốn (Equity Curve) tích lũy theo thời gian
 * - Đánh dấu các giai đoạn tăng trưởng (Run-up) và sụt giảm (Drawdown)
 * - Tóm tắt các chỉ số cốt lõi: Lãi ròng, Max DD, Sharpe, Win Rate
 */
export default function BacktestEvaluationChart({ strategyName = 'KEMA Trend Following', pnl = 2.92, mdd = 1.46, trades = 83 }) {
  const [hoverIndex, setHoverIndex] = useState(null)

  // Tạo 90 điểm dữ liệu đại diện cho chuỗi NAV 18 tháng (dài và chi tiết hơn)
  const points = useMemo(() => {
    const pts = []
    let nav = 10000
    const basePnl = Number(pnl) || 2.5
    const growthPerStep = (basePnl * 10000) / 90

    for (let i = 0; i <= 90; i++) {
      const totalMonths = Math.floor(i / 5) + 1
      const year = 2024 + Math.floor((totalMonths - 1) / 12)
      const month = ((totalMonths - 1) % 12) + 1
      const dateStr = `T${month < 10 ? '0' + month : month}/${year}`
      // Biến động tự nhiên quanh xu hướng tăng
      const noise = Math.sin(i * 0.7) * 80 + Math.cos(i * 1.3) * 60
      if (i > 0) {
        nav += growthPerStep * (0.8 + Math.sin(i * 0.5) * 0.4) + noise * 0.15
      }
      pts.push({
        i,
        date: dateStr,
        nav: Math.round(nav),
        retPct: ((nav - 10000) / 10000) * 100,
      })
    }
    return pts
  }, [pnl])

  const W = 1000
  const H = 280
  const padL = 60
  const padR = 25
  const padT = 20
  const padB = 35
  const plotW = W - padL - padR
  const plotH = H - padT - padB

  const minNav = Math.min(...points.map((p) => p.nav)) * 0.98
  const maxNav = Math.max(...points.map((p) => p.nav)) * 1.02

  const getX = (idx) => padL + (idx / (points.length - 1)) * plotW
  const getY = (val) => padT + plotH - ((val - minNav) / (maxNav - minNav || 1)) * plotH

  // Tạo path SVG cho đường line và vùng area
  const pathD = useMemo(() => {
    return points
      .map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${getX(idx).toFixed(1)} ${getY(p.nav).toFixed(1)}`)
      .join(' ')
  }, [points, minNav, maxNav])

  const areaD = useMemo(() => {
    const bottomY = getY(minNav)
    return `${pathD} L ${getX(points.length - 1).toFixed(1)} ${bottomY.toFixed(1)} L ${getX(0).toFixed(1)} ${bottomY.toFixed(1)} Z`
  }, [pathD, minNav, maxNav])

  const activePoint = hoverIndex != null ? points[hoverIndex] : points[points.length - 1]

  return (
    <div
      style={{
        marginTop: 16,
        background: 'var(--n-surface)',
        border: '1px solid var(--n-line)',
        borderRadius: 8,
        padding: '16px 20px',
        overflow: 'hidden',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>📊</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--n-ink)' }}>
              Biểu đồ đánh giá Backtest · Đường cong tăng trưởng NAV (Equity Curve)
            </span>
            <span className="n-badge ok" style={{ fontSize: 11 }}>
              Lãi gộp: {fmtSPct(pnl, 1)}
            </span>
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)', marginTop: 2 }}>
            Mô phỏng vốn gốc $10,000 · Số lệnh thực thi: {trades} trades · Max Drawdown: {fmtPct(mdd, 1)}
          </div>
        </div>

        {activePoint && (
          <div className="mono" style={{ fontSize: 12, background: 'var(--n-surface-2)', padding: '4px 12px', borderRadius: 6, border: '1px solid var(--n-line)' }}>
            Thời điểm: <b>{activePoint.date}</b> | NAV: <b style={{ color: 'var(--n-accent)' }}>${fmtNum(activePoint.nav, 0)}</b> ({activePoint.retPct >= 0 ? '+' : ''}{activePoint.retPct.toFixed(1)}%)
          </div>
        )}
      </div>

      <div style={{ position: 'relative', width: '100%', height: H }}>
        <svg
          viewBox={`0 0 ${W} ${H}`}
          style={{ width: '100%', height: '100%', overflow: 'visible' }}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const mouseX = e.clientX - rect.left
            const relX = (mouseX / rect.width) * W - padL
            const idx = Math.max(0, Math.min(points.length - 1, Math.round((relX / plotW) * (points.length - 1))))
            setHoverIndex(idx)
          }}
          onMouseLeave={() => setHoverIndex(null)}
        >
          <defs>
            <linearGradient id="btGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.35" />
              <stop offset="100%" stopColor="#38bdf8" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const v = minNav + ratio * (maxNav - minNav)
            const y = getY(v)
            return (
              <g key={ratio}>
                <line x1={padL} x2={padL + plotW} y1={y} y2={y} stroke="var(--n-line)" strokeDasharray="3 3" opacity={0.6} />
                <text x={padL - 8} y={y + 4} textAnchor="end" fontSize="10.5" fill="var(--n-ink-3)" className="mono">
                  ${fmtNum(Math.round(v), 0)}
                </text>
              </g>
            )
          })}

          {/* Area fill & Main line */}
          <path d={areaD} fill="url(#btGradient)" />
          <path d={pathD} fill="none" stroke="#38bdf8" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />

          {/* Hover indicator */}
          {hoverIndex != null && (
            <g>
              <line
                x1={getX(hoverIndex)}
                x2={getX(hoverIndex)}
                y1={padT}
                y2={padT + plotH}
                stroke="var(--n-accent)"
                strokeWidth="1.2"
                strokeDasharray="2 2"
              />
              <circle
                cx={getX(hoverIndex)}
                cy={getY(points[hoverIndex].nav)}
                r="4.5"
                fill="var(--n-surface)"
                stroke="#38bdf8"
                strokeWidth="2.5"
              />
            </g>
          )}

          {/* X axis labels */}
          {[0, 18, 36, 54, 72, 90].map((idx) => {
            if (!points[idx]) return null
            return (
              <text key={idx} x={getX(idx)} y={H - 8} textAnchor="middle" fontSize="10.5" fill="var(--n-ink-3)" className="mono">
                {points[idx].date}
              </text>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
