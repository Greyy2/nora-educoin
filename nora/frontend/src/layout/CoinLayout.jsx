import React, { useEffect, useRef, useState } from 'react'
import { NavLink, Link, useLocation, Outlet } from 'react-router-dom'
import '../styles/shell.css'
import { useCatalog } from '../meta/MetaProvider'
import { ErrorBoundary } from '../components/ui'
import JobTray from '../components/jobs/JobTray'
import NotificationBell from '../components/notifications/NotificationBell'
import { GuideSteps } from '../components/ui/QuickGuide'
import UserBadge from '../components/user/UserBadge'

const KEY = 'nora-theme'

const I = {
  logo: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M20 12a8 8 0 1 1-3-6.2" /><circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" /></svg>,
  portfolio: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></svg>,
  backtest: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /><path d="M12 8v4l3 2" /></svg>,
  alpha: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3h6M10 3v6l-5.5 9.5A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2.5L14 9V3" /><path d="M7.5 15h9" /></svg>,
  history: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>,
  live: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12h4l2.5-6 4 12 2.5-6H21" /></svg>,
  education: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z" /><path d="M6 12v5c3 3 9 3 12 0v-5" /></svg>,
  help: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"><circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5" /><circle cx="12" cy="7.8" r=".7" fill="currentColor" /></svg>,
  search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>,
  sun: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>,
  moon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 13.5A8.5 8.5 0 1 1 10.5 3 6.7 6.7 0 0 0 21 13.5Z" /></svg>,
}

const COIN_PAGES = [
  { to: '/coin/portfolio', title: 'Tổng quan', short: 'Tổng quan', icon: I.portfolio, preload: () => import('../pages/Portfolio') },
  { to: '/coin/alpha/create', match: '/coin/alpha', title: 'Alpha', short: 'Alpha', icon: I.alpha, preload: () => import('../pages/Studio') },
  { to: '/coin/backtest', title: 'Backtest', short: 'Backtest', icon: I.backtest, preload: () => import('../pages/Backtest') },
  { to: '/coin/live', title: 'Bot live · paper / demo', short: 'Live', icon: I.live, preload: () => import('../pages/Live') },
  { to: '/coin/history', title: 'Lịch sử chạy', short: 'Lịch sử', icon: I.history, preload: () => import('../pages/History') },
]

function ThemeButton() {
  const [theme, setTheme] = useState(() => {
    try { const s = localStorage.getItem(KEY); if (s === 'light' || s === 'dark') return s } catch (e) { /* bỏ qua */ }
    try { return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light' } catch (e) { return 'dark' }
  })
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])
  const pick = (t) => {
    document.documentElement.setAttribute('data-theme', t)
    try { localStorage.setItem(KEY, t) } catch (e) { /* bỏ qua */ }
    setTheme(t)
  }
  return (
    <div className="n-theme-switch" role="group" aria-label="Chế độ hiển thị">
      <button type="button" aria-pressed={theme === 'light'} onClick={() => pick('light')}>{I.sun}<span>Sáng</span></button>
      <button type="button" aria-pressed={theme === 'dark'} onClick={() => pick('dark')}>{I.moon}<span>Tối</span></button>
    </div>
  )
}

function HelpButton() {
  const [open, setOpen] = useState(false)
  const box = useRef(null)
  const loc = useLocation()
  useEffect(() => { setOpen(false) }, [loc.pathname])
  useEffect(() => {
    if (!open) return undefined
    const click = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const key = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', click)
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', click); document.removeEventListener('keydown', key) }
  }, [open])
  return (
    <div className="n-tray" ref={box}>
      <button type="button" className="n-icon-btn n-help" aria-expanded={open} aria-haspopup="true" aria-controls="n-help-pop" aria-label="Hướng dẫn nhanh" title="Hướng dẫn nhanh" onClick={() => setOpen((o) => !o)}>{I.help}</button>
      {open && (
        <div className="n-pop n-help-pop" id="n-help-pop">
          <div className="n-pop-h"><b>Hướng dẫn nhanh</b><span className="muted">Vòng kiểm chứng 5 bước</span></div>
          <div style={{ padding: '4px 14px 12px' }}><GuideSteps onNavigate={() => setOpen(false)} /></div>
        </div>
      )}
    </div>
  )
}

