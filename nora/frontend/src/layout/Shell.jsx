import React, { useEffect, useRef, useState } from 'react'
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import '../styles/shell.css'
import { useCatalog } from '../context/Catalog'
import { ErrorBoundary } from '../components/ui'
import JobTray from '../components/jobs/JobTray'
import { GuideSteps } from '../components/ui/QuickGuide'

const KEY = 'nora-theme' // cùng khoá với ThemeToggle cũ

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

// Hệ thống chính (Coin)
const COIN_PAGES = [
  { to: '/portfolio', title: 'Tổng quan danh mục', short: 'Tổng quan', icon: I.portfolio },
  { to: '/alpha', title: 'Alpha · Tạo chiến lược + Danh mục + Tối ưu + Phễu', short: 'Alpha', icon: I.alpha },
  { to: '/backtest', title: 'Backtest · WFA · Monte Carlo', short: 'Backtest', icon: I.backtest },
  { to: '/live', title: 'Bot live · paper / demo', short: 'Live', icon: I.live },
  { to: '/history', title: 'Lịch sử chạy', short: 'Lịch sử', icon: I.history },
]

// Hệ thống Education riêng
const EDU_PAGES = [
  { to: '/education', title: 'Thực hành Mẫu Chiến lược Định lượng', short: 'Mẫu', icon: I.education },
]

const ALL_SEARCH_PAGES = [...COIN_PAGES, ...EDU_PAGES]

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

function Search() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const nav = useNavigate()
  const norm = (s) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd')
  const res = q.trim() ? ALL_SEARCH_PAGES.filter((p) => norm(p.title).includes(norm(q.trim()))) : []
  useEffect(() => {
    const h = (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); ref.current?.focus() } }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])
  const go = (to) => { nav(to); setQ(''); setOpen(false); ref.current?.blur() }
  return (
    <div className="n-search" role="search">
      {I.search}
      <input ref={ref} value={q} aria-label="Tìm màn hình" placeholder="Tìm màn hình…" onChange={(e) => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => { if (e.key === 'Enter' && res[0]) go(res[0].to); if (e.key === 'Escape') { setQ(''); ref.current?.blur() } }} />
      <kbd>⌘K</kbd>
      {open && res.length > 0 && (
        <div className="n-search-res">{res.map((r) => <button type="button" key={r.to} onMouseDown={() => go(r.to)}>{r.title}</button>)}</div>
      )}
    </div>
  )
}

export default function Shell({ children }) {
  const loc = useLocation()
  const { data, loading, error } = useCatalog()
  const isEdu = loc.pathname.startsWith('/education')
  const page = ALL_SEARCH_PAGES.find((p) => loc.pathname.startsWith(p.to))
  const runCrumb = loc.pathname.startsWith('/alpha/funnel/') ? decodeURIComponent(loc.pathname.split('/')[3] || '') : ''
  const apiTone = error ? 'bad' : loading && !data ? 'warn' : 'ok'
  const apiText = error ? 'API ngoại tuyến' : loading && !data ? 'Đang kết nối' : 'API trực tuyến'
  const dataEnd = data?.windows?.end

  return (
    <div className="v2">
      <nav className="n-rail" aria-label="Điều hướng chính">
        <div className="n-logo" aria-hidden="true" title={isEdu ? 'Nora Education' : 'Nora Quant'}>
          {isEdu ? I.education : I.logo}
        </div>

        {/* Sidebar riêng biệt: Education không chung sidebar với các tab Coin */}
        {isEdu ? (
          <>
            {EDU_PAGES.map((p) => (
              <NavLink key={p.to} to={p.to} className={({ isActive }) => `n-rail-btn ${isActive ? 'on' : ''}`} title={p.title}>
                {p.icon}<span className="n-rl">{p.short || p.title}</span>
              </NavLink>
            ))}
            <div className="n-rail-sp" />
            <NavLink to="/portfolio" className="n-rail-btn" title="Quay lại Hệ thống Giao dịch Nora (Coin)">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 20, height: 20 }}>
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
              <span className="n-rl">Về Coin</span>
            </NavLink>
          </>
        ) : (
          <>
            {COIN_PAGES.map((p) => (
              <NavLink key={p.to} to={p.to} className={({ isActive }) => `n-rail-btn ${isActive ? 'on' : ''}`} title={p.title}>
                {p.icon}<span className="n-rl">{p.short || p.title}</span>
              </NavLink>
            ))}
            <div className="n-rail-sp" />
            <NavLink to="/education" className="n-rail-btn" title="Chuyển sang Chế độ Học tập (Education)">
              {I.education}
              <span className="n-rl">Education</span>
            </NavLink>
          </>
        )}
      </nav>

      <div className="n-main">
        <header className="n-top">
          <div className="n-crumb">
            {isEdu ? (
              <>
                <Link to="/education" style={{ fontWeight: 700, color: '#6366f1' }}>🎓 Education</Link>
                <span className="sep">›</span>
                <span>Mẫu chiến lược & Backtest</span>
              </>
            ) : (
              <>
                <Link to="/portfolio">Tổng quan</Link><span className="sep">›</span>
                {runCrumb ? <><Link to={page?.to}>{page?.title}</Link><span className="sep">›</span><span className="mono">Lượt {runCrumb}</span></>
                  : <span>{page ? page.title : 'Không tìm thấy trang'}</span>}
              </>
            )}
          </div>
          <div className="n-top-sp" />
          {!isEdu && (
            <>
              <Search />
              <JobTray />
              <HelpButton />
              {data?.windows?.end && <span className="n-pill" title="Ngày cuối của dữ liệu thị trường"><span className="n-dot ok" />Dữ liệu đến <span className="mono">{dataEnd}</span></span>}
            </>
          )}
          <span className="n-pill"><span className={`n-dot ${apiTone}`} />{apiText}</span>
          <ThemeButton />
        </header>
        <div className={`n-content${loc.pathname.startsWith('/alpha/create') || loc.pathname.startsWith('/education') ? ' flush' : ''}`}>
          <ErrorBoundary key={loc.pathname}>{children}</ErrorBoundary>
        </div>
      </div>
    </div>
  )
}
