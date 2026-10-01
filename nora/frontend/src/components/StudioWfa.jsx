import React, { useState, useEffect, useRef } from 'react'

export default function StudioWfa({ wfaInput, onSendToMonteCarlo, onBackToBuilder, autoRun = false, initialResult = null, onCompleted = null }) {
  // Khớp với backend WfaFoldConfig (extra="forbid"): chỉ gửi các field backend hiểu
  const [config, setConfig] = useState({
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

  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState({ progress_pct: 0, message: '', current_fold: 0, total_folds: 0 })
  const [result, setResult] = useState(initialResult)
  const [error, setError] = useState(null)
  const [activeFoldIdx, setActiveFoldIdx] = useState(null)

  useEffect(() => {
    if (initialResult) {
      setResult(initialResult)
    }
  }, [initialResult])

  const autoRanRef = useRef(false)

  const stratName = wfaInput?.strategy_snapshot?.name || wfaInput?.strategy_name || 'Studio Strategy'
  const symbol = wfaInput?.symbol || wfaInput?.strategy_snapshot?.symbol || ''
  const sourceHandle = wfaInput?.source_handle || 'N/A'

  const handleRunWfa = async () => {
    if (!wfaInput?.source_handle && !wfaInput?.strategy_snapshot) {
      setError('Chưa có nguồn Backtest nào. Vui lòng chạy Backtest trước hoặc bấm "Chuyển sang WFA".')
      return
    }

    setRunning(true)
    setError(null)
    setResult(null)
    setProgress({ progress_pct: 0, message: 'Đang gửi yêu cầu khởi chạy WFA...', current_fold: 0, total_folds: 0 })

    try {
      const payload = {
        source_handle: wfaInput.source_handle,
        strategy_snapshot: wfaInput.strategy_snapshot,
        ...(symbol ? { symbol } : {}),
        config: config,
      }

      const res = await fetch('/api/studio/wfa/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        const d = errData.detail
        const msg = !d ? '' : typeof d === 'string' ? d
          : Array.isArray(d) ? d.map((x) => `${(x.loc || []).join('.')}: ${x.msg}`).join('\n')
          : d.message ? [d.message, ...(d.issues || [])].join('\n') : JSON.stringify(d)
        throw new Error(msg || 'Không thể khởi chạy WFA')
      }

      const jobData = await res.json()
      const jobId = jobData.job_id

      // Polling vòng lặp kiểm tra tiến trình
      const timer = setInterval(async () => {
        try {
          const progRes = await fetch(`/api/studio/wfa/${jobId}/progress`)
          if (!progRes.ok) return
          const progData = await progRes.json()

          setProgress({
            progress_pct: progData.progress_pct || 0,
            message: progData.message || 'Đang thực thi...',
            current_fold: progData.current_fold || 0,
            total_folds: progData.total_folds || 0,
          })

          if (progData.status === 'completed') {
            clearInterval(timer)
            const resultRes = await fetch(`/api/studio/wfa/${jobId}/result`)
            const finalResult = await resultRes.json()
            setResult(finalResult)
            setRunning(false)
            onCompleted && onCompleted(finalResult)
          } else if (progData.status === 'failed') {
            clearInterval(timer)
            setError(progData.error || 'WFA job gặp sự cố khi chạy')
            setRunning(false)
          }
        } catch (pollErr) {
          console.error('WFA poll error:', pollErr)
        }
      }, 800)
    } catch (err) {
      setError(err.message)
      setRunning(false)
    }
  }

  useEffect(() => {
    if (autoRun && wfaInput && (wfaInput.source_handle || wfaInput.strategy_snapshot) && !autoRanRef.current && !running && !result) {
      autoRanRef.current = true
      handleRunWfa()
    }
  }, [autoRun, wfaInput])

  const gatePassed = result?.acceptance_gate_passed

  return (
    <div className="studio-pipeline-container">
      {/* ── Top Info & Handoff Banner ── */}
      <div className="studio-pipeline-header">
        <div className="studio-pipeline-meta">
          <span className="studio-pill active" style={{ fontSize: 11 }}>Giai đoạn 2: Walk-Forward</span>
          <b style={{ fontSize: 16, color: 'var(--ink)' }}>{stratName}</b>
          <span className="tag run">{symbol}</span>
          <span style={{ fontSize: 12, color: 'var(--ink-3)', fontFamily: 'var(--mono)' }}>
            Handle: {sourceHandle}
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {onBackToBuilder && (
            <button className="studio-secondary-btn" onClick={onBackToBuilder}>
              ← Quay lại Builder
            </button>
          )}
          {result && onSendToMonteCarlo && (
            <button
              className="studio-handoff-btn"
              onClick={() => onSendToMonteCarlo(result)}
              title="Chuyển toàn bộ danh sách lệnh OOS sang bước Mô phỏng Monte Carlo"
            >
              <span>🎲 Chạy Monte Carlo</span>
              <span style={{ fontWeight: 'bold' }}>➔</span>
            </button>
          )}
        </div>
      </div>

      {/* ── Configuration Card ── */}
      <div className="studio-pipeline-card">
        <div className="studio-pipeline-card-title">
          <span>Cấu hình Cửa sổ Rolling & Tiêu chuẩn Acceptance Gate (WFO)</span>
          <span style={{ fontSize: 12, color: 'var(--ink-3)', fontWeight: 'normal' }}>
            Kiểm tra tính bền vững của chiến lược trên dữ liệu ngoài mẫu (Out-of-Sample)
          </span>
        </div>

        <div className="studio-config-grid">
          <div className="studio-config-item">
            <label>Cửa sổ Train (IS)</label>
            <div className="studio-input-group">
              <input
                type="number" min="1" max="365"
                value={config.train_days}
                onChange={(e) => setConfig({ ...config, train_days: Number(e.target.value) })}
              />
              <span>ngày</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Cửa sổ Test (OOS)</label>
            <div className="studio-input-group">
              <input
                type="number" min="1" max="180"
                value={config.test_days}
                onChange={(e) => setConfig({ ...config, test_days: Number(e.target.value) })}
              />
              <span>ngày</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Bước trượt (≥ Test)</label>
            <div className="studio-input-group">
              <input
                type="number" min="1" max="180"
                value={config.step_days}
                onChange={(e) => setConfig({ ...config, step_days: Number(e.target.value) })}
              />
              <span>ngày</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Embargo Train→Test</label>
            <div className="studio-input-group">
              <input
                type="number" min="0" max="30"
                value={config.embargo_days}
                onChange={(e) => setConfig({ ...config, embargo_days: Number(e.target.value) })}
              />
              <span>ngày</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Số fold tối thiểu</label>
            <div className="studio-input-group">
              <input
                type="number" min="1" max="50"
                value={config.min_folds}
                onChange={(e) => setConfig({ ...config, min_folds: Number(e.target.value) })}
              />
              <span>folds</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Tỉ lệ fold có lãi tối thiểu</label>
            <div className="studio-input-group">
              <input
                type="number" min="0" max="1" step="0.05"
                value={config.min_positive_ratio}
                onChange={(e) => setConfig({ ...config, min_positive_ratio: Number(e.target.value) })}
              />
              <span>(0–1)</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Tổng lệnh OOS tối thiểu</label>
            <div className="studio-input-group">
              <input
                type="number" min="1"
                value={config.min_oos_trades}
                onChange={(e) => setConfig({ ...config, min_oos_trades: Number(e.target.value) })}
              />
              <span>lệnh</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Lệnh IS tối thiểu / fold</label>
            <div className="studio-input-group">
              <input
                type="number" min="1"
                value={config.min_is_trades}
                onChange={(e) => setConfig({ ...config, min_is_trades: Number(e.target.value) })}
              />
              <span>lệnh</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Max Drawdown từng Fold</label>
            <div className="studio-input-group">
              <input
                type="number" min="1" max="100"
                value={config.max_oos_mdd_pct}
                onChange={(e) => setConfig({ ...config, max_oos_mdd_pct: Number(e.target.value) })}
              />
              <span>%</span>
            </div>
          </div>
          <div className="studio-config-item">
            <label>Tổng lợi nhuận OOS (lãi kép) tối thiểu</label>
            <div className="studio-input-group">
              <input
                type="number"
                value={config.min_total_oos_profit_pct}
                onChange={(e) => setConfig({ ...config, min_total_oos_profit_pct: Number(e.target.value) })}
              />
              <span>%</span>
            </div>
          </div>
        </div>

        <div style={{ marginTop: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>
            Gate: đủ số fold tối thiểu, tỉ lệ fold có lãi ≥ ngưỡng, đủ lệnh OOS, MDD mỗi fold ≤ ngưỡng, lợi nhuận OOS lãi kép ≥ ngưỡng. Fold không đủ lệnh IS được đánh NO_TRADE.
          </span>
          <button
            className="studio-simulate-btn"
            style={{ minWidth: 200 }}
            onClick={handleRunWfa}
            disabled={running}
          >
            {running ? (
              <>
                <span className="studio-btn-spinner"></span>
                <span>Đang kiểm định WFA...</span>
              </>
            ) : (
              <>
                <span>▶ Khởi chạy Walk-Forward</span>
              </>
            )}
          </button>
        </div>

        {/* ── Progress Bar ── */}
        {running && (
          <div className="studio-progress-box">
            <div className="studio-progress-head">
              <span>{progress.message}</span>
              <b>{progress.progress_pct}%</b>
            </div>
            <div className="studio-progress-track">
              <div className="studio-progress-fill" style={{ width: `${progress.progress_pct}%` }}></div>
            </div>
          </div>
        )}

        {error && (
          <div className="studio-error-box" style={{ marginTop: 14 }}>
            <div className="studio-error-title">Lỗi thực thi WFA</div>
            <div className="studio-error-content">{error}</div>
          </div>
        )}
      </div>

      {/* ── Result Section ── */}
      {result && (
        <>
          {/* Gate Verification Summary */}
          <div className={`studio-alpha-grade-card ${gatePassed ? 'passed' : 'warning'}`}>
            <div className="studio-alpha-grade-head">
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ fontSize: 18 }}>{gatePassed ? '🛡️' : '⚠️'}</span>
                <div>
                  <b style={{ fontSize: 14, color: gatePassed ? 'var(--up)' : 'var(--amber)' }}>
                    {gatePassed ? 'WFA Acceptance Gate: ĐẠT TIÊU CHUẨN' : 'WFA Acceptance Gate: CẦN TINH CHỈNH'}
                  </b>
                  <p style={{ margin: 0, fontSize: 12, color: 'var(--ink-3)' }}>
                    Kiểm định trượt qua {result.total_folds} Folds Out-of-Sample
                  </p>
                </div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>Tổng OOS Return:</span>{' '}
                <b style={{ fontSize: 16, color: result.total_oos_return_pct >= 0 ? 'var(--up)' : 'var(--down)' }}>
                  {result.total_oos_return_pct >= 0 ? '+' : ''}{result.total_oos_return_pct}%
                </b>
              </div>
            </div>

            <div className="studio-alpha-checks" style={{ marginTop: 12 }}>
              {Object.entries(result.gate_checks || {}).map(([key, check]) => (
                <div key={key} className={`studio-alpha-check ${check.passed ? 'ok' : 'warn'}`}>
                  <span>{check.passed ? '✓' : '!'}</span>
                  <b>{check.label}</b>
                  <em>Yêu cầu: {check.required}</em>
                </div>
              ))}
            </div>
          </div>

          {/* Aggregated Metrics Grid */}
          <div className="studio-metrics-grid" style={{ gridTemplateColumns: 'repeat(5, 1fr)', marginTop: 14 }}>
            <div className="studio-metric-card">
              <span className="studio-metric-label">Tổng Fold OOS</span>
              <span className="studio-metric-value">{result.total_folds} folds</span>
              <span className="studio-metric-sub">{result.positive_folds_count} fold dương</span>
            </div>
            <div className="studio-metric-card">
              <span className="studio-metric-label">Lợi nhuận TB / Fold</span>
              <span
                className="studio-metric-value"
                style={{ color: result.avg_oos_return_pct >= 0 ? 'var(--up)' : 'var(--down)' }}
              >
                {result.avg_oos_return_pct >= 0 ? '+' : ''}{result.avg_oos_return_pct}%
              </span>
              <span className="studio-metric-sub">OOS return trung bình</span>
            </div>
            <div className="studio-metric-card">
              <span className="studio-metric-label">Worst Fold MDD</span>
              <span className="studio-metric-value" style={{ color: 'var(--down)' }}>
                {result.worst_fold_mdd_pct}%
              </span>
              <span className="studio-metric-sub">Sụt giảm lớn nhất</span>
            </div>
            <div className="studio-metric-card">
              <span className="studio-metric-label">Tổng số lệnh OOS</span>
              <span className="studio-metric-value">{result.total_oos_trades}</span>
              <span className="studio-metric-sub">Dùng cho Monte Carlo</span>
            </div>
            <div className="studio-metric-card">
              <span className="studio-metric-label">Win Rate OOS</span>
              <span className="studio-metric-value" style={{ color: 'var(--amber)' }}>
                {result.overall_oos_win_rate}%
              </span>
              <span className="studio-metric-sub">Tỷ lệ thắng ngoài mẫu</span>
            </div>
          </div>

          {/* Fold Breakdown Table */}
          <div className="studio-pipeline-card" style={{ marginTop: 14 }}>
            <div className="studio-pipeline-card-title">
              <span>Chi tiết Kết quả từng Fold (Train IS vs Test OOS)</span>
              <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>
                Bấm vào một fold để xem hoặc chuyển toàn bộ {result.aggregate_oos_trades?.length || 0} lệnh sang Monte Carlo
              </span>
            </div>

            <div className="studio-table-wrapper">
              <table className="studio-table">
                <thead>
                  <tr>
                    <th>Fold</th>
                    <th>In-Sample (Train)</th>
                    <th>Out-of-Sample (Test)</th>
                    <th style={{ textAlign: 'right' }}>IS Return</th>
                    <th style={{ textAlign: 'right' }}>IS MDD</th>
                    <th style={{ textAlign: 'right' }}>OOS Return</th>
                    <th style={{ textAlign: 'right' }}>OOS MDD</th>
                    <th style={{ textAlign: 'right' }}>OOS Win Rate</th>
                    <th style={{ textAlign: 'right' }}>OOS Trades</th>
                    <th style={{ textAlign: 'center' }}>Trạng thái</th>
                  </tr>
                </thead>
                <tbody>
                  {(result.folds || []).map((f) => (
                    <tr
                      key={f.fold_index}
                      className={activeFoldIdx === f.fold_index ? 'active-row' : ''}
                      onClick={() => setActiveFoldIdx(activeFoldIdx === f.fold_index ? null : f.fold_index)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td style={{ fontWeight: 600 }}>#{f.fold_index}</td>
                      <td style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>
                        {f.train_start_date} → {f.train_end_date}
                      </td>
                      <td style={{ fontSize: 11.5, color: 'var(--ink-2)' }}>
                        {f.test_start_date} → {f.test_end_date}
                      </td>
                      <td style={{ textAlign: 'right', color: f.is_return_pct >= 0 ? 'var(--up)' : 'var(--down)' }}>
                        {f.is_return_pct >= 0 ? '+' : ''}{f.is_return_pct}%
                      </td>
                      <td style={{ textAlign: 'right', color: 'var(--ink-2)' }}>{f.is_max_drawdown_pct}%</td>
                      <td style={{ textAlign: 'right', fontWeight: 700, color: f.oos_return_pct >= 0 ? 'var(--up)' : 'var(--down)' }}>
                        {f.oos_return_pct >= 0 ? '+' : ''}{f.oos_return_pct}%
                      </td>
                      <td style={{ textAlign: 'right', color: f.oos_max_drawdown_pct <= config.max_oos_mdd_pct ? 'var(--ink-2)' : 'var(--down)' }}>
                        {f.oos_max_drawdown_pct}%
                      </td>
                      <td style={{ textAlign: 'right' }}>{f.oos_win_rate}%</td>
                      <td style={{ textAlign: 'right' }}>{f.oos_trades_count}</td>
                      <td style={{ textAlign: 'center' }}>
                        <span
                          className={`tag ${f.passed_gate ? 'run' : 'off'}`}
                          title={(f.gate_notes || []).join('\n')}
                        >
                          {f.status === 'NO_TRADE' ? 'NO_TRADE' : f.passed_gate ? 'PASS' : 'WARN'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
