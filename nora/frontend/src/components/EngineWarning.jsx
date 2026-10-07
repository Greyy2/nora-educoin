import React from 'react'
import useAsync from '../hooks/useAsync'
import { getAlphas } from '../api'
import { fmtDateTime } from '../lib/format'

/** Cảnh báo "cần dựng lại" của một sổ (P9.15): `status` = engine.main | engine.explore do API /api/studio/alphas trả (backend so hash mã engine).
 *  Không tự so sánh gì ở trình duyệt; chỉ hiển thị needs_rebuild + lý do backend nêu. needs_rebuild null/false -> không hiện. */
export default function EngineWarning({ status, label }) {
  if (!status || status.needs_rebuild !== true) return null
  return (
    <div className="n-warnbox" role="alert">
      <b>⚠ Cần dựng lại sổ {label}.</b> {status.reason}.{' '}
      <span className="muted">Số trong sổ (lãi, MDD, bằng chứng) có thể không còn khớp engine hiện hành; chạy lại dựng sổ rồi xuất bản.
        {status.current?.commit ? ` Engine hiện hành: commit ${status.current.commit}${status.current.dirty ? ' (có sửa đổi chưa commit)' : ''}.` : ''}</span>
    </div>
  )
}

export function EngineStamp({ book }) {
  const v = book?.engine_version
  if (!v) return null
  return <p className="n-note">Dựng bằng engine: commit {v.commit || '?'}{v.dirty ? ' (có sửa đổi chưa commit)' : ''} · hash {String(v.hash || '').slice(0, 8)}{book.generated_at ? ` · ${fmtDateTime(book.generated_at)}` : ''}</p>
}

/** Cảnh báo cho trang thư viện alpha: số thống kê của thẻ alpha lấy từ sổ main/explore, nên sổ dựng bằng engine cũ thì phải cảnh báo ở đây.
 *  Tự gọi /api/studio/alphas (kèm engine.*); lỗi tải thì im lặng (trang chính đã có trạng thái lỗi riêng). */
export function CatalogEngineWarning() {
  const q = useAsync(() => getAlphas(), [])
  const e = q.data?.engine
  if (!e) return null
  return (
    <>
      <EngineWarning status={e.main} label="chính (book.json) — thống kê alpha bên dưới lấy từ sổ này" />
      <EngineWarning status={e.explore} label="thử nghiệm (explore/book.json)" />
    </>
  )
}
