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
  coin: sv(<><circle cx="12" cy="12" r="9" /><path d="M14.5 9.2c-.5-.8-1.4-1.2-2.5-1.2-1.4 0-2.5.7-2.5 1.8 0 2.6 5 1.2 5 3.8 0 1.1-1.1 1.9-2.5 1.9-1.1 0-2.1-.5-2.6-1.4M12 6.5V8M12 16v1.5" /></>),
}
const FLOW = [
  { t: 'Ý tưởng', s: 'Đặt giả thuyết giao dịch', i: sv(<><path d="M9 18h6M10 21h4" /><path d="M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z" /></>) },
  { t: 'Chiến lược', s: 'Viết quy tắc vào và thoát lệnh', i: sv(<><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" /></>) },
  { t: 'Backtest', s: 'Thử trên dữ liệu thật', i: sv(<><path d="M3 3v18h18" /><path d="M7 15l4-4 3 3 5-6" /></>) },
  { t: 'Kiểm định bền vững', s: 'Walk-forward, Monte Carlo', i: sv(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" /></>) },
  { t: 'Chạy thử', s: 'Paper / demo trước khi dùng vốn', soon: true, i: sv(<><circle cx="12" cy="12" r="9" /><path d="M10 8.5l5 3.5-5 3.5z" /></>) },
  { t: 'Vận hành', s: 'Theo dõi và quản lý danh mục', i: sv(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M8 14h3" /></>) },
]
const MODULES = [
  { t: 'Dữ liệu & tư duy định lượng', s: 'Nền tảng để đọc thị trường', tags: ['Nến & khung thời gian', 'Lãi, lỗ & rủi ro', 'Dữ liệu thật đã kiểm định', 'Đọc biểu đồ'] },
  { t: 'Chỉ báo & tín hiệu', s: 'Biến giá thành tín hiệu', tags: ['Xu hướng (EMA, Keltner)', 'Đảo chiều (RSI, Bollinger)', 'Phá vỡ (Donchian)', 'Kết hợp tín hiệu'] },
  { t: 'Viết chiến lược', s: 'Từ ý tưởng đến quy tắc', tags: ['Mẫu hướng dẫn', 'Vào & thoát lệnh', 'Cắt lỗ, chốt lời', 'Quản lý vốn'] },
  { t: 'Kiểm thử & đánh giá', s: 'Biết chiến lược đáng tin đến đâu', tags: ['Backtest', 'Train · Test', 'Sharpe, MDD, Win rate', 'So với mua & giữ'] },
  { t: 'Cộng đồng & thực chiến', s: 'Học cùng nhau, thử thật', tags: ['Market chiến lược', 'Hồ sơ & thành tích', 'Sao chép & cải tiến', 'Chạy thử demo (sắp có)'] },
]
const NAV = [[0, 'Trang chủ'], [1, 'Hệ thống'], [2, 'Education'], [3, 'Coin']]

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

  const enterSystem = (targetPath) => {
    if (typeof window !== 'undefined') {
      const host = window.location.hostname
      if (targetPath.startsWith('/coin') && host.includes('edu.nora.')) {
        window.location.href = window.location.origin.replace('edu.nora.', 'coin.nora.') + targetPath
        return
      }
      if (targetPath.startsWith('/edu') && host.includes('coin.nora.')) {
        window.location.href = window.location.origin.replace('coin.nora.', 'edu.nora.') + targetPath
        return
      }
    }
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

      {/* Header tối giản theo phong cách Claude, các nút dồn sang phải */}
      <header className="nora-home-header">
        <Link to="/" className="nora-home-logo" onClick={() => scrollToSlide(0)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ width: 20, height: 20, color: 'var(--text-primary)' }}>
            <path d="M20 12a8 8 0 1 1-3-6.2" />
            <circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />
          </svg>
          <span style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--text-primary)' }}>Nora</span>
        </Link>

        {/* Các điều khiển được gom và dồn hoàn toàn sang phải */}
        <div className="nora-header-right">
          {NAV.map(([i, lbl]) => (
            <button key={i} type="button" className={`nora-nav-btn ${currentSlide === i ? 'active' : ''}`} onClick={() => scrollToSlide(i)}>
              {lbl}
            </button>
          ))}

          {/* Theme Toggle Button đồng nhất với các tab view */}
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

      <section id="slide-0" className="nora-slide">
        <div className="nora-hero-content">
          <div className="nora-hero-kicker"><span>Nora</span></div>
          <h1 className="nora-hero-title">
            Kiểm chứng chiến lược<br />
            <span className="nora-hero-title-grad">trên dữ liệu thật</span>
          </h1>
          <p className="nora-hero-subtitle">
            Viết ý tưởng giao dịch, thử trên dữ liệu thị trường thật và biết rõ nó bền đến đâu.
          </p>
          <button type="button" className="n-btn primary nh-start" onClick={() => scrollToSlide(1)}>
            Bắt đầu
          </button>
        </div>
      </section>

      <section id="slide-1" className="nora-slide nh-sec">
        <div className="nh-wrap">
          <div className="nh-head">
            <h2>Chọn hệ thống</h2>
            <p>Hai không gian làm việc cho hai mục tiêu khác nhau.</p>
          </div>
          <div className="nh-choose">
            <div className="nh-choice nh-edu">
              <div className="nh-ico">{ICONS.edu}</div>
              <h3>Education</h3>
              <p className="nh-tag">Học giao dịch định lượng bằng cách tự tay làm.</p>
              <ul>
                <li>Lộ trình từ cơ bản đến viết chiến lược hoàn chỉnh</li>
                <li>Mẫu hướng dẫn sẵn để bắt đầu ngay</li>
                <li>Xem kết quả kiểm thử ngay sau khi viết</li>
                <li>Chia sẻ và học hỏi cùng cộng đồng</li>
              </ul>
              <button type="button" onClick={() => enterSystem('/edu')} className="nora-btn-cta">
                <span>Vào Education →</span>
              </button>
            </div>
            <div className="nh-choice nh-coin">
              <div className="nh-ico">{ICONS.coin}</div>
              <h3>Coin</h3>
              <p className="nh-tag">Kiểm thử và đánh giá chiến lược nghiêm túc.</p>
              <ul>
                <li>Kiểm thử trên nhiều tài sản cùng lúc</li>
                <li>Đánh giá độ bền ngoài mẫu, tránh chiến lược chỉ khớp quá khứ</li>
                <li>Lưu lại toàn bộ lịch sử để xem và đối chiếu</li>
                <li>Quản lý danh mục chiến lược tập trung</li>
              </ul>
              <button type="button" onClick={() => enterSystem('/coin/portfolio')} className="nora-btn-cta">
                <span>Vào Coin →</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      <section id="slide-2" className="nora-slide nh-sec">
        <div className="nh-wrap nh-wide">
          <div className="nh-head">
            <h2>Hệ sinh thái Education</h2>
            <p>Lộ trình 5 module, từ đọc dữ liệu đến chia sẻ chiến lược cùng cộng đồng.</p>
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
            <Stat v={loading ? <Spinner /> : fmtVal(edu?.users)} l="người học" />
            <Stat v={loading ? <Spinner /> : fmtVal(edu?.strategies)} l="chiến lược đã viết" />
            <Stat v={loading ? <Spinner /> : fmtVal(edu?.samples_ready)} l="mẫu sẵn sàng" />
          </div>
        </div>
      </section>

      <section id="slide-3" className="nora-slide nh-sec">
        <div className="nh-wrap nh-wide">
          <div className="nh-head">
            <h2>Quy trình Coin</h2>
            <p>Từ ý tưởng đến vận hành, mỗi bước đều có kiểm chứng.</p>
          </div>
          <ol className="nh-flow">
            {FLOW.map((f, i) => (
              <li key={f.t} className="nh-step">
                <div className="nh-sico">{f.i}</div>
                <strong>{f.t}</strong>
                <span>{f.s}</span>
                {f.soon && <em>sắp có</em>}
              </li>
            ))}
          </ol>
          <div className="nh-stats">
            <Stat v={loading ? <Spinner /> : fmtVal(coin?.system_strategies)} l="chiến lược hệ thống" />
            <Stat v={loading ? <Spinner /> : fmtVal(coin?.symbols)} l="tài sản" />
            <Stat v={loading ? <Spinner /> : fmtVal(coin?.data_end)} l="dữ liệu cập nhật đến" small />
          </div>
          <div style={{ marginTop: 32 }}>
            <button
              type="button"
              onClick={() => enterSystem('/coin/portfolio')}
              className="n-btn primary nh-start"
              style={{ textDecoration: 'none', display: 'inline-block' }}
            >
              Vào Coin
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
        Nora · 2026 · Kiểm chứng chiến lược trên dữ liệu thật
      </footer>
    </div>
  )
}
