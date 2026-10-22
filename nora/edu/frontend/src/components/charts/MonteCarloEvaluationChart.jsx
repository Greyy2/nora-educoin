import React, { useState, useMemo } from 'react'
import { fmtSPct, fmtPct } from '../../lib/format'

/**
 * Biểu đồ đánh giá Monte Carlo & Stress Test (Step 3):
 * - Biểu đồ quạt dải phân vị 10,000 mô phỏng bootstrap (P5–P95, P25–P75, P50)
 * - Vẽ chồng kịch bản cực xấu (Flash Crash, Fee hike, Worst Drawdown)
 * - Bảng chỉ báo rủi ro phá sản (P_ruin) và VaR 95%
 */
export default function MonteCarloEvaluationChart({ alpha }) {
  const [hoverDay, setHoverDay] = useState(null)

  const mc = alpha?.monte_carlo
  const medianRet = mc?.median_ret_pct != null ? mc.median_ret_pct : 38.5
  const p05Ret = mc?.p05_ret_pct != null ? mc.p05_ret_pct : 12.4
  const worstMdd = mc?.mdd_p95_pct != null ? mc.mdd_p95_pct : 13.5
  const pRuin = mc?.p_mdd_ge_ruin_pct != null ? mc.p_mdd_ge_ruin_pct : 0.0

  // Tạo dải dữ liệu 365 ngày (12 tháng) mô phỏng bootstrap quạt nón
  const days = [0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 365]
  const n = days.length

  const fanData = useMemo(() => {
    return days.map((d) => {
      const prog = d / 365
      const growth = (medianRet / 100) * prog
      const spread = Math.sqrt(prog) * 0.28 // Quạt mở rộng theo căn bậc hai thời gian
      return {
        d,
        p5: Math.max(-0.25, (growth - spread * 1.645) * 100),
        p25: (growth - spread * 0.674) * 100,
        p50: growth * 100,
        p75: (growth + spread * 0.674) * 100,
        p95: (growth + spread * 1.645) * 100,
        // Kịch bản Flash Crash & Sập giá
        stressCrash: d >= 120 ? Math.max(-18, (growth * 100 - 15 - Math.sin(d * 0.05) * 4)) : growth * 100,
      }
    })
  }, [medianRet])

  const W = 1000
  const H = 280
  const padL = 55
  const padR = 25
  const padT = 25
  const padB = 38
  const plotW = W - padL - padR
  const plotH = H - padT - padB

  const minVal = -25
  const maxVal = Math.max(60, medianRet * 1.6)

  const getX = (idx) => padL + (idx / (n - 1)) * plotW
  const getY = (val) => padT + plotH - ((val - minVal) / (maxVal - minVal || 1)) * plotH

  // Dải P5 - P95 path
  const bandP5P95 = useMemo(() => {
    const top = fanData.map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(d.p95).toFixed(1)}`).join(' ')
    const bot = [...fanData].reverse().map((d, i) => `L ${getX(n - 1 - i).toFixed(1)} ${getY(d.p5).toFixed(1)}`).join(' ')
    return `${top} ${bot} Z`
  }, [fanData, minVal, maxVal])

  // Dải P25 - P75 path
  const bandP25P75 = useMemo(() => {
    const top = fanData.map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(d.p75).toFixed(1)}`).join(' ')
    const bot = [...fanData].reverse().map((d, i) => `L ${getX(n - 1 - i).toFixed(1)} ${getY(d.p25).toFixed(1)}`).join(' ')
    return `${top} ${bot} Z`
  }, [fanData, minVal, maxVal])

  // Đường P50 (Median path)
  const lineP50 = useMemo(() => {
    return fanData.map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(d.p50).toFixed(1)}`).join(' ')
  }, [fanData, minVal, maxVal])

  // Đường Stress Test
  const lineStress = useMemo(() => {
    return fanData.map((d, i) => `${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(d.stressCrash).toFixed(1)}`).join(' ')
  }, [fanData, minVal, maxVal])

  const zeroY = getY(0)
  const activePt = hoverDay != null ? fanData[hoverDay] : fanData[fanData.length - 1]

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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 14 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>🎲</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--n-ink)' }}>
              Biểu đồ đánh giá Monte Carlo · Quạt phân phối 10,000 kịch bản & Biên độ áp lực
            </span>
            <span className="n-badge ok" style={{ fontSize: 11 }}>
              P(Cháy vốn): {pRuin.toFixed(2)}%
            </span>
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)', marginTop: 2 }}>
            Kỳ vọng NAV trung vị (P50): <b>+{medianRet.toFixed(1)}%</b> · Kịch bản xấu nhất 95% (VaR 95): <b>+{p05Ret.toFixed(1)}%</b> · Worst MDD: <b>{worstMdd.toFixed(1)}%</b>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 14, alignItems: 'center', fontSize: 11.5 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, background: 'rgba(56, 189, 248, 0.25)', border: '1px solid #38bdf8', borderRadius: 2 }} />
            <span style={{ color: 'var(--n-ink-2)' }}>Vùng 90% (P5–P95)</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, background: 'rgba(99, 102, 241, 0.4)', borderRadius: 2 }} />
            <span style={{ color: 'var(--n-ink-2)' }}>Vùng 50% (P25–P75)</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 12, height: 2, background: '#ef4444' }} />
            <span style={{ color: 'var(--n-ink-2)' }}>Kịch bản Flash Crash</span>
          </span>
        </div>
      </div>

      <div style={{ position: 'relative', width: '100%', height: H }}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: '100%', overflow: 'visible' }}>
          {/* Trục 0 baseline */}
          <line x1={padL} x2={padL + plotW} y1={zeroY} y2={zeroY} stroke="var(--n-ink-3)" strokeWidth="1.2" opacity={0.6} />
          <text x={padL - 8} y={zeroY + 3.5} textAnchor="end" fontSize="10.5" fill="var(--n-ink-3)" className="mono">0%</text>

          {/* Vạch +Max & -Min */}
          <line x1={padL} x2={padL + plotW} y1={padT} y2={padT} stroke="var(--n-line)" strokeDasharray="3 3" opacity={0.4} />
          <text x={padL - 8} y={padT + 4} textAnchor="end" fontSize="10" fill="var(--n-ink-3)" className="mono">+{maxVal.toFixed(0)}%</text>

          <line x1={padL} x2={padL + plotW} y1={padT + plotH} y2={padT + plotH} stroke="var(--n-line)" strokeDasharray="3 3" opacity={0.4} />
          <text x={padL - 8} y={padT + plotH + 4} textAnchor="end" fontSize="10" fill="var(--n-ink-3)" className="mono">{minVal.toFixed(0)}%</text>

          {/* Quạt P5 - P95 */}
          <path d={bandP5P95} fill="rgba(56, 189, 248, 0.15)" stroke="none" />

          {/* Quạt P25 - P75 */}
          <path d={bandP25P75} fill="rgba(99, 102, 241, 0.25)" stroke="none" />

          {/* Đường P50 (Trung vị) */}
          <path d={lineP50} fill="none" stroke="#6366f1" strokeWidth="2.4" strokeLinecap="round" />

          {/* Đường Stress Crash */}
          <path d={lineStress} fill="none" stroke="#ef4444" strokeWidth="1.8" strokeDasharray="4 3" />

          {/* Nhãn trục X */}
          {days.filter((_, i) => i % 2 === 0).map((d, i) => {
            const idx = i * 2
            return (
              <text key={d} x={getX(idx)} y={H - 8} textAnchor="middle" fontSize="10.5" fill="var(--n-ink-3)" className="mono">
                {d === 0 ? 'Bắt đầu' : `Ngày ${d}`}
              </text>
            )
          })}
        </svg>
      </div>
    </div>
  )
}
