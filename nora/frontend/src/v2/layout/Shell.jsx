import React, { useEffect, useRef, useState } from 'react'
import { NavLink, Link, useLocation, useNavigate } from 'react-router-dom'
import '../v2.css'
import { useCatalog } from '../context/Catalog'
import { mockEnabled } from '../api'
import { ErrorBoundary } from '../components/ui'

const KEY = 'nora-theme' // cùng khoá với ThemeToggle cũ

const I = {
  logo: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M20 12a8 8 0 1 1-3-6.2" /><circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" /></svg>,
  portfolio: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round"><rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" /></svg>,
  backtest: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /><path d="M12 8v4l3 2" /></svg>,
  alpha: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M9 3h6M10 3v6l-5.5 9.5A1.5 1.5 0 0 0 5.8 21h12.4a1.5 1.5 0 0 0 1.3-2.5L14 9V3" /><path d="M7.5 15h9" /></svg>,
  legacy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="5" rx="1" /><path d="M5 9v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9M10 13h4" /></svg>,
  search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>,
  sun: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>,
  moon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 13.5A8.5 8.5 0 1 1 10.5 3 6.7 6.7 0 0 0 21 13.5Z" /></svg>,
}

const PAGES = [
  { to: '/portfolio', title: 'Danh mục', icon: I.portfolio },
  { to: '/backtest', title: 'Backtest · WFA · Monte Carlo', short: 'Backtest', icon: I.backtest },
  { to: '/alpha', title: 'Alpha · Hiệu chỉnh tham số', short: 'Alpha', icon: I.alpha },
]
const LEGACY = [
  { to: '/dashboard', title: 'Tổng quan (cũ)' },
  { to: '/library/alpha', title: 'Alpha · Chiến lược (cũ)' },
  { to: '/library/base', title: 'Base · Cấu hình chạy' },
  { to: '/library/wfa', title: 'Walk-Forward (cũ)' },
  { to: '/library/monte-carlo', title: 'Monte Carlo (cũ)' },
  { to: '/library/result', title: 'Result · Kết quả' },
  { to: '/research/analysis', title: 'Market Research Command Center' },
]

function ThemeButton() {
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem(KEY) || 'dark' } catch (e) { return 'dark' } })
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try { localStorage.setItem(KEY, theme) } catch (e) { /* bỏ qua */ }
  }, [theme])
  const dark = theme === 'dark'
  return (
    <button type="button" className="n-icon-btn" onClick={() => setTheme(dark ? 'light' : 'dark')}
      aria-label={dark ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối'} title={dark ? 'Chế độ sáng' : 'Chế độ tối'}>
      {dark ? I.sun : I.moon}
    </button>
  )
}

function Search() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const nav = useNavigate()
  const all = [...PAGES.map((p) => ({ to: p.to, title: p.title })), ...LEGACY]
  const norm = (s) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd')
  const res = q.trim() ? all.filter((p) => norm(p.title).includes(norm(q.trim()))) : []
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
  const [legacyOpen, setLegacyOpen] = useState(false)
  const page = PAGES.find((p) => loc.pathname.startsWith(p.to))
  const isLegacy = !page
  const legacyPage = LEGACY.find((l) => loc.pathname.startsWith(l.to))
  const apiTone = error ? 'bad' : loading && !data ? 'warn' : 'ok'
  const apiText = error ? 'API ngoại tuyến' : loading && !data ? 'Đang kết nối' : 'API trực tuyến'
  const dataEnd = data?.windows?.end

  useEffect(() => { setLegacyOpen(false) }, [loc.pathname])

  return (
    <div className="v2">
      <nav className="n-rail" aria-label="Điều hướng chính">
        <div className="n-logo" aria-hidden="true">{I.logo}</div>
        {PAGES.map((p) => (
          <NavLink key={p.to} to={p.to} className={({ isActive }) => `n-rail-btn ${isActive ? 'on' : ''}`} aria-label={p.short || p.title}>
            {p.icon}<span className="n-tipl">{p.short || p.title}</span>
          </NavLink>
        ))}
        <div className="n-rail-sp" />
        <button type="button" className={`n-rail-btn ${isLegacy || legacyOpen ? 'on' : ''}`} aria-expanded={legacyOpen} aria-controls="n-legacy" aria-label="Legacy" onClick={() => setLegacyOpen((o) => !o)}>
          {I.legacy}<span className="n-tipl">Legacy</span>
        </button>
        {legacyOpen && (
          <div className="n-legacy-pop" id="n-legacy">
            <h4>Legacy</h4>
            {LEGACY.map((l) => <NavLink key={l.to} to={l.to} className={({ isActive }) => (isActive ? 'on' : '')}>{l.title}</NavLink>)}
          </div>
        )}
      </nav>

      <div className="n-main">
        <header className="n-top">
          <div className="n-crumb">
            <Link to="/portfolio">Tổng quan</Link><span className="sep">›</span>
            <span>{page ? page.title : `Legacy${legacyPage ? ` · ${legacyPage.title}` : ''}`}</span>
          </div>
          <div className="n-top-sp" />
          <Search />
          {data?.windows?.end && <span className="n-pill" title="Ngày cuối của dữ liệu thị trường"><span className="n-dot ok" />Dữ liệu đến <span className="mono">{dataEnd}</span></span>}
          <span className="n-pill"><span className={`n-dot ${apiTone}`} />{apiText}</span>
          {mockEnabled() && <span className="n-pill" title="Đang dùng dữ liệu mẫu khi mất kết nối"><span className="n-dot warn" />Mock</span>}
          <ThemeButton />
        </header>
        <div className={`n-content ${isLegacy ? 'legacy-host' : ''}`}>
          <ErrorBoundary key={loc.pathname}>{isLegacy ? <main className="main">{children}</main> : children}</ErrorBoundary>
        </div>
      </div>
    </div>
  )
}
