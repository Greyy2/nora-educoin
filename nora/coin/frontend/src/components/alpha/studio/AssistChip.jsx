import React from 'react'
import { styleLabel } from '../../../lib/assist'

// Chip phán quyết của trợ lý hợp đồng chiến lược: RUN (đúng dạng native) / ADAPT (dạng khác, đã chuẩn hoá tất định) / REJECT (có lỗi, kèm dòng/cột).
// `a` = trạng thái từ CodeEditor.onAssist: { status: idle | checking | unavailable | done, verdict, style, diagnostics, normalized_code, meta }.
const TONE = { RUN: 'ok', ADAPT: 'warn', REJECT: 'bad' }

// onlyErrors (trang soạn chiến lược): chỉ hiện khi REJECT (số lỗi màu đỏ); RUN / ADAPT / đang kiểm tra / chưa kết nối -> không hiện gì.
export default function AssistChip({ a, onApply, onToggle, onlyErrors = false }) {
  if (!a || a.status === 'idle') return null
  if (onlyErrors && !(a.status === 'done' && a.verdict === 'REJECT')) return null
  if (a.status === 'unavailable') return <span className="se-vchip" title="Máy chủ chưa có API trợ lý viết code: vẫn soạn và chạy bình thường"><i className="d" />Trợ lý: chưa kết nối</span>
  if (a.status === 'checking') return <span className="se-vchip"><i className="d" />Đang kiểm tra…</span>
  const diags = a.diagnostics || []
  const errs = diags.filter((d) => d.severity === 'error').length
  const warns = diags.filter((d) => d.severity === 'warning').length
  const tone = TONE[a.verdict] || ''
  const title = a.verdict === 'RUN' ? 'Đúng hợp đồng native: chạy được nguyên văn'
    : a.verdict === 'ADAPT' ? `Dạng “${styleLabel(a.style)}” được chuẩn hoá về mã native (IR giống hệt)` : 'Không chạy được: xem các lỗi đánh dấu trong code'
  return (
    <span className="se-vwrap">
      <button type="button" className={`se-vchip ${tone}`} title={title} onClick={onToggle}>
        <i className={`d ${tone}`} />
        <b>{a.verdict}</b>
        {a.verdict === 'ADAPT' && <span>· từ {styleLabel(a.style)}</span>}
        {a.verdict === 'REJECT' && <span>· {errs} lỗi{warns ? `, ${warns} cảnh báo` : ''}</span>}
        {a.verdict === 'RUN' && a.style && <span>· {styleLabel(a.style)}</span>}
      </button>
      {a.verdict === 'ADAPT' && a.normalized_code && onApply && <button type="button" className="n-btn sm" title="Thay code bằng mã native tương đương" onClick={() => onApply(a.normalized_code)}>Chuẩn hoá code</button>}
    </span>
  )
}

/** Danh sách chẩn đoán của trợ lý; bấm một dòng để nhảy tới vị trí. */
export function AssistList({ a, onGo }) {
  const diags = a?.diagnostics || []
  if (!diags.length) return <p className="n-note se-pad">Không có chẩn đoán.</p>
  return (
    <ul className="se-dl">
      {diags.map((d, i) => (
        <li key={i}>
          <button type="button" className={`se-di ${d.severity}`} onClick={() => onGo && onGo(d.line, d.col)}>
            <span className="se-dpos">{d.line}:{d.col}</span>
            <span className="se-dmsg">{d.message_vi}{d.path ? ` (${d.path})` : ''}</span>
            {d.suggest?.length > 0 && <span className="se-dsug">gợi ý: {d.suggest.slice(0, 3).join(', ')}</span>}
          </button>
        </li>
      ))}
    </ul>
  )
}
