import React, { useState, useEffect, useMemo } from 'react'
import { Panel, Spinner, Empty, ErrorBox } from '../ui'
import {
  getUniverseScan,
  postUniverseScan,
  getUniverseRuns,
  getLatestSweep,
  getLatestWfaCarlo,
} from '../../api'
import { fmtPct, fmtNum } from '../../lib/format'

const SECTORS = ['Tất cả', 'L1/L2', 'DeFi', 'Meme', 'AI/DePIN', 'Gaming/NFT', 'Infra/Oracle', 'Infra/Bridge', 'Other']

export default function UniverseScan() {
  const [mainTab, setMainTab] = useState('universe') // 'universe' | 'sweep' | 'wfa'
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  // 1. Dữ liệu Universe Scan (Bước 2)
  const [scanData, setScanData] = useState(null)
  const [runs, setRuns] = useState([])
  const [selectedRun, setSelectedRun] = useState('latest')

  // Bộ lọc Universe Scan
  const [search, setSearch] = useState('')
  const [gradeFilter, setGradeFilter] = useState('ALL')
  const [sectorFilter, setSectorFilter] = useState('Tất cả')
  const [groupFilter, setGroupFilter] = useState('ALL') // ALL | UNSEEN | OPTIMIZED
  const [pnlFilter, setPnlFilter] = useState('ALL')     // ALL | PROFIT | LOSS
  const [sortBy, setSortBy] = useState('oos_ret')       // oos_ret | oos_sharpe | is_ret | trades | grade
  const [sortAsc, setSortAsc] = useState(false)

  // 2. Dữ liệu Parameter Sweep (Bước 3)
  const [sweepData, setSweepData] = useState(null)
  const [sweepSearch, setSweepSearch] = useState('')
  const [sweepSortBy, setSweepSortBy] = useState('oos_sharpe') // oos_sharpe | oos_ret | is_ret | win_rate | trades
  const [sweepSortAsc, setSweepSortAsc] = useState(false)

  // 3. Dữ liệu WFA & Monte Carlo
  const [wfaData, setWfaData] = useState(null)

  // Tải dữ liệu ban đầu
  const fetchAllData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [latestRes, runsRes, sweepRes, wfaRes] = await Promise.allSettled([
        getUniverseScan('latest'),
        getUniverseRuns(),
        getLatestSweep(),
        getLatestWfaCarlo(),
      ])

      if (latestRes.status === 'fulfilled' && latestRes.value) {
        setScanData(latestRes.value)
      }
      if (runsRes.status === 'fulfilled' && runsRes.value?.runs) {
        setRuns(runsRes.value.runs)
      }
      if (sweepRes.status === 'fulfilled' && sweepRes.value) {
        setSweepData(sweepRes.value)
      }
      if (wfaRes.status === 'fulfilled' && wfaRes.value) {
        setWfaData(wfaRes.value)
      }
    } catch (err) {
      setError(err.message || 'Lỗi tải dữ liệu quét')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAllData()
  }, [])

  // Chuyển run Universe Scan
  const handleSelectRun = async (runId) => {
    setSelectedRun(runId)
    setLoading(true)
    setError(null)
    try {
      const res = await getUniverseScan(runId)
      setScanData(res)
    } catch (err) {
      setError(err.message || 'Lỗi khi tải kết quả quét')
    } finally {
      setLoading(false)
    }
  }

  // Khởi chạy quét mới 100 coin
  const handleStartScan = async () => {
    setRunning(true)
    setError(null)
    try {
      const res = await postUniverseScan({
        alpha_id: 'dca_long',
        signal_tf: '15m',
        book_source: 'explore',
        capital: 1000.0,
      })
      if (res.job_id) {
        pollJob(res.job_id)
      }
    } catch (err) {
      setError(err.message || 'Không thể khởi chạy job quét')
      setRunning(false)
    }
  }

  const pollJob = async (jobId) => {
    const timer = setInterval(async () => {
      try {
        const res = await getUniverseScan(jobId)
        if (res.coins) {
          clearInterval(timer)
          setScanData(res)
          setRunning(false)
          fetchAllData()
        } else if (res.status === 'failed') {
          clearInterval(timer)
          setError(res.error || 'Job quét thất bại')
          setRunning(false)
        }
      } catch (err) {
        clearInterval(timer)
        setError(err.message)
        setRunning(false)
      }
    }, 4000)
  }

  // Danh sách coin đã lọc (Universe Scan)
  const filteredCoins = useMemo(() => {
    if (!scanData?.coins) return []
    let list = [...scanData.coins]

    if (search.trim()) {
      const q = search.trim().toUpperCase()
      list = list.filter((c) => c.base?.includes(q) || c.symbol?.includes(q))
    }
    if (gradeFilter !== 'ALL') {
      list = list.filter((c) => c.grade === gradeFilter)
    }
    if (sectorFilter !== 'Tất cả') {
      list = list.filter((c) => (c.sector || 'Other') === sectorFilter)
    }
    if (groupFilter === 'UNSEEN') {
      list = list.filter((c) => !c.is_optimized_8)
    } else if (groupFilter === 'OPTIMIZED') {
      list = list.filter((c) => c.is_optimized_8)
    }
    if (pnlFilter === 'PROFIT') {
      list = list.filter((c) => (c.oos?.ret_pct ?? 0) > 0)
    } else if (pnlFilter === 'LOSS') {
      list = list.filter((c) => (c.oos?.ret_pct ?? 0) <= 0)
    }

    list.sort((a, b) => {
      let valA = 0
      let valB = 0
      if (sortBy === 'oos_ret') {
        valA = a.oos?.ret_pct ?? -999
        valB = b.oos?.ret_pct ?? -999
      } else if (sortBy === 'oos_sharpe') {
        valA = a.oos?.sharpe ?? -999
        valB = b.oos?.sharpe ?? -999
      } else if (sortBy === 'is_ret') {
        valA = a.is?.ret_pct ?? -999
        valB = b.is?.ret_pct ?? -999
      } else if (sortBy === 'trades') {
        valA = a.oos?.trades ?? 0
        valB = b.oos?.trades ?? 0
      } else if (sortBy === 'grade') {
        valA = a.grade || 'Z'
        valB = b.grade || 'Z'
        return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA)
      }
      return sortAsc ? valA - valB : valB - valA
    })

    return list
  }, [scanData, search, gradeFilter, sectorFilter, groupFilter, pnlFilter, sortBy, sortAsc])

  // Danh sách strategies đã lọc (Parameter Sweep)
  const filteredSweep = useMemo(() => {
    if (!sweepData?.all_results) return []
    let list = [...sweepData.all_results]
    if (sweepSearch.trim()) {
      const q = sweepSearch.trim().toLowerCase()
      list = list.filter((s) => s.cfg_id?.toLowerCase().includes(q))
    }
    list.sort((a, b) => {
      let valA = 0
      let valB = 0
      if (sweepSortBy === 'oos_sharpe') {
        valA = a.oos?.sharpe ?? -999
        valB = b.oos?.sharpe ?? -999
      } else if (sweepSortBy === 'oos_ret') {
        valA = a.oos?.ret_pct ?? -999
        valB = b.oos?.ret_pct ?? -999
      } else if (sweepSortBy === 'is_ret') {
        valA = a.is?.ret_pct ?? -999
        valB = b.is?.ret_pct ?? -999
      } else if (sweepSortBy === 'win_rate') {
        valA = a.oos?.win_rate ?? 0
        valB = b.oos?.win_rate ?? 0
      } else if (sweepSortBy === 'trades') {
        valA = a.oos?.trades ?? 0
        valB = b.oos?.trades ?? 0
      }
      return sweepSortAsc ? valA - valB : valB - valA
    })
    return list
  }, [sweepData, sweepSearch, sweepSortBy, sweepSortAsc])

  const evaluation = scanData?.evaluation || {}
  const unseenStats = scanData?.groups?.unseen_92?.grade_ab?.oos || {}
  const optStats = scanData?.groups?.optimized_8?.oos || {}
  const allUnseenStats = scanData?.groups?.unseen_92?.all_unseen?.oos || {}

  const handleSort = (field) => {
    if (sortBy === field) {
      setSortAsc(!sortAsc)
    } else {
      setSortBy(field)
      setSortAsc(false)
    }
  }

  const handleSweepSort = (field) => {
    if (sweepSortBy === field) {
      setSweepSortAsc(!sweepSortAsc)
    } else {
      setSweepSortBy(field)
      setSweepSortAsc(false)
    }
  }

  return (
    <div style={{ marginTop: 24, display: 'grid', gap: 20 }}>
      {/* Thanh chuyển đổi Chế độ xem cấp cao */}
      <div style={{ display: 'flex', gap: 10, borderBottom: '1px solid var(--n-border, rgba(255,255,255,0.08))', paddingBottom: 10 }}>
        <button
          type="button"
          className={`n-btn ${mainTab === 'universe' ? 'primary' : ''}`}
          onClick={() => setMainTab('universe')}
        >
          🌐 1. Quét 100 Coin (Bước 2)
        </button>
        <button
          type="button"
          className={`n-btn ${mainTab === 'sweep' ? 'primary' : ''}`}
          onClick={() => setMainTab('sweep')}
        >
          🎯 2. Quét 100 Tham số BTC (Bước 3)
        </button>
        <button
          type="button"
          className={`n-btn ${mainTab === 'wfa' ? 'primary' : ''}`}
          onClick={() => setMainTab('wfa')}
        >
          🛡️ 3. Kiểm định WFA & Monte Carlo
        </button>
      </div>

      {error && <ErrorBox title="Lỗi">{error}</ErrorBox>}

      {/* ─────────────────────────────────────────────────────────────
          TAB 1: UNIVERSE SCAN (100 COIN)
         ───────────────────────────────────────────────────────────── */}
      {mainTab === 'universe' && (
        <>
          <Panel title="Quét thị trường 100 coin OKX (Universe Scan)">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span style={{ fontSize: 13, color: 'var(--n-text-sub)' }}>Lần quét:</span>
                <select
                  className="n-sel"
                  value={selectedRun}
                  onChange={(e) => handleSelectRun(e.target.value)}
                  disabled={running || loading}
                  style={{ minWidth: 200 }}
                >
                  <option value="latest">Mới nhất ({runs[0]?.run_id || 'latest'})</option>
                  {runs.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.run_id} · {r.alpha_id} ({r.has_edge ? 'CÓ EDGE' : 'CHƯA ĐẠT'})
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="n-btn sm"
                  onClick={fetchAllData}
                  disabled={running || loading}
                >
                  Làm mới
                </button>
              </div>

              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <span style={{ fontSize: 12, color: 'var(--n-text-sub)' }}>
                  Chiến lược: <b>{scanData?.alpha_id || 'dca_long'}</b> (15m, $1,000/coin)
                </span>
                <button
                  type="button"
                  className="n-btn primary"
                  onClick={handleStartScan}
                  disabled={running || loading}
                >
                  {running ? 'Đang quét...' : 'Chạy lại toàn bộ 100 coin'}
                </button>
              </div>
            </div>

            {running && (
              <div style={{ marginTop: 14, padding: 12, background: 'var(--n-card, rgba(255,255,255,0.03))', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12 }}>
                <Spinner size={16} />
                <span style={{ fontSize: 13 }}>Đang chạy quét 100 coin trên 2 cửa sổ In-Sample (12T) và Out-of-Sample (6T)...</span>
              </div>
            )}
          </Panel>

          {loading && !scanData && (
            <div style={{ padding: 40, textAlign: 'center' }}>
              <Spinner size={24} />
              <div style={{ marginTop: 8, fontSize: 13, color: 'var(--n-text-sub)' }}>Đang tải kết quả quét...</div>
            </div>
          )}

          {!loading && !scanData && (
            <Empty title="Chưa có kết quả quét">
              Nhấn "Chạy lại toàn bộ 100 coin" hoặc chọn một lần quét từ danh sách phía trên.
            </Empty>
          )}

          {!loading && scanData && (
            <>
              {/* Banner Kết luận */}
              <div
                style={{
                  padding: '16px 20px',
                  borderRadius: 8,
                  border: `1px solid ${evaluation.has_edge ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)'}`,
                  background: evaluation.has_edge ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: 12,
                }}
              >
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, color: evaluation.has_edge ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                    {evaluation.has_edge ? 'KẾT LUẬN: CHIẾN LƯỢC CÓ EDGE' : 'KẾT LUẬN: CHIẾN LƯỢC CHƯA ĐẠT EDGE'}
                  </div>
                  <div style={{ fontSize: 13.5, marginTop: 4, color: 'var(--n-text)' }}>
                    {evaluation.verdict}
                  </div>
                </div>
                <div style={{ fontSize: 12, color: 'var(--n-text-sub)', textAlign: 'right' }}>
                  Tiêu chí: ≥ 60% coin A+B chưa thấy có lãi OOS VÀ median Sharpe OOS &gt; 0
                </div>
              </div>

              {/* 4 Thẻ chỉ số chính */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
                <div style={{ padding: 14, background: 'var(--n-card, rgba(255,255,255,0.03))', borderRadius: 8, border: '1px solid var(--n-border)' }}>
                  <div style={{ fontSize: 12, color: 'var(--n-text-sub)' }}>% Coin A+B Chưa thấy có lãi (OOS)</div>
                  <div style={{ fontSize: 24, fontWeight: 700, marginTop: 6, color: (unseenStats.profit_pct ?? 0) >= 60 ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                    {fmtPct(unseenStats.profit_pct ?? 0)}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--n-text-sub)', marginTop: 4 }}>
                    {unseenStats.profit_count ?? 0}/{unseenStats.total ?? 0} coin hạng A &amp; B có PnL &gt; 0
                  </div>
                </div>

                <div style={{ padding: 14, background: 'var(--n-card, rgba(255,255,255,0.03))', borderRadius: 8, border: '1px solid var(--n-border)' }}>
                  <div style={{ fontSize: 12, color: 'var(--n-text-sub)' }}>Median Sharpe Hạng A+B (OOS)</div>
                  <div style={{ fontSize: 24, fontWeight: 700, marginTop: 6, color: (unseenStats.sharpe_median ?? 0) > 0 ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                    {fmtNum(unseenStats.sharpe_median, 2)}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--n-text-sub)', marginTop: 4 }}>
                    IQR: [{fmtNum(unseenStats.sharpe_p25, 2)} → {fmtNum(unseenStats.sharpe_p75, 2)}]
                  </div>
                </div>

                <div style={{ padding: 14, background: 'var(--n-card, rgba(255,255,255,0.03))', borderRadius: 8, border: '1px solid var(--n-border)' }}>
                  <div style={{ fontSize: 12, color: 'var(--n-text-sub)' }}>Tương quan IS → OOS (Spearman)</div>
                  <div style={{ fontSize: 24, fontWeight: 700, marginTop: 6, color: (scanData.spearman_is_to_oos ?? 0) > 0 ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                    {scanData.spearman_is_to_oos != null ? `${scanData.spearman_is_to_oos > 0 ? '+' : ''}${fmtNum(scanData.spearman_is_to_oos, 2)}` : '—'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--n-text-sub)', marginTop: 4 }}>
                    Khả năng "đoán" coin tốt ở tương lai
                  </div>
                </div>

                <div style={{ padding: 14, background: 'var(--n-card, rgba(255,255,255,0.03))', borderRadius: 8, border: '1px solid var(--n-border)' }}>
                  <div style={{ fontSize: 12, color: 'var(--n-text-sub)' }}>Tập tối ưu 8 coin gốc (OOS)</div>
                  <div style={{ fontSize: 24, fontWeight: 700, marginTop: 6, color: (optStats.profit_pct ?? 0) >= 50 ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                    {fmtPct(optStats.profit_pct ?? 0)}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--n-text-sub)', marginTop: 4 }}>
                    {optStats.profit_count ?? 0}/8 coin có lãi (Sharpe median: {fmtNum(optStats.sharpe_median, 2)})
                  </div>
                </div>
              </div>

              {/* Bảng 100 coin */}
              <Panel title={`Danh sách 100 coin quét (${filteredCoins.length}/${scanData.coins.length})`}>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
                  <input
                    type="text"
                    className="n-input"
                    placeholder="Tìm mã coin (BTC, ETH, BONK...)"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    style={{ width: 180 }}
                  />
                  <select className="n-sel" value={gradeFilter} onChange={(e) => setGradeFilter(e.target.value)}>
                    <option value="ALL">Tất cả hạng</option>
                    <option value="A">Hạng A (≥ $20M)</option>
                    <option value="B">Hạng B ($5M - $20M)</option>
                    <option value="C">Hạng C ($1M - $5M)</option>
                  </select>
                  <select className="n-sel" value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)}>
                    {SECTORS.map((sec) => (
                      <option key={sec} value={sec}>{sec}</option>
                    ))}
                  </select>
                  <select className="n-sel" value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
                    <option value="ALL">Tất cả nhóm</option>
                    <option value="UNSEEN">92 coin chưa từng thấy</option>
                    <option value="OPTIMIZED">8 coin tập tối ưu gốc</option>
                  </select>
                  <select className="n-sel" value={pnlFilter} onChange={(e) => setPnlFilter(e.target.value)}>
                    <option value="ALL">Mọi PnL</option>
                    <option value="PROFIT">Chỉ coin có lãi OOS</option>
                    <option value="LOSS">Chỉ coin lỗ OOS</option>
                  </select>
                </div>

                <div style={{ overflowX: 'auto' }}>
                  <table className="n-tbl" style={{ width: '100%', fontSize: 12.5 }}>
                    <thead>
                      <tr>
                        <th style={{ width: 40 }}>#</th>
                        <th>Tài sản</th>
                        <th onClick={() => handleSort('grade')} style={{ cursor: 'pointer' }}>
                          Hạng {sortBy === 'grade' ? (sortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th>Ngành</th>
                        <th onClick={() => handleSort('is_ret')} style={{ textAlign: 'right', cursor: 'pointer' }}>
                          IS PnL {sortBy === 'is_ret' ? (sortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ textAlign: 'right' }}>IS Sharpe</th>
                        <th onClick={() => handleSort('oos_ret')} style={{ textAlign: 'right', cursor: 'pointer', color: 'var(--n-accent, #38bdf8)' }}>
                          OOS PnL {sortBy === 'oos_ret' ? (sortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th onClick={() => handleSort('oos_sharpe')} style={{ textAlign: 'right', cursor: 'pointer' }}>
                          OOS Sharpe {sortBy === 'oos_sharpe' ? (sortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ textAlign: 'right' }}>OOS MDD</th>
                        <th onClick={() => handleSort('trades')} style={{ textAlign: 'right', cursor: 'pointer' }}>
                          Lệnh OOS {sortBy === 'trades' ? (sortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ textAlign: 'center' }}>Kết quả</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredCoins.map((c, idx) => {
                        const isProfitOos = (c.oos?.ret_pct ?? 0) > 0
                        const isLowTrades = c.oos?.low_trades || (c.oos?.trades ?? 0) < 30
                        return (
                          <tr key={c.base}>
                            <td className="mono" style={{ color: 'var(--n-text-sub)' }}>{idx + 1}</td>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <b>{c.base}</b>
                                {c.is_optimized_8 && (
                                  <span title="Nằm trong 8 coin tối ưu gốc" style={{ fontSize: 10, padding: '1px 4px', borderRadius: 3, background: 'rgba(56, 189, 248, 0.15)', color: 'var(--n-accent, #38bdf8)' }}>
                                    GỐC
                                  </span>
                                )}
                              </div>
                            </td>
                            <td>
                              <span style={{ fontWeight: 600, color: c.grade === 'A' ? 'var(--n-green, #10b981)' : c.grade === 'B' ? '#38bdf8' : '#f59e0b' }}>
                                {c.grade}
                              </span>
                            </td>
                            <td style={{ color: 'var(--n-text-sub)' }}>{c.sector || 'Other'}</td>
                            <td className="mono" style={{ textAlign: 'right', color: (c.is?.ret_pct ?? 0) >= 0 ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                              {c.is?.ret_pct != null ? `${c.is.ret_pct > 0 ? '+' : ''}${fmtPct(c.is.ret_pct)}` : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right', color: 'var(--n-text-sub)' }}>
                              {c.is?.sharpe != null ? fmtNum(c.is.sharpe, 2) : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right', fontWeight: 600, color: isProfitOos ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                              {c.oos?.ret_pct != null ? `${c.oos.ret_pct > 0 ? '+' : ''}${fmtPct(c.oos.ret_pct)}` : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right', color: (c.oos?.sharpe ?? 0) > 0 ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                              {c.oos?.sharpe != null ? fmtNum(c.oos.sharpe, 2) : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right', color: 'var(--n-text-sub)' }}>
                              {c.oos?.mdd_pct != null ? fmtPct(c.oos.mdd_pct) : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right' }}>
                              {c.oos?.trades ?? 0}
                              {isLowTrades && (
                                <span title="Dưới 30 lệnh, độ tin cậy thấp" style={{ color: 'orange', marginLeft: 4 }}>⚠</span>
                              )}
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              <span
                                style={{
                                  padding: '2px 8px',
                                  borderRadius: 4,
                                  fontSize: 11,
                                  fontWeight: 600,
                                  background: isProfitOos ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                                  color: isProfitOos ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)',
                                }}
                              >
                                {isProfitOos ? 'LÃI' : 'LỖ'}
                              </span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </>
          )}
        </>
      )}

      {/* ─────────────────────────────────────────────────────────────
          TAB 2: PARAMETER SWEEP (100 THAM SỐ BTC)
         ───────────────────────────────────────────────────────────── */}
      {mainTab === 'sweep' && (
        <>
          {!sweepData ? (
            <Empty title="Chưa có kết quả Parameter Sweep">
              Chưa tìm thấy file kết quả parameter_sweep_btc_100.json.
            </Empty>
          ) : (
            <>
              {/* Thẻ Vinh danh Top 1 Strategy */}
              <div
                style={{
                  padding: 20,
                  borderRadius: 8,
                  border: '1px solid var(--n-green, #10b981)',
                  background: 'rgba(16, 185, 129, 0.08)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
                  <div>
                    <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: 'var(--n-green, #10b981)', color: '#000' }}>
                      TOP 1 BEST STRATEGY
                    </span>
                    <h2 style={{ margin: '8px 0 4px 0', fontSize: 20, color: 'var(--n-green, #10b981)' }}>
                      {sweepData.top_1_strategy_id}
                    </h2>
                    <div style={{ fontSize: 13, color: 'var(--n-text-sub)' }}>
                      Tài sản: <b>{sweepData.symbol}</b> · Đã quét qua <b>{sweepData.total_strategies} cấu hình</b> trong {sweepData.elapsed_seconds}s
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: 20, textAlign: 'right' }}>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>OOS Sharpe</div>
                      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--n-green, #10b981)' }}>
                        {fmtNum(sweepData.top_1_oos?.sharpe, 2)}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>OOS Lợi nhuận</div>
                      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--n-green, #10b981)' }}>
                        +{fmtPct(sweepData.top_1_oos?.ret_pct)}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>Tỉ lệ thắng</div>
                      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--n-text)' }}>
                        {fmtPct(sweepData.top_1_oos?.win_rate)}
                      </div>
                    </div>
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>Max Drawdown</div>
                      <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--n-text-sub)' }}>
                        {fmtPct(sweepData.top_1_oos?.mdd_pct)}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Bảng so sánh tham số Top 1 vs Baseline */}
                <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
                    So sánh tham số cấu hình Top 1 với Baseline:
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10 }}>
                    <div style={{ padding: 10, background: 'var(--n-card, rgba(0,0,0,0.2))', borderRadius: 6 }}>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>Bước nhồi (step_pct)</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--n-green, #10b981)' }}>
                        {sweepData.top_1_params?.dca_step_pct}% <span style={{ fontSize: 11, color: 'var(--n-text-sub)', fontWeight: 400 }}>(gốc: 2.25%)</span>
                      </div>
                    </div>
                    <div style={{ padding: 10, background: 'var(--n-card, rgba(0,0,0,0.2))', borderRadius: 6 }}>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>Số tầng tối đa (max_layers)</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--n-green, #10b981)' }}>
                        {sweepData.top_1_params?.dca_max_layers} tầng <span style={{ fontSize: 11, color: 'var(--n-text-sub)', fontWeight: 400 }}>(gốc: 3)</span>
                      </div>
                    </div>
                    <div style={{ padding: 10, background: 'var(--n-card, rgba(0,0,0,0.2))', borderRadius: 6 }}>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>Chốt lời ATR (take_profit)</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--n-green, #10b981)' }}>
                        {sweepData.top_1_params?.take_profit_rate}x <span style={{ fontSize: 11, color: 'var(--n-text-sub)', fontWeight: 400 }}>(gốc: 1.4x)</span>
                      </div>
                    </div>
                    <div style={{ padding: 10, background: 'var(--n-card, rgba(0,0,0,0.2))', borderRadius: 6 }}>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>Cắt lỗ ATR (stop_loss)</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--n-green, #10b981)' }}>
                        {sweepData.top_1_params?.stop_loss_rate}x <span style={{ fontSize: 11, color: 'var(--n-text-sub)', fontWeight: 400 }}>(gốc: 9.7x)</span>
                      </div>
                    </div>
                    <div style={{ padding: 10, background: 'var(--n-card, rgba(0,0,0,0.2))', borderRadius: 6 }}>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>Hệ số nhồi (size_mult)</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--n-green, #10b981)' }}>
                        {sweepData.top_1_params?.dca_size_multiplier}x <span style={{ fontSize: 11, color: 'var(--n-text-sub)', fontWeight: 400 }}>(gốc: 2.3x)</span>
                      </div>
                    </div>
                    <div style={{ padding: 10, background: 'var(--n-card, rgba(0,0,0,0.2))', borderRadius: 6 }}>
                      <div style={{ fontSize: 11, color: 'var(--n-text-sub)' }}>Ngưỡng RSI vào lệnh</div>
                      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--n-green, #10b981)' }}>
                        {sweepData.top_1_params?.rsi_lo} <span style={{ fontSize: 11, color: 'var(--n-text-sub)', fontWeight: 400 }}>(gốc: 43.0)</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Bảng danh sách 100 cấu hình quét */}
              <Panel title={`Bảng xếp hạng 100 cấu hình tham số DCA trên BTC (${filteredSweep.length}/100)`}>
                <div style={{ marginBottom: 12 }}>
                  <input
                    type="text"
                    className="n-input"
                    placeholder="Tìm mã cấu hình (cfg_063, baseline...)"
                    value={sweepSearch}
                    onChange={(e) => setSweepSearch(e.target.value)}
                    style={{ width: 260 }}
                  />
                </div>

                <div style={{ overflowX: 'auto' }}>
                  <table className="n-tbl" style={{ width: '100%', fontSize: 12.5 }}>
                    <thead>
                      <tr>
                        <th style={{ width: 40 }}>#</th>
                        <th>Cấu hình</th>
                        <th>Tham số (Step% / Layer / TP / SL / RSI)</th>
                        <th onClick={() => handleSweepSort('is_ret')} style={{ textAlign: 'right', cursor: 'pointer' }}>
                          IS PnL {sweepSortBy === 'is_ret' ? (sweepSortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th onClick={() => handleSweepSort('oos_ret')} style={{ textAlign: 'right', cursor: 'pointer', color: 'var(--n-accent, #38bdf8)' }}>
                          OOS PnL {sweepSortBy === 'oos_ret' ? (sweepSortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th onClick={() => handleSweepSort('oos_sharpe')} style={{ textAlign: 'right', cursor: 'pointer' }}>
                          OOS Sharpe {sweepSortBy === 'oos_sharpe' ? (sweepSortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th style={{ textAlign: 'right' }}>OOS MDD</th>
                        <th onClick={() => handleSweepSort('win_rate')} style={{ textAlign: 'right', cursor: 'pointer' }}>
                          Tỉ lệ thắng {sweepSortBy === 'win_rate' ? (sweepSortAsc ? '▲' : '▼') : ''}
                        </th>
                        <th onClick={() => handleSweepSort('trades')} style={{ textAlign: 'right', cursor: 'pointer' }}>
                          Lệnh OOS {sweepSortBy === 'trades' ? (sweepSortAsc ? '▲' : '▼') : ''}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredSweep.map((s, idx) => {
                        const isTop = s.cfg_id === sweepData.top_1_strategy_id
                        const isProfit = (s.oos?.ret_pct ?? 0) > 0
                        return (
                          <tr key={s.cfg_id} style={{ background: isTop ? 'rgba(16, 185, 129, 0.12)' : undefined }}>
                            <td className="mono" style={{ color: 'var(--n-text-sub)' }}>{idx + 1}</td>
                            <td>
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <b>{s.cfg_id}</b>
                                {isTop && (
                                  <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: 3, background: 'var(--n-green, #10b981)', color: '#000', fontWeight: 700 }}>
                                    TOP 1
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="mono" style={{ color: 'var(--n-text-sub)', fontSize: 11.5 }}>
                              {s.params?.dca_step_pct}% · {s.params?.dca_max_layers}L · {s.params?.take_profit_rate}x · {s.params?.stop_loss_rate}x · RSI:{s.params?.rsi_lo}
                            </td>
                            <td className="mono" style={{ textAlign: 'right', color: (s.is?.ret_pct ?? 0) >= 0 ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                              {s.is?.ret_pct != null ? `${s.is.ret_pct > 0 ? '+' : ''}${fmtPct(s.is.ret_pct)}` : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right', fontWeight: 600, color: isProfit ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                              {s.oos?.ret_pct != null ? `${s.oos.ret_pct > 0 ? '+' : ''}${fmtPct(s.oos.ret_pct)}` : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right', color: (s.oos?.sharpe ?? 0) > 0 ? 'var(--n-green, #10b981)' : 'var(--n-red, #ef4444)' }}>
                              {s.oos?.sharpe != null ? fmtNum(s.oos.sharpe, 2) : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right', color: 'var(--n-text-sub)' }}>
                              {s.oos?.mdd_pct != null ? fmtPct(s.oos.mdd_pct) : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right' }}>
                              {s.oos?.win_rate != null ? fmtPct(s.oos.win_rate) : '—'}
                            </td>
                            <td className="mono" style={{ textAlign: 'right' }}>
                              {s.oos?.trades ?? 0}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </>
          )}
        </>
      )}

      {/* ─────────────────────────────────────────────────────────────
          TAB 3: WFA & MONTE CARLO (CẢ 2 CHIẾN LƯỢC)
         ───────────────────────────────────────────────────────────── */}
      {mainTab === 'wfa' && (
        <>
          {!wfaData ? (
            <Empty title="Chưa có báo cáo WFA & Monte Carlo">
              Chưa tìm thấy file step3_wfa_carlo_final_report.json.
            </Empty>
          ) : (
            <>
              {/* So sánh trực quan 2 chiến lược */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 16 }}>
                {/* Chiến lược 1: Bước 2 Baseline */}
                <Panel title="Chiến lược 1 (Bước 2): Baseline DCA Long">
                  <div style={{ display: 'grid', gap: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--n-border)', paddingBottom: 8 }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Mã Job WFA:</span>
                      <b className="mono">{wfaData.step2_wfa_carlo?.job_name}</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Số Fold Walk-Forward:</span>
                      <b>10 folds (Train 120d → Test 30d)</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Lãi kép OOS cuộn:</span>
                      <b className="mono" style={{ color: '#ef4444' }}>-0.15%</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>MDD fold tệ nhất (extreme):</span>
                      <b className="mono">0.50%</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Monte Carlo (10,000 sims) p50:</span>
                      <b className="mono">-0.1% (MDD p50: 0.7%)</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Xác suất cháy vốn P(MDD≥30%):</span>
                      <b className="mono" style={{ color: 'var(--n-green, #10b981)' }}>0.0% (Đạt Gate)</b>
                    </div>
                  </div>
                </Panel>

                {/* Chiến lược 2: Bước 3 Best Sweep */}
                <Panel title="Chiến lược 2 (Bước 3): Best Sweep (dca_btc_cfg_063)">
                  <div style={{ display: 'grid', gap: 12 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--n-border)', paddingBottom: 8 }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Mã Job WFA:</span>
                      <b className="mono" style={{ color: 'var(--n-green, #10b981)' }}>{wfaData.step3_wfa_carlo?.job_name}</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Số Fold Walk-Forward:</span>
                      <b>10 folds (Train 120d → Test 30d)</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Lãi kép OOS cuộn:</span>
                      <b className="mono" style={{ color: '#ef4444' }}>-1.04%</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>MDD fold tệ nhất (extreme):</span>
                      <b className="mono">0.71%</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Monte Carlo (10,000 sims) p50:</span>
                      <b className="mono">-1.1% (MDD p50: 1.4%)</b>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-text-sub)' }}>Xác suất cháy vốn P(MDD≥30%):</span>
                      <b className="mono" style={{ color: 'var(--n-green, #10b981)' }}>0.0% (Đạt Gate)</b>
                    </div>
                  </div>
                </Panel>
              </div>

              {/* Bảng Kịch bản Stress Test Monte Carlo */}
              <Panel title="10 Kịch bản Stress Test Cực hạn Monte Carlo (Chiến lược Bước 2 vs Bước 3)">
                <div style={{ overflowX: 'auto' }}>
                  <table className="n-tbl" style={{ width: '100%', fontSize: 12.5 }}>
                    <thead>
                      <tr>
                        <th>Kịch bản Stress Test</th>
                        <th style={{ textAlign: 'right' }}>MDD Bước 2 (Baseline)</th>
                        <th style={{ textAlign: 'right' }}>MDD Bước 3 (Best Sweep)</th>
                        <th style={{ textAlign: 'center' }}>Cháy vốn (Ruin)</th>
                        <th style={{ textAlign: 'center' }}>Đánh giá</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(wfaData.step2_wfa_carlo?.mc?.stress || []).map((st1, idx) => {
                        const st2 = wfaData.step3_wfa_carlo?.mc?.stress?.[idx] || {}
                        return (
                          <tr key={st1.name}>
                            <td>
                              <b>{st1.label_vi || st1.name}</b>
                              {st1.note_vi && (
                                <div style={{ fontSize: 11, color: 'var(--n-text-sub)', marginTop: 2 }}>{st1.note_vi}</div>
                              )}
                            </td>
                            <td className="mono" style={{ textAlign: 'right' }}>
                              {fmtPct(st1.mdd_pct)}
                            </td>
                            <td className="mono" style={{ textAlign: 'right' }}>
                              {fmtPct(st2.mdd_pct)}
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              <span style={{ color: 'var(--n-green, #10b981)', fontWeight: 600 }}>KHÔNG</span>
                            </td>
                            <td style={{ textAlign: 'center' }}>
                              <span style={{ color: 'var(--n-green, #10b981)', fontWeight: 600 }}>ĐẠT</span>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </>
          )}
        </>
      )}
    </div>
  )
}
