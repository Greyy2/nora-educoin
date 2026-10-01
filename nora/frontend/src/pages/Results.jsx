import React, { useEffect, useState, useMemo } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Loading, ErrorBox, Empty, Block, Spark, Legend } from '../components/common'
import { Pager, usePaged } from '../components/Pager'
import MetricTable from '../components/MetricTable'
import { int, money } from '../lib/format'

/** Bảng chỉ số chi tiết Backtest bung ra khi bấm vào một lần chạy */
function MetricPanel({ runId }) {
  const [m, setM] = useState(null)
  const [err, setErr] = useState(null)
  const navigate = useNavigate()

  useEffect(() => {
    setM(null)
    setErr(null)
    api.metrics(runId).then(setM).catch(setErr)
  }, [runId])

  if (err) return <div className="msg err">{String(err.message || err)}</div>
  if (!m) return <Loading text="Đang tính chỉ số…" />

  const eq = m.equity_daily || []

  return (
    <div style={{ background: 'var(--panel-2)', borderTop: '1px solid var(--line-2)', padding: '16px 18px' }}>
      <div style={{ border: '1px solid var(--line)', background: 'var(--panel)', marginBottom: 16 }}>
        <MetricTable m={m} gonNheYNghia />
      </div>

      {eq.length > 1 && (
        <div style={{ border: '1px solid var(--line)', background: 'var(--panel)', padding: '12px 14px' }}>
          <div
            style={{
              fontFamily: 'var(--mono)',
              fontSize: 10.5,
              letterSpacing: '.1em',
              textTransform: 'uppercase',
              color: 'var(--ink-3)',
              marginBottom: 8,
            }}
          >
            Đường vốn theo ngày · {eq.length} ngày
            {m.peak_at && ` · sụt sâu nhất từ ${m.peak_at} đến ${m.trough_at}`}
          </div>
          <Spark series={[{ data: eq.map((e) => e.balance), color: 'var(--amber)' }]} height={150} />
          <Legend
            items={[
              { label: 'Số dư đầu', color: 'var(--ink-3)', value: m.start_balance },
              { label: 'Số dư cuối', color: 'var(--amber)', value: m.end_balance },
            ]}
          />
        </div>
      )}

      <div className="bar-ctl" style={{ marginTop: 14, marginBottom: 0 }}>
        <Link className="btn" to={`/library/result/${runId}`}>
          Xem đầy đủ
        </Link>
        <Link className="btn" to={`/library/result/${runId}/trades`}>
          Danh sách lệnh
        </Link>
        <Link className="btn pri" to={`/library/result/${runId}/chart`}>
          Biểu đồ
        </Link>
      </div>
    </div>
  )
}

