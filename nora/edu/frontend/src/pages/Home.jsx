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

const ICONS = {
  edu: sv(<><path d="M2 9l10-5 10 5-10 5z" /><path d="M6 11.5V16c3 2 9 2 12 0v-4.5" /></>),
}

const MODULES = [
  { t: 'Dữ liệu & tư duy định lượng', s: 'Nền tảng để đọc thị trường', tags: ['Nến & khung thời gian', 'Lãi, lỗ & rủi ro', 'Dữ liệu thật đã kiểm định', 'Đọc biểu đồ'] },
  { t: 'Chỉ báo & tín hiệu', s: 'Biến giá thành tín hiệu', tags: ['Xu hướng (EMA, Keltner)', 'Đảo chiều (RSI, Bollinger)', 'Phá vỡ (Donchian)', 'Kết hợp tín hiệu'] },
  { t: 'Viết chiến lược', s: 'Từ ý tưởng đến quy tắc', tags: ['Mẫu hướng dẫn', 'Vào & thoát lệnh', 'Cắt lỗ, chốt lời', 'Quản lý vốn'] },
  { t: 'Kiểm thử & đánh giá', s: 'Biết chiến lược đáng tin đến đâu', tags: ['Backtest', 'Train · Test', 'Sharpe, MDD, Win rate', 'So với mua & giữ'] },
  { t: 'Cộng đồng & thực chiến', s: 'Học cùng nhau, thử thật', tags: ['Market chiến lược', 'Hồ sơ & thành tích', 'Sao chép & cải tiến', 'Học tập không rủi ro'] },
]

const NAV = [[0, 'Trang chủ'], [1, 'Lộ trình học'], [2, 'Thực hành Studio']]

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

  const enterSystem = (targetPath = '/market') => {
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

  const edu = summary?.edu
  const fmtVal = (val) => (val !== null && val !== undefined ? val : '—')

  return (
    <div className="nora-home-root">
      {/* Background Animated Gradient Orbs */}
      <div className="nora-hero-bg">
        <div className="nora-orb nora-orb-1" />
        <div className="nora-orb nora-orb-2" />
        <div className="nora-orb nora-orb-3" />
      </div>

      {/* Header tối giản EDU */}
      <header className="nora-home-header">
        <Link to="/" className="nora-home-logo" onClick={() => scrollToSlide(0)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ width: 20, height: 20, color: 'var(--text-primary)' }}>
            <path d="M2 9l10-5 10 5-10 5z" /><path d="M6 11.5V16c3 2 9 2 12 0v-4.5" />
          </svg>
          <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--text-primary)' }}>Nora EDU</span>
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
          <div className="nora-hero-kicker"><span>Nora Education</span></div>
          <h1 className="nora-hero-title">
            Học giao dịch định lượng<br />
            <span className="nora-hero-title-grad">bằng cách tự tay làm</span>
          </h1>
          <p className="nora-hero-subtitle">
            Lộ trình học tập trực quan, mẫu chiến lược có sẵn, thử nghiệm trên dữ liệu thật và chia sẻ cùng cộng đồng học viên.
          </p>
          <button type="button" className="n-btn primary nh-start" onClick={() => enterSystem('/market')}>
            Bắt đầu học ngay →
          </button>
        </div>
      </section>

      {/* Slide 1: Lộ trình 5 Module */}
      <section id="slide-1" className="nora-slide nh-sec">
        <div className="nh-wrap nh-wide">
          <div className="nh-head">
            <h2>Lộ trình 5 Module học tập</h2>
            <p>Từ đọc hiểu dữ liệu đến tự thiết kế chiến lược và kiểm thử không rủi ro.</p>
          </div>
          <ol className="nh-road">
            {MODULES.map((m, i) => (
              <li key={m.t} className={`nh-mod ${i % 2 ? 'alt' : ''}`} style={{ '--k': i }}>
                <ul className="nh-tags top">
                  {m.tags.slice(0, 2).map((t) => <li key={t}>{t}</li>)}
                </ul>
                <div className="nh-chev">
                  <small>MODULE {i + 1}</small>
                  <strong>{m.t}</strong>
                  <span>{m.s}</span>
                </div>
                <ul className="nh-tags bot">
                  {m.tags.slice(2).map((t) => <li key={t}>{t}</li>)}
                </ul>
              </li>
            ))}
          </ol>
          <div className="nh-stats">
            <Stat v={loading ? <Spinner /> : fmtVal(edu?.users)} l="học viên" />
            <Stat v={loading ? <Spinner /> : fmtVal(edu?.strategies)} l="chiến lược đã lưu" />
            <Stat v={loading ? <Spinner /> : fmtVal(edu?.samples_ready)} l="chiến lược mẫu sẵn sàng" />
          </div>
        </div>
      </section>

      {/* Slide 2: Thực hành Studio */}
      <section id="slide-2" className="nora-slide nh-sec">
        <div className="nh-wrap">
          <div className="nh-head">
            <h2>Không gian Thực hành Studio</h2>
            <p>Viết chiến lược bằng ngôn ngữ DSL tự nhiên và chạy kiểm thử tức thì.</p>
          </div>
          <div className="nh-choose">
            <div className="nh-choice nh-edu" style={{ gridColumn: 'span 2' }}>
              <div className="nh-ico">{ICONS.edu}</div>
              <h3>Trình biên soạn & Chạy thử Giáo dục</h3>
              <p className="nh-tag">Môi trường sandbox an toàn, không lo mất vốn hay cấu hình phức tạp.</p>
              <ul>
                <li><strong>Cú pháp dễ tiếp cận:</strong> Viết quy tắc vào/thoát lệnh bằng tiếng Việt hoặc Python DSL trực quan.</li>
                <li><strong>Báo lỗi thông minh:</strong> Chỉ rõ từng dòng, gợi ý chỉnh sửa và hoàn thiện chiến lược.</li>
                <li><strong>Biểu đồ tín hiệu:</strong> Quan sát điểm mua, điểm bán và đường giá đồng bộ.</li>
                <li><strong>Thư viện mẫu:</strong> Bắt đầu từ các chiến lược nổi tiếng: Trend Following, Mean Reversion, Breakout.</li>
              </ul>
              <button type="button" onClick={() => enterSystem('/studio')} className="nora-btn-cta">
                <span>Vào Studio Thực hành →</span>
              </button>
            </div>
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
        Nora EDU · 2026 · Nền tảng học giao dịch định lượng & kiểm chứng chiến lược
      </footer>
    </div>
  )
}
