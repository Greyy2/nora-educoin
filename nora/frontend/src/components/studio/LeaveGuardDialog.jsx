import React, { useState } from 'react'
import '../../styles/pushToAlpha.css'

/**
 * Hộp thoại khi người dùng định rời trang còn thay đổi chưa lưu (blocker từ hooks/useUnsavedGuard).
 *   dirtyNames : tên các bản nháp chưa lưu
 *   canSave    : có thể lưu ngay bản nháp đang mở (đã có kết quả chạy xong của code hiện tại) và là bản duy nhất chưa lưu
 *   onSave     : () => Promise — lưu bản nháp đang mở; thành công thì tiếp tục rời đi
 */
export default function LeaveGuardDialog({ blocker, dirtyNames = [], canSave = false, onSave }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  if (!blocker || blocker.state !== 'blocked') return null
  const saveAndLeave = async () => {
    setBusy(true); setErr('')
    try { await onSave(); blocker.proceed() } catch (e) { setErr(e?.message || 'Không lưu được') } finally { setBusy(false) }
  }
  return (
    <div className="n-modal-backdrop" role="presentation">
      <div className="n-modal-content push-alpha-modal" role="alertdialog" aria-modal="true" aria-labelledby="leave-t" style={{ maxWidth: 480 }}>
        <header className="push-alpha-header">
          <div>
            <div className="push-alpha-kicker">Chưa lưu</div>
            <h2 className="push-alpha-title" id="leave-t">Bạn có thay đổi chưa lưu</h2>
          </div>
        </header>
        <div className="push-alpha-body">
          <p style={{ margin: 0, fontSize: 13 }}>
            Code và kết quả chạy ở đây chỉ là tạm thời, chỉ lưu trong trình duyệt lúc này. Nếu rời đi, chúng sẽ <b>mất</b>
            {dirtyNames.length ? <>: <b>{dirtyNames.join(', ')}</b></> : ''}.
          </p>
          {!canSave && <p className="n-note" style={{ margin: 0 }}>Muốn giữ lại: ở lại, chạy backtest cho đúng code hiện tại rồi bấm “Lưu chiến lược”.</p>}
          {err && <div className="push-alpha-err">⚠ {err}</div>}
          <footer className="push-alpha-footer">
            <button type="button" className="n-btn brand" onClick={() => blocker.reset()} disabled={busy}>Ở lại</button>
            {canSave && <button type="button" className="n-btn" onClick={saveAndLeave} disabled={busy}>{busy ? 'Đang lưu…' : 'Lưu rồi rời'}</button>}
            <button type="button" className="n-btn" onClick={() => blocker.proceed()} disabled={busy}>Rời không lưu</button>
          </footer>
        </div>
      </div>
    </div>
  )
}