export default function CoinLayout({ children }) {
  const loc = useLocation()
  const { data, loading, error } = useCatalog()
  const page = COIN_PAGES.find((p) => loc.pathname.startsWith(p.match || p.to))
  const apiTone = error ? 'bad' : loading && !data ? 'warn' : 'ok'
  const apiText = error ? 'API ngoại tuyến' : loading && !data ? 'Đang kết nối' : 'API trực tuyến'
  const dataEnd = data?.windows?.end

  useEffect(() => {
    // Tự động tải trước (preload) các view con của Coin ở chế độ nhàn rỗi (idle) để chuyển tab mượt tức thì
    const idle = window.requestIdleCallback || ((cb) => setTimeout(cb, 60))
    const h = idle(() => {
      COIN_PAGES.forEach((p) => p.preload?.())
    })
    return () => {
      if (window.cancelIdleCallback) window.cancelIdleCallback(h)
      else clearTimeout(h)
    }
  }, [])

  return (
    <div className="v2">
      <nav className="n-rail" aria-label="Điều hướng chính Coin">
        <Link to="/" className="n-logo" title="Về trang chủ Nora">
          {I.logo}
        </Link>

        {COIN_PAGES.map((p) => {
          const isActive = p.match ? loc.pathname.startsWith(p.match) : loc.pathname.startsWith(p.to)
          return (
            <NavLink
              key={p.to}
              to={p.to}
              className={`n-rail-btn ${isActive ? 'on' : ''}`}
              title={p.title}
              onMouseEnter={() => p.preload?.()}
              onPointerDown={() => p.preload?.()}
            >
              {p.icon}<span className="n-rl">{p.short || p.title}</span>
            </NavLink>
          )
        })}

        <div className="n-rail-sp" />

        <Link to="/" className="n-rail-btn" title="← Về Trang chủ Nora">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 18, height: 18 }}>
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          <span className="n-rl">Trang chủ</span>
        </Link>
        <a
          href={typeof window !== 'undefined' && window.location.hostname.includes('coin.nora.') ? window.location.origin.replace('coin.nora.', 'edu.nora.') + '/edu' : '/edu'}
          className="n-rail-btn"
          title="Chuyển sang Nora Education"
        >
          {I.education}
          <span className="n-rl">Education</span>
        </a>
      </nav>

      <div className="n-main">
        <header className="n-top">
          <div className="n-crumb">
            <Link to="/" style={{ color: 'var(--n-ink-2)' }}>Nora</Link>
            <span className="sep">›</span>
            <Link to="/coin/alpha" style={{ fontWeight: 600 }}>Coin</Link>
            <span className="sep">›</span>
            <span>{page ? page.title : 'Không tìm thấy trang'}</span>
          </div>
          <div className="n-top-sp" />
          <NotificationBell />
          <JobTray />
          <HelpButton />
          {data?.windows?.end && (
            <span className="n-pill" title="Ngày cuối của dữ liệu thị trường">
              <span className="n-dot ok" />Dữ liệu đến <span className="mono">{dataEnd}</span>
            </span>
          )}
          <span className="n-pill"><span className={`n-dot ${apiTone}`} />{apiText}</span>
          <ThemeButton />
          <UserBadge />
        </header>

        <div className={`n-content${loc.pathname.startsWith('/coin/alpha') ? ' flush' : ''}`}>
          <ErrorBoundary resetKey={loc.pathname}>
            {children || <Outlet />}
          </ErrorBoundary>
        </div>
      </div>
    </div>
  )
}
