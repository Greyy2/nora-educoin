import React, { useEffect, useState } from 'react'
import { getUsers } from '../../api'
import { useUser } from '../../meta/UserProvider'
import { Spinner } from '../ui'

/** Form một ô: nhập tên rồi bấm "Vào"; bên dưới là danh sách người dùng có sẵn để bấm chọn. */
export default function EnterForm({ onDone, autoFocus = true }) {
  const { me, enter } = useUser()
  const [name, setName] = useState('')
  const [users, setUsers] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    getUsers().then((d) => { if (alive) setUsers(Array.isArray(d) ? d : []) }).catch(() => {})
    return () => { alive = false }
  }, [])

  const go = async (value) => {
    const clean = (value || '').trim()
    if (!clean) { setError('Vui lòng nhập tên của bạn.'); return }
    setBusy(true)
    setError(null)
    try {
      const u = await enter(clean)
      if (onDone) onDone(u)
    } catch (err) {
      setError(err?.message || 'Không vào được, thử lại nhé.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="n-enter">
      <form onSubmit={(e) => { e.preventDefault(); go(name) }} className="n-enter-form">
        <label htmlFor="n-enter-name" className="n-enter-lbl">Tên của bạn</label>
        <div className="n-enter-row">
          <input
            id="n-enter-name"
            className="n-enter-in"
            type="text"
            value={name}
            maxLength={40}
            autoFocus={autoFocus}
            autoComplete="off"
            placeholder="vd: Nguyễn Văn A"
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="n-btn primary" disabled={busy || !name.trim()}>
            {busy ? <Spinner /> : 'Vào'}
          </button>
        </div>
      </form>
      {error && <div className="n-err" style={{ marginTop: 10, fontSize: 13 }}>{error}</div>}
      {users.length > 0 && (
        <div className="n-enter-list">
          <div className="n-enter-sub">Hoặc chọn nhanh</div>
          <div className="n-enter-chips">
            {users.map((u) => (
              <button
                key={u.id || u.handle}
                type="button"
                className={`n-enter-chip${me && me.id === u.id ? ' on' : ''}`}
                disabled={busy}
                onClick={() => go(u.display_name)}
              >
                <span className="n-enter-av" style={{ background: u.avatar?.color || 'var(--n-accent)' }}>{u.avatar?.emoji || '👤'}</span>
                <span className="n-enter-nm">{u.display_name}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
