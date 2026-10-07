import React from 'react'
import { fmtNum, isNum } from '../../lib/format'
import '../../styles/diagnostics.css'

const stamp = (s) => (typeof s === 'string' && s.length >= 16 ? `${s.slice(0, 10)} ${s.slice(11, 16)} UTC` : s || '—')

/** Ghi chú nguồn của kết quả chạy sẵn: thời điểm, nguồn dữ liệu, cấu hình và cảnh báo của bản ghi. superseded: đã có lần chạy mới thay thế. */
export default function PrecomputedNote({ record, superseded = false }) {
  if (!record) return null
  const cfg = record.config || {}
  const warns = (Array.isArray(record.warnings) ? record.warnings : []).map((w) => (typeof w === 'string' ? w : w?.message || JSON.stringify(w)))
  const nSym = Array.isArray(cfg.symbols) ? cfg.symbols.length : null
  return (
    <div className={`dg-pre ${superseded ? 'stale' : ''}`}>
      <span><b>Kết quả chạy sẵn</b> · {stamp(record.generated_at)} · dữ liệu {record.data?.source || '—'}</span>
      <span className="muted">
        {[cfg.start && cfg.end && `${cfg.start} → ${cfg.end}`, nSym != null && `${nSym} tài sản`, cfg.run_frame && `khung chạy ${cfg.run_frame}`, isNum(cfg.initial_capital) && `vốn ${fmtNum(cfg.initial_capital, 0)}`].filter(Boolean).join(' · ')}
      </span>
      {superseded && <span style={{ color: 'var(--n-warn)' }}>Đã cũ: đang hiển thị lần chạy mới của bạn.</span>}
      {warns.length > 0 && <ul className="dg-pre-w">{warns.map((w, i) => <li key={i}>▲ {w}</li>)}</ul>}
    </div>
  )
}
