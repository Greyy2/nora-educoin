import React, { useId } from 'react'
const fmtCount = (n) => (Number.isFinite(n) ? n.toLocaleString('en-US') : '—')

/** Phân trang theo offset/limit. */
export default function Pager({ total, offset, limit, onChange, sizes = [25, 50, 100] }) {
  const id = useId()
  const from = total ? offset + 1 : 0
  const to = Math.min(total, offset + limit)
  return (
    <div className="n-pager" role="navigation" aria-label="Phân trang">
      <span className="mono">{fmtCount(from)}–{fmtCount(to)} / {fmtCount(total)}</span>
      <span className="sp" />
      <label className="n-lbl" htmlFor={id}>Số dòng</label>
      <select id={id} className="n-sel" style={{ width: 70 }} value={limit} onChange={(e) => onChange({ offset: 0, limit: Number(e.target.value) })}>
        {sizes.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <button type="button" className="n-btn sm" disabled={offset <= 0} onClick={() => onChange({ offset: Math.max(0, offset - limit), limit })}>← Trước</button>
      <button type="button" className="n-btn sm" disabled={offset + limit >= total} onClick={() => onChange({ offset: offset + limit, limit })}>Sau →</button>
    </div>
  )
}
