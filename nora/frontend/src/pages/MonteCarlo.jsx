import React, { useState, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

/**
 * MonteCarlo — Unified inline table, no Tab 1/Tab 2.
 * Mỗi kết quả WFA là 1 row, có thể:
 *   - Thấy kết quả MC cũ ngay trên dòng (nếu đã chạy rồi)
 *   - Click ▸ để xem chi tiết / chạy lại
 *   - Khi đang chạy: hiển thị progress bar inline
 *   - Khi xong: kết quả gắn ngay vào hàng
 */
const gateBadge = (g) => {
  if (g === true) return { text: '✓ Nguồn đã qua WFA gate', color: '#10b981' }
  if (g === false) return { text: '⚠ Nguồn KHÔNG qua WFA gate — kết quả chỉ để tham khảo', color: '#ef4444' }
  return { text: 'Chưa kiểm định WFA (chạy trực tiếp từ backtest)', color: '#f59e0b' }
}

export default function MonteCarlo() {
  const location = useLocation()
  const navigate = useNavigate()

  // Danh sách kết quả WFA (source stage trước)
  const [rows, setRows] = useState([])   // { ...wfaItem, mcResult? }
  const [loading, setLoading] = useState(false)

  // expandedId: hàng nào đang mở detail / fan chart
  const [expandedId, setExpandedId] = useState(null)

  // runningMap: job_id -> { progress_pct }
  const [runningMap, setRunningMap] = useState({})
  const [simCount, setSimCount] = useState(1000)

  const [filterPass, setFilterPass] = useState(false)
  const [filterSafe, setFilterSafe] = useState(false)

  const timerRefs = useRef({})

  // ── Load WFA history + MC history, merge ──
  const fetchAll = () => {
    setLoading(true)
    Promise.all([
      fetch('/api/studio/wfa/history?limit=50').then((r) => r.json()).catch(() => ({ history: [] })),
      fetch('/api/studio/monte-carlo/history?limit=100').then((r) => r.json()).catch(() => ({ history: [] })),
    ]).then(([wfaData, mcData]) => {
      // Index MC results by source_wfa_id or strategy_name
      const mcByWfaId = {}
      for (const mc of (mcData.history || [])) {
        const key = mc.source_wfa_id || mc.job_id
        if (!mcByWfaId[key] || mc.created_at > mcByWfaId[key].created_at) {
          mcByWfaId[key] = mc
        }
      }

      const wfaCompleted = (wfaData.history || []).filter((w) => w.status === 'completed')
      const list = wfaCompleted.map((w) => {
        const mc = mcByWfaId[w.job_id] || mcByWfaId[w.source_handle] || (mcData.history || []).find((m) => m.strategy_name === w.strategy_name)
        return { ...w, mcResult: mc || null }
      })

      setRows(list)
      setLoading(false)

      // Auto-open from navigation
      if (location.state?.mcInput) {
        const wfaId = location.state.mcInput.source_wfa_id
        const found = list.find((r) => r.job_id === wfaId)
        if (found) {
          setExpandedId(found.job_id)
          // Auto-run if requested
          if (location.state.autoRun) {
            setTimeout(() => triggerMonteCarlo(found, location.state.mcInput.trades), 400)
          }
        }
      }
    }).catch(() => setLoading(false))
  }

  useEffect(() => {
    fetchAll()
    return () => {
      for (const t of Object.values(timerRefs.current)) clearInterval(t)
    }
  }, [])

  const toggleExpand = (row) => {
    setExpandedId(expandedId === row.job_id ? null : row.job_id)
  }

  const triggerMonteCarlo = async (row, tradesOverride) => {
    const trades = tradesOverride || row.result?.aggregate_oos_trades || []
    if (trades.length === 0) {
      alert('Không có lệnh ngoài mẫu (OOS trades) để mô phỏng.')
      return
    }

    const rowId = row.job_id
    setRunningMap((prev) => ({ ...prev, [rowId]: { progress_pct: 0 } }))
    setExpandedId(null)

    try {
      const res = await fetch('/api/studio/monte-carlo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Gửi source_wfa_id để backend tự lấy lệnh OOS từ job WFA và xác định gate
        body: JSON.stringify({
          source_wfa_id: row.job_id,
          strategy_name: row.strategy_name,
          ...(row.symbol ? { symbol: row.symbol } : {}),
          simulations: Number(simCount),
          trades, // backend bỏ qua khi có source_wfa_id (dùng lệnh OOS của job)
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        const d = err.detail
        const msg = !d ? '' : typeof d === 'string' ? d
          : Array.isArray(d) ? d.map((x) => `${(x.loc || []).join('.')}: ${x.msg}`).join('\n')
          : d.message ? [d.message, ...(d.issues || [])].join('\n') : JSON.stringify(d)
        throw new Error(msg || 'Lỗi khởi chạy Monte Carlo')
      }
      const jobData = await res.json()
      const jobId = jobData.job_id

      let attempts = 0
      const timer = setInterval(async () => {
        attempts++
        try {
          const resultRes = await fetch(`/api/studio/monte-carlo/${jobId}/result`)
          if (resultRes.ok) {
            const finalRes = await resultRes.json()
            if (finalRes.simulations) {
              clearInterval(timer)
              delete timerRefs.current[rowId]
              setRunningMap((prev) => { const n = { ...prev }; delete n[rowId]; return n })
              const mcResult = {
                job_id: jobId,
                status: 'completed',
                result: finalRes,
                risk_of_ruin_pct: finalRes.risk_of_ruin_pct,
                source_gate_passed: finalRes.source_gate_passed,
                robust_passed: finalRes.robust_passed,
                percentile_mdd: finalRes.percentile_mdd,
                summary: finalRes.summary,
                simulations: Number(simCount),
                trades_count: finalRes.trades_count ?? trades.length,
              }
              setRows((prev) => prev.map((r) => r.job_id === rowId ? { ...r, mcResult } : r))
              setExpandedId(rowId) // Open the result row
            }
          }
          if (attempts > 30) {
            clearInterval(timer)
            delete timerRefs.current[rowId]
            setRunningMap((prev) => { const n = { ...prev }; delete n[rowId]; return n })
          }
        } catch {}
      }, 500)
      timerRefs.current[rowId] = timer
    } catch (err) {
      setRunningMap((prev) => { const n = { ...prev }; delete n[row.job_id]; return n })
      alert(`Lỗi: ${err.message}`)
    }
  }

  const formatPct = (v) => (v != null ? `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%` : '—')
  const isSafe = (mc) => {
    if (!mc) return false
    // Backend quyết định: robust_passed = nguồn đã qua WFA gate VÀ ruin <= max_ruin_pct
    const robust = mc.robust_passed ?? mc.result?.robust_passed
    return robust === true && (mc.percentile_mdd?.p95 ?? 100) <= 20
  }

  const displayedRows = filterPass
    ? rows.filter((r) => r.acceptance_gate_passed)
    : filterSafe
    ? rows.filter((r) => isSafe(r.mcResult))
    : rows

  // ── High-Precision Quant Fan Chart Visualizer ──
  const renderFanChart = (mcData) => {
    const q = mcData?.result?.quantile_curves || mcData?.quantile_curves
    const paths = mcData?.result?.sample_paths || mcData?.sample_paths || []
    if (!q && !paths?.length) {
      return (
        <div style={{ color: 'var(--ink-3)', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
          Không có dữ liệu Fan Chart để hiển thị.
        </div>
      )
    }

    const W = 760, H = 220, padL = 60, padR = 24, padT = 20, padB = 28
    const plotW = W - padL - padR
    const plotH = H - padT - padB

    let minV = Infinity, maxV = -Infinity
    if (q) {
      minV = Math.min(...q.worst, ...q.p5, 10000)
      maxV = Math.max(...q.best, ...q.p95, 10000)
    } else {
      for (const p of paths) {
        for (const v of p) {
          if (v < minV) minV = v
          if (v > maxV) maxV = v
        }
      }
    }
    minV = Math.floor(Math.min(9000, minV * 0.96) / 500) * 500
    maxV = Math.ceil(Math.max(11000, maxV * 1.04) / 500) * 500
    const vRange = maxV - minV || 1

    const numSteps = q ? q.steps : (paths[0]?.length || 10)
    const sx = (i) => padL + (i / Math.max(1, numSteps - 1)) * plotW
    const sy = (v) => padT + plotH - ((v - minV) / vRange) * plotH

    // Build SVG Polygons for Quantile Bands
    let polyP5P95 = ''
    let polyP25P75 = ''
    if (q && q.p5 && q.p95) {
      const topPts = q.p95.map((v, i) => `${sx(i)},${sy(v)}`).join(' ')
      const btmPts = q.p5.map((v, i) => `${sx(numSteps - 1 - i)},${sy(q.p5[numSteps - 1 - i])}`).join(' ')
      polyP5P95 = `${topPts} ${btmPts}`
    }
    if (q && q.p25 && q.p75) {
      const topPts = q.p75.map((v, i) => `${sx(i)},${sy(v)}`).join(' ')
      const btmPts = q.p25.map((v, i) => `${sx(numSteps - 1 - i)},${sy(q.p25[numSteps - 1 - i])}`).join(' ')
      polyP25P75 = `${topPts} ${btmPts}`
    }

    const gridDivs = 4
    const gridVals = Array.from({ length: gridDivs + 1 }, (_, i) => minV + (i / gridDivs) * vRange)

    return (
      <div style={{ position: 'relative', width: '100%', overflowX: 'auto' }}>
        <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', background: 'var(--surface-2)', borderRadius: 8 }}>
          <defs>
            <linearGradient id="cloudOuter" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0.06" />
            </linearGradient>
            <linearGradient id="cloudInner" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#059669" stopOpacity="0.45" />
              <stop offset="100%" stopColor="#059669" stopOpacity="0.18" />
            </linearGradient>
          </defs>

          {/* Grid lines & Y-labels */}
          {gridVals.map((v, i) => {
            const y = sy(v)
            return (
              <g key={i}>
                <line x1={padL} y1={y} x2={W - padR} y2={y} stroke="var(--line)" strokeDasharray="3 3" opacity={0.6} />
                <text x={padL - 8} y={y + 3.5} textAnchor="end" fontSize="10" fill="var(--ink-3)" fontFamily="monospace">
                  ${(v / 1000).toFixed(1)}k
                </text>
              </g>
            )
          })}

          {/* Baseline Reference (Initial capital $10,000) */}
          <line
            x1={padL}
            y1={sy(10000)}
            x2={W - padR}
            y2={sy(10000)}
            stroke="rgba(239, 68, 68, 0.65)"
            strokeDasharray="4 3"
            strokeWidth="1.5"
          />
          <text x={W - padR - 4} y={sy(10000) - 5} textAnchor="end" fontSize="9.5" fill="rgba(239, 68, 68, 0.85)" fontWeight="600">
            Vốn gốc $10k
          </text>

          {/* Quantile Cloud Bands */}
          {polyP5P95 && <polygon points={polyP5P95} fill="url(#cloudOuter)" />}
          {polyP25P75 && <polygon points={polyP25P75} fill="url(#cloudInner)" />}

          {/* Raw individual sample paths */}
          {paths.map((path, pi) => (
            <polyline
              key={pi}
              points={path.map((v, si) => `${sx(si)},${sy(v)}`).join(' ')}
              fill="none"
              stroke="rgba(59, 130, 246, 0.12)"
              strokeWidth="1"
            />
          ))}

          {/* Quantile Curves */}
          {q && (
            <>
              {/* Best Scenario */}
              <polyline
                points={q.best.map((v, i) => `${sx(i)},${sy(v)}`).join(' ')}
                fill="none"
                stroke="#22c55e"
                strokeWidth="1.5"
                strokeDasharray="4 2"
                opacity={0.8}
              />
              {/* Worst Scenario */}
              <polyline
                points={q.worst.map((v, i) => `${sx(i)},${sy(v)}`).join(' ')}
                fill="none"
                stroke="#f59e0b"
                strokeWidth="1.5"
                strokeDasharray="4 2"
                opacity={0.8}
              />
              {/* Median Line (P50) */}
              <polyline
                points={q.p50.map((v, i) => `${sx(i)},${sy(v)}`).join(' ')}
                fill="none"
                stroke="#10b981"
                strokeWidth="2.5"
                strokeLinecap="round"
              />
            </>
          )}

          {/* X-axis labels */}
          <text x={padL} y={H - 8} fontSize="9.5" fill="var(--ink-3)">Bắt đầu</text>
          <text x={padL + plotW / 2} y={H - 8} textAnchor="middle" fontSize="9.5" fill="var(--ink-3)">Tiến trình các lệnh OOS</text>
          <text x={W - padR} y={H - 8} textAnchor="end" fontSize="9.5" fill="var(--ink-3)">Kết thúc</text>
        </svg>

        {/* Legend strip */}
        <div style={{ display: 'flex', gap: 14, justifyContent: 'center', marginTop: 8, fontSize: 11, color: 'var(--ink-2)' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 12, height: 3, background: '#10b981', borderRadius: 2 }} /> Median (P50)
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, background: 'rgba(16, 185, 129, 0.45)', borderRadius: 2 }} /> Vùng tin cậy 50% (P25-P75)
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, background: 'rgba(16, 185, 129, 0.20)', borderRadius: 2 }} /> Vùng tin cậy 90% (P5-P95)
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 12, height: 2, background: '#f59e0b', borderTop: '1px dashed #f59e0b' }} /> Kịch bản tệ nhất
          </span>
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* ── Page Header ── */}
      <div className="head" style={{ paddingBottom: 12, borderBottom: '1px solid var(--line)' }}>
        <div className="head-row">
          <div>
            <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span>Mô phỏng Rủi ro Monte Carlo</span>
              <span className="tag run" style={{ fontSize: 12 }}>Stage 3</span>
            </h1>
            <p style={{ margin: '4px 0 0', color: 'var(--ink-3)', fontSize: 13 }}>
              Chọn kết quả WFA, bấm chạy Monte Carlo inline. Kết quả và Fan Chart hiển thị ngay trên dòng.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>Kịch bản:</label>
            <select
              className="input"
              value={simCount}
              onChange={(e) => setSimCount(Number(e.target.value))}
              style={{ fontSize: 12, padding: '3px 8px' }}
            >
              <option value={1000}>1,000</option>
              <option value={5000}>5,000</option>
              <option value={10000}>10,000</option>
            </select>
            <button
              className={`btn ${!filterPass && !filterSafe ? 'active' : ''}`}
              onClick={() => { setFilterPass(false); setFilterSafe(false) }}
              style={{ fontSize: 12, background: !filterPass && !filterSafe ? '#3b82f6' : 'transparent', color: !filterPass && !filterSafe ? '#fff' : 'var(--ink)' }}
            >
              Tất cả ({rows.length})
            </button>
            <button
              className={`btn ${filterPass ? 'active' : ''}`}
              onClick={() => { setFilterPass(true); setFilterSafe(false) }}
              style={{ fontSize: 12, background: filterPass ? '#3b82f6' : 'transparent', color: filterPass ? '#fff' : 'var(--ink)' }}
            >
              WFA PASS ({rows.filter((r) => r.acceptance_gate_passed).length})
            </button>
            <button
              className={`btn ${filterSafe ? 'active' : ''}`}
              onClick={() => { setFilterSafe(true); setFilterPass(false) }}
              style={{ fontSize: 12, background: filterSafe ? '#10b981' : 'transparent', color: filterSafe ? '#fff' : 'var(--ink)' }}
            >
              ✓ MC PASS ({rows.filter((r) => isSafe(r.mcResult)).length})
            </button>
            <button className="btn" onClick={fetchAll} style={{ fontSize: 12 }}>🔄</button>
          </div>
        </div>
      </div>

      {/* ── Unified Table ── */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-3)' }}>Đang nạp dữ liệu...</div>
        ) : rows.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-3)' }}>
            Chưa có kết quả WFA nào. Hãy sang <strong>WFA</strong> để kiểm định chiến lược trước.
          </div>
        ) : displayedRows.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-3)' }}>
            Không có bộ tham số nào thỏa mãn bộ lọc hiện tại.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
            <thead style={{ background: 'var(--surface-2)', position: 'sticky', top: 0, zIndex: 2 }}>
              <tr>
                <th style={{ width: 30, padding: '8px 6px' }}></th>
                <th style={{ textAlign: 'left', padding: '8px 10px' }}>Chiến lược WFA</th>
                <th style={{ textAlign: 'left', padding: '8px 8px' }}>Coin</th>
                <th style={{ textAlign: 'center', padding: '8px 8px' }}>WFA Gate</th>
                <th style={{ textAlign: 'right', padding: '8px 8px', color: '#3b82f6' }}>OOS PnL TB</th>
                <th style={{ textAlign: 'right', padding: '8px 8px', color: '#3b82f6' }}>Worst MDD</th>
                <th style={{ textAlign: 'right', padding: '8px 8px', color: '#3b82f6' }}>OOS Trades</th>
                <th style={{ textAlign: 'center', padding: '8px 8px', color: '#10b981' }}>MC Ruin</th>
                <th style={{ textAlign: 'center', padding: '8px 8px', color: '#10b981' }}>P95 VaR MDD</th>
                <th style={{ textAlign: 'center', padding: '8px 8px', color: '#10b981' }}>MC Gate</th>
                <th style={{ textAlign: 'right', padding: '8px 12px' }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {displayedRows.map((row) => {
                const isExpanded = expandedId === row.job_id
                const isRunning = !!runningMap[row.job_id]
                const hasMc = !!row.mcResult
                const mc = row.mcResult
                const safe = isSafe(mc)
                const passed = row.acceptance_gate_passed
                const oosRet = row.avg_oos_return_pct
                const worstMdd = row.worst_fold_mdd_pct
                const oosTrades = row.result?.total_oos_trades || row.total_oos_trades || 0
                const ruin = mc?.risk_of_ruin_pct
                const p95 = mc?.percentile_mdd?.p95

                return (
                  <React.Fragment key={row.job_id}>
                    {/* ── Main row ── */}
                    <tr
                      style={{
                        background: isExpanded ? 'rgba(16,185,129,0.05)' : hasMc ? 'rgba(16,185,129,0.02)' : 'transparent',
                        borderBottom: isExpanded ? 'none' : '1px solid var(--line)',
                        cursor: 'pointer',
                        transition: 'background 0.15s',
                      }}
                      onClick={() => !isRunning && toggleExpand(row)}
                    >
                      <td style={{ textAlign: 'center', padding: '10px 6px', color: isRunning ? '#3b82f6' : '#10b981' }}>
                        {isRunning ? '⚙' : isExpanded ? '▾' : '▸'}
                      </td>
                      <td style={{ padding: '10px 10px', fontWeight: 600, maxWidth: 220 }}>
                        <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {row.strategy_name}
                        </div>
                        {isRunning && (
                          <div style={{ marginTop: 4 }}>
                            <div style={{ height: 4, background: 'var(--line)', borderRadius: 2, overflow: 'hidden', width: 160 }}>
                              <div style={{ height: '100%', background: '#10b981', transition: 'width 0.3s' }} />
                            </div>
                            <div style={{ fontSize: 10, color: '#10b981', marginTop: 1 }}>Đang mô phỏng {simCount.toLocaleString()} kịch bản...</div>
                          </div>
                        )}
                      </td>
                      <td style={{ padding: '10px 8px' }}>
                        <span className="tag" style={{ fontSize: 10.5 }}>{row.symbol}</span>
                      </td>
                      <td style={{ textAlign: 'center', padding: '10px 8px' }}>
                        <span className="tag" style={{
                          background: passed ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                          color: passed ? '#10b981' : '#f59e0b', fontSize: 11,
                        }}>
                          {passed ? '✓ ĐẠT' : '⚠ CẢNH'}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right', padding: '10px 8px', fontWeight: 600,
                        color: oosRet == null ? 'var(--ink-3)' : oosRet >= 0 ? '#10b981' : '#ef4444' }}>
                        {oosRet != null ? formatPct(oosRet) : '—'}
                      </td>
                      <td style={{ textAlign: 'right', padding: '10px 8px',
                        color: worstMdd == null ? 'var(--ink-3)' : worstMdd <= 15 ? '#10b981' : '#f59e0b' }}>
                        {worstMdd != null ? `${Number(worstMdd).toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ textAlign: 'right', padding: '10px 8px' }}>
                        {oosTrades > 0 ? oosTrades.toLocaleString() : '—'}
                      </td>
                      {/* Monte Carlo result columns */}
                      <td style={{ textAlign: 'center', padding: '10px 8px',
                        fontWeight: hasMc ? 700 : 400,
                        color: ruin == null ? 'var(--ink-3)' : ruin === 0 ? '#10b981' : '#ef4444' }}>
                        {ruin != null ? `${Number(ruin).toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ textAlign: 'center', padding: '10px 8px',
                        color: p95 == null ? 'var(--ink-3)' : p95 <= 20 ? '#10b981' : '#f59e0b' }}>
                        {p95 != null ? `${Number(p95).toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ textAlign: 'center', padding: '10px 8px' }}>
                        {hasMc ? (
                          <span className="tag" style={{
                            background: safe ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
                            color: safe ? '#10b981' : '#ef4444', fontSize: 11,
                          }}>
                            {safe ? '✓ AN TOÀN' : '⚠ RỦI RO'}
                          </span>
                        ) : '—'}
                      </td>
                      {/* Actions */}
                      <td style={{ textAlign: 'right', padding: '10px 12px' }} onClick={(e) => e.stopPropagation()}>
                        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                          {!isRunning && (
                            <button
                              className="btn btn-primary"
                              onClick={(e) => { e.stopPropagation(); triggerMonteCarlo(row) }}
                              style={{ fontSize: 11, padding: '3px 8px', background: '#10b981', borderColor: '#10b981' }}
                            >
                              {hasMc ? '🔄 Chạy lại' : '🎲 Chạy Carlo'}
                            </button>
                          )}
                          {!isRunning && (
                            <button
                              className="btn"
                              onClick={(e) => { e.stopPropagation(); toggleExpand(row) }}
                              style={{ fontSize: 11, padding: '3px 8px', background: isExpanded ? 'var(--surface-2)' : 'transparent' }}
                            >
                              {isExpanded ? 'Đóng ▴' : 'Kết quả ▾'}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* ── Expanded: Fan Chart + Tail Risk ── */}
                    {isExpanded && !isRunning && (
                      <tr style={{ borderBottom: '1px solid var(--line)' }}>
                        <td colSpan={11} style={{ padding: '0 12px 16px 40px', background: 'rgba(16,185,129,0.03)' }}>
                          {!hasMc ? (
                            <div style={{ padding: '16px 0', color: 'var(--ink-3)', fontSize: 13 }}>
                              Chưa có kết quả Monte Carlo nào cho bộ tham số này. Bấm <strong>🎲 Chạy Carlo</strong> để bắt đầu.
                            </div>
                          ) : (
                            <div style={{ paddingTop: 12 }}>
                              {(() => {
                                const b = gateBadge(mc.source_gate_passed ?? mc.result?.source_gate_passed)
                                return <div style={{ fontSize: 12, fontWeight: 600, color: b.color, marginBottom: 10 }}>{b.text}</div>
                              })()}
                              {/* 5 Metrics */}
                              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 14 }}>
                                {[
                                  { label: 'Xác suất cháy (Ruin)', val: `${Number(mc.risk_of_ruin_pct ?? 0).toFixed(1)}%`, color: (mc.risk_of_ruin_pct ?? 0) === 0 ? '#10b981' : '#ef4444' },
                                  { label: 'Median MDD (P50)', val: `${mc.percentile_mdd?.p50?.toFixed(2) ?? '—'}%`, color: 'var(--ink)' },
                                  { label: 'P90 VaR MDD', val: `${mc.percentile_mdd?.p90?.toFixed(2) ?? '—'}%`, color: '#f59e0b' },
                                  { label: 'P95 VaR MDD', val: `${mc.percentile_mdd?.p95?.toFixed(2) ?? '—'}%`, color: '#f59e0b' },
                                  { label: 'Win ratio kịch bản', val: `${mc.summary?.win_ratio_of_simulations?.toFixed(1) ?? '—'}%`, color: '#10b981' },
                                ].map((m, i) => (
                                  <div key={i} style={{ background: 'var(--surface-1)', border: '1px solid var(--line)', padding: '8px 12px', borderRadius: 6 }}>
                                    <div style={{ fontSize: 10.5, color: 'var(--ink-3)', marginBottom: 2 }}>{m.label}</div>
                                    <div style={{ fontSize: 16, fontWeight: 700, color: m.color }}>{m.val}</div>
                                  </div>
                                ))}
                              </div>
                              {/* Fan Chart */}
                              <div style={{ background: 'var(--surface-1)', border: '1px solid var(--line)', borderRadius: 6, padding: '10px 14px' }}>
                                <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 8 }}>
                                  Equity Fan Chart · {mc.simulations?.toLocaleString()} kịch bản · {mc.trades_count} lệnh OOS
                                </div>
                                {renderFanChart(mc)}
                              </div>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
