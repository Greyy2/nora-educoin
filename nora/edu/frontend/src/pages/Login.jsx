import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import EnterForm from '../components/user/EnterForm'
import { useUser } from '../meta/UserProvider'
import { socialLogin } from '../api'
import '../styles/home.css'

const THEME_KEY = 'nora-theme'
const GOOGLE_CLIENT_ID = '214794961821-upa51khm7tkh28r4241ar2mf39b9teh9.apps.googleusercontent.com'

export default function Login() {
  const { me, refresh } = useUser()
  const navigate = useNavigate()
  const location = useLocation()
  const from = location.state?.from || '/market'

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

  const [googleMsg, setGoogleMsg] = useState(null)
  const [googleLoading, setGoogleLoading] = useState(false)

  const initGoogleSignIn = () => {
    if (!window.google?.accounts?.id) return
    try {
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async (resp) => {
          if (resp?.credential) {
            try {
              setGoogleLoading(true)
              setGoogleMsg('Đang xác thực tài khoản Google...')
              const res = await socialLogin(resp.credential, 'google')
              if (res?.user) {
                setGoogleMsg('Đăng nhập thành công! Đang chuyển hướng...')
                await refresh()
                navigate(from, { replace: true })
              }
            } catch (err) {
              setGoogleMsg(err.message || 'Xác thực Google thất bại. Vui lòng thử lại.')
            } finally {
              setGoogleLoading(false)
            }
          }
        },
        auto_select: false,
      })

      const container = document.getElementById('g_btn_hidden')
      if (container) {
        container.innerHTML = ''
        window.google.accounts.id.renderButton(container, {
          type: 'standard',
          theme: theme === 'dark' ? 'filled_black' : 'outline',
          size: 'large',
          width: 320,
          text: 'signin_with',
          locale: 'vi',
        })
      }
    } catch (e) {
      console.warn('Google Init error:', e)
    }
  }

  useEffect(() => {
    if (!window.google?.accounts?.id) {
      const script = document.createElement('script')
      script.src = 'https://accounts.google.com/gsi/client'
      script.async = true
      script.defer = true
      script.onload = () => {
        initGoogleSignIn()
      }
      document.body.appendChild(script)
    } else {
      initGoogleSignIn()
    }
  }, [theme])

  const handleGoogleSignIn = () => {
    setGoogleMsg(null)
    const hiddenBtn = document.querySelector('#g_btn_hidden div[role=button]')
    if (hiddenBtn) {
      hiddenBtn.click()
    } else if (window.google?.accounts?.id) {
      window.google.accounts.id.prompt((notification) => {
        if (notification.isNotDisplayed()) {
          setGoogleMsg('Vui lòng kiểm tra cho phép popup hoặc đăng nhập bằng tài khoản bên dưới.')
        }
      })
    } else {
      setGoogleMsg('Đang tải thư viện Google, vui lòng thử lại sau giây lát...')
    }
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

      {/* Header tối giản EDU: Logo bên trái, Điều khiển bên phải */}
      <header className="nora-home-header">
        <Link to="/" className="nora-home-logo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" style={{ width: 20, height: 20, color: 'var(--text-primary)' }}>
            <path d="M2 9l10-5 10 5-10 5z" /><path d="M6 11.5V16c3 2 9 2 12 0v-4.5" />
          </svg>
          <span style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>Nora EDU</span>
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

      {/* Giao diện đăng nhập EDU */}
      <div className="login-split-container">
        {/* LEFT SIDE: Branding & info */}
        <div className="login-left-panel">
          <div className="branding-content">
            <h1 className="brand-title">
              Nora <span className="brand-highlight">Education</span>
            </h1>

            <div className="feature-list">
              <div className="feature-item">
                <div className="feature-bullet">
                  <span className="bullet-circle" />
                </div>
                <div className="feature-text">
                  <h3>Học Viết Chiến Lược DSL</h3>
                  <p>Lộ trình 5 module từ cơ bản đến nâng cao, cú pháp tiếng Việt/Python trực quan</p>
                </div>
              </div>

              <div className="feature-item">
                <div className="feature-bullet">
                  <span className="bullet-circle" />
                </div>
                <div className="feature-text">
                  <h3>Kiểm Thử Miễn Phí & Trực Quan</h3>
                  <p>Chạy backtest trên dữ liệu thật với biểu đồ tín hiệu, học tập an toàn không rủi ro</p>
                </div>
              </div>

              <div className="feature-item">
                <div className="feature-bullet">
                  <span className="bullet-circle" />
                </div>
                <div className="feature-text">
                  <h3>Cộng Đồng & Sàn Market</h3>
                  <p>Khám phá, sao chép (fork) và thử nghiệm ý tưởng mới cùng cộng đồng học viên</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* RIGHT SIDE: Form card */}
        <div className="login-right-panel">
          <div className="login-form-container">
            <div className="form-header">
              <h2>Đăng nhập</h2>
              <p>Đăng nhập để bảo vệ, quản lý và khôi phục các chiến lược định lượng của bạn.</p>
            </div>

            {/* Nút Đăng nhập với Google */}
            <div style={{ marginBottom: 16 }}>
              <div id="g_btn_hidden" style={{ display: 'none' }} />
              <button
                type="button"
                onClick={handleGoogleSignIn}
                disabled={googleLoading}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '10px',
                  padding: '10px 16px',
                  borderRadius: '8px',
                  border: '1px solid var(--n-line-soft, rgba(255, 255, 255, 0.15))',
                  background: 'var(--n-surface-2, rgba(255, 255, 255, 0.05))',
                  color: 'var(--text-primary, #ffffff)',
                  fontSize: '13px',
                  fontWeight: 600,
                  cursor: googleLoading ? 'wait' : 'pointer',
                  opacity: googleLoading ? 0.7 : 1,
                  transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                  boxShadow: '0 1px 2px rgba(0, 0, 0, 0.05)',
                }}
                onMouseEnter={(e) => {
                  if (!googleLoading) {
                    e.currentTarget.style.background = 'var(--n-surface-hover, rgba(255, 255, 255, 0.1))'
                    e.currentTarget.style.borderColor = 'var(--n-accent, #6366f1)'
                    e.currentTarget.style.transform = 'translateY(-1px)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!googleLoading) {
                    e.currentTarget.style.background = 'var(--n-surface-2, rgba(255, 255, 255, 0.05))'
                    e.currentTarget.style.borderColor = 'var(--n-line-soft, rgba(255, 255, 255, 0.15))'
                    e.currentTarget.style.transform = 'translateY(0)'
                  }
                }}
              >
                <svg width="18" height="18" viewBox="0 0 48 48" style={{ flexShrink: 0 }}>
                  <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                  <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                  <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                  <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
                  <path fill="none" d="M0 0h48v48H0z"/>
                </svg>
                <span>{googleLoading ? 'Đang kết nối Google...' : 'Đăng nhập với Google'}</span>
              </button>

              {googleMsg && (
                <div style={{ marginTop: 8, padding: '8px 12px', borderRadius: 6, fontSize: 12, background: 'rgba(99, 102, 241, 0.12)', color: 'var(--n-accent, #6366f1)', border: '1px solid rgba(99, 102, 241, 0.25)', textAlign: 'center' }}>
                  {googleMsg}
                </div>
              )}


              <div style={{ display: 'flex', alignItems: 'center', margin: '16px 0 12px', color: 'var(--n-ink-2, #94a3b8)', fontSize: 12 }}>
                <div style={{ flex: 1, height: '1px', background: 'var(--n-line-soft, rgba(255, 255, 255, 0.12))' }} />
                <span style={{ padding: '0 12px', textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: 11, fontWeight: 600 }}>Hoặc</span>
                <div style={{ flex: 1, height: '1px', background: 'var(--n-line-soft, rgba(255, 255, 255, 0.12))' }} />
              </div>
            </div>

            <EnterForm onDone={() => navigate(from, { replace: true })} />
          </div>
        </div>
      </div>
    </div>
  )
}
