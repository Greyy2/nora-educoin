import React from 'react'
import { normWarnings } from '../../lib/customResult'

/** Danh sách cảnh báo của kết quả backtest (result.warnings: string[]). Rỗng / vắng -> không hiện gì. bare=true: chỉ danh sách, không khung. */
export default function WarningsPanel({ warnings, bare = false }) {
  const list = normWarnings(warnings)
  if (!list.length) return null
  const ul = <ul className="n-events">{list.map((w, i) => <li key={i}><span className="ic warn" role="img" aria-label="Cảnh báo">▲</span><span className="tx">{w}</span></li>)}</ul>
  if (bare) return ul
  return (
    <section className="se-cc"><div className="se-cc-h"><b>Cảnh báo</b><span className="sp" /><span className="muted">{list.length}</span></div><div className="se-cc-b">{ul}</div></section>
  )
}
