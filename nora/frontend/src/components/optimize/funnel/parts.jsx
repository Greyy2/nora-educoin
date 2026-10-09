import React from 'react'
import { Status } from '../../ui'
import { paramText } from '../../../lib/params'
import { shortId, stageShort, stageName, fmtMetric, metricLabel } from '../../../lib/funnel'
import { isNum, signClass } from '../../../lib/format'
import { legLabel, legSide } from '../../../lib/strategyLabel'

/** Mã alpha rút gọn, bấm để mở chi tiết. */
export function AlphaLink({ id, onOpen, active }) {
  return (
    <button type="button" className={`n-idlink mono ${active ? 'on' : ''}`} title={`Mở chi tiết alpha ${id}`} onClick={() => onOpen(id)}>{shortId(id)}</button>
  )
}

/** "Cắt lỗ 2× ATR · Trailing 3× ATR" (khoá thô nằm trong tooltip). */
export function ParamList({ params }) {
  const e = Object.entries(params || {})
  if (!e.length) return <span className="muted">—</span>
  return <span className="n-plist-inline" title={e.map(([k, v]) => `${k} = ${v}`).join('\n')}>{e.map(([k, v]) => paramText(k, v)).join(' · ')}</span>
}

/** Trạng thái hành trình của một alpha: FINAL / bị loại ở tầng / đang ở tầng. */
export function AlphaStatus({ a }) {
  if (a.rejected_stage) return <Status tone="bad" ><span title={a.reject_msg || a.reject_code}>✗ Loại ở {stageShort(a.rejected_stage)}</span></Status>
  if (a.stage_reached === 'FINAL') return <Status tone="ok">✓ FINAL</Status>
  return <Status tone="info">{stageShort(a.stage_reached)}</Status>
}

export { stageName, stageShort, metricLabel }

/** Tên chiến lược kèm chiều ("KEMA · Long"; id cũ có hậu tố "(cũ)"), id thô là chữ phụ. */
export function StrategyName({ id }) {
  const side = legSide(id)
  return (
    <span className="n-strat-name" title={id}>
      <span>{legLabel(id)}</span>
      {side && <span className={`n-badge ${side.toLowerCase()}`}>{side}</span>}
    </span>
  )
}

/** Tầng chưa có alpha nào vào (tầng trước không cho alpha nào qua / lượt dừng sớm). */
export function EmptyStage({ stage, prev, reasons = [], children }) {
  return (
    <div className="n-fn-empty" role="status">
      <h3>{stageShort(stage)} · {stageName(stage)}: chưa có alpha nào</h3>
      <p>{prev ? <>{prev.passed === 0 ? <><b>0 alpha qua {stageShort(prev.stage)}</b>{isNum(prev.input) ? ` (0/${prev.input.toLocaleString('en-US')})` : ''} nên không alpha nào vào tầng này.</> : 'Tầng này chưa chạy.'}</> : 'Tầng này chưa chạy.'}</p>
      {reasons.length > 0 && (
        <div className="n-note">Lý do loại chính ở {stageShort(prev.stage)}: {reasons.slice(0, 3).map((r, i) => <span key={r.code}>{i ? ' · ' : ''}{r.label || r.code} <span className="mono">({r.count.toLocaleString('en-US')})</span></span>)}</div>
      )}
      {children}
    </div>
  )
}
