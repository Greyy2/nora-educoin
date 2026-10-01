import React from 'react'
import { Status } from './ui'
import { fmtNum, isNum } from '../lib/format'

/** Checklist cổng chấp nhận: thực tế so với yêu cầu, kèm biểu tượng đạt/không đạt (không chỉ màu). */
export default function GateList({ checks, passed, title = 'Cổng chấp nhận' }) {
  const rows = Array.isArray(checks) ? checks : Object.entries(checks || {}).map(([k, v]) => ({ key: k, ...v }))
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
        <b>{title}</b>
        {passed != null && <Status tone={passed ? 'ok' : 'bad'}>{passed ? '✓ Đạt' : '✗ Không đạt'}</Status>}
      </div>
      <ul className="n-gate">
        {rows.map((c, i) => (
          <li key={c.key || i}>
            <span className={c.passed ? 'pos' : 'neg'} role="img" aria-label={c.passed ? 'đạt' : 'không đạt'}>{c.passed ? '✓' : '✗'}</span>
            <span>{c.label || c.key}</span>
            <span className="v">{isNum(c.actual) ? fmtNum(c.actual, Number.isInteger(c.actual) ? 0 : 2) : String(c.actual ?? '—')}</span>
            <span className="req">yêu cầu {c.required}</span>
          </li>
        ))}
        {!rows.length && <li><span /><span className="muted">Không có chi tiết cổng.</span></li>}
      </ul>
    </div>
  )
}
