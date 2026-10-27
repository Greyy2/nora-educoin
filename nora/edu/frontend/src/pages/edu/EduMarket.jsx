import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { eduMarketCached, getEduMarket, prefetchEduUser } from '../../api'
import UserPicker from '../../components/user/UserPicker'
import { useUser } from '../../meta/UserProvider'
import { Avatar, usd, pct, tone } from './eduUi'

const SORTS = [
  ['name', 'Tên tác giả (A-Z)'],
  ['pnl', 'Lợi nhuận (PnL cao nhất)'],
  ['sharpe', 'Chỉ số Sharpe tốt nhất'],
  ['new', 'Tác giả mới nhất'],
]

const TIMEFRAMES = [
  ['all', 'Mọi khung nến'],
  ['15m', '15m (Scalp)'],
  ['1h', '1h (Intraday)'],
  ['4h', '4h (Swing)'],
  ['1d', '1D (Daily)'],
]

const SYMBOLS = [
  ['all', 'Mọi cặp tài sản'],
  ['BTC-USDT', 'BTC-USDT'],
  ['ETH-USDT', 'ETH-USDT'],
  ['SOL-USDT', 'SOL-USDT'],
  ['BNB-USDT', 'BNB-USDT'],
]

const REGIMES = [
  ['all', 'Mọi chế độ thị trường (Regime)'],
  ['RANGE', '🌊 Đi ngang (Range)'],
  ['TREND_UP', '📈 Xu hướng tăng (Bull)'],
  ['TREND_DOWN', '📉 Xu hướng giảm (Bear)'],
  ['VOL_EXPANSION', '⚡ Biến động mạnh (Volatile)'],
  ['SURGE', '🚀 Bứt phá mạnh (Surge)'],
  ['CRASH', '💥 Sụt giảm sâu (Crash)'],
]