export default function Results() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = searchParams.get('tab') || 'backtest'
  const navigate = useNavigate()

  // ── Backtest Data ──
  const [rows, setRows] = useState(null)
  const [groups, setGroups] = useState([])
  const [group, setGroup] = useState('')
  const [q, setQ] = useState('')
  const [err, setErr] = useState(null)
  const [openRun, setOpenRun] = useState(null)

  // ── WFA Data ──
  const [wfaHistory, setWfaHistory] = useState([])
  const [loadingWfa, setLoadingWfa] = useState(false)
  const [wfaFilterPass, setWfaFilterPass] = useState(false)
  const [openWfaId, setOpenWfaId] = useState(null)

  // ── Monte Carlo Data ──
  const [mcHistory, setMcHistory] = useState([])
  const [loadingMc, setLoadingMc] = useState(false)
  const [mcFilterPass, setMcFilterPass] = useState(false)
  const [openMcId, setOpenMcId] = useState(null)

  // ── Load Backtest ──
  const loadBacktests = () => {
    setRows(null)
    setErr(null)
    setOpenRun(null)
    api.runs({ group, q, limit: 300 }).then((r) => setRows(r.rows)).catch(setErr)
  }

  // ── Load WFA ──
  const loadWfa = () => {
    setLoadingWfa(true)
    fetch('/api/studio/wfa/history?limit=100')
      .then((r) => r.json())
      .then((data) => setWfaHistory(data.history || []))
      .catch(console.error)
      .finally(() => setLoadingWfa(false))
  }

  // ── Load Monte Carlo ──
  const loadMonteCarlo = () => {
    setLoadingMc(true)
    fetch('/api/studio/monte-carlo/history?limit=100')
      .then((r) => r.json())
      .then((data) => setMcHistory(data.history || []))
      .catch(console.error)
      .finally(() => setLoadingMc(false))
  }

  useEffect(() => {
    api.groups().then((r) => setGroups(r.rows)).catch(() => {})
    loadBacktests()
    loadWfa()
    loadMonteCarlo()
  }, [])

  useEffect(() => {
    if (activeTab === 'backtest') loadBacktests()
    if (activeTab === 'wfa') loadWfa()
    if (activeTab === 'carlo') loadMonteCarlo()
  }, [activeTab, group])

  const pg = usePaged(rows)

  // ── Funnel Counters ──
  const totalBacktests = rows ? rows.length : 0
  const passWfaList = useMemo(() => wfaHistory.filter((i) => i.acceptance_gate_passed), [wfaHistory])
  const passMcList = useMemo(
    () => mcHistory.filter((i) => (i.risk_of_ruin_pct ?? 100) === 0 && (i.percentile_mdd?.p95 ?? 100) <= 20),
    [mcHistory]
  )

  const displayedWfa = wfaFilterPass ? passWfaList : wfaHistory
  const displayedMc = mcFilterPass ? passMcList : mcHistory

  const formatTs = (ms) => {
    if (!ms) return 'N/A'
    return new Date(ms).toLocaleString('vi-VN', {
      hour: '2-digit',
      minute: '2-digit',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    })
  }

  return (
    <>
      {/* ── Page Header ── */}
      <div className="head" style={{ paddingBottom: 12 }}>
        <div className="head-row">
          <div>
            <h1 style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span>Kết quả kiểm định định lượng</span>
              <span className="tag" style={{ fontSize: 12 }}>Funnel Result</span>
            </h1>
            <p style={{ margin: '4px 0 0', color: 'var(--ink-3)', fontSize: 13 }}>
              Theo dõi kết quả 3 tầng của phễu định lượng: <strong>Backtest ➔ Walk-Forward (WFA) ➔ Monte Carlo</strong>.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className="btn"
              onClick={() => {
                loadBacktests()
                loadWfa()
                loadMonteCarlo()
              }}
              style={{ fontSize: 12 }}
            >
              🔄 Làm mới toàn bộ
            </button>
          </div>
        </div>

        {/* ── Quantitative Funnel Overview Summary Bar ── */}
        <div
          style={{
            marginTop: 16,
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 12,
          }}
        >
          {/* Card 1: Backtest */}
          <div
            onClick={() => setSearchParams({ tab: 'backtest' })}
            style={{
              padding: '14px 18px',
              background: activeTab === 'backtest' ? 'rgba(245, 158, 11, 0.08)' : 'var(--surface-1)',
              border: `1px solid ${activeTab === 'backtest' ? 'var(--amber)' : 'var(--line)'}`,
              borderRadius: 8,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--ink-3)', fontWeight: 600 }}>
              Tầng 1 · Backtest Candidates
            </div>
            <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--ink)', margin: '4px 0' }}>
              {totalBacktests.toLocaleString()} <span style={{ fontSize: 13, fontWeight: 400, color: 'var(--ink-3)' }}>lần chạy</span>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>
              Kiểm tra Logic & Edge trên nến lịch sử
            </div>
          </div>

          {/* Card 2: WFA */}
          <div
            onClick={() => setSearchParams({ tab: 'wfa' })}
            style={{
              padding: '14px 18px',
              background: activeTab === 'wfa' ? 'rgba(59, 130, 246, 0.08)' : 'var(--surface-1)',
              border: `1px solid ${activeTab === 'wfa' ? '#3b82f6' : 'var(--line)'}`,
              borderRadius: 8,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--ink-3)', fontWeight: 600, display: 'flex', justifyContent: 'space-between' }}>
              <span>Tầng 2 · Walk-Forward (WFA)</span>
              <span style={{ color: '#10b981', fontWeight: 700 }}>
                {wfaHistory.length > 0 ? `${((passWfaList.length / wfaHistory.length) * 100).toFixed(0)}% Pass` : '—'}
              </span>
            </div>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#3b82f6', margin: '4px 0' }}>
              {passWfaList.length}{' '}
              <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--ink-3)' }}>
                / {wfaHistory.length} kiểm định
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>
              Lọc bỏ Overfitting trên 12 Folds OOS
            </div>
          </div>

          {/* Card 3: Monte Carlo */}
          <div
            onClick={() => setSearchParams({ tab: 'carlo' })}
            style={{
              padding: '14px 18px',
              background: activeTab === 'carlo' ? 'rgba(16, 185, 129, 0.08)' : 'var(--surface-1)',
              border: `1px solid ${activeTab === 'carlo' ? '#10b981' : 'var(--line)'}`,
              borderRadius: 8,
              cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <div style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--ink-3)', fontWeight: 600, display: 'flex', justifyContent: 'space-between' }}>
              <span>Tầng 3 · Monte Carlo Stress-Test</span>
              <span style={{ color: '#10b981', fontWeight: 700 }}>
                {mcHistory.length > 0 ? `${((passMcList.length / mcHistory.length) * 100).toFixed(0)}% Pass` : '—'}
              </span>
            </div>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#10b981', margin: '4px 0' }}>
              {passMcList.length}{' '}
              <span style={{ fontSize: 14, fontWeight: 400, color: 'var(--ink-3)' }}>
                / {mcHistory.length} mô phỏng
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>
              Xác nhận Ruin = 0% & P95 VaR MDD ≤ 20%
            </div>
          </div>
        </div>

        {/* ── Tab Switcher ── */}
        <div style={{ marginTop: 16, display: 'flex', gap: 6, borderBottom: '1px solid var(--line)', paddingBottom: 6 }}>
          <button
            className={`btn ${activeTab === 'backtest' ? 'active' : ''}`}
            onClick={() => setSearchParams({ tab: 'backtest' })}
            style={{
              fontSize: 13,
              background: activeTab === 'backtest' ? 'var(--amber)' : 'transparent',
              color: activeTab === 'backtest' ? '#fff' : 'var(--ink)',
              border: 'none',
              padding: '6px 14px',
              borderRadius: 6,
            }}
          >
            1. Kết quả Backtest ({totalBacktests})
          </button>
          <button
            className={`btn ${activeTab === 'wfa' ? 'active' : ''}`}
            onClick={() => setSearchParams({ tab: 'wfa' })}
            style={{
              fontSize: 13,
              background: activeTab === 'wfa' ? '#3b82f6' : 'transparent',
              color: activeTab === 'wfa' ? '#fff' : 'var(--ink)',
              border: 'none',
              padding: '6px 14px',
              borderRadius: 6,
            }}
          >
            2. Kết quả Walk-Forward ({wfaHistory.length})
          </button>
          <button
            className={`btn ${activeTab === 'carlo' ? 'active' : ''}`}
            onClick={() => setSearchParams({ tab: 'carlo' })}
            style={{
              fontSize: 13,
              background: activeTab === 'carlo' ? '#10b981' : 'transparent',
              color: activeTab === 'carlo' ? '#fff' : 'var(--ink)',
              border: 'none',
              padding: '6px 14px',
              borderRadius: 6,
            }}
          >
            3. Kết quả Monte Carlo ({mcHistory.length})
          </button>
        </div>
      </div>

      {/* ════════════════════ TAB 1: BACKTEST ════════════════════ */}
      {activeTab === 'backtest' && (
        <>
          <div className="bar-ctl" style={{ marginTop: 12 }}>
            <select value={group} onChange={(e) => setGroup(e.target.value)}>
              <option value="">Tất cả nhóm</option>
              {groups.map((g) => (
                <option key={g.name} value={g.name}>
                  {g.name} ({g.n})
                </option>
              ))}
            </select>
            <input
              placeholder="Tìm theo tên hoặc mã…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && loadBacktests()}
              style={{ minWidth: 240 }}
            />
            <button className="btn" onClick={loadBacktests}>
              Tìm
            </button>
          </div>

          <Block flush>
            {err ? (
              <ErrorBox error={err} onRetry={loadBacktests} />
            ) : rows === null ? (
              <Loading text="Đang nạp danh sách Backtest..." />
            ) : rows.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center' }}>
                <Empty text="Chưa có lần chạy Backtest nào." />
                <div style={{ marginTop: 14 }}>
                  <Link to="/library/base" className="btn btn-primary">
                    Sang Base để cấu hình chạy Backtest ➔
                  </Link>
                </div>
              </div>
            ) : (
              <>
                <div className="tblwrap">
                  <table>
                    <thead>
                      <tr>
                        <th style={{ width: 26 }}></th>
                        <th>Mã</th>
                        <th>Tên lần chạy</th>
                        <th>Nhóm</th>
                        <th className="n">Số lệnh</th>
                        <th className="n">Số dư</th>
                        <th>Trạng thái</th>
                        <th style={{ textAlign: 'right' }}>Thao tác</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pg.slice.map((r) => (
                        <React.Fragment key={r.id}>
                          <tr
                            className="rowlink"
                            onClick={() => setOpenRun(openRun === r.id ? null : r.id)}
                            style={openRun === r.id ? { background: 'var(--panel-2)' } : undefined}
                          >
                            <td style={{ color: 'var(--amber)', fontFamily: 'var(--mono)' }}>
                              {openRun === r.id ? '▾' : '▸'}
                            </td>
                            <td className="mono">{r.id}</td>
                            <td>{r.name || '—'}</td>
                            <td style={{ color: 'var(--ink-3)' }}>{r.group || '—'}</td>
                            <td className="n">{r.trades ? int(r.trades) : '—'}</td>
                            <td className="n">{money(r.balance)}</td>
                            <td>
                              <span className={`tag ${r.running ? 'run' : 'stop'}`}>
                                {r.running ? 'Đang chạy' : 'Đã dừng'}
                              </span>
                            </td>
                            <td style={{ textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                              <button
                                className="btn"
                                disabled
                                title="Run legacy (MySQL) chưa có snapshot AST nên không chạy được WFA. Hãy chạy lại chiến lược trong Studio."
                                style={{ fontSize: 11.5, padding: '3px 10px' }}
                              >
                                WFA: cần Studio
                              </button>
                            </td>
                          </tr>
                          {openRun === r.id && (
                            <tr>
                              <td colSpan={8} style={{ padding: 0, whiteSpace: 'normal' }}>
                                <MetricPanel runId={r.id} />
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pager {...pg} unit="lần chạy" />
              </>
            )}
          </Block>
        </>
      )}

      {/* ════════════════════ TAB 2: WALK-FORWARD (WFA) ════════════════════ */}
      {activeTab === 'wfa' && (
        <div style={{ marginTop: 12 }}>
          {/* Controls Bar */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>Bộ lọc:</span>
              <button
                className={`btn ${!wfaFilterPass ? 'active' : ''}`}
                onClick={() => setWfaFilterPass(false)}
                style={{
                  fontSize: 12,
                  background: !wfaFilterPass ? '#3b82f6' : 'transparent',
                  color: !wfaFilterPass ? '#fff' : 'var(--ink)',
                }}
              >
                Tất cả ({wfaHistory.length})
              </button>
              <button
                className={`btn ${wfaFilterPass ? 'active' : ''}`}
                onClick={() => setWfaFilterPass(true)}
                style={{
                  fontSize: 12,
                  background: wfaFilterPass ? '#10b981' : 'transparent',
                  color: wfaFilterPass ? '#fff' : 'var(--ink)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                <span>✓ Chỉ xem PASS</span>
                <span className="badge" style={{ background: 'rgba(255,255,255,0.2)', padding: '1px 6px', borderRadius: 10 }}>
                  {passWfaList.length}
                </span>
              </button>
            </div>
            <Link to="/library/wfa" className="btn btn-primary" style={{ fontSize: 12 }}>
              + Sang màn hình chạy WFA
            </Link>
          </div>

          <Block flush>
            {loadingWfa ? (
              <Loading text="Đang nạp lịch sử Walk-Forward..." />
            ) : displayedWfa.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center' }}>
                <Empty
                  text={
                    wfaFilterPass
                      ? 'Chưa có chiến lược nào vượt qua Acceptance Gate của WFA.'
                      : 'Chưa có lần chạy WFA nào được ghi lại.'
                  }
                />
                <div style={{ marginTop: 14 }}>
                  <Link to="/library/wfa" className="btn btn-primary">
                    Sang Walk-Forward để kiểm định ngay ➔
                  </Link>
                </div>
              </div>
            ) : (
              <div className="tblwrap">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 26 }}></th>
                      <th>Mã Job</th>
                      <th>Chiến lược</th>
                      <th>Coin</th>
                      <th>Folds</th>
                      <th className="n">Lợi nhuận OOS TB</th>
                      <th className="n">Worst MDD</th>
                      <th>Acceptance Gate</th>
                      <th>Thời gian</th>
                      <th style={{ textAlign: 'right' }}>Thao tác</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayedWfa.map((item) => {
                      const isPass = item.acceptance_gate_passed
                      const oosRet = item.avg_oos_return_pct
                      const mdd = item.worst_fold_mdd_pct
                      const isOpen = openWfaId === item.job_id
                      return (
                        <React.Fragment key={item.job_id}>
                          <tr
                            className="rowlink"
                            onClick={() => setOpenWfaId(isOpen ? null : item.job_id)}
                            style={isOpen ? { background: 'var(--panel-2)' } : undefined}
                          >
                            <td style={{ color: '#3b82f6', fontFamily: 'var(--mono)' }}>
                              {isOpen ? '▾' : '▸'}
                            </td>
                            <td className="mono" style={{ fontSize: 11 }}>{item.job_id.slice(-14)}</td>
                            <td style={{ fontWeight: 600 }}>{item.strategy_name}</td>
                            <td>
                              <span className="tag" style={{ fontSize: 11 }}>{item.symbol}</span>
                            </td>
                            <td>{item.total_folds} Folds</td>
                            <td
                              className="n"
                              style={{ color: (oosRet ?? 0) >= 0 ? '#10b981' : '#ef4444', fontWeight: 600 }}
                            >
                              {oosRet != null ? `${oosRet >= 0 ? '+' : ''}${oosRet.toFixed(2)}%` : '—'}
                            </td>
                            <td
                              className="n"
                              style={{ color: (mdd ?? 0) <= 15 ? '#10b981' : '#f59e0b' }}
                            >
                              {mdd != null ? `${mdd.toFixed(2)}%` : '—'}
                            </td>
                            <td>
                              {item.status === 'completed' ? (
                                <span
                                  className="tag"
                                  style={{
                                    background: isPass ? 'rgba(16,185,129,0.15)' : 'rgba(245,158,11,0.15)',
                                    color: isPass ? '#10b981' : '#f59e0b',
                                    fontSize: 11,
                                  }}
                                >
                                  {isPass ? '✓ ĐẠT' : '⚠ CẢNH BÁO'}
                                </span>
                              ) : (
                                <span className="tag" style={{ fontSize: 11 }}>{item.status}</span>
                              )}
                            </td>
                            <td style={{ color: 'var(--ink-3)', fontSize: 11 }}>{formatTs(item.created_at)}</td>
                            <td style={{ textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                              <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                                {item.result && (
                                  <button
                                    className="btn btn-primary"
                                    onClick={() => {
                                      navigate('/library/monte-carlo', {
                                        state: {
                                          mcInput: {
                                            source_wfa_id: item.job_id,
                                            source_handle: item.result.source_handle,
                                            trades: item.result.aggregate_oos_trades || [],
                                            symbol: item.symbol,
                                            strategy_name: item.strategy_name,
                                          },
                                          autoRun: true,
                                        },
                                      })
                                    }}
                                    style={{ fontSize: 11, padding: '3px 8px' }}
                                  >
                                    🎲 Chạy Monte Carlo ➔
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>

                          {/* WFA Fold Breakdown Accordion */}
                          {isOpen && item.result && (
                            <tr>
                              <td colSpan={10} style={{ padding: '14px 18px', background: 'var(--surface-2)', borderBottom: '1px solid var(--line)' }}>
                                <div style={{ fontSize: 12, marginBottom: 8, fontWeight: 600 }}>
                                  Chi tiết các Fold Out-of-Sample ({item.result.folds?.length || 0} Folds):
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
                                  {item.result.folds?.map((f, i) => (
                                    <div
                                      key={i}
                                      style={{
                                        background: 'var(--surface-1)',
                                        border: '1px solid var(--line)',
                                        borderRadius: 6,
                                        padding: '8px 12px',
                                        fontSize: 11.5,
                                      }}
                                    >
                                      <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 600 }}>
                                        <span>Fold #{f.fold_index}</span>
                                        <span style={{ color: f.oos_return_pct >= 0 ? '#10b981' : '#ef4444' }}>
                                          {f.oos_return_pct >= 0 ? '+' : ''}{f.oos_return_pct.toFixed(2)}%
                                        </span>
                                      </div>
                                      <div style={{ color: 'var(--ink-3)', fontSize: 10.5, marginTop: 4 }}>
                                        MDD: {f.oos_max_drawdown_pct.toFixed(2)}% · Lệnh: {f.oos_trades_count}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Block>
        </div>
      )}

      {/* ════════════════════ TAB 3: MONTE CARLO ════════════════════ */}
      {activeTab === 'carlo' && (
        <div style={{ marginTop: 12 }}>
          {/* Controls Bar */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>Bộ lọc:</span>
              <button
                className={`btn ${!mcFilterPass ? 'active' : ''}`}
                onClick={() => setMcFilterPass(false)}
                style={{
                  fontSize: 12,
                  background: !mcFilterPass ? '#10b981' : 'transparent',
                  color: !mcFilterPass ? '#fff' : 'var(--ink)',
                }}
              >
                Tất cả ({mcHistory.length})
              </button>
              <button
                className={`btn ${mcFilterPass ? 'active' : ''}`}
                onClick={() => setMcFilterPass(true)}
                style={{
                  fontSize: 12,
                  background: mcFilterPass ? '#10b981' : 'transparent',
                  color: mcFilterPass ? '#fff' : 'var(--ink)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                <span>✓ Chỉ xem PASS (An toàn vốn)</span>
                <span className="badge" style={{ background: 'rgba(255,255,255,0.2)', padding: '1px 6px', borderRadius: 10 }}>
                  {passMcList.length}
                </span>
              </button>
            </div>
            <Link to="/library/monte-carlo" className="btn btn-primary" style={{ fontSize: 12 }}>
              + Sang màn hình Monte Carlo
            </Link>
          </div>

          <Block flush>
            {loadingMc ? (
              <Loading text="Đang nạp lịch sử Monte Carlo..." />
            ) : displayedMc.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center' }}>
                <Empty
                  text={
                    mcFilterPass
                      ? 'Chưa có chiến lược nào đạt chuẩn an toàn vốn (Ruin = 0% & MDD ≤ 20%).'
                      : 'Chưa có lần mô phỏng Monte Carlo nào được lưu.'
                  }
                />
                <div style={{ marginTop: 14 }}>
                  <Link to="/library/monte-carlo" className="btn btn-primary">
                    Sang Monte Carlo để stress-test ngay ➔
                  </Link>
                </div>
              </div>
            ) : (
              <div className="tblwrap">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 26 }}></th>
                      <th>Mã Job</th>
                      <th>Chiến lược</th>
                      <th>Coin</th>
                      <th>Kịch bản</th>
                      <th>Lệnh OOS</th>
                      <th className="n">Xác suất cháy (Ruin)</th>
                      <th className="n">P95 VaR MDD</th>
                      <th className="n">Tỷ lệ thắng kịch bản</th>
                      <th>Thời gian</th>
                      <th style={{ textAlign: 'right' }}>Thao tác</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayedMc.map((item) => {
                      const ruin = item.risk_of_ruin_pct
                      const p95Mdd = item.percentile_mdd?.p95
                      const winRatio = item.summary?.win_ratio_of_simulations
                      const isOpen = openMcId === item.job_id
                      return (
                        <React.Fragment key={item.job_id}>
                          <tr
                            className="rowlink"
                            onClick={() => setOpenMcId(isOpen ? null : item.job_id)}
                            style={isOpen ? { background: 'var(--panel-2)' } : undefined}
                          >
                            <td style={{ color: '#10b981', fontFamily: 'var(--mono)' }}>
                              {isOpen ? '▾' : '▸'}
                            </td>
                            <td className="mono" style={{ fontSize: 11 }}>{item.job_id.slice(-14)}</td>
                            <td style={{ fontWeight: 600 }}>{item.strategy_name}</td>
                            <td>
                              <span className="tag" style={{ fontSize: 11 }}>{item.symbol}</span>
                            </td>
                            <td>{item.simulations?.toLocaleString()} runs</td>
                            <td>{item.trades_count} lệnh</td>
                            <td
                              className="n"
                              style={{ color: (ruin ?? 0) === 0 ? '#10b981' : '#ef4444', fontWeight: 600 }}
                            >
                              {ruin != null ? `${ruin.toFixed(1)}%` : '—'}
                            </td>
                            <td
                              className="n"
                              style={{ color: (p95Mdd ?? 0) <= 20 ? '#10b981' : '#f59e0b' }}
                            >
                              {p95Mdd != null ? `${p95Mdd.toFixed(2)}%` : '—'}
                            </td>
                            <td className="n" style={{ fontWeight: 600 }}>
                              {winRatio != null ? `${winRatio.toFixed(1)}%` : '—'}
                            </td>
                            <td style={{ color: 'var(--ink-3)', fontSize: 11 }}>{formatTs(item.created_at)}</td>
                            <td style={{ textAlign: 'right' }} onClick={(e) => e.stopPropagation()}>
                              {item.result && (
                                <button
                                  className="btn btn-primary"
                                  onClick={() => {
                                    navigate('/library/monte-carlo', {
                                      state: {
                                        mcInput: {
                                          trades: item.result.trades || [],
                                          symbol: item.symbol,
                                          strategy_name: item.strategy_name,
                                          source_handle: item.job_id,
                                        },
                                      },
                                    })
                                  }}
                                  style={{ fontSize: 11, padding: '3px 8px' }}
                                >
                                  📂 Mở Fan Chart ➔
                                </button>
                              )}
                            </td>
                          </tr>

                          {/* Monte Carlo Percentiles Accordion */}
                          {isOpen && item.result && (
                            <tr>
                              <td colSpan={11} style={{ padding: '14px 18px', background: 'var(--surface-2)', borderBottom: '1px solid var(--line)' }}>
                                <div style={{ fontSize: 12, marginBottom: 8, fontWeight: 600 }}>
                                  Phân phối rủi ro đuôi Monte Carlo ({item.simulations?.toLocaleString()} simulations):
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
                                  <div style={{ background: 'var(--surface-1)', border: '1px solid var(--line)', borderRadius: 6, padding: '8px 12px' }}>
                                    <div style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>Median MDD (P50)</div>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--ink)' }}>{item.result.percentile_mdd?.p50?.toFixed(2)}%</div>
                                  </div>
                                  <div style={{ background: 'var(--surface-1)', border: '1px solid var(--line)', borderRadius: 6, padding: '8px 12px' }}>
                                    <div style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>P90 VaR MDD</div>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: '#f59e0b' }}>{item.result.percentile_mdd?.p90?.toFixed(2)}%</div>
                                  </div>
                                  <div style={{ background: 'var(--surface-1)', border: '1px solid var(--line)', borderRadius: 6, padding: '8px 12px' }}>
                                    <div style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>P95 VaR MDD</div>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: '#f59e0b' }}>{item.result.percentile_mdd?.p95?.toFixed(2)}%</div>
                                  </div>
                                  <div style={{ background: 'var(--surface-1)', border: '1px solid var(--line)', borderRadius: 6, padding: '8px 12px' }}>
                                    <div style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>P99 Worst Case MDD</div>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: '#ef4444' }}>{item.result.percentile_mdd?.p99?.toFixed(2)}%</div>
                                  </div>
                                  <div style={{ background: 'var(--surface-1)', border: '1px solid var(--line)', borderRadius: 6, padding: '8px 12px' }}>
                                    <div style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>Lợi nhuận trung vị</div>
                                    <div style={{ fontSize: 15, fontWeight: 700, color: '#10b981' }}>${Math.round(item.result.summary?.median_profit_usd || 0).toLocaleString()}</div>
                                  </div>
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Block>
        </div>
      )}
    </>
  )
}
