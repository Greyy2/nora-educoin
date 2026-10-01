import React, { useState, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'

/**
 * Wfa — Unified inline table, no Tab 1/2.
 * Mỗi bộ tham số Backtest là 1 row, có thể:
 *   - Thấy kết quả cũ ngay trên dòng (nếu đã chạy WFA rồi)
 *   - Click ▸ mở phần cấu hình WFA inline và chạy
 *   - Khi đang chạy: hiển thị progress bar thay cho config
 *   - Khi xong: kết quả gắn luôn vào hàng, cột WFA được tô màu
 */
export default function Wfa() {
  const location = useLocation()
  const navigate = useNavigate()

  // Danh sách các bộ tham số từ Backtest
  const [rows, setRows] = useState([])          // { ...backtestRun, wfaResult?, wfaStatus }
  const [loading, setLoading] = useState(false)

  // expandedId: hàng nào đang mở config WFA
  const [expandedId, setExpandedId] = useState(null)

  // wfaConfig per-row (keyed by source_handle)
  const [configMap, setConfigMap] = useState({})

  // runningMap: source_handle -> { progress_pct, message, current_fold, total_folds }
  const [runningMap, setRunningMap] = useState({})

  // Bộ lọc kết quả
  const [filterPass, setFilterPass] = useState(false)

  const timerRefs = useRef({})

  // Khớp với backend WfaFoldConfig (extra="forbid"): chỉ gửi các field backend hiểu
  const defaultConfig = () => ({
    train_days: 30,
    test_days: 10,
    step_days: 10,
    embargo_days: 0,
    min_folds: 4,
    min_positive_ratio: 0.6,
    min_oos_trades: 30,
    min_is_trades: 10,
    min_oos_profit_pct: 0.0,
    max_oos_mdd_pct: 25.0,
    min_total_oos_profit_pct: 0.0,
  })

  const formatApiError = (detail) => {
    if (!detail) return 'Lỗi không xác định'
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((d) => `${(d.loc || []).join('.')}: ${d.msg}`).join('\n')
    if (detail.message) return [detail.message, ...(detail.issues || [])].join('\n')
    return JSON.stringify(detail)
  }

  // ── Load & merge Backtest runs với WFA history ──
  const fetchAll = () => {
    setLoading(true)
    Promise.all([
      fetch('/api/runs?limit=50').then((r) => r.json()).catch(() => ({ rows: [] })),
      fetch('/api/studio/backtest/history?limit=20').then((r) => r.json()).catch(() => ({ history: [] })),
      fetch('/api/studio/wfa/history?limit=100').then((r) => r.json()).catch(() => ({ history: [] })),
    ]).then(([runsData, studioData, wfaData]) => {
      // Build lookup: source_handle -> latest wfa result
      const wfaByHandle = {}
      for (const w of (wfaData.history || [])) {
        const h = w.source_handle || w.job_id
        if (!wfaByHandle[h] || w.created_at > wfaByHandle[h].created_at) {
          wfaByHandle[h] = w
        }
      }
      // Also index by strategy_name if no handle match
      const wfaByName = {}
      for (const w of (wfaData.history || [])) {
        const n = w.strategy_name
        if (n && (!wfaByName[n] || w.created_at > wfaByName[n].created_at)) {
          wfaByName[n] = w
        }
      }

      const list = []

      // From Studio backtest history
      for (const item of (studioData.history || [])) {
        const handle = item.handle
        const wfa = wfaByHandle[handle] || wfaByName[item.strategy_name]
        list.push({
          id: handle,
          source_handle: handle,
          name: item.strategy_name || 'Studio Simulation',
          symbol: item.symbol || '',
          type: 'Studio',
          trades: item.trades_count || 0,
          return_pct: item.summary?.total_pnl_pct,
          mdd_pct: item.summary?.max_drawdown_pct,
          winrate: item.summary?.winrate,
          sharpe: item.summary?.sharpe_ratio,
          summary: item.summary,
          wfaResult: wfa || null,
          wfaStatus: wfa?.status || null,
        })
      }

      // From Base runs
      for (const r of (runsData.rows || [])) {
        const handle = `run_${r.id}`
        const wfa = wfaByHandle[handle] || wfaByHandle[`run_${r.id}`] || wfaByName[r.name]
        list.push({
          id: handle,
          source_handle: handle,
          run_id: r.id,
          name: r.name || `Run #${r.id}`,
          symbol: r.symbol || '',
          type: 'Base',
          trades: r.trades || 0,
          return_pct: r.return_pct ?? null,
          mdd_pct: r.mdd_pct ?? null,
          winrate: r.winrate ?? null,
          sharpe: r.sharpe ?? null,
          balance: r.balance,
          wfaResult: wfa || null,
          wfaStatus: wfa?.status || null,
        })
      }

      setRows(list)
      setLoading(false)

      // Auto-select from navigation state
      if (location.state?.wfaInput) {
        const navHandle = location.state.wfaInput.source_handle
        const found = list.find((r) => r.source_handle === navHandle)
        if (found) {
          setExpandedId(found.id)
        }
      }
    }).catch(() => setLoading(false))
  }

  // Load metrics for Base runs (lazy, when row expands)
  const loadRunMetrics = async (runId, handle) => {
    try {
      const m = await api.metrics(runId)
      setRows((prev) => prev.map((r) => r.source_handle === handle
        ? {
            ...r,
            return_pct: m.total_pnl_pct ?? r.return_pct,
            mdd_pct: m.max_drawdown_pct ?? r.mdd_pct,
            winrate: m.winrate ?? r.winrate,
            sharpe: m.sharpe_ratio ?? r.sharpe,
          }
        : r
      ))
    } catch {}
  }

  useEffect(() => {
    fetchAll()
    return () => {
      // Cleanup timers
      for (const t of Object.values(timerRefs.current)) clearInterval(t)
    }
  }, [])

  const toggleExpand = (row) => {
    const newId = expandedId === row.id ? null : row.id
    setExpandedId(newId)
    if (newId && row.run_id && !row.return_pct) {
      loadRunMetrics(row.run_id, row.source_handle)
    }
    if (newId && !configMap[row.id]) {
      setConfigMap((prev) => ({ ...prev, [row.id]: defaultConfig() }))
    }
  }

  const updateConfig = (id, patch) => {
    setConfigMap((prev) => ({ ...prev, [id]: { ...(prev[id] || defaultConfig()), ...patch } }))
  }

  const handleRunWfa = async (row) => {
    if (row.type === 'Base') {
      alert('Run legacy (Base) chưa có snapshot AST nên không thể chạy WFA. Hãy chạy lại chiến lược trong Studio.')
      return
    }
    const config = configMap[row.id] || defaultConfig()
    const handle = row.source_handle

    // Mark as running
    setRunningMap((prev) => ({
      ...prev,
      [row.id]: { progress_pct: 0, message: 'Đang khởi chạy WFA...', current_fold: 0, total_folds: 0 },
    }))
    setExpandedId(null) // Close config when running starts

    try {
      const res = await fetch('/api/studio/wfa/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_handle: handle,
          symbol: row.symbol || '',
          config,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(formatApiError(err.detail) || 'Lỗi khởi chạy WFA')
      }
      const jobData = await res.json()
      const jobId = jobData.job_id

      const timer = setInterval(async () => {
        try {
          const progRes = await fetch(`/api/studio/wfa/${jobId}/progress`)
          if (!progRes.ok) return
          const prog = await progRes.json()

          setRunningMap((prev) => ({
            ...prev,
            [row.id]: {
              progress_pct: prog.progress_pct || 0,
              message: prog.message || 'Đang thực thi...',
              current_fold: prog.current_fold || 0,
              total_folds: prog.total_folds || 0,
            },
          }))

          if (prog.status === 'completed') {
            clearInterval(timer)
            delete timerRefs.current[row.id]
            setRunningMap((prev) => {
              const next = { ...prev }
              delete next[row.id]
              return next
            })
            // Fetch final result and attach to row
            const resultRes = await fetch(`/api/studio/wfa/${jobId}/result`)
            if (resultRes.ok) {
              const result = await resultRes.json()
              setRows((prev) => prev.map((r) => r.id === row.id
                ? { ...r, wfaResult: { job_id: jobId, status: 'completed', result, ...result }, wfaStatus: 'completed' }
                : r
              ))
            }
          } else if (prog.status === 'failed') {
            clearInterval(timer)
            delete timerRefs.current[row.id]
            setRunningMap((prev) => {
              const next = { ...prev }
              delete next[row.id]
              return next
            })
            setRows((prev) => prev.map((r) => r.id === row.id
              ? { ...r, wfaStatus: 'failed' }
              : r
            ))
          }
        } catch {}
      }, 700)

      timerRefs.current[row.id] = timer
    } catch (err) {
      setRunningMap((prev) => {
        const next = { ...prev }
        delete next[row.id]
        return next
      })
      alert(`Lỗi: ${err.message}`)
    }
  }

  const handleSendToCarlo = (row) => {
    const wfa = row.wfaResult
    if (!wfa) return
    const trades = wfa.result?.aggregate_oos_trades || wfa.aggregate_oos_trades || []
    navigate('/library/monte-carlo', {
      state: {
        mcInput: {
          source_wfa_id: wfa.job_id,
          source_handle: row.source_handle,
          trades,
          symbol: row.symbol,
          strategy_name: row.name,
        },
        autoRun: true,
      },
    })
  }

  const formatPct = (v) => (v != null ? `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%` : '—')
  const formatNum = (v) => (v != null ? Number(v).toFixed(2) : '—')

  const wfaHasRun = (row) => row.wfaResult && row.wfaStatus === 'completed'
  const wfaPass = (row) => {
    const w = row.wfaResult
    if (!w) return false
    return (w.acceptance_gate_passed ?? w.result?.acceptance_gate_passed) === true
  }

  const displayedRows = filterPass ? rows.filter(wfaHasRun) : rows

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* ── Page Header ── */}
      <div className="head" style={{ paddingBottom: 12, borderBottom: '1px solid var(--line)' }}>
        <div className="head-row">
          <div>
            <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span>Walk-Forward Analysis (WFA)</span>
              <span className="tag run" style={{ fontSize: 12 }}>Stage 2</span>
            </h1>
            <p style={{ margin: '4px 0 0', color: 'var(--ink-3)', fontSize: 13 }}>
              Chọn bộ tham số đã Backtest, mở cấu hình inline và chạy WFA. Kết quả hiển thị ngay trên từng dòng.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              className={`btn ${!filterPass ? 'active' : ''}`}
              onClick={() => setFilterPass(false)}
              style={{ fontSize: 12, background: !filterPass ? '#3b82f6' : 'transparent', color: !filterPass ? '#fff' : 'var(--ink)' }}
            >
              Tất cả ({rows.length})
            </button>
            <button
              className={`btn ${filterPass ? 'active' : ''}`}
              onClick={() => setFilterPass(true)}
              style={{ fontSize: 12, background: filterPass ? '#10b981' : 'transparent', color: filterPass ? '#fff' : 'var(--ink)' }}
            >
              ✓ Đã chạy WFA ({rows.filter(wfaHasRun).length})
            </button>
            <button className="btn" onClick={fetchAll} style={{ fontSize: 12 }}>
              🔄 Làm mới
            </button>
          </div>
        </div>
      </div>

      {/* ── Unified Table ── */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-3)' }}>Đang nạp dữ liệu...</div>
        ) : displayedRows.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--ink-3)' }}>
            {filterPass ? 'Chưa có bộ tham số nào đã chạy WFA.' : 'Chưa có dữ liệu Backtest nào.'}
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
            <thead style={{ background: 'var(--surface-2)', position: 'sticky', top: 0, zIndex: 2 }}>
              <tr>
                <th style={{ width: 30, padding: '8px 6px' }}></th>
                <th style={{ textAlign: 'left', padding: '8px 10px' }}>Tên bộ tham số</th>
                <th style={{ textAlign: 'left', padding: '8px 8px' }}>Coin / Loại</th>
                <th style={{ textAlign: 'right', padding: '8px 8px' }}>Số lệnh</th>
                <th style={{ textAlign: 'right', padding: '8px 8px' }}>PnL %</th>
                <th style={{ textAlign: 'right', padding: '8px 8px' }}>MDD %</th>
                <th style={{ textAlign: 'right', padding: '8px 8px' }}>Winrate</th>
                <th style={{ textAlign: 'right', padding: '8px 8px' }}>Sharpe</th>
                <th style={{ textAlign: 'center', padding: '8px 8px', color: '#3b82f6' }}>OOS PnL TB</th>
                <th style={{ textAlign: 'center', padding: '8px 8px', color: '#3b82f6' }}>WFA Gate</th>
                <th style={{ textAlign: 'right', padding: '8px 12px' }}>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {displayedRows.map((row) => {
                const isExpanded = expandedId === row.id
                const isRunning = !!runningMap[row.id]
                const prog = runningMap[row.id]
                const hasWfa = wfaHasRun(row)
                const passed = wfaPass(row)
                const wfa = row.wfaResult
                const oosRet = wfa?.avg_oos_return_pct ?? wfa?.result?.avg_oos_return_pct
                const mddWfa = wfa?.worst_fold_mdd_pct ?? wfa?.result?.worst_fold_mdd_pct
                const config = configMap[row.id] || defaultConfig()

                return (
                  <React.Fragment key={row.id}>
                    {/* ── Main data row ── */}
                    <tr
                      style={{
                        background: isExpanded ? 'rgba(59,130,246,0.06)' : hasWfa ? 'rgba(16,185,129,0.03)' : 'transparent',
                        borderBottom: isExpanded ? 'none' : '1px solid var(--line)',
                        cursor: isRunning ? 'default' : 'pointer',
                        transition: 'background 0.15s',
                      }}
                      onClick={() => !isRunning && toggleExpand(row)}
                    >
                      {/* Expand indicator */}
                      <td style={{ textAlign: 'center', padding: '10px 6px', color: isRunning ? 'var(--ink-3)' : '#3b82f6' }}>
                        {isRunning ? '⚙' : isExpanded ? '▾' : '▸'}
                      </td>

                      {/* Name */}
                      <td style={{ padding: '10px 10px', fontWeight: 600, maxWidth: 220 }}>
                        <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {row.name}
                        </div>
                        {isRunning && (
                          <div style={{ fontSize: 11, color: '#3b82f6', marginTop: 3 }}>
                            {prog.message} — Fold {prog.current_fold}/{prog.total_folds}
                          </div>
                        )}
                      </td>

                      {/* Coin / Type */}
                      <td style={{ padding: '10px 8px' }}>
                        <span className="tag" style={{ fontSize: 10.5 }}>{row.symbol}</span>
                        {' '}
                        <span style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{row.type}</span>
                      </td>

                      {/* Backtest metrics */}
                      <td style={{ textAlign: 'right', padding: '10px 8px' }}>
                        {row.trades ? row.trades.toLocaleString() : <span style={{ color: 'var(--ink-3)' }}>—</span>}
                      </td>
                      <td style={{ textAlign: 'right', padding: '10px 8px', fontWeight: 600,
                        color: row.return_pct == null ? 'var(--ink-3)' : row.return_pct >= 0 ? '#10b981' : '#ef4444' }}>
                        {formatPct(row.return_pct)}
                      </td>
                      <td style={{ textAlign: 'right', padding: '10px 8px',
                        color: row.mdd_pct == null ? 'var(--ink-3)' : row.mdd_pct <= 15 ? '#10b981' : '#f59e0b' }}>
                        {row.mdd_pct != null ? `${Number(row.mdd_pct).toFixed(2)}%` : '—'}
                      </td>
                      <td style={{ textAlign: 'right', padding: '10px 8px' }}>
                        {row.winrate != null ? `${Number(row.winrate).toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ textAlign: 'right', padding: '10px 8px' }}>
                        {formatNum(row.sharpe)}
                      </td>

                      {/* WFA columns */}
                      <td style={{ textAlign: 'center', padding: '10px 8px',
                        color: oosRet == null ? 'var(--ink-3)' : oosRet >= 0 ? '#10b981' : '#ef4444',
                        fontWeight: oosRet != null ? 600 : 400 }}>
                        {oosRet != null ? formatPct(oosRet) : isRunning ? (
                          <div style={{ width: '100%' }}>
                            <div style={{ height: 4, background: 'var(--line)', borderRadius: 2, overflow: 'hidden' }}>
                              <div style={{ height: '100%', background: '#3b82f6', width: `${prog?.progress_pct || 0}%`, transition: 'width 0.3s' }} />
                            </div>
                            <div style={{ fontSize: 10, color: '#3b82f6', marginTop: 2 }}>{prog?.progress_pct || 0}%</div>
                          </div>
                        ) : '—'}
                      </td>
                      <td style={{ textAlign: 'center', padding: '10px 8px' }}>
                        {hasWfa ? (
                          <span className="tag" style={{
                            background: passed ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                            color: passed ? '#10b981' : '#f59e0b', fontSize: 11,
                          }}>
                            {passed ? '✓ ĐẠT' : '⚠ CẢNH'}
                          </span>
                        ) : isRunning ? (
                          <span style={{ fontSize: 10.5, color: '#3b82f6' }}>Đang chạy</span>
                        ) : '—'}
                      </td>

                      {/* Actions */}
                      <td style={{ textAlign: 'right', padding: '10px 12px' }} onClick={(e) => e.stopPropagation()}>
                        <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center' }}>
                          {!isRunning && (
                            <button
                              className="btn"
                              onClick={(e) => { e.stopPropagation(); toggleExpand(row) }}
                              style={{ fontSize: 11, padding: '3px 8px', background: isExpanded ? '#3b82f6' : 'transparent', color: isExpanded ? '#fff' : 'var(--ink)' }}
                            >
                              {isExpanded ? 'Đóng ▴' : hasWfa ? 'Chạy lại ▾' : 'Cấu hình WFA ▾'}
                            </button>
                          )}
                          {hasWfa && !isRunning && (
                            <button
                              className="btn btn-primary"
                              onClick={(e) => { e.stopPropagation(); handleSendToCarlo(row) }}
                              style={{ fontSize: 11, padding: '3px 8px', background: '#10b981', borderColor: '#10b981' }}
                            >
                              🎲 Carlo ➔
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* ── WFA Result mini-summary (if done, below main row) ── */}
                    {hasWfa && !isExpanded && !isRunning && (
                      <tr style={{ borderBottom: '1px solid var(--line)', background: 'rgba(16,185,129,0.03)' }}>
                        <td colSpan={11} style={{ padding: '0 12px 8px 40px' }}>
                          <div style={{ display: 'flex', gap: 20, fontSize: 11, color: 'var(--ink-3)', flexWrap: 'wrap' }}>
                            <span style={{ color: '#3b82f6', fontWeight: 600 }}>WFA Kết quả:</span>
                            <span>Folds: {wfa?.total_folds ?? wfa?.result?.folds?.length ?? '—'}</span>
                            <span>Worst MDD: <strong style={{ color: '#f59e0b' }}>{mddWfa != null ? `${Number(mddWfa).toFixed(2)}%` : '—'}</strong></span>
                            <span>OOS Trades: <strong>{wfa?.result?.total_oos_trades?.toLocaleString() ?? '—'}</strong></span>
                            <span style={{ color: 'var(--ink-3)' }}>Job: {(wfa?.job_id || '').slice(-12)}</span>
                          </div>
                        </td>
                      </tr>
                    )}

                    {/* ── Expanded: WFA Config Form (if not running) ── */}
                    {isExpanded && !isRunning && (
                      <tr style={{ borderBottom: '1px solid var(--line)' }}>
                        <td colSpan={11} style={{ padding: '0 0 0 30px', background: 'rgba(59,130,246,0.04)' }}>
                          <div style={{ padding: '14px 16px 14px 10px' }}>
                            {/* Section: Phần 1 — Backtest Summary */}
                            <div style={{ display: 'flex', gap: 10, marginBottom: 14, alignItems: 'center', flexWrap: 'wrap' }}>
                              <span style={{ fontSize: 11, fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                Cấu hình WFA cho: {row.name}
                              </span>
                              {hasWfa && (
                                <span style={{ fontSize: 11, color: 'var(--ink-3)' }}>
                                  · Đã từng chạy: {passed ? '✓ ĐẠT' : '⚠ CẢNH BÁO'}
                                </span>
                              )}
                            </div>

                            {row.type === 'Base' ? (
                              <div style={{ fontSize: 12, color: 'var(--down)', padding: '8px 0' }}>
                                ⚠ Run legacy (Base) chưa có snapshot AST nên không thể chạy WFA. Hãy chạy lại chiến lược trong Studio để có source_handle hợp lệ.
                              </div>
                            ) : (<>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr) auto', gap: 12, alignItems: 'end' }}>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Train / IS (ngày)</label>
                                <input type="number" className="input" min={1} max={365}
                                  value={config.train_days}
                                  onChange={(e) => updateConfig(row.id, { train_days: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 12 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Test / OOS (ngày)</label>
                                <input type="number" className="input" min={1} max={180}
                                  value={config.test_days}
                                  onChange={(e) => updateConfig(row.id, { test_days: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 12 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Bước trượt (ngày, ≥ Test)</label>
                                <input type="number" className="input" min={1} max={180}
                                  value={config.step_days}
                                  onChange={(e) => updateConfig(row.id, { step_days: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 12 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Embargo (ngày)</label>
                                <input type="number" className="input" min={0} max={30}
                                  value={config.embargo_days}
                                  onChange={(e) => updateConfig(row.id, { embargo_days: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 12 }}
                                />
                              </div>
                              <button
                                className="btn btn-primary"
                                onClick={(e) => { e.stopPropagation(); handleRunWfa(row) }}
                                style={{ fontSize: 12.5, padding: '8px 16px', whiteSpace: 'nowrap', background: '#3b82f6', borderColor: '#3b82f6' }}
                              >
                                ▶ Chạy WFA
                              </button>
                            </div>

                            {/* Acceptance gate thresholds */}
                            <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Số fold tối thiểu</label>
                                <input type="number" className="input" min={1} max={50}
                                  value={config.min_folds}
                                  onChange={(e) => updateConfig(row.id, { min_folds: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 11 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Tỉ lệ fold có lãi tối thiểu (0–1)</label>
                                <input type="number" className="input" step={0.05} min={0} max={1}
                                  value={config.min_positive_ratio}
                                  onChange={(e) => updateConfig(row.id, { min_positive_ratio: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 11 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Tổng lệnh OOS tối thiểu</label>
                                <input type="number" className="input" min={1}
                                  value={config.min_oos_trades}
                                  onChange={(e) => updateConfig(row.id, { min_oos_trades: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 11 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Lệnh IS tối thiểu / fold</label>
                                <input type="number" className="input" min={1}
                                  value={config.min_is_trades}
                                  onChange={(e) => updateConfig(row.id, { min_is_trades: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 11 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Min OOS Profit (% / Fold)</label>
                                <input type="number" className="input" 
                                  value={config.min_oos_profit_pct}
                                  onChange={(e) => updateConfig(row.id, { min_oos_profit_pct: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 11 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Max OOS MDD (%)</label>
                                <input type="number" className="input" min={1} max={100}
                                  value={config.max_oos_mdd_pct}
                                  onChange={(e) => updateConfig(row.id, { max_oos_mdd_pct: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 11 }}
                                />
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'block', marginBottom: 3 }}>Tổng lợi nhuận OOS (lãi kép) tối thiểu (%)</label>
                                <input type="number" className="input" 
                                  value={config.min_total_oos_profit_pct}
                                  onChange={(e) => updateConfig(row.id, { min_total_oos_profit_pct: Number(e.target.value) })}
                                  style={{ width: '100%', fontSize: 11 }}
                                />
                              </div>
                            </div>
                            </>)}

                            {/* WFA fold breakdown (if already ran) */}
                            {hasWfa && wfa?.result?.folds?.length > 0 && (
                              <div style={{ marginTop: 12, borderTop: '1px solid var(--line)', paddingTop: 10 }}>
                                <div style={{ fontSize: 11, color: 'var(--ink-3)', marginBottom: 8 }}>
                                  Chi tiết {wfa.result.folds.length} Folds OOS đã chạy:
                                </div>
                                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                                  {wfa.result.folds.map((f, i) => (
                                    <div key={i} style={{
                                      background: f.passed_gate ? 'rgba(16,185,129,0.1)' : 'rgba(239,68,68,0.1)',
                                      border: `1px solid ${f.passed_gate ? 'rgba(16,185,129,0.3)' : 'rgba(239,68,68,0.3)'}`,
                                      borderRadius: 5, padding: '4px 8px', fontSize: 10.5, minWidth: 80, textAlign: 'center',
                                    }}>
                                      <div style={{ fontWeight: 600 }}>Fold #{f.fold_index}</div>
                                      {f.status === 'NO_TRADE' ? (
                                        <div style={{ color: 'var(--ink-3)' }} title={(f.gate_notes || []).join('\n')}>NO_TRADE</div>
                                      ) : (
                                        <>
                                          <div style={{ color: f.oos_return_pct >= 0 ? '#10b981' : '#ef4444' }}>
                                            {f.oos_return_pct >= 0 ? '+' : ''}{f.oos_return_pct.toFixed(1)}%
                                          </div>
                                          <div style={{ color: 'var(--ink-3)' }}>MDD {f.oos_max_drawdown_pct.toFixed(1)}%</div>
                                        </>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
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
