import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getHomeSummary } from '../api'
import UserBadge from '../components/user/UserBadge'
import { Spinner } from '../components/ui'
import { useUser } from '../meta/UserProvider'
import '../styles/home.css'

const THEME_KEY = 'nora-theme'

const sv = (d) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{d}</svg>
)

const FLOW = [
  { t: 'Ý tưởng & Giả thuyết', s: 'Đặt giả thuyết thị trường có cơ sở kinh tế', i: sv(<><path d="M9 18h6M10 21h4" /><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z" /></>) },
  { t: 'Thiết kế Chiến lược', s: 'Quy tắc vào và thoát lệnh chính xác, quản trị rủi ro', i: sv(<><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" /></>) },
  { t: 'Backtest Đa tài sản', s: 'Thử nghiệm trên dữ liệu nến & tick thực', i: sv(<><path d="M3 3v18h18" /><path d="M7 15l4-4 3 3 5-6" /></>) },
  { t: 'Kiểm định Bền vững', s: 'Walk-Forward Analysis và Monte Carlo 10,000 kịch bản', i: sv(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" /></>) },
  { t: 'Paper / Testnet Demo', s: 'Chạy thử nghiệm an toàn, không dùng vốn thật', i: sv(<><circle cx="12" cy="12" r="9" /><path d="M10 8.5l5 3.5-5 3.5z" /></>) },
  { t: 'Vận hành Danh mục', s: 'Theo dõi chỉ số Sharpe, MDD, Regime thị trường', i: sv(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M8 14h3" /></>) },
]

const NAV = [[0, 'Trang chủ'], [1, 'Tính năng'], [2, 'Quy trình'], [3, 'Bắt đầu']]

function Stat({ v, l, small }) {
  return (
    <div className="nh-stat">
      <b style={small ? { fontSize: 20 } : undefined}>{v}</b>
      <span>{l}</span>
    </div>
  )
}

export default function Home() {
  const { me } = useUser()
  const navigate = useNavigate()
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [currentSlide, setCurrentSlide] = useState(0)

  const enterSystem = (targetPath = '/coin/portfolio') => {
    if (me) {
      navigate(targetPath)
    } else {
      navigate('/login', { state: { from: targetPath } })
    }
  }

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

  useEffect(() => {
    let active = true
    getHomeSummary()
      .then((data) => {
        if (active) setSummary(data)
      })
      .catch(() => {})
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const scrollToSlide = (idx) => {
    setCurrentSlide(idx)
    const el = document.getElementById(`slide-${idx}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' })
    }
  }

  const coin = summary?.coin
  const fmtVal = (val) => (val !== null && val !== undefined ? val : '—')

  return (
    <div className="nora-home-root">
      {/* Background Animated Gradient Orbs */}
      <div className="nora-hero-bg">
        <div className="nora-orb nora-orb-1" />
        <div className="nora-orb nora-orb-2" />
        <div className="nora-orb nora-orb-3" />
      </div>

      {/* Header tối giản COIN */}
      <header className="nora-home-header">
        <Link to="/" className="nora-home-logo" onClick={() => scrollToSlide(0)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ width: 20, height: 20, color: 'var(--text-primary)' }}>
            <circle cx="12" cy="12" r="9" />
            <path d="M14.5 9.2c-.5-.8-1.4-1.2-2.5-1.2-1.4 0-2.5.7-2.5 1.8 0 2.6 5 1.2 5 3.8 0 1.1-1.1 1.9-2.5 1.9-1.1 0-2.1-.5-2.6-1.4M12 6.5V8M12 16v1.5" />
          </svg>
          <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--text-primary)' }}>Nora COIN</span>
        </Link>

        <div className="nora-header-right">
          {NAV.map(([i, lbl]) => (
            <button key={i} type="button" className={`nora-nav-btn ${currentSlide === i ? 'active' : ''}`} onClick={() => scrollToSlide(i)}>
              {lbl}
            </button>
          ))}

          {/* Theme Toggle Button */}
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

          {me ? (
            <UserBadge />
          ) : (
            <Link to="/login" className="n-btn sm" style={{ textDecoration: 'none' }}>
              Đăng nhập
            </Link>
          )}
        </div>
      </header>

      {/* Slide 0: Hero Section */}
      <section id="slide-0" className="nora-slide">
        <div className="nora-hero-content">
          <div className="nora-hero-kicker"><span>Nora COIN Workspace</span></div>
          <h1 className="nora-hero-title">
            Kiểm chứng chiến lược<br />
            <span className="nora-hero-title-grad">trên dữ liệu thị trường thật</span>
          </h1>
          <p className="nora-hero-subtitle">
            Hệ thống backtest định lượng, đánh giá độ bền ngoài mẫu Walk-Forward, Monte Carlo và quản trị rủi ro danh mục chuyên nghiệp.
          </p>
          <button type="button" className="n-btn primary nh-start" onClick={() => enterSystem('/coin/portfolio')}>
            Vào Coin Workspace →
          </button>
        </div>
      </section>

      {/* Slide 1: Tính năng cốt lõi COIN */}
      <section id="slide-1" className="nora-slide nh-sec">
        <div className="nh-wrap">
          <div className="nh-head">
            <h2>Tính năng cốt lõi</h2>
            <p>Không gian làm việc chuyên sâu cho giao dịch định lượng & kiểm định danh mục.</p>
          </div>
          <div className="nh-choose">
            <div className="nh-choice nh-coin" style={{ gridColumn: 'span 2' }}>
              <div className="nh-ico">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" style={{ width: 32, height: 32, color: 'var(--n-accent)' }}>
                  <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="3.5" width="7" height="7" rx="1.5" /><rect x="3.5" y="13.5" width="7" height="7" rx="1.5" /><rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
                </svg>
              </div>
              <h3>Hệ thống Định lượng & Danh mục COIN</h3>
              <p className="nh-tag">Đầy đủ công cụ từ nghiên cứu ý tưởng đến kiểm định bền vững.</p>
              <ul>
                <li><strong>Quản lý danh mục & KPI:</strong> Theo dõi NAV, Sharpe, Sortino, Calmar, Max Drawdown và chỉ báo Regime có dấu.</li>
                <li><strong>Kiểm định đa tầng:</strong> Backtest trên dữ liệu thật, Scan Universe, Walk-Forward Analysis và Monte Carlo 10,000 kịch bản.</li>
                <li><strong>Nghiên cứu Alpha:</strong> Phát triển ý tưởng, xây dựng giả thuyết thị trường có thể kiểm chứng độc lập.</li>
                <li><strong>Vận hành Paper / Testnet:</strong> Kiểm soát rủi ro đa tài sản, cầu chì sụt giảm vốn và nút ngắt khẩn cấp.</li>
              </ul>
              <button type="button" onClick={() => enterSystem('/coin/portfolio')} className="nora-btn-cta">
                <span>Vào Coin Workspace →</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* Slide 2: Quy trình định lượng 5 bước */}
      <section id="slide-2" className="nora-slide nh-sec">
        <div className="nh-wrap nh-wide">
          <div className="nh-head">
            <h2>Quy trình kiểm chứng định lượng</h2>
            <p>Từ ý tưởng ban đầu đến vận hành danh mục thực tế — mọi bước đều có bằng chứng.</p>
          </div>
          <ol className="nh-flow">
            {FLOW.map((f) => (
              <li key={f.t} className="nh-step">
                <div className="nh-sico">{f.i}</div>
                <strong>{f.t}</strong>
                <span>{f.s}</span>
              </li>
            ))}
          </ol>
          <div className="nh-stats">
            <Stat v={loading ? <Spinner /> : fmtVal(coin?.system_strategies)} l="chiến lược hệ thống" />
            <Stat v={loading ? <Spinner /> : fmtVal(coin?.symbols)} l="tài sản perp" />
            <Stat v={loading ? <Spinner /> : fmtVal(coin?.data_end)} l="dữ liệu nến cập nhật đến" small />
          </div>
        </div>
      </section>

      {/* Slide 3: Khởi đầu */}
      <section id="slide-3" className="nora-slide nh-sec">
        <div className="nh-wrap nh-wide">
          <div className="nh-head">
            <h2>Sẵn sàng bắt đầu</h2>
            <p>Truy cập bảng điều khiển danh mục và kiểm chứng chiến lược của bạn ngay bây giờ.</p>
          </div>
          <div style={{ textAlign: 'center', marginTop: 32 }}>
            <button
              type="button"
              onClick={() => enterSystem('/coin/portfolio')}
              className="n-btn primary nh-start"
              style={{ textDecoration: 'none', display: 'inline-block' }}
            >
              Vào Bảng điều khiển COIN →
            </button>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer style={{
        position: 'relative',
        zIndex: 1,
        padding: '24px 32px',
        textAlign: 'center',
        fontSize: 12,
        color: 'var(--text-secondary)',
        borderTop: '1px solid var(--border-color)',
        background: 'var(--header-bg)',
      }}>
        Nora COIN · 2026 · Nền tảng kiểm chứng chiến lược định lượng trên dữ liệu thật
      </footer>
    </div>
  )
}
