import React, { useState } from 'react'
import useAsync from '../../hooks/useAsync'
import { getLiveBot } from '../../api'
import { useMeta } from '../../meta/MetaProvider'
import { invalidateResource } from '../../lib/bus'
import { fmtDateTime } from '../../lib/format'
import { Spinner } from '../ui'

/** Cảnh báo "cần dựng lại" của một sổ (P9.15, Bước 5):
 *  Đọc meta.books.{main,explore}, hiện reason, nút bấm gọi fix.endpoint với fix.body,
 *  cảnh báo nếu bot live đang chạy dùng sổ đó.
 */
export default function EngineWarning({ status, label, bookKey }) {
  const meta = useMeta()
  const st = status || (bookKey ? meta?.books?.[bookKey] : null)
  const botQ = useAsync(getLiveBot, [])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  if (!st || st.needs_rebuild !== true) return null

  const isBotRunning = botQ.data?.running && (botQ.data?.state?.book_kind === (bookKey || 'main') || botQ.data?.book === (bookKey || 'main'))

  const handleFix = async () => {
    if (!st.fix?.endpoint) return
    if (isBotRunning) {
      const ok = window.confirm(`Bot live đang chạy sử dụng sổ ${label || bookKey || 'này'}. Bạn có chắc chắn muốn dựng lại không?`)
      if (!ok) return
    }
    setBusy(true)
    setErr('')
    setMsg('')
    try {
      const res = await fetch(st.fix.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: st.fix.body ? JSON.stringify(st.fix.body) : undefined,
      })
      if (!res.ok) {
        const j = await res.json().catch(() => ({}))
        throw new Error(j.detail || j.message || `Lỗi ${res.status}`)
      }
      setMsg('Đã khởi chạy tác vụ dựng lại sổ thành công!')
      invalidateResource('meta')
      invalidateResource('catalog')
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="n-warnbox" role="alert" style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <b>⚠ Cần dựng lại sổ {label || bookKey || ''}.</b> {st.reason}.{' '}
          <span className="muted">
            Số trong sổ có thể không còn khớp engine hiện hành ({st.current?.commit ? `commit ${st.current.commit}` : 'hiện tại'}).
          </span>
          {isBotRunning && (
            <div style={{ color: 'var(--n-neg, #ef4444)', marginTop: 4, fontWeight: 500 }}>
              ⚠ Cảnh báo: Bot live đang chạy dùng sổ này!
            </div>
          )}
          {msg && <div style={{ color: 'var(--n-pos, #10b981)', marginTop: 4 }}>✓ {msg}</div>}
          {err && <div style={{ color: 'var(--n-neg, #ef4444)', marginTop: 4 }}>✗ {err}</div>}
        </div>
        {st.fix && (
          <button
            type="button"
            className="n-btn sm primary"
            disabled={busy}
            onClick={handleFix}
            style={{ whiteSpace: 'nowrap' }}
          >
            {busy ? <Spinner /> : null} Dựng lại sổ
          </button>
        )}
      </div>
    </div>
  )
}

export function EngineStamp({ book }) {
  const v = book?.engine_version
  if (!v) return null
  return <p className="n-note">Dựng bằng engine: commit {v.commit || '?'}{v.dirty ? ' (có sửa đổi chưa commit)' : ''} · hash {String(v.hash || '').slice(0, 8)}{book.generated_at ? ` · ${fmtDateTime(book.generated_at)}` : ''}</p>
}

/** Cảnh báo cho trang thư viện alpha: số thống kê của thẻ alpha lấy từ sổ main/explore, nên sổ dựng bằng engine cũ thì phải cảnh báo ở đây. */
export function CatalogEngineWarning() {
  const meta = useMeta()
  const books = meta?.books
  if (!books) return null
  return (
    <>
      <EngineWarning status={books.main} bookKey="main" label="chính (book.json) — thống kê alpha bên dưới lấy từ sổ này" />
      <EngineWarning status={books.explore} bookKey="explore" label="thử nghiệm (explore/book.json)" />
    </>
  )
}
