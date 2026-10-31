import React, { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { eduMarketCached, getEduMarket, prefetchEduUser } from '../../api'
import { fmtNum, isNum } from '../../lib/format'
import UserPicker from '../../components/user/UserPicker'
import { useUser } from '../../meta/UserProvider'
import { Avatar, usd, pct, spct, tone } from './eduUi'

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
  ['RANGE', 'Đi ngang (Range)'],
  ['TREND_UP', 'Xu hướng tăng (Bull)'],
  ['TREND_DOWN', 'Xu hướng giảm (Bear)'],
  ['VOL_EXPANSION', 'Biến động mạnh (Volatile)'],
  ['SURGE', 'Bứt phá mạnh (Surge)'],
  ['CRASH', 'Sụt giảm sâu (Crash)'],
]

const SPOTLIGHT_TABS = [
  { id: 'pnl', label: 'Lợi nhuận PnL', desc: 'Top tác giả có lợi nhuận chiến lược cao nhất' },
  { id: 'mdd', label: 'An toàn (MDD thấp)', desc: 'Top tác giả có mức sụt giảm vốn thấp nhất' },
  { id: 'sharpe', label: 'Tối ưu Sharpe', desc: 'Top tác giả có tỷ lệ Sharpe cao nhất' },
  { id: 'win_rate', label: 'Tỷ lệ thắng (Win)', desc: 'Top tác giả có tỷ lệ lệnh thắng cao nhất' },
]

const MEDALS = [
  {
    rank: 1,
    rankText: '1st',
    badge: '1st Quán Quân',
    color: '#F59E0B',
    wash: 'rgba(245, 158, 11, 0.22)',
    border: '#FCD34D',
    glow: 'rgba(245, 158, 11, 0.45)',
    topFace: 'linear-gradient(135deg, #FEF08A 0%, #FDE047 40%, #F59E0B 100%)',
    frontFace: 'linear-gradient(180deg, #FBBF24 0%, #F59E0B 45%, #D97706 100%)',
    frontBorder: '#FEF08A',
    frontShadow: '0 18px 36px -4px rgba(217, 119, 6, 0.45), inset 0 2px 4px rgba(255, 255, 255, 0.6), inset 0 -4px 8px rgba(180, 83, 9, 0.4)',
    numColor: '#FFFFFF',
    numShadow: '0 4px 10px rgba(120, 53, 15, 0.65)',
    pillBg: 'rgba(120, 53, 15, 0.35)',
    pillColor: '#FEF08A',
    pillBorder: 'rgba(254, 240, 138, 0.4)',
    subTitle: 'Quán Quân',
  },
  {
    rank: 2,
    rankText: '2nd',
    badge: '2nd Á Quân 1',
    color: '#64748B',
    wash: 'rgba(100, 116, 139, 0.22)',
    border: '#CBD5E1',
    glow: 'rgba(100, 116, 139, 0.35)',
    topFace: 'linear-gradient(135deg, #FFFFFF 0%, #E2E8F0 45%, #CBD5E1 100%)',
    frontFace: 'linear-gradient(180deg, #CBD5E1 0%, #94A3B8 45%, #64748B 100%)',
    frontBorder: '#F1F5F9',
    frontShadow: '0 16px 30px -4px rgba(100, 116, 139, 0.4), inset 0 2px 4px rgba(255, 255, 255, 0.7), inset 0 -4px 8px rgba(51, 65, 85, 0.4)',
    numColor: '#FFFFFF',
    numShadow: '0 4px 10px rgba(15, 23, 42, 0.55)',
    pillBg: 'rgba(15, 23, 42, 0.35)',
    pillColor: '#F1F5F9',
    pillBorder: 'rgba(241, 245, 249, 0.4)',
    subTitle: 'Á Quân 1',
  },
  {
    rank: 3,
    rankText: '3rd',
    badge: '3rd Á Quân 2',
    color: '#EA580C',
    wash: 'rgba(234, 88, 12, 0.22)',
    border: '#FB923C',
    glow: 'rgba(234, 88, 12, 0.35)',
    topFace: 'linear-gradient(135deg, #FFEDD5 0%, #FDBA74 45%, #FB923C 100%)',
    frontFace: 'linear-gradient(180deg, #FB923C 0%, #EA580C 45%, #C2410C 100%)',
    frontBorder: '#FFEDD5',
    frontShadow: '0 16px 28px -4px rgba(194, 65, 12, 0.4), inset 0 2px 4px rgba(255, 255, 255, 0.6), inset 0 -4px 8px rgba(124, 45, 18, 0.4)',
    numColor: '#FFFFFF',
    numShadow: '0 4px 10px rgba(67, 20, 7, 0.65)',
    pillBg: 'rgba(67, 20, 7, 0.35)',
    pillColor: '#FFEDD5',
    pillBorder: 'rgba(255, 237, 213, 0.4)',
    subTitle: 'Á Quân 2',
  },
]

