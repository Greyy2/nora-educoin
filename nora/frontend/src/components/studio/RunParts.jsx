import React from 'react'
import { Status } from '../ui'
import { normWarnings } from '../../lib/customResult'
import { isNum, toMs, fmtDuration } from '../../lib/format'

// Phần giao diện dùng chung của /alpha/create và /education (thanh chạy / lưu, dòng job, kết quả biên dịch).
const label = (x) => (typeof x === 'string' ? x : x?.side || x?.name || x?.id || JSON.stringify(x))

export const ICON = {
  gear: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>,
  save: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4h11l3 3v13H5z" /><path d="M8 4v5h7V4M8 20v-6h8v6" /></svg>,
  copy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>,
  play: <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d="M7 5l12 7-12 7z" /></svg>,
}

export function JobLine({ job, onClear, savedId }) {
  const t0 = toMs(job?.started) || toMs(job?.created)
  const t1 = toMs(job?.finished)
  const lines = job?.log_tail || []
  return (
    <span className="se-jobline">
      <Status tone="ok">Hoàn tất</Status>
      <span className="mono muted" title="Mã job (chạy tạm, tự xoá sau 24 giờ nếu không lưu)">{job?.job_id || job?.id}</span>
      {t0 && t1 && <span className="muted">{fmtDuration((t1 - t0) / 1000)}</span>}
      {lines.length > 0 && <details className="se-logd"><summary>Log</summary><pre className="mono">{lines.join('\n')}</pre></details>}
      {savedId && <Status tone="ok">Đã lưu {savedId}</Status>}
      <button type="button" className="se-link" onClick={onClear}>Bỏ kết quả</button>
    </span>
  )
}

export function StoredLine({ rec }) {
  return (
    <span className="se-jobline">
      <Status tone="ok">Đã lưu</Status>
      <span className="mono muted" title="Mã alpha">{rec.id}</span>
      <span className="muted" title="Kết quả đã lưu cùng bản ghi, không chạy lại">{rec.updated_at ? String(rec.updated_at).slice(0, 10) : ''}</span>
    </span>
  )
}

export function CompileOutput({ c, stale }) {
  if (!c) return <p className="n-note se-out">Bấm “Kiểm tra” để biên dịch code và xem tóm tắt (khung thời gian, chỉ báo, chân lệnh, cảnh báo) mà không chạy backtest.</p>
  const warns = normWarnings(c.warnings)
  const m = c.meta || {}
  const list = (v) => (Array.isArray(v) ? v : []).map(label)
  return (
    <div className="se-out" aria-live="polite">
      {stale && <p className="n-note">Code đã sửa sau lần kiểm tra này.</p>}
      {c.ok ? (
        <>
          <div className="se-meta">
            <Status tone="ok">Hợp lệ</Status>
            {m.timeframe && <span>Khung <b className="mono">{m.timeframe}</b></span>}
            {isNum(m.warmup_bars) && <span>Khởi động <b className="mono">{m.warmup_bars}</b> nến</span>}
            {isNum(m.position_levels) && <span>Mức vị thế <b className="mono">{m.position_levels}</b></span>}
            {c.hash && <span className="mono muted" title="Mã băm chương trình">{String(c.hash).slice(0, 12)}</span>}
          </div>
          {list(m.legs).length > 0 && <div className="se-meta"><span className="n-lbl">Chân lệnh</span>{list(m.legs).map((l) => <span key={l} className={`n-badge ${l.toLowerCase()}`}>{l}</span>)}</div>}
          {list(m.features).length > 0 && <div className="se-meta"><span className="n-lbl">Chỉ báo</span>{list(m.features).map((f) => <span key={f} className="n-badge">{f}</span>)}</div>}
        </>
      ) : (
        <div className="n-err" role="alert">
          <b>Lỗi biên dịch{c.error?.line ? ` · dòng ${c.error.line}${c.error.col ? `, cột ${c.error.col}` : ''}` : ''}</b>
          <div className="mono se-errmsg">{c.error?.message || 'Không rõ nguyên nhân.'}</div>
        </div>
      )}
      {warns.length > 0 && (
        <ul className="n-events">{warns.map((w, i) => <li key={i}><span className="ic warn" role="img" aria-label="Cảnh báo">▲</span><span className="tx">{w}</span></li>)}</ul>
      )}
    </div>
  )
}
