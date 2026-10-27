import React, { useState } from 'react'
import { useUser } from '../../meta/UserProvider'
import { Spinner } from '../ui'

/** Form xác thực người dùng: Đăng nhập (Tên + Password) / Đăng ký tài khoản (Tên + Password). */
export default function EnterForm({ onDone, autoFocus = true }) {
  const [tab, setTab] = useState('login') // 'login' | 'register'
  const [loginName, setLoginName] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [regName, setRegName] = useState('')
  const [regPassword, setRegPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const { login, create } = useUser()

  const handleLogin = async (e) => {
    e.preventDefault()
    const cleanName = loginName.trim()
    if (!cleanName) { setError('Vui lòng nhập tên đăng nhập.'); return }
    const cleanPw = loginPassword.trim()
    if (!cleanPw) { setError('Vui lòng nhập mật khẩu.'); return }
    setBusy(true)
    setError(null)
    try {
      const u = await login(cleanName, cleanPw)
      if (onDone) onDone(u)
    } catch (err) {
      setError(err?.message || 'Tài khoản hoặc mật khẩu không chính xác.')
    } finally {
      setBusy(false)
    }
  }

  const handleRegister = async (e) => {
    e.preventDefault()
    const cleanName = regName.trim()
    if (!cleanName) { setError('Vui lòng nhập tên của bạn.'); return }
    if (cleanName.length < 1 || cleanName.length > 40) {
      setError('Tên phải từ 1 đến 40 ký tự.')
      return
    }
    const cleanPw = regPassword.trim()
    if (!cleanPw) { setError('Vui lòng nhập mật khẩu.'); return }
    setBusy(true)
    setError(null)
    try {
      const u = await create({
        name: cleanName,
        password: cleanPw,
      })
      if (onDone) onDone(u)
    } catch (err) {
      const msg = err?.message || ''
      if (msg.includes('đã tồn tại')) {
        setError(`Tên "${cleanName}" đã tồn tại trong hệ thống. Vui lòng chọn tên khác hoặc chuyển sang Đăng nhập.`)
      } else {
        setError(msg || 'Không thể tạo tài khoản, vui lòng thử lại.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="n-enter-card" style={{ width: '100%' }}>
      {/* Tab Switcher */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 18, borderBottom: '1px solid var(--n-line-soft)', paddingBottom: 6 }}>
        <button
          type="button"
          onClick={() => { setTab('login'); setError(null) }}
          style={{
            flex: 1,
            padding: '8px 12px',
            background: tab === 'login' ? 'var(--n-surface-2, rgba(255,255,255,0.06))' : 'transparent',
            border: 'none',
            borderRadius: 6,
            fontWeight: tab === 'login' ? 700 : 500,
            color: tab === 'login' ? 'var(--n-ink)' : 'var(--n-ink-2)',
            cursor: 'pointer',
            fontSize: 13,
            borderBottom: tab === 'login' ? '2px solid var(--n-accent, #6366f1)' : '2px solid transparent',
          }}
        >
          Đăng nhập
        </button>
        <button
          type="button"
          onClick={() => { setTab('register'); setError(null) }}
          style={{
            flex: 1,
            padding: '8px 12px',
            background: tab === 'register' ? 'var(--n-surface-2, rgba(255,255,255,0.06))' : 'transparent',
            border: 'none',
            borderRadius: 6,
            fontWeight: tab === 'register' ? 700 : 500,
            color: tab === 'register' ? 'var(--n-ink)' : 'var(--n-ink-2)',
            cursor: 'pointer',
            fontSize: 13,
            borderBottom: tab === 'register' ? '2px solid var(--n-accent, #6366f1)' : '2px solid transparent',
          }}
        >
          Đăng ký tài khoản
        </button>
      </div>

      {tab === 'login' && (
        <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label htmlFor="coin-auth-handle" style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--n-ink-2)' }}>
              Tên đăng nhập
            </label>
            <input
              id="coin-auth-handle"
              className="n-in"
              type="text"
              value={loginName}
              maxLength={40}
              autoFocus={autoFocus}
              autoComplete="username"
              placeholder="Ví dụ: vinh"
              disabled={busy}
              onChange={(e) => setLoginName(e.target.value)}
              style={{ width: '100%', padding: '9px 12px', fontSize: 13, borderRadius: 6 }}
            />
          </div>

          <div>
            <label htmlFor="coin-auth-pwd" style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--n-ink-2)' }}>
              Mật khẩu
            </label>
            <input
              id="coin-auth-pwd"
              className="n-in"
              type="password"
              value={loginPassword}
              autoComplete="current-password"
              placeholder="Nhập mật khẩu"
              disabled={busy}
              onChange={(e) => setLoginPassword(e.target.value)}
              style={{ width: '100%', padding: '9px 12px', fontSize: 13, borderRadius: 6 }}
            />
          </div>

          <button
            type="submit"
            className="n-btn primary"
            disabled={busy || !loginName.trim()}
            style={{ width: '100%', padding: '10px 0', marginTop: 4, fontSize: 14, fontWeight: 600 }}
          >
            {busy ? <Spinner /> : 'Đăng nhập'}
          </button>
        </form>
      )}

      {tab === 'register' && (
        <form onSubmit={handleRegister} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <label htmlFor="coin-reg-name" style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--n-ink-2)' }}>
              Tên của bạn <span style={{ fontWeight: 400, opacity: 0.8 }}>(kiêm tên đăng nhập)</span>
            </label>
            <input
              id="coin-reg-name"
              className="n-in"
              type="text"
              value={regName}
              maxLength={40}
              autoFocus={autoFocus}
              autoComplete="username"
              placeholder="Ví dụ: vinh"
              disabled={busy}
              onChange={(e) => setRegName(e.target.value)}
              style={{ width: '100%', padding: '9px 12px', fontSize: 13, borderRadius: 6 }}
            />
            <span style={{ fontSize: 11, color: 'var(--n-ink-2)', marginTop: 4, display: 'block' }}>
              Tên này sẽ hiển thị trên hệ thống và dùng trực tiếp để đăng nhập.
            </span>
          </div>

          <div>
            <label htmlFor="coin-reg-pwd" style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4, color: 'var(--n-ink-2)' }}>
              Mật khẩu
            </label>
            <input
              id="coin-reg-pwd"
              className="n-in"
              type="password"
              value={regPassword}
              autoComplete="new-password"
              placeholder="Nhập mật khẩu (tối thiểu 1 ký tự)"
              disabled={busy}
              onChange={(e) => setRegPassword(e.target.value)}
              style={{ width: '100%', padding: '9px 12px', fontSize: 13, borderRadius: 6 }}
            />
          </div>

          <button
            type="submit"
            className="n-btn primary"
            disabled={busy || !regName.trim()}
            style={{ width: '100%', padding: '10px 0', marginTop: 4, fontSize: 14, fontWeight: 600 }}
          >
            {busy ? <Spinner /> : 'Tạo tài khoản & Đăng nhập'}
          </button>
        </form>
      )}

      {error && (
        <div className="n-err" style={{ marginTop: 12, padding: '8px 12px', borderRadius: 6, fontSize: 13 }}>
          {error}
        </div>
      )}
    </div>
  )
}