export default function EduMarket() {
  const nav = useNavigate()
  const { me } = useUser()
  const [rows, setRows] = useState(() => eduMarketCached('name')?.users || [])
  const [sort, setSort] = useState('name')
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
  const [spotlightTab, setSpotlightTab] = useState('pnl')
  const [spotlightData, setSpotlightData] = useState(() => eduMarketCached('name')?.spotlight || null)
  const [hoveredTopIdx, setHoveredTopIdx] = useState(null)
  const reqSeq = React.useRef(0)

  const hasComparisonPartition = timeframe !== 'all' && symbol !== 'all' && !!startDate && !!endDate && startDate <= endDate

  const updatePartition = (kind, value) => {
    setPage(1)
    const nextTimeframe = kind === 'timeframe' ? value : timeframe
    const nextSymbol = kind === 'symbol' ? value : symbol
    const incomplete = nextTimeframe === 'all' || nextSymbol === 'all' || !startDate || !endDate || startDate > endDate
    if (incomplete) {
      if (sort === 'pnl' || sort === 'sharpe') setSort('name')
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
    setSort('name')
    setQ('')
    setPage(1)
  }

  const load = async () => {
    const seq = ++reqSeq.current
    setLoading(true)
    setError(null)
    try {
      const res = await getEduMarket({ sort, timeframe, symbol, startDate, endDate, regime, page, pageSize })
      if (seq !== reqSeq.current) return
      setRows(res?.users || [])
      if (res?.spotlight) {
        setSpotlightData(res.spotlight)
      }
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
  }, [sort, timeframe, symbol, startDate, endDate, regime, page]) // eslint-disable-line react-hooks/exhaustive-deps

  // Tính toán Top 3 xuất sắc nhất theo danh mục đang chọn (ưu tiên dữ liệu toàn sàn từ server)
  const top3Spotlight = useMemo(() => {
    if (spotlightData && Array.isArray(spotlightData[spotlightTab]) && spotlightData[spotlightTab].length > 0) {
      return spotlightData[spotlightTab]
    }
    const valid = rows.filter((u) => (u.n_strategies || 0) > 0 && u.best)
    if (!valid.length) return []

    let sorted = []
    if (spotlightTab === 'pnl') {
      sorted = [...valid]
        .filter((u) => isNum(u.best?.ret_pct))
        .sort((a, b) => {
          const diff = (b.best?.ret_pct || 0) - (a.best?.ret_pct || 0)
          if (Math.abs(diff) > 1e-6) return diff
          const mddDiff = (a.best?.mdd_pct ?? 999) - (b.best?.mdd_pct ?? 999)
          if (Math.abs(mddDiff) > 1e-6) return mddDiff
          const sharpeDiff = (b.best?.sharpe || 0) - (a.best?.sharpe || 0)
          if (Math.abs(sharpeDiff) > 1e-6) return sharpeDiff
          return (b.best?.trades || 0) - (a.best?.trades || 0)
        })
    } else if (spotlightTab === 'mdd') {
      sorted = [...valid]
        .filter((u) => isNum(u.best?.mdd_pct) && (u.best?.trades || 0) > 0)
        .sort((a, b) => {
          const diff = (a.best?.mdd_pct ?? 999) - (b.best?.mdd_pct ?? 999)
          if (Math.abs(diff) > 1e-6) return diff
          const pnlDiff = (b.best?.ret_pct || 0) - (a.best?.ret_pct || 0)
          if (Math.abs(pnlDiff) > 1e-6) return pnlDiff
          const sharpeDiff = (b.best?.sharpe || 0) - (a.best?.sharpe || 0)
          if (Math.abs(sharpeDiff) > 1e-6) return sharpeDiff
          return (b.best?.trades || 0) - (a.best?.trades || 0)
        })
    } else if (spotlightTab === 'sharpe') {
      sorted = [...valid]
        .filter((u) => isNum(u.best?.sharpe))
        .sort((a, b) => {
          const diff = (b.best?.sharpe || 0) - (a.best?.sharpe || 0)
          if (Math.abs(diff) > 1e-6) return diff
          const pnlDiff = (b.best?.ret_pct || 0) - (a.best?.ret_pct || 0)
          if (Math.abs(pnlDiff) > 1e-6) return pnlDiff
          return (a.best?.mdd_pct ?? 999) - (b.best?.mdd_pct ?? 999)
        })
    } else if (spotlightTab === 'win_rate') {
      sorted = [...valid]
        .filter((u) => isNum(u.best?.win_rate) && (u.best?.trades || 0) > 0)
        .sort((a, b) => {
          const diff = (b.best?.win_rate || 0) - (a.best?.win_rate || 0)
          if (Math.abs(diff) > 1e-6) return diff
          const tradeDiff = (b.best?.trades || 0) - (a.best?.trades || 0)
          if (tradeDiff !== 0) return tradeDiff
          return (b.best?.ret_pct || 0) - (a.best?.ret_pct || 0)
        })
    }
    return sorted.slice(0, 3)
  }, [rows, spotlightTab, spotlightData])

  const shown = useMemo(() => {
    let list = rows.filter((u) => (u.n_strategies || 0) > 0 && u.best)
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
              Đăng nhập
            </button>
          </div>
        )}
      </div>

      {/* ── BẢNG VINH DANH TOP 3 TÁC GIẢ NỔI BẬT (3D PODIUM ARENA) ── */}
      <div style={{
        background: 'radial-gradient(circle at 50% 18%, var(--n-accent-wash) 0%, rgba(245, 158, 11, 0.05) 35%, transparent 70%), var(--n-surface)',
        border: '1px solid var(--n-line)',
        borderRadius: 18,
        padding: '14px 18px 14px',
        marginBottom: 16,
        boxShadow: 'var(--n-shadow)',
        backdropFilter: 'blur(20px)',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* ÁNH SÁNG SÂN KHẤU (BACKGROUND AURA & RAYS) */}
        <div style={{
          position: 'absolute',
          top: '30%',
          left: '50%',
          transform: 'translate(-50%, -30%)',
          width: 360,
          height: 200,
          background: 'radial-gradient(ellipse, rgba(245, 158, 11, 0.12) 0%, var(--n-accent-wash) 42%, transparent 72%)',
          filter: 'blur(28px)',
          pointerEvents: 'none',
          zIndex: 0,
        }} />

        {/* VÒNG TRÒN HÀO QUANG ĐỒNG TÂM (CHAMPION ARCH RINGS) */}
        <div style={{
          position: 'absolute',
          top: '48%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 300,
          height: 300,
          borderRadius: '50%',
          border: '1px solid var(--n-line)',
          pointerEvents: 'none',
          zIndex: 0,
        }} />
        <div style={{
          position: 'absolute',
          top: '48%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: 190,
          height: 190,
          borderRadius: '50%',
          border: '1px solid var(--n-line-soft)',
          pointerEvents: 'none',
          zIndex: 0,
        }} />

        {/* DẢI SÁNG SÀN BỤC VINH DANH (STAGE FLOOR BEAM) */}
        <div style={{
          position: 'absolute',
          bottom: 10,
          left: '10%',
          right: '10%',
          height: 2,
          borderRadius: 2,
          background: 'linear-gradient(90deg, transparent 0%, var(--n-line) 20%, var(--n-accent) 50%, var(--n-line) 80%, transparent 100%)',
          filter: 'blur(0.5px)',
          zIndex: 1,
        }} />

        {/* Header của Spotlight: Tiêu đề + Tabs chuyển đổi */}
        <div style={{ position: 'relative', zIndex: 2, display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 12, borderBottom: '1px solid var(--n-line)', paddingBottom: 10 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <h2 style={{ fontSize: 14.5, fontWeight: 700, margin: 0, color: 'var(--n-ink)', letterSpacing: '-0.01em' }}>
                Top 3 Chiến Lược Xuất Sắc Nhất
              </h2>
              <span style={{ fontSize: 9.5, fontWeight: 700, padding: '1.5px 6px', borderRadius: 10, background: 'var(--n-pos-wash)', color: 'var(--n-pos)', border: '1px solid var(--n-pos)' }}>
                LIVE
              </span>
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)', marginTop: 1 }}>
              {SPOTLIGHT_TABS.find((t) => t.id === spotlightTab)?.desc || 'Tự động xếp hạng tác giả tốt nhất'}
            </div>
          </div>

          {/* Danh sách tab chuyển đổi */}
          <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', background: 'var(--n-surface-2)', padding: 2.5, borderRadius: 8, border: '1px solid var(--n-line)' }}>
            {SPOTLIGHT_TABS.map((tab) => {
              const active = spotlightTab === tab.id
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setSpotlightTab(tab.id)}
                  style={{
                    padding: '4px 10px',
                    fontSize: 11.5,
                    fontWeight: active ? 700 : 500,
                    borderRadius: 6,
                    border: 'none',
                    background: active ? 'var(--n-accent)' : 'transparent',
                    color: active ? 'var(--n-accent-ink)' : 'var(--n-ink-2)',
                    boxShadow: active ? '0 2px 6px rgba(99, 102, 241, 0.35)' : 'none',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                    display: 'inline-flex',
                    alignItems: 'center',
                  }}
                >
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* ── BỤC VINH DANH 3D PODIUM (RANK 2 - RANK 1 - RANK 3) ── */}
        {top3Spotlight.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--n-ink-3)', fontSize: 12.5, position: 'relative', zIndex: 2 }}>
            Chưa có dữ liệu tác giả nào thỏa mãn tiêu chí này.
          </div>
        ) : (
          <div style={{
            position: 'relative',
            zIndex: 2,
            paddingTop: 8,
            paddingBottom: 2,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'flex-end',
          }}>
            {/* Lưới bục vinh danh 3 cột: [Hạng 2 - Hạng 1 - Hạng 3] */}
            <div style={{
              display: 'flex',
              alignItems: 'flex-end',
              justifyContent: 'center',
              gap: 12,
              width: '100%',
              maxWidth: 540,
            }}>
              {[
                { rank: 2, u: top3Spotlight[1], medal: MEDALS[1], pedestalH: 64, avatarSz: 38 },
                { rank: 1, u: top3Spotlight[0], medal: MEDALS[0], pedestalH: 92, avatarSz: 48, isTop1: true },
                { rank: 3, u: top3Spotlight[2], medal: MEDALS[2], pedestalH: 48, avatarSz: 34 },
              ].map(({ rank, u, medal, pedestalH, avatarSz, isTop1 }) => {
                if (!u) {
                  return (
                    <div key={`empty-${rank}`} style={{ flex: 1, minWidth: 110, maxWidth: 165, opacity: 0.35, textAlign: 'center' }}>
                      <div style={{ width: '100%', height: pedestalH, background: 'var(--n-surface-2)', borderRadius: 8, border: '1px dashed var(--n-line)' }} />
                    </div>
                  )
                }

                const best = u.best || {}
                const isHovered = hoveredTopIdx === rank

                // Chỉ số hiển thị chính theo tab
                let metricVal = '—'
                let metricLabel = 'Lợi nhuận'
                let subVal = '—'
                let metricColor = 'inherit'

                if (spotlightTab === 'pnl') {
                  metricVal = spct(best.ret_pct)
                  metricColor = tone(best.ret_pct)
                  metricLabel = 'PnL Lợi nhuận'
                  subVal = usd(best.pnl_usd)
                } else if (spotlightTab === 'mdd') {
                  metricVal = pct(best.mdd_pct)
                  metricColor = 'var(--n-pos)'
                  metricLabel = 'Max Drawdown'
                  subVal = `${best.trades || 0} lệnh`
                } else if (spotlightTab === 'sharpe') {
                  metricVal = isNum(best.sharpe) ? fmtNum(best.sharpe, 2) : '—'
                  metricColor = 'var(--n-accent)'
                  metricLabel = 'Sharpe Ratio'
                  subVal = spct(best.ret_pct)
                } else if (spotlightTab === 'win_rate') {
                  metricVal = pct(best.win_rate, 1)
                  metricColor = 'var(--n-pos)'
                  metricLabel = 'Win Rate'
                  subVal = `${best.trades || 0} lệnh`
                }

                return (
                  <div
                    key={u.id || u.handle}
                    onMouseEnter={() => setHoveredTopIdx(rank)}
                    onMouseLeave={() => setHoveredTopIdx(null)}
                    onClick={() => nav(best.id ? `/s/${encodeURIComponent(best.id)}` : `/u/${encodeURIComponent(u.handle)}`)}
                    style={{
                      flex: 1,
                      minWidth: 110,
                      maxWidth: 165,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      cursor: 'pointer',
                      position: 'relative',
                      zIndex: isHovered ? 25 : isTop1 ? 5 : 2,
                      transform: isHovered ? 'translateY(-6px)' : 'none',
                      transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                    }}
                  >
                    {/* CROWN CHO TOP 1 / BADGE CHO TOP 2 & 3 */}
                    {isTop1 ? (
                      <div style={{
                        lineHeight: 1,
                        marginBottom: 3,
                        animation: 'bounce 2s infinite ease-in-out',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}>
                        <svg width="24" height="18" viewBox="0 0 24 24" fill="url(#goldCrownGrad)" stroke="#B45309" strokeWidth="1" style={{ filter: 'drop-shadow(0 3px 6px rgba(245, 158, 11, 0.75))' }}>
                          <defs>
                            <linearGradient id="goldCrownGrad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="#FEF08A" />
                              <stop offset="50%" stopColor="#F59E0B" />
                              <stop offset="100%" stopColor="#B45309" />
                            </linearGradient>
                          </defs>
                          <path d="M2 20h20v2H2v-2zm1.2-5.5L5 6l4.5 4.5L12 3l2.5 7.5L19 6l1.8 8.5H3.2z" />
                          <circle cx="5" cy="5" r="1.5" fill="#FEF08A" />
                          <circle cx="12" cy="2" r="1.5" fill="#FEF08A" />
                          <circle cx="19" cy="5" r="1.5" fill="#FEF08A" />
                        </svg>
                      </div>
                    ) : (
                      <div style={{
                        fontSize: 9.5,
                        fontWeight: 700,
                        color: medal.color,
                        marginBottom: 4,
                        display: 'inline-flex',
                        alignItems: 'center',
                        background: 'var(--n-surface-2)',
                        padding: '1px 6px',
                        borderRadius: 8,
                        border: `1px solid ${medal.border}`,
                      }}>
                        <span>Top {rank}</span>
                      </div>
                    )}

                    {/* VÒNG TRÒN AVATAR + BADGE HUY CHƯƠNG */}
                    <div style={{
                      position: 'relative',
                      marginBottom: 5,
                    }}>
                      <div style={{
                        padding: isTop1 ? 3 : 2.5,
                        borderRadius: '50%',
                        background: `linear-gradient(135deg, ${medal.color}, transparent 85%)`,
                        boxShadow: isHovered
                          ? `0 0 20px 3px ${medal.glow}`
                          : isTop1
                            ? `0 0 14px 2px ${medal.glow}`
                            : `0 0 8px ${medal.glow}`,
                        transition: 'all 0.25s ease',
                        display: 'inline-flex',
                      }}>
                        <Avatar avatar={u.avatar} size={avatarSz} />
                      </div>

                      {/* Huy chương góc avatar kiểu ruy băng thể thao */}
                      <div style={{
                        position: 'absolute',
                        bottom: -2,
                        right: -2,
                        width: isTop1 ? 18 : 15,
                        height: isTop1 ? 18 : 15,
                        borderRadius: '50%',
                        background: medal.color,
                        color: rank === 1 ? '#78350F' : rank === 2 ? '#0F172A' : '#451A03',
                        fontSize: isTop1 ? 10 : 8.5,
                        fontWeight: 900,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        border: '1.5px solid var(--n-surface)',
                        boxShadow: '0 2px 4px rgba(0,0,0,0.4)',
                      }}>
                        {rank}
                      </div>
                    </div>

                    {/* TÊN TÁC GIẢ & HANDLE */}
                    <div style={{ textAlign: 'center', width: '100%', padding: '0 4px', marginBottom: 4 }}>
                      <div style={{
                        fontSize: isTop1 ? 12.5 : 11.5,
                        fontWeight: 700,
                        color: 'var(--n-ink)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}>
                        {u.display_name}
                      </div>
                      <div style={{
                        fontSize: 10,
                        color: 'var(--n-ink-3)',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        marginTop: 1,
                      }}>
                        @{u.handle}
                      </div>
                    </div>

                    {/* RUY BĂNG ĐIỂM SỐ CHÍNH (SCORE RIBBON) */}
                    <div style={{
                      width: '88%',
                      padding: isTop1 ? '4px 8px' : '3px 6px',
                      borderRadius: 10,
                      background: 'var(--n-surface)',
                      border: `1px solid ${medal.border}`,
                      boxShadow: `0 3px 10px ${medal.glow}`,
                      textAlign: 'center',
                      marginBottom: 6,
                      transition: 'all 0.2s ease',
                      backdropFilter: 'blur(8px)',
                    }}>
                      <div style={{
                        fontSize: isTop1 ? 13.5 : 12,
                        fontWeight: 800,
                        color: metricColor,
                        lineHeight: 1.2,
                        letterSpacing: '-0.02em',
                      }}>
                        {metricVal}
                      </div>
                      <div style={{
                        fontSize: 8,
                        color: 'var(--n-ink-2)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.04em',
                        fontWeight: 600,
                        marginTop: 1.5,
                      }}>
                        {metricLabel}
                      </div>
                    </div>

                    {/* ── BỤC KHỐI 3D (PEDESTAL BLOCK) CÓ MÀU SẮC RIÊNG BIỆT ── */}
                    {/* Mặt trên (3D Top Bevel) */}
                    <div style={{
                      width: '100%',
                      height: isTop1 ? 14 : 11,
                      background: medal.topFace,
                      borderRadius: '8px 8px 0 0',
                      transform: 'perspective(160px) rotateX(28deg)',
                      transformOrigin: 'bottom',
                      border: `1px solid ${medal.border}`,
                      borderBottom: 'none',
                      boxShadow: `inset 0 1px 2px rgba(255,255,255,0.7), 0 -2px 8px ${medal.glow}`,
                      position: 'relative',
                      zIndex: 2,
                    }} />

                    {/* Thân bục đứng (Front Face) */}
                    <div style={{
                      width: '100%',
                      height: pedestalH,
                      background: medal.frontFace,
                      border: `1px solid ${medal.frontBorder}`,
                      borderTop: 'none',
                      borderRadius: '0 0 10px 10px',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      position: 'relative',
                      boxShadow: medal.frontShadow,
                      overflow: 'hidden',
                      zIndex: 1,
                    }}>
                      {/* Quầng sáng bóng bề mặt bục */}
                      <div style={{
                        position: 'absolute',
                        top: 0,
                        left: '50%',
                        transform: 'translateX(-50%)',
                        width: '90%',
                        height: '42%',
                        background: 'linear-gradient(180deg, rgba(255, 255, 255, 0.32) 0%, transparent 100%)',
                        pointerEvents: 'none',
                      }} />

                      {/* Chữ số xếp hạng 3D to nổi bật (1st, 2nd, 3rd) */}
                      <div style={{
                        fontSize: isTop1 ? 30 : rank === 2 ? 22 : 18,
                        fontWeight: 900,
                        fontFamily: 'var(--n-sans)',
                        color: medal.numColor,
                        lineHeight: 1,
                        letterSpacing: '-0.03em',
                        textShadow: medal.numShadow,
                        userSelect: 'none',
                        display: 'flex',
                        alignItems: 'baseline',
                        gap: 1.5,
                      }}>
                        <span>{rank}</span>
                        <span style={{ fontSize: isTop1 ? 12 : 10, fontWeight: 700, opacity: 0.95 }}>
                          {rank === 1 ? 'st' : rank === 2 ? 'nd' : 'rd'}
                        </span>
                      </div>

                      {/* Pill nhãn danh hiệu / điểm số bên trong bục giống ảnh mẫu */}
                      <div style={{
                        fontSize: 8,
                        fontWeight: 800,
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        color: medal.pillColor,
                        background: medal.pillBg,
                        border: `1px solid ${medal.pillBorder}`,
                        padding: '1.5px 5px',
                        borderRadius: 6,
                        marginTop: 3,
                        backdropFilter: 'blur(4px)',
                        boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
                      }}>
                        {medal.subTitle}
                      </div>
                    </div>

                    {/* ── HOVER INSPECTION TOOLTIP (BUNG CHI TIẾT KHI RÊ CHUỘT) ── */}
                    {isHovered && (
                      <div style={{
                        position: 'absolute',
                        bottom: pedestalH + 14,
                        left: '50%',
                        transform: 'translateX(-50%)',
                        width: 256,
                        background: 'var(--n-surface)',
                        backdropFilter: 'blur(20px)',
                        border: `1px solid ${medal.color}`,
                        boxShadow: `0 16px 36px -4px rgba(0,0,0,0.25), 0 0 0 1px var(--n-line)`,
                        borderRadius: 14,
                        padding: '12px 14px',
                        zIndex: 40,
                        animation: 'fadeIn 0.18s ease-out',
                        pointerEvents: 'none',
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: medal.color }}>
                            {medal.badge} · @{u.handle}
                          </span>
                          <span style={{ fontSize: 10, color: 'var(--n-ink-3)' }}>
                            {best.symbol || 'BTC-USDT'}
                          </span>
                        </div>

                        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--n-ink)', marginBottom: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {best.name || 'Chiến lược tốt nhất'}
                        </div>

                        {/* 4 chỉ số cốt lõi */}
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6, marginBottom: 8 }}>
                          <div style={{ background: 'var(--n-surface-2)', padding: '5px 8px', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                            <div style={{ fontSize: 9.5, color: 'var(--n-ink-2)' }}>Lợi nhuận PnL</div>
                            <div style={{ fontSize: 12, fontWeight: 800, color: tone(best.ret_pct), marginTop: 2 }}>
                              {spct(best.ret_pct)}
                            </div>
                          </div>
                          <div style={{ background: 'var(--n-surface-2)', padding: '5px 8px', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                            <div style={{ fontSize: 9.5, color: 'var(--n-ink-2)' }}>Max Drawdown</div>
                            <div style={{ fontSize: 12, fontWeight: 800, color: best.mdd_pct != null ? 'var(--n-neg)' : 'inherit', marginTop: 2 }}>
                              {pct(best.mdd_pct)}
                            </div>
                          </div>
                          <div style={{ background: 'var(--n-surface-2)', padding: '5px 8px', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                            <div style={{ fontSize: 9.5, color: 'var(--n-ink-2)' }}>Chỉ số Sharpe</div>
                            <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--n-accent)', marginTop: 2 }}>
                              {isNum(best.sharpe) ? fmtNum(best.sharpe, 2) : '—'}
                            </div>
                          </div>
                          <div style={{ background: 'var(--n-surface-2)', padding: '5px 8px', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                            <div style={{ fontSize: 9.5, color: 'var(--n-ink-2)' }}>Tỷ lệ thắng</div>
                            <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--n-pos)', marginTop: 2 }}>
                              {pct(best.win_rate, 0)}
                            </div>
                          </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11, color: 'var(--n-accent)', fontWeight: 700, borderTop: '1px dashed var(--n-line)', paddingTop: 6 }}>
                          <span style={{ color: 'var(--n-ink-3)' }}>Khung: {best.timeframe || '1h'}</span>
                          <span>Bấm mở chiến lược →</span>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>

      {/* ── THANH ĐIỀU KHIỂN & BỘ LỌC THÔNG MINH (GLASS PANEL) ── */}
      <div className="edu-glass-panel" style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          {/* Ô tìm kiếm - Không icon */}
          <div style={{ flex: '1 1 200px', minWidth: 180 }}>
            <input
              className="n-input"
              placeholder="Tìm theo tên tác giả..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ width: '100%' }}
            />
          </div>

          {/* Lọc Khung thời gian */}
          <select className="n-input" value={timeframe} onChange={(e) => updatePartition('timeframe', e.target.value)} aria-label="Khung thời gian" style={{ flex: '1 1 140px', minWidth: 130 }}>
            {TIMEFRAMES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>

          {/* Lọc Cặp tài sản */}
          <select className="n-input" value={symbol} onChange={(e) => updatePartition('symbol', e.target.value)} aria-label="Cặp tài sản" style={{ flex: '1 1 140px', minWidth: 130 }}>
            {SYMBOLS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>

          {/* Khoảng ngày (Date Range) */}
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flex: '1 1 240px', minWidth: 230 }}>
            <input className="n-input" type="date" value={startDate} onChange={(e) => updateWindow('startDate', e.target.value)} style={{ fontSize: 12, flex: 1, minWidth: 0 }} aria-label="Ngày bắt đầu" title="Ngày bắt đầu" />
            <span style={{ color: 'var(--n-ink-3)', fontSize: 12 }}>→</span>
            <input className="n-input" type="date" value={endDate} onChange={(e) => updateWindow('endDate', e.target.value)} style={{ fontSize: 12, flex: 1, minWidth: 0 }} aria-label="Ngày kết thúc" title="Ngày kết thúc" />
          </div>

          {/* Lọc Regime tham khảo */}
          <select className="n-input" value={regime} disabled={!hasComparisonPartition} onChange={(e) => { setPage(1); setRegime(e.target.value) }} style={{ flex: '1 1 180px', minWidth: 170, opacity: !hasComparisonPartition ? 0.6 : 1 }} aria-label="Regime tham khảo">
            {REGIMES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>

          {/* Sắp xếp */}
          <select className="n-input" value={sort} onChange={(e) => { setPage(1); setSort(e.target.value) }} aria-label="Sắp xếp" style={{ flex: '1 1 160px', minWidth: 150 }}>
            {SORTS.map(([k, l]) => <option key={k} value={k} disabled={['pnl', 'sharpe'].includes(k) && !hasComparisonPartition}>{l}</option>)}
          </select>
        </div>

        {(timeframe !== 'all' || symbol !== 'all' || startDate || endDate || regime !== 'all' || q) && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--n-line-soft)' }}>
            <button
              type="button"
              className="n-btn xs ghost"
              onClick={resetFilters}
              style={{ fontSize: 11, color: 'var(--n-neg)', padding: '4px 10px', borderRadius: 6 }}
            >
              Xóa bộ lọc
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
            const best = u.best
            const isRanked = Boolean(best?.pass_analyst || best?.is_ranked || u.ranked_strategies > 0)
            const badgeLabel = best?.pass_analyst ? '✓ Pass Analyst' : (best?.is_ranked ? '✓ Đạt chuẩn' : (best?.unranked_reason || '⏳ Mẫu nhỏ'))
            const ret = best?.ret_pct
            const pnl = best?.pnl_usd
            const mdd = best?.mdd_pct
            const sharpe = best?.sharpe

            return (
              <div
                key={u.handle}
                onClick={() => nav(best ? `/s/${encodeURIComponent(best.id)}` : `/u/${encodeURIComponent(u.handle)}`)}
                onMouseEnter={() => prefetchEduUser(u.handle)}
                className="edu-market-card"
                style={{ cursor: 'pointer', display: 'flex', flexDirection: 'column' }}
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

                {/* 1. Thông tin tác giả + Huy hiệu */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14 }}>
                  <div
                    onClick={(e) => { e.stopPropagation(); nav(`/u/${encodeURIComponent(u.handle)}`) }}
                    style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0, cursor: 'pointer' }}
                    title={`Xem toàn bộ hồ sơ tác giả @${u.handle}`}
                  >
                    <Avatar avatar={u.avatar} size={42} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: 15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--n-ink)' }}>
                        {u.display_name}
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--n-accent)', marginTop: 1, fontWeight: 500 }}>
                        @{u.handle}
                      </div>
                    </div>
                  </div>

                  <span
                    title={best?.pass_analyst ? 'Chiến lược đã vượt qua kiểm định Analyst' : (isRanked ? 'Đạt chuẩn xếp hạng kiểm định định lượng' : (best?.unranked_reason || 'Mẫu nhỏ / Chưa xếp hạng'))}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: '3px 9px',
                      borderRadius: 12,
                      whiteSpace: 'nowrap',
                      background: isRanked ? 'var(--n-pos-wash)' : 'var(--n-surface-2)',
                      color: isRanked ? 'var(--n-pos)' : 'var(--n-warn)',
                      border: isRanked ? '1px solid var(--n-pos)' : '1px solid var(--n-line)',
                    }}
                  >
                    {badgeLabel}
                  </span>
                </div>

                {/* 2. Tiêu điểm: Chiến lược tốt nhất / Pass Analyst (Chỉ 1 Alpha duy nhất) */}
                <div style={{
                  background: 'var(--n-surface-2)',
                  border: '1px solid var(--n-line-soft)',
                  borderRadius: 12,
                  padding: '12px 14px',
                  marginBottom: 14,
                }}>
                  {best ? (
                    <>
                      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--n-ink)', lineHeight: 1.35 }}>
                          ⚡ {best.name}
                        </div>
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--n-ink-2)' }}>
                        {best.category && (
                          <span style={{ padding: '2px 7px', borderRadius: 4, background: 'var(--n-surface)', border: '1px solid var(--n-line)', fontWeight: 600 }}>
                            {best.category}
                          </span>
                        )}
                        <span>{best.symbol || 'BTC-USDT'}</span>
                        <span>·</span>
                        <span>{best.timeframe || '15m'}</span>
                        {best.trades != null && (
                          <>
                            <span>·</span>
                            <span>{best.trades} lệnh</span>
                          </>
                        )}
                      </div>
                    </>
                  ) : (
                    <div style={{ fontSize: 12.5, color: 'var(--n-ink-3)', padding: '6px 0' }}>Chưa lưu chiến lược nào</div>
                  )}
                </div>

                {/* 3. Ba ô chỉ số định lượng của CHÍNH CHIẾN LƯỢC ĐÓ */}
                {best ? (
                  <div className="edu-metric-grid" style={{ marginBottom: 14 }}>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 11, color: 'var(--n-ink-2)', marginBottom: 2 }}>Lợi nhuận</div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: tone(ret), whiteSpace: 'nowrap' }}>
                        {spct(ret)}
                      </div>
                      {pnl != null && (
                        <div style={{ fontSize: 10.5, color: tone(pnl), marginTop: 1 }}>{usd(pnl)}</div>
                      )}
                    </div>
                    <div style={{ textAlign: 'center', borderLeft: '1px solid var(--n-line)', borderRight: '1px solid var(--n-line)' }}>
                      <div style={{ fontSize: 11, color: 'var(--n-ink-2)', marginBottom: 2 }}>Max DD</div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: mdd != null ? 'var(--n-neg)' : 'inherit' }}>
                        {pct(mdd)}
                      </div>
                      <div style={{ fontSize: 10.5, color: 'var(--n-ink-3)', marginTop: 1 }}>Sụt giảm</div>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 11, color: 'var(--n-ink-2)', marginBottom: 2 }}>Sharpe</div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: isNum(sharpe) && sharpe > 1 ? 'var(--n-accent)' : 'inherit' }}>
                        {isNum(sharpe) ? fmtNum(sharpe, 2) : '—'}
                      </div>
                      <div style={{ fontSize: 10.5, color: 'var(--n-ink-3)', marginTop: 1 }}>
                        {best.win_rate != null ? `Win ${pct(best.win_rate, 0)}` : 'Định lượng'}
                      </div>
                    </div>
                  </div>
                ) : null}

                {/* 4. Chế độ thị trường Regime (nếu có) */}
                {best?.market_context?.status === 'available' && (
                  <div style={{ fontSize: 11, color: 'var(--n-ink-2)', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span>Regime tham khảo: {best.market_context.dominant === 'RANGE' ? 'Đi ngang' : (REGIMES.find(([key]) => key === best.market_context.dominant)?.[1] || best.market_context.dominant)}</span>
                  </div>
                )}

                {/* 5. Nút xem chi tiết chiến lược */}
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  fontSize: 12.5,
                  color: 'var(--n-accent)',
                  fontWeight: 600,
                  marginTop: 'auto',
                  paddingTop: 10,
                  borderTop: '1px solid var(--n-line-soft)',
                }}>
                  <span>Xem chiến lược này ⚡</span>
                  <span>→</span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* ── THANH PHÂN TRANG HIỆN ĐẠI (CHUẨN CĂN GIỮA, GLASSMORPHISM) ── */}
      {pagination.total > 0 && (
        <div className="edu-pagination-wrapper">
          <div className="edu-pagination-info">
            <span className="edu-pagination-badge">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: 0.85 }}>
                <rect x="3" y="3" width="7" height="7"></rect>
                <rect x="14" y="3" width="7" height="7"></rect>
                <rect x="14" y="14" width="7" height="7"></rect>
                <rect x="3" y="14" width="7" height="7"></rect>
              </svg>
              Trang {pagination.page} / {pagination.total_pages || 1}
            </span>
            <span>
              Đang xem <b style={{ color: 'var(--n-ink)', fontWeight: 600 }}>{shown.length}</b> / <b style={{ color: 'var(--n-ink)', fontWeight: 600 }}>{pagination.total}</b> tác giả
            </span>
            <span style={{ opacity: 0.5 }}>·</span>
            <span style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>9 thẻ/trang</span>
          </div>

          <div className="edu-pagination-controls">
            {(pagination.total_pages || 1) > 5 && (
              <button
                type="button"
                className="edu-pagination-nav"
                disabled={page <= 1 || loading}
                onClick={() => setPage(1)}
                title="Về trang đầu (Trang 1)"
                aria-label="Về trang đầu"
              >
                « Đầu
              </button>
            )}

            <button
              type="button"
              className="edu-pagination-nav"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              title="Trang trước"
              aria-label="Trang trước"
            >
              ← Trước
            </button>

            {pageNumbers.map((p) => (
              <button
                key={p}
                type="button"
                className={`edu-pagination-page ${p === page ? 'active' : ''}`}
                disabled={loading}
                onClick={() => setPage(p)}
                title={`Chuyển tới trang ${p}`}
                aria-label={`Trang ${p}`}
                aria-current={p === page ? 'page' : undefined}
              >
                <span>{p}</span>
              </button>
            ))}

            <button
              type="button"
              className="edu-pagination-nav"
              disabled={page >= (pagination.total_pages || 1) || loading}
              onClick={() => setPage((p) => Math.min(pagination.total_pages || 1, p + 1))}
              title="Trang sau"
              aria-label="Trang sau"
            >
              Sau →
            </button>

            {(pagination.total_pages || 1) > 5 && (
              <button
                type="button"
                className="edu-pagination-nav"
                disabled={page >= (pagination.total_pages || 1) || loading}
                onClick={() => setPage(pagination.total_pages || 1)}
                title={`Tới trang cuối (Trang ${pagination.total_pages || 1})`}
                aria-label="Tới trang cuối"
              >
                Cuối »
              </button>
            )}
          </div>
        </div>
      )}

      <UserPicker open={pickerOpen} onClose={() => { setPickerOpen(false); load() }} />
    </div>
  )
}
