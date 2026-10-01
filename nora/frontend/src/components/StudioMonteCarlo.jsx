import React, { useState, useEffect, useRef } from 'react'

const gateBadge = (g) => {
  if (g === true) return { text: '✓ Nguồn đã qua WFA gate', color: '#10b981' }
  if (g === false) return { text: '⚠ Nguồn KHÔNG qua WFA gate — kết quả chỉ để tham khảo', color: '#ef4444' }
  return { text: 'Chưa kiểm định WFA (chạy trực tiếp từ backtest)', color: '#f59e0b' }
}

export default function StudioMonteCarlo({ mcInput, onBackToWfa, autoRun = false, initialResult = null, onCompleted = null }) {
  const [simulations, setSimulations] = useState(1000)
  const [ruinThreshold, setRuinThreshold] = useState(30)
  const [blockSize, setBlockSize] = useState(1)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(initialResult)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (initialResult) {
      setResult(initialResult)
    }
  }, [initialResult])

  const autoRanRef = useRef(false)

  const stratName = mcInput?.strategy_name || 'Studio Strategy'
  const symbol = mcInput?.symbol || ''
  const tradesCount = mcInput?.trades?.length || 0
  const sourceWfaId = mcInput?.source_wfa_id || null

  const handleRunSimulation = async () => {
    setRunning(true)
    setError(null)
    setResult(null)

    try {
      const payload = {
        source_wfa_id: sourceWfaId,
        source_handle: mcInput?.source_handle,
        trades: mcInput?.trades,
        strategy_name: stratName,
        ...(symbol ? { symbol } : {}),
        simulations: Number(simulations),
        ruin_threshold_pct: Number(ruinThreshold),
        block_size: Number(blockSize),
      }

      const res = await fetch('/api/studio/monte-carlo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        const d = err.detail
        const msg = !d ? '' : typeof d === 'string' ? d
          : Array.isArray(d) ? d.map((x) => `${(x.loc || []).join('.')}: ${x.msg}`).join('\n')
          : d.message ? [d.message, ...(d.issues || [])].join('\n') : JSON.stringify(d)
        throw new Error(msg || 'Không thể khởi chạy Monte Carlo')
      }

      const jobData = await res.json()
      const jobId = jobData.job_id

      // Chờ worker hoàn thành (mô phỏng vector 1,000 - 10,000 lần mất < 0.5s)
      let attempts = 0
      const timer = setInterval(async () => {
        attempts++
        try {
          const resRes = await fetch(`/api/studio/monte-carlo/${jobId}/result`)
          if (resRes.ok) {
            const finalRes = await resRes.json()
            if (finalRes.simulations) {
              clearInterval(timer)
              setResult(finalRes)
              setRunning(false)
              onCompleted && onCompleted(finalRes)
            }
          }
          if (attempts > 15) {
            clearInterval(timer)
            setError('Quá thời gian chờ phản hồi Monte Carlo')
            setRunning(false)
          }
        } catch (pollErr) {
          console.error('Monte Carlo poll error:', pollErr)
        }
      }, 600)
    } catch (err) {
      setError(err.message)
      setRunning(false)
    }
  }

  useEffect(() => {
    if (autoRun && mcInput?.trades?.length > 0 && !autoRanRef.current && !running && !result) {
      autoRanRef.current = true
      handleRunSimulation()
    }
  }, [autoRun, mcInput])

  // ─── SVG Fan Chart Helper ───────────────────────────────────────────────────
  let fanChartPaths = []
  let chartMin = 0
  let chartMax = 1
  const width = 680
  const height = 240
  const padTop = 20
  const padBottom = 30
  const padLeft = 55
  const padRight = 20

  if (result?.sample_paths && result.sample_paths.length > 0) {
    const allValues = result.sample_paths.flat()
    chartMin = Math.min(...allValues) * 0.95
    chartMax = Math.max(...allValues) * 1.05
    if (chartMin === chartMax) chartMax += 1000

    const numPoints = result.sample_paths[0].length
    const scaleX = (i) => padLeft + (i / (numPoints - 1)) * (width - padLeft - padRight)
    const scaleY = (val) => padTop + (1 - (val - chartMin) / (chartMax - chartMin)) * (height - padTop - padBottom)

    fanChartPaths = result.sample_paths.map((path, pIdx) => {
      const d = path.map((val, i) => `${i === 0 ? 'M' : 'L'} ${scaleX(i).toFixed(1)} ${scaleY(val).toFixed(1)}`).join(' ')
      // Xác định loại đường: Worst, Best, Median, hoặc thông thường
      const finalVal = path[path.length - 1]
      return { d, finalVal, index: pIdx }
    })
  }

  return (
    <div className="studio-pipeline-container">
      {/* ── Top Info & Navigation Banner ── */}
      <div className="studio-pipeline-header">
        <div className="studio-pipeline-meta">
          <span className="studio-pill active" style={{ fontSize: 11 }}>Giai đoạn 3: Monte Carlo</span>
          <b style={{ fontSize: 16, color: 'var(--ink)' }}>{stratName}</b>
          <span className="tag run">{symbol}</span>
          <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>
            {sourceWfaId ? `Nguồn OOS từ WFA: ${sourceWfaId}` : 'Nguồn: Backtest Trade Log'} ({tradesCount} lệnh)
          </span>
        </div>
        <div>
          {onBackToWfa && (
            <button className="studio-secondary-btn" onClick={onBackToWfa}>
              ← Quay lại WFA
            </button>
          )}
        </div>
      </div>

      {/* ── Configuration Card ── */}
      <div className="studio-pipeline-card">
        <div className="studio-pipeline-card-title">
          <span>Tham số Mô phỏng Rủi ro Đuôi (Bootstrap Resampling)</span>
          <span style={{ fontSize: 12, color: 'var(--ink-3)', fontWeight: 'normal' }}>
            Tái lấy mẫu có hoàn lại từ danh sách lệnh OOS để đo lường phân phối Drawdown và Xác suất Cháy tài khoản
          </span>
        </div>

        <div className="studio-config-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          <div className="studio-config-item">
            <label>Số lần Mô phỏng (Simulations)</label>
            <select
              value={simulations}
              onChange={(e) => setSimulations(Number(e.target.value))}
              className="studio-select"
              style={{ width: '100%' }}
            >
              <option value="1000">1,000 lần (Nhanh)</option>
              <option value="5000">5,000 lần (Chuẩn)</option>
              <option value="10000">10,000 lần (Định lượng cao)</option>
            </select>
          </div>

          <div className="studio-config-item">
            <label>Ngưỡng Sụt giảm Cháy (Ruin %)</label>
            <div className="studio-input-group">
              <input
                type="number"
                min="5"
                max="95"
                value={ruinThreshold}
                onChange={(e) => setRuinThreshold(Number(e.target.value))}
              />
              <span>%</span>
            </div>
          </div>

          <div className="studio-config-item">
            <label>Phương pháp Resampling</label>
            <select
              value={blockSize}
              onChange={(e) => setBlockSize(Number(e.target.value))}
              className="studio-select"
              style={{ width: '100%' }}
            >
              <option value="1">Trade Bootstrap (Độc lập)</option>
              <option value="3">Block Bootstrap (Cụm 3 lệnh)</option>
              <option value="5">Block Bootstrap (Cụm 5 lệnh)</option>
            </select>
          </div>

          <div className="studio-config-item" style={{ justifyContent: 'flex-end' }}>
            <button
              className="studio-simulate-btn"
              style={{ width: '100%', marginTop: 20 }}
              onClick={handleRunSimulation}
              disabled={running || tradesCount === 0}
            >
              {running ? (
                <>
                  <span className="studio-btn-spinner"></span>
                  <span>Đang mô phỏng...</span>
                </>
              ) : (
                <>
                  <span>▶ Chạy Monte Carlo</span>
                </>
              )}
            </button>
          </div>
        </div>

        {tradesCount === 0 && (
          <p style={{ margin: '10px 0 0', fontSize: 12, color: 'var(--amber)' }}>
            ⚠️ Chưa có danh sách lệnh nào. Vui lòng bấm "Chuyển sang WFA" từ kết quả Backtest, chạy WFA rồi chuyển tiếp sang đây.
          </p>
        )}

        {error && (
          <div className="studio-error-box" style={{ marginTop: 14 }}>
            <div className="studio-error-title">Lỗi thực thi Monte Carlo</div>
            <div className="studio-error-content">{error}</div>
          </div>
        )}
      </div>

      {/* ── Result Section ── */}
      {result && (
        <>
          {(() => {
            const b = gateBadge(result.source_gate_passed)
            return <div style={{ marginTop: 14, fontSize: 13, fontWeight: 600, color: b.color }}>{b.text}</div>
          })()}
          {/* Risk Metrics Cards */}
          <div className="studio-metrics-grid" style={{ gridTemplateColumns: 'repeat(5, 1fr)', marginTop: 14 }}>
            <div className="studio-metric-card">
              <span className="studio-metric-label">Xác suất Cháy (Risk of Ruin)</span>
              <span
                className="studio-metric-value"
                style={{
                  color: result.risk_of_ruin_pct === 0 ? 'var(--up)' : result.risk_of_ruin_pct <= 2 ? 'var(--amber)' : 'var(--down)',
                }}
              >
                {result.risk_of_ruin_pct}%
              </span>
              <span className="studio-metric-sub">Chạm ngưỡng MDD ≥ {result.ruin_threshold_pct}%</span>
            </div>

            <div className="studio-metric-card">
              <span className="studio-metric-label">Max Drawdown (95% CI)</span>
              <span className="studio-metric-value" style={{ color: 'var(--amber)' }}>
                {result.percentile_mdd?.p95}%
              </span>
              <span className="studio-metric-sub">95% kịch bản MDD dưới mức này</span>
            </div>

            <div className="studio-metric-card">
              <span className="studio-metric-label">Max Drawdown (99% CI)</span>
              <span className="studio-metric-value" style={{ color: 'var(--down)' }}>
                {result.percentile_mdd?.p99}%
              </span>
              <span className="studio-metric-sub">Rủi ro đuôi nghiêm trọng</span>
            </div>

            <div className="studio-metric-card">
              <span className="studio-metric-label">Drawdown Trung vị (P50)</span>
              <span className="studio-metric-value" style={{ color: 'var(--ink)' }}>
                {result.percentile_mdd?.p50}%
              </span>
              <span className="studio-metric-sub">Mức sụt giảm điển hình</span>
            </div>

            <div className="studio-metric-card">
              <span className="studio-metric-label">Tỷ lệ Kịch bản Có lãi</span>
              <span className="studio-metric-value" style={{ color: 'var(--up)' }}>
                {result.summary?.win_ratio_of_simulations}%
              </span>
              <span className="studio-metric-sub">Trong {result.simulations} kịch bản</span>
            </div>
          </div>

          {/* Terminal Return Distribution Box */}
          <div className="studio-alpha-grade-card" style={{ marginTop: 14 }}>
            <div className="studio-alpha-grade-head">
              <span>Phân phối Lợi nhuận Cuối kỳ (Terminal Return Distribution)</span>
              <b>{result.simulations} Lần Mô phỏng</b>
            </div>
            <div className="studio-alpha-checks">
              <div className="studio-alpha-check warn">
                <span>📉</span>
                <b>Kịch bản Thận trọng (P10)</b>
                <em>{result.terminal_return_pct?.p10}%</em>
              </div>
              <div className="studio-alpha-check ok">
                <span>🎯</span>
                <b>Kịch bản Kỳ vọng (Trung vị P50)</b>
                <em>{result.terminal_return_pct?.p50}%</em>
              </div>
              <div className="studio-alpha-check ok">
                <span>🚀</span>
                <b>Kịch bản Lạc quan (P90)</b>
                <em>{result.terminal_return_pct?.p90}%</em>
              </div>
              <div className="studio-alpha-check warn">
                <span>⚠️</span>
                <b>Trường hợp Xấu nhất (Worst)</b>
                <em>{result.terminal_return_pct?.worst}%</em>
              </div>
            </div>
          </div>

          {/* Fan Chart Visualization */}
          <div className="studio-pipeline-card" style={{ marginTop: 14 }}>
            <div className="studio-pipeline-card-title">
              <span>Biểu đồ Phân tán Đường cong Vốn Giả lập (Monte Carlo Equity Fan Chart)</span>
              <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>
                Vẽ 35 đường vốn mẫu từ khởi điểm $10,000 USD
              </span>
            </div>

            <div style={{ position: 'relative', width: '100%', overflowX: 'auto', background: 'var(--panel-2)', borderRadius: 6, padding: '12px 6px' }}>
              <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
                <defs>
                  <linearGradient id="mcPathGrad" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="var(--amber)" stopOpacity="0.1" />
                    <stop offset="100%" stopColor="var(--amber)" stopOpacity="0.4" />
                  </linearGradient>
                </defs>

                {/* Y Axis Grid Lines */}
                {[0, 0.25, 0.5, 0.75, 1].map((pct, idx) => {
                  const val = chartMin + pct * (chartMax - chartMin)
                  const y = padTop + (1 - pct) * (height - padTop - padBottom)
                  return (
                    <g key={idx}>
                      <line x1={padLeft} y1={y} x2={width - padRight} y2={y} stroke="var(--line)" strokeDasharray="3 3" />
                      <text x={padLeft - 6} y={y + 3} fill="var(--ink-3)" fontSize="10" textAnchor="end">
                        ${Math.round(val).toLocaleString()}
                      </text>
                    </g>
                  )
                })}

                {/* Simulation Fan Paths */}
                {fanChartPaths.map((p, idx) => (
                  <path
                    key={idx}
                    d={p.d}
                    fill="none"
                    stroke="var(--amber)"
                    strokeOpacity={idx % 4 === 0 ? '0.45' : '0.18'}
                    strokeWidth={idx % 4 === 0 ? '1.5' : '1'}
                  />
                ))}

                {/* Initial Capital Reference Line */}
                <line
                  x1={padLeft}
                  y1={padTop + (1 - (result.initial_capital - chartMin) / (chartMax - chartMin)) * (height - padTop - padBottom)}
                  x2={width - padRight}
                  y2={padTop + (1 - (result.initial_capital - chartMin) / (chartMax - chartMin)) * (height - padTop - padBottom)}
                  stroke="var(--ink-3)"
                  strokeDasharray="4 2"
                  strokeWidth="1.2"
                />
              </svg>

              <div style={{ display: 'flex', justifyContent: 'center', gap: 20, marginTop: 8, fontSize: 11.5, color: 'var(--ink-2)' }}>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 12, height: 2, background: 'var(--amber)', display: 'inline-block' }}></span> Các kịch bản giả lập
                </span>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ width: 12, height: 1, borderTop: '1px dashed var(--ink-3)', display: 'inline-block' }}></span> Vốn gốc ($10,000)
                </span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
