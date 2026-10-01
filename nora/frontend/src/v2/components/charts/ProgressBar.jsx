import React from 'react'
import { isNum } from '../../lib/format'

/** Thanh tiến độ / ký quỹ 0–100 với vạch mốc. Màu đổi theo mức (an toàn → cảnh báo → dừng). */
export default function ProgressBar({ value, marks = [], warnAt, critAt, label = 'Tỉ lệ' }) {
  const has = isNum(value)
  const v = has ? Math.max(0, Math.min(100, value)) : 0
  const tone = has && critAt != null && v >= critAt ? 'crit' : has && warnAt != null && v >= warnAt ? 'warn' : ''
  return (
    <div className="n-meter" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={has ? v : undefined}>
      {has && <div className={`fill ${tone}`} style={{ width: `${v}%` }} />}
      {marks.map((m) => <div key={m} className="mark" style={{ left: `${m}%` }} />)}
    </div>
  )
}
