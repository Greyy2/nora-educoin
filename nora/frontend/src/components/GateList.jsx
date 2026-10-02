import React from 'react'
import { Status } from './ui'
import Term from './Term'
import { fillWording } from '../lib/stopfill'
import { fmtNum, isNum } from '../lib/format'

// khoá cổng của backend -> thuật ngữ giải thích
const GATE_TERMS = { simulations: 'mc', stress_mdd: 'mdd', mc_simulations: 'mc', mc_stress_mdd: 'mdd', folds: 'fold', avg_is_return: 'is', positive_folds: 'oos', worst_fold_mdd: 'mdd', compounded_oos: 'oos', mc_ruin: 'p_mdd', ruin: 'p_mdd' }

// giá trị thực tế: cổng theo % luôn 2 chữ số thập phân (khớp ô KPI tương ứng), số đếm là số nguyên
function fmtActual(c) {
  if (!isNum(c.actual)) return String(c.actual ?? '—')
  const pct = (c.unit ?? (/%\s*$/.test(String(c.required)) ? '%' : '')) === '%'
  return pct ? `${fmtNum(c.actual, 2)}%` : `${fmtNum(c.actual, Number.isInteger(c.actual) ? 0 : 2)}${c.unit || ''}`
}

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
            <span>{GATE_TERMS[c.key] ? <Term k={GATE_TERMS[c.key]}>{fillWording(c.label || c.key)}</Term> : fillWording(c.label || c.key)}</span>
            <span className="v">{fmtActual(c)}</span>
            <span className="req">yêu cầu {c.required}</span>
          </li>
        ))}
        {!rows.length && <li><span /><span className="muted">Không có chi tiết cổng.</span></li>}
      </ul>
    </div>
  )
}