export default function EduMarket() {
  const { me } = useUser()
  const [rows, setRows] = useState(() => eduMarketCached('name')?.users || [])
  const [sort, setSort] = useState('name')
  const [rankedOnly, setRankedOnly] = useState(false)
  const [timeframe, setTimeframe] = useState('all')
  const [symbol, setSymbol] = useState('all')
  const [regime, setRegime] = useState('all')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 9 // Chuẩn hóa xem chính xác 9 card/trang (lưới 3x3)
  const [pagination, setPagination] = useState({ page: 1, page_size: 9, total: 0, total_pages: 1 })
  const [loading, setLoading] = useState(() => !eduMarketCached('name'))
  const [error, setError] = useState(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const reqSeq = React.useRef(0)

  const hasComparisonPartition = timeframe !== 'all' && symbol !== 'all' && !!startDate && !!endDate && startDate <= endDate

  const updatePartition = (kind, value) => {
    setPage(1)
    const nextTimeframe = kind === 'timeframe' ? value : timeframe
    const nextSymbol = kind === 'symbol' ? value : symbol
    const incomplete = nextTimeframe === 'all' || nextSymbol === 'all' || !startDate || !endDate || startDate > endDate
    if (incomplete) {
      if (sort === 'pnl' || sort === 'sharpe') setSort('name')
      if (rankedOnly) setRankedOnly(false)
      if (regime !== 'all') setRegime('all')
    }
    if (kind === 'timeframe') setTimeframe(value)
    else setSymbol(value)
  }

  const updateWindow = (kind, value) => {
    setPage(1)
    const nextStart = kind === 'startDate' ? value : startDate
    const nextEnd = kind === 'endDate' ? value : endDate
    if (!nextStart || !nextEnd || nextStart > nextEnd) {
      if (sort === 'pnl' || sort === 'sharpe') setSort('name')
      if (rankedOnly) setRankedOnly(false)
      if (regime !== 'all') setRegime('all')
    }
    if (kind === 'startDate') setStartDate(value)
    else setEndDate(value)
  }

  const resetFilters = () => {
    setTimeframe('all')
    setSymbol('all')
    setStartDate('')
    setEndDate('')
    setRegime('all')
    setRankedOnly(false)
    setSort('name')
    setQ('')
    setPage(1)
  }

  const load = async () => {
    const seq = ++reqSeq.current
    setLoading(true)
    setError(null)
    try {
      const res = await getEduMarket({ sort, rankedOnly, timeframe, symbol, startDate, endDate, regime, page, pageSize })
      if (seq !== reqSeq.current) return
      setRows(res?.users || [])
      if (res?.pagination) {
        setPagination(res.pagination)
      } else {
        const total = (res?.users || []).length
        setPagination({ page, page_size: pageSize, total, total_pages: Math.max(1, Math.ceil(total / pageSize)) })
      }
    } catch (e) {
      if (seq !== reqSeq.current) return
      setError(e.message || 'Không tải được danh sách tác giả')
    } finally {
      if (seq === reqSeq.current) setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [sort, rankedOnly, timeframe, symbol, startDate, endDate, regime, page]) // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(() => {
    let list = rows
    if (me?.handle || me?.id) {
      list = list.filter((u) => u.handle !== me.handle && u.id !== me.id)
    }
    const t = q.trim().toLowerCase()
    return t ? list.filter((u) => `${u.display_name} ${u.handle}`.toLowerCase().includes(t)) : list
  }, [rows, q, me])

  // Tạo mảng số trang hiển thị (cửa sổ trượt 5 trang)
  const pageNumbers = useMemo(() => {
    const totalP = pagination.total_pages || 1
    const cur = pagination.page || 1
    let start = Math.max(1, cur - 2)
    let end = Math.min(totalP, cur + 2)
    if (cur <= 2) end = Math.min(totalP, 5)
    if (cur >= totalP - 1) start = Math.max(1, totalP - 4)
    const pages = []
    for (let i = start; i <= end; i++) pages.push(i)
    return pages
  }, [pagination.total_pages, pagination.page])

  return (
    <div style={{ maxWidth: 1240, margin: '0 auto', padding: '32px 24px', fontFamily: 'inherit' }}>
      {/* ── HEADER KHÔNG GIAN THỊ TRƯỜNG ── */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 20, marginBottom: 28 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <h1 style={{ fontSize: 28, fontWeight: 700, margin: 0, letterSpacing: '-0.02em', color: 'var(--n-ink)' }}>
              Market — Thị Trường Chiến Lược
            </h1>
            <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 20, background: 'var(--n-accent-wash)', color: 'var(--n-accent)', border: '1px solid var(--n-accent)' }}>
              EDU MARKET
            </span>
          </div>
          <p style={{ margin: '8px 0 0', fontSize: 13.5, color: 'var(--n-ink-2)', lineHeight: 1.5 }}>
            Sàn giao dịch học thuật định lượng: Minh bạch thuật toán, đối soát mẫu độc lập ≥ 20 lệnh và kỳ kiểm định chuẩn hóa.
          </p>
        </div>

        {!me && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button type="button" className="n-btn sm" onClick={() => setPickerOpen(true)} style={{ fontSize: 13, borderRadius: 8 }}>
              👤 Đăng nhập
            </button>
          </div>
        )}
      </div>

      {/* ── THANH ĐIỀU KHIỂN & BỘ LỌC THÔNG MINH (GLASS PANEL) ── */}
      <div className="edu-glass-panel" style={{ marginBottom: 24 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, alignItems: 'center' }}>
          {/* Ô tìm kiếm */}
          <div style={{ position: 'relative' }}>
            <span style={{ position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', fontSize: 13, color: 'var(--n-ink-3)', pointerEvents: 'none' }}>🔍</span>
            <input
              className="n-input"
              placeholder="Tìm theo tên tác giả..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ paddingLeft: 32 }}
            />
          </div>

          {/* Lọc Khung thời gian */}
          <select className="n-input" value={timeframe} onChange={(e) => updatePartition('timeframe', e.target.value)} aria-label="Khung thời gian">
            {TIMEFRAMES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>

          {/* Lọc Cặp tài sản */}
          <select className="n-input" value={symbol} onChange={(e) => updatePartition('symbol', e.target.value)} aria-label="Cặp tài sản">
            {SYMBOLS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>

          {/* Khoảng ngày (Date Range) */}
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input className="n-input" type="date" value={startDate} onChange={(e) => updateWindow('startDate', e.target.value)} style={{ fontSize: 12, flex: 1 }} aria-label="Ngày bắt đầu" title="Ngày bắt đầu" />
            <span style={{ color: 'var(--n-ink-3)', fontSize: 12 }}>→</span>
            <input className="n-input" type="date" value={endDate} onChange={(e) => updateWindow('endDate', e.target.value)} style={{ fontSize: 12, flex: 1 }} aria-label="Ngày kết thúc" title="Ngày kết thúc" />
          </div>

          {/* Lọc Regime tham khảo */}
          <select className="n-input" value={regime} disabled={!hasComparisonPartition} onChange={(e) => { setPage(1); setRegime(e.target.value) }} style={{ opacity: !hasComparisonPartition ? 0.6 : 1 }} aria-label="Regime tham khảo">
            {REGIMES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>

          {/* Sắp xếp */}
          <select className="n-input" value={sort} onChange={(e) => { setPage(1); setSort(e.target.value) }} aria-label="Sắp xếp">
            {SORTS.map(([k, l]) => <option key={k} value={k} disabled={['pnl', 'sharpe'].includes(k) && !hasComparisonPartition}>{l}</option>)}
          </select>

          {/* Chỉ hiện có xếp hạng */}
          <div style={{ display: 'flex', alignItems: 'center', minHeight: 38, position: 'relative', zIndex: 1 }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: hasComparisonPartition ? 'pointer' : 'not-allowed', color: 'var(--n-ink-2)', opacity: !hasComparisonPartition ? 0.6 : 1, userSelect: 'none' }}>
              <input type="checkbox" disabled={!hasComparisonPartition} checked={rankedOnly} onChange={(e) => { setPage(1); setRankedOnly(e.target.checked) }} style={{ cursor: 'pointer', width: 16, height: 16 }} />
              <span>Chỉ hiện có xếp hạng</span>
            </label>
          </div>
        </div>

        {(timeframe !== 'all' || symbol !== 'all' || startDate || endDate || regime !== 'all' || q) && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--n-line-soft)' }}>
            <button
              type="button"
              className="n-btn xs ghost"
              onClick={resetFilters}
              style={{ fontSize: 11, color: 'var(--n-neg)', padding: '4px 10px', borderRadius: 6 }}
            >
              ✕ Xóa bộ lọc
            </button>
          </div>
        )}
      </div>

      {error && <div className="n-err" style={{ marginBottom: 20, borderRadius: 10 }}>{error}</div>}

      {/* ── LƯỚI CARD TÁC GIẢ & CHIẾN LƯỢC (9 CARD TRÊN TRANG - 3x3) ── */}
      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 20 }}>
          {[0, 1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
            <div
              key={i}
              style={{
                background: 'var(--n-surface)',
                border: '1px solid var(--n-line)',
                borderRadius: 16,
                height: 220,
                opacity: 0.5,
                animation: 'eduPulse 1.4s ease-in-out infinite',
              }}
            />
          ))}
          <style>{'@keyframes eduPulse{0%,100%{opacity:.3}50%{opacity:.6}}'}</style>
        </div>
      ) : shown.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 24px', background: 'var(--n-surface)', border: '1px dashed var(--n-line)', borderRadius: 16, color: 'var(--n-ink-2)' }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>🧭</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--n-ink)' }}>Không tìm thấy tác giả nào</div>
          <p style={{ fontSize: 13, maxWidth: 440, margin: '8px auto 16px', lineHeight: 1.5 }}>
            Thử thay đổi từ khóa tìm kiếm hoặc bấm nút đặt lại bộ lọc để xem toàn bộ danh sách tác giả cộng đồng.
          </p>
          <button type="button" className="n-btn sm" onClick={resetFilters} style={{ borderRadius: 8 }}>
            Đặt lại bộ lọc
          </button>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 20 }}>
          {shown.map((u) => {
            const isRanked = u.ranked_strategies > 0
            const best = u.best
            return (
              <Link
                key={u.handle}
                to={`/u/${encodeURIComponent(u.handle)}`}
                onMouseEnter={() => prefetchEduUser(u.handle)}
                className="edu-market-card"
              >
                {/* Viền highlight trên đỉnh */}
                <div style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  height: 3,
                  background: isRanked ? 'var(--n-pos)' : 'var(--n-warn)',
                }} />

                {/* 1. Thông tin tác giả + Huy hiệu đạt chuẩn */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
                    <div style={{ position: 'relative' }}>
                      <Avatar avatar={u.avatar} size={44} />
                      {isRanked && (
                        <span style={{
                          position: 'absolute',
                          bottom: -2,
                          right: -2,
                          width: 14,
                          height: 14,
                          borderRadius: '50%',
                          background: 'var(--n-pos)',
                          border: '2px solid var(--n-surface)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 8,
                          color: '#fff',
                          fontWeight: 700,
                        }}>
                          ✓
                        </span>
                      )}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: 15.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--n-ink)' }}>
                        {u.display_name}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--n-ink-2)', marginTop: 1 }}>
                        @{u.handle}
                      </div>
                    </div>
                  </div>

                  <span
                    title={isRanked ? `${u.ranked_strategies} chiến lược vượt checklist kiểm định (N ≥ 20 và ≥ 30 ngày / 500 nến)` : (u.primary_unranked_reason || best?.unranked_reason || 'Đang chờ backtest thêm lệnh')}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: '4px 10px',
                      borderRadius: 14,
                      whiteSpace: 'nowrap',
                      background: isRanked ? 'var(--n-pos-wash)' : 'var(--n-surface-2)',
                      color: isRanked ? 'var(--n-pos)' : 'var(--n-warn)',
                      border: isRanked ? '1px solid var(--n-pos)' : '1px solid var(--n-line)',
                    }}
                  >
                    {isRanked ? `✓ ${u.ranked_strategies} Đạt chuẩn` : '⏳ Mẫu nhỏ'}
                  </span>
                </div>

                {/* 2. Ba ô chỉ số thống kê định lượng */}
                <div className="edu-metric-grid">
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: 'var(--n-ink-2)', marginBottom: 2 }}>Chiến lược</div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--n-ink)' }}>{u.n_strategies}</div>
                  </div>
                  <div style={{ textAlign: 'center', borderLeft: '1px solid var(--n-line)', borderRight: '1px solid var(--n-line)' }}>
                    <div style={{ fontSize: 11, color: 'var(--n-ink-2)', marginBottom: 2 }}>Tổng PnL</div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: tone(u.total_pnl_usd), whiteSpace: 'nowrap' }}>
                      {usd(u.total_pnl_usd)}
                    </div>
                  </div>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: 'var(--n-ink-2)', marginBottom: 2 }}>Max DD</div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: u.max_mdd_pct != null ? 'var(--n-neg)' : 'inherit' }}>
                      {pct(u.max_mdd_pct)}
                    </div>
                  </div>
                </div>

                {/* 3. Khối thuật toán tốt nhất (Best Alpha) */}
                <div style={{
                  borderTop: '1px solid var(--n-line-soft)',
                  paddingTop: 12,
                  minHeight: 52,
                  display: 'flex',
                  flexDirection: 'column',
                  justifyContent: 'center',
                }}>
                  {best ? (
                    <>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 4 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--n-ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          ⚡ {best.name}
                        </div>
                        {best.sharpe != null && (
                          <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: '9999px', background: 'var(--n-accent-wash)', color: 'var(--n-accent)', border: '1px solid var(--n-accent)' }}>
                            Sharpe {best.sharpe.toFixed(2)}
                          </span>
                        )}
                      </div>

                      {best.market_context?.status === 'available' ? (
                        <div style={{ fontSize: 11, color: 'var(--n-ink-2)', display: 'flex', alignItems: 'center', gap: 5 }}>
                          <span>Regime tham khảo: {best.market_context.dominant === 'RANGE' ? 'Đi ngang' : (REGIMES.find(([key]) => key === best.market_context.dominant)?.[1] || best.market_context.dominant)}</span>
                        </div>
                      ) : (
                        <div style={{ fontSize: 11, color: 'var(--n-ink-3)' }}>
                          Chưa có thông số regime cửa sổ
                        </div>
                      )}
                    </>
                  ) : (
                    <div style={{ fontSize: 12, color: 'var(--n-ink-3)' }}>Chưa lưu chiến lược</div>
                  )}
                </div>

                {/* 4. Link xem chi tiết */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: 12,
                  color: 'var(--n-accent)',
                  fontWeight: 600,
                  marginTop: 'auto',
                }}>
                  <span>Xem hồ sơ & chiến lược</span>
                  <span>→</span>
                </div>
              </Link>
            )
          })}
        </div>
      )}

      {/* ── THANH PHÂN TRANG CHUẨN HOÁ (XEM 9 CARD 1 TRANG) ── */}
      {pagination.total > 0 && (
        <div className="edu-glass-panel" style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginTop: 32,
          padding: '16px 20px',
          flexWrap: 'wrap',
          gap: 16,
        }}>
          <div style={{ fontSize: 13, color: 'var(--n-ink-2)' }}>
            Đang xem <b style={{ color: 'var(--n-ink)' }}>{shown.length}</b> / <b style={{ color: 'var(--n-ink)' }}>{pagination.total}</b> tác giả · Trang <b style={{ color: 'var(--n-accent)' }}>{pagination.page}</b> / {pagination.total_pages || 1} (9 thẻ/trang)
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
            <button
              type="button"
              className="n-btn sm"
              disabled={page <= 1 || loading}
              onClick={() => setPage(1)}
              title="Về trang đầu (Trang 1)"
              style={{ fontSize: 12, borderRadius: 8, padding: '6px 12px' }}
            >
              « Trang đầu
            </button>

            <button
              type="button"
              className="n-btn sm"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              title="Trang trước"
              style={{ fontSize: 12, borderRadius: 8, padding: '6px 12px' }}
            >
              ← Trang trước
            </button>

            {pageNumbers.map((p) => (
              <button
                key={p}
                type="button"
                className={`n-btn sm ${p === page ? 'primary' : ''}`}
                disabled={loading}
                onClick={() => setPage(p)}
                style={{
                  fontSize: 12,
                  width: 34,
                  height: 34,
                  minWidth: 34,
                  padding: 0,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  textAlign: 'center',
                  lineHeight: 1,
                  borderRadius: 8,
                  fontWeight: p === page ? 700 : 500,
                  background: p === page ? 'var(--n-accent)' : 'var(--n-surface-2)',
                  border: p === page ? '1px solid var(--n-accent)' : '1px solid var(--n-line)',
                  color: p === page ? 'var(--n-accent-ink)' : 'var(--n-ink)',
                  cursor: 'pointer',
                }}
              >
                {p}
              </button>
            ))}

            <button
              type="button"
              className="n-btn sm"
              disabled={page >= (pagination.total_pages || 1) || loading}
              onClick={() => setPage((p) => Math.min(pagination.total_pages || 1, p + 1))}
              title="Trang sau"
              style={{ fontSize: 12, borderRadius: 8, padding: '6px 12px' }}
            >
              Trang sau →
            </button>

            <button
              type="button"
              className="n-btn sm"
              disabled={page >= (pagination.total_pages || 1) || loading}
              onClick={() => setPage(pagination.total_pages || 1)}
              title={`Tới trang cuối (Trang ${pagination.total_pages || 1})`}
              style={{ fontSize: 12, borderRadius: 8, padding: '6px 12px' }}
            >
              Trang cuối »
            </button>
          </div>
        </div>
      )}

      <UserPicker open={pickerOpen} onClose={() => { setPickerOpen(false); load() }} />
    </div>
  )
}
