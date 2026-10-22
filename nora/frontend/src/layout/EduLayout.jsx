import React, { useEffect, useState } from 'react'
import { NavLink, Link, useLocation, Outlet } from 'react-router-dom'
import '../styles/shell.css'
import { ErrorBoundary } from '../components/ui'
import UserBadge from '../components/user/UserBadge'
import { useCatalog } from '../meta/MetaProvider'

const KEY = 'nora-theme'

const I = {
  logo: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z" /><path d="M6 12v5c3 3 9 3 12 0v-5" /></svg>,
  market: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></svg>,
  studio: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg>,
  sun: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>,
  moon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 13.5A8.5 8.5 0 1 1 10.5 3 6.7 6.7 0 0 0 21 13.5Z" /></svg>,
}

const EDU_PAGES = [
  { to: '/edu', end: true, title: 'Market', short: 'Market', icon: I.market },
  { to: '/edu/studio', end: false, title: 'Studio', short: 'Studio', icon: I.studio },
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

export default function EduLayout({ children }) {
  const loc = useLocation()
  const { data, loading, error } = useCatalog()
  const apiTone = error ? 'bad' : loading && !data ? 'warn' : 'ok'
  const apiText = error ? 'API ngoại tuyến' : loading && !data ? 'Đang kết nối' : 'API trực tuyến'

  return (
    <div className="v2">
      <nav className="n-rail" aria-label="Điều hướng chính Education">
        <Link to="/" className="n-logo" title="Về trang chủ Nora">
          {I.logo}
        </Link>

        {EDU_PAGES.map((p) => (
          <NavLink
            key={p.to}
            to={p.to}
            end={p.end}
            className={({ isActive }) => `n-rail-btn ${isActive ? 'on' : ''}`}
            title={p.title}
          >
            {p.icon}
            <span className="n-rl">{p.short || p.title}</span>
          </NavLink>
        ))}

        <div className="n-rail-sp" />

        <Link to="/" className="n-rail-btn" title="← Về Trang chủ Nora">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 18, height: 18 }}>
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          <span className="n-rl">Trang chủ</span>
        </Link>

        <a
          href={typeof window !== 'undefined' && window.location.hostname.includes('edu.nora.') ? window.location.origin.replace('edu.nora.', 'coin.nora.') + '/coin' : '/coin'}
          className="n-rail-btn"
          title="Chuyển sang Nora Coin"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ width: 18, height: 18 }}>
            <path d="M20 12a8 8 0 1 1-3-6.2" /><circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />
          </svg>
          <span className="n-rl">Coin</span>
        </a>
      </nav>

      <div className="n-main">
        <header className="n-top">
          <div className="n-crumb">
            <Link to="/" style={{ color: 'var(--n-ink-2)' }}>Nora</Link>
            <span className="sep">›</span>
            <Link to="/edu" style={{ fontWeight: 600 }}>Education</Link>
            <span className="sep">›</span>
            <span>{loc.pathname.startsWith('/edu/studio') ? 'Studio' : 'Market'}</span>
          </div>

          <div className="n-top-sp" />

          <span className="n-pill">
            <span className={`n-dot ${apiTone}`} />
            {apiText}
          </span>
          <ThemeButton />
          <UserBadge />
        </header>

        <div className={`n-content ${loc.pathname.startsWith('/edu/studio') ? 'flush' : ''}`}>
          <ErrorBoundary key={loc.pathname}>
            {children || <Outlet />}
          </ErrorBoundary>
        </div>
      </div>
    </div>
  )
}
