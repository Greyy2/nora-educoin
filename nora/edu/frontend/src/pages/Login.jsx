import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import EnterForm from '../components/user/EnterForm'
import { useUser } from '../meta/UserProvider'
import '../styles/home.css'

const THEME_KEY = 'nora-theme'

export default function Login() {
  const { me } = useUser()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from || '/'

  const [theme, setTheme] = useState(() => {
    try {
      const s = localStorage.getItem(THEME_KEY)
      if (s === 'light' || s === 'dark') return s
    } catch (e) { /* bỏ qua */ }
    try {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    } catch (e) {
      return 'dark'
    }
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch (e) { /* bỏ qua */ }
  }, [theme])

  const toggleTheme = () => {
    setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))
  }

  // Chuyển hướng nếu đã đăng nhập
  useEffect(() => {
    if (me) {
      navigate(from, { replace: true })
    }
  }, [me, navigate, from])

  return (
    <div className="nora-home-root">
      {/* Background Subtle Gradient Orbs */}
      <div className="nora-hero-bg">
        <div className="nora-orb nora-orb-1" />
        <div className="nora-orb nora-orb-2" />
        <div className="nora-orb nora-orb-3" />
      </div>

      {/* Header tối giản: Logo bên trái, Điều khiển bên phải */}
      <header className="nora-home-header">
        <Link to="/" className="nora-home-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ width: 20, height: 20, color: 'var(--text-primary)' }}>
            <path d="M20 12a8 8 0 1 1-3-6.2" />
            <circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />
          </svg>
          <span style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>noraquantengine</span>
        </Link>

        <div className="nora-header-right">
          <Link to="/" className="nora-nav-btn">
            ← Trang chủ
          </Link>
          <button
            type="button"
            className="nora-nav-btn nora-theme-toggle"
            onClick={toggleTheme}
            title={theme === 'dark' ? 'Chuyển sang chế độ Sáng' : 'Chuyển sang chế độ Tối'}
            aria-label="Theme toggle"
          >
            <span className="nora-tab-icon">
              {theme === 'dark' ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" style={{ width: 14, height: 14 }}>
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 14, height: 14 }}>
                  <path d="M21 13.5A8.5 8.5 0 1 1 10.5 3 6.7 6.7 0 0 0 21 13.5Z" />
                </svg>
              )}
            </span>
            <span>{theme === 'dark' ? 'Sáng' : 'Tối'}</span>
          </button>
        </div>
      </header>

      {/* Giao diện đăng nhập 2 layout như SOVA */}
      <div className="login-split-container">
        {/* LEFT SIDE: Branding & info */}
        <div className="login-left-panel">
          <div className="branding-content">
            <h1 className="brand-title">
              Nora <span className="brand-highlight">Trading</span>
            </h1>

            <div className="feature-list">
              <div className="feature-item">
                <div className="feature-bullet">
                  <span className="bullet-circle" />
                </div>
                <div className="feature-text">
                  <h3>Backtest Chiến lược</h3>
                  <p>Chạy backtest nhanh chóng trên dữ liệu lịch sử chất lượng cao</p>
                </div>
              </div>

              <div className="feature-item">
                <div className="feature-bullet">
                  <span className="bullet-circle" />
                </div>
                <div className="feature-text">
                  <h3>Kiểm định Nghiêm ngặt</h3>
                  <p>Đánh giá Walk-Forward, Monte Carlo và loại bỏ hiện tượng học vẹt thị trường</p>
                </div>
              </div>

              <div className="feature-item">
                <div className="feature-bullet">
                  <span className="bullet-circle" />
                </div>
                <div className="feature-text">
                  <h3>Độ chính xác Cao</h3>
                  <p>Phân tích hiệu suất chi tiết với metrics chuyên sâu và sổ lệnh thực</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT SIDE: Form card "Bạn là ai?" */}
        <div className="login-right-panel">
          <div className="login-form-container">
            <div className="form-header">
              <h2>Bạn là ai?</h2>
              <p>Nhập tên để vào. Chiến lược bạn lưu sẽ gắn với tên này.</p>
            </div>
            <EnterForm onDone={() => navigate(from, { replace: true })} />
          </div>
        </div>
      </div>
    </div>
  )
}
