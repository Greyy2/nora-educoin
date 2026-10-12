import React from 'react'
import { Spinner } from '../../ui'
import { isNum, fmtNum } from '../../../lib/format'

/**
 * Định dạng PNL theo phong cách định lượng:
 * $2362.78 (23.63%) hoặc +23.63%
 */
function formatPnl(pnlUsd, retPct) {
  if (!isNum(pnlUsd) && !isNum(retPct)) return '—'
  const pctStr = isNum(retPct) ? (retPct >= 0 ? `+${fmtNum(retPct, 2)}%` : `${fmtNum(retPct, 2)}%`) : ''
  if (isNum(pnlUsd)) {
    const absUsd = Math.abs(pnlUsd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    const prefix = pnlUsd >= 0 ? '$' : '-$'
    return pctStr ? `${prefix}${absUsd} (${pctStr})` : `${prefix}${absUsd}`
  }
  return pctStr || '—'
}

function formatMdd(mdd) {
  if (!isNum(mdd)) return '—'
  const val = -Math.abs(mdd)
  return `${fmtNum(val, 2)}%`
}

function formatSharpe(sharpe) {
  if (!isNum(sharpe)) return '—'
  return fmtNum(sharpe, 2)
}

function formatWinRate(win) {
  if (!isNum(win)) return '—'
  return `${fmtNum(win, 2)}%`
}

/**
 * Tab "Chiến lược mẫu": danh sách các chiến lược mẫu chuẩn trong hệ thống.
 * Hiển thị thẻ kết quả định lượng trực quan (PNL, Max Drawdown, Sharpe Ratio, Win-rate).
 * Bấm vào lập tức chuyển tab file và mở kết quả chi tiết.
 */
export default function SamplesPane({ samples, onUse, saved, onOpenSaved, openingId = '', activeId = '' }) {
  const savedItems = (Array.isArray(saved?.data) ? saved.data : []).filter((s) => s.status !== 'ARCHIVED')

  // Bản đồ đối chiếu các bản ghi đã lưu theo tên hoặc id/key
  const savedByName = new Map()
  savedItems.forEach((item) => {
    if (item.name) savedByName.set(item.name.toLowerCase().trim(), item)
    if (item.id) savedByName.set(item.id.toLowerCase().trim(), item)
  })

  const matchedSavedIds = new Set()

  // Danh sách các mẫu tiêu chuẩn kèm kết quả tính trước
  const sampleEntries = samples.map((s) => {
    const savedRec =
      savedByName.get((s.name || '').toLowerCase().trim()) ||
      savedByName.get((s.key || '').toLowerCase().trim())
    if (savedRec) matchedSavedIds.add(savedRec.id)

    const m = s.metrics || savedRec?.metrics || s.result?.metrics || null
    const sim = m ? (m.simulate || m.test || null) : null
    const pnlUsd = s.pnl_usd ?? (s.final_equity && s.initial_capital ? s.final_equity - s.initial_capital : (sim && isNum(sim.ret_pct) ? (10000 * sim.ret_pct) / 100 : null))
    const retPct = sim ? (sim.ret_pct ?? sim.return_pct) : null
    const mddPct = sim ? (sim.mdd_pct ?? sim.max_drawdown_pct) : null
    const sharpe = sim ? sim.sharpe : null
    const winRate = sim ? (sim.win_rate_trades ?? sim.win_rate) : null

    return {
      key: s.key || s.name,
      name: s.name,
      summary: s.summary || s.note,
      code: s.code,
      result: s.result || savedRec?.result || null,
      metrics: m,
      pnlUsd,
      retPct,
      mddPct,
      sharpe,
      winRate,
      savedRec: savedRec || null,
      isSample: true,
    }
  })

  // Các chiến lược người dùng lưu mà không trùng tên với mẫu nào
  const userEntries = savedItems
    .filter((item) => !matchedSavedIds.has(item.id))
    .map((item) => {
      const m = item.metrics || item.result?.metrics || null
      const sim = m ? (m.simulate || m.test || null) : null
      const pnlUsd = item.pnl_usd ?? (item.result?.final_equity && item.result?.config?.initial_capital ? item.result.final_equity - item.result.config.initial_capital : (sim && isNum(sim.ret_pct) ? (10000 * sim.ret_pct) / 100 : null))
      const retPct = sim ? (sim.ret_pct ?? sim.return_pct) : null
      const mddPct = sim ? (sim.mdd_pct ?? sim.max_drawdown_pct) : null
      const sharpe = sim ? sim.sharpe : null
      const winRate = sim ? (sim.win_rate_trades ?? sim.win_rate) : null

      return {
        key: item.id,
        name: item.name || item.id,
        summary: `Chiến lược người dùng · Cập nhật ${item.updated_at ? String(item.updated_at).slice(0, 10) : ''}`,
        code: item.code,
        result: item.result || null,
        metrics: m,
        pnlUsd,
        retPct,
        mddPct,
        sharpe,
        winRate,
        savedRec: item,
        isUserAlpha: true,
      }
    })

  const allItems = [...userEntries, ...sampleEntries]

  return (
    <div className="se-samples">
      <div className="se-cards-hdr" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <h3 className="se-h3" style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>
          Danh mục chiến lược ({allItems.length})
        </h3>
        {saved?.loading && <span className="muted" style={{ fontSize: 12 }}><Spinner /> Đang tải...</span>}
      </div>

      <div className="se-cards">
        {allItems.map((s) => {
          const isOpening = openingId && s.savedRec && openingId === s.savedRec.id
          const isActive = activeId && s.savedRec && activeId === s.savedRec.id

          const handleClick = () => {
            if (s.savedRec && onOpenSaved) {
              onOpenSaved(s.savedRec.id)
            } else if (onUse) {
              onUse(s)
            }
          }

          return (
            <div
              key={s.key || s.name}
              className={`n-card-sel se-sample-card ${isActive ? 'on' : ''}`}
              role="button"
              tabIndex={0}
              aria-busy={isOpening}
              onClick={handleClick}
              onKeyDown={(e) => { if (e.key === 'Enter') handleClick() }}
            >
              <div className="se-card-h">
                <b className="se-card-title">{s.name}</b>
              </div>

              {/* Bảng kết quả định lượng trực quan theo chuẩn quốc tế */}
              <div className="se-card-metrics">
                <div className="se-metric-row">
                  <span className="se-metric-lbl">PNL</span>
                  <span className={`se-metric-val ${s.retPct > 0 ? 'pos' : s.retPct < 0 ? 'neg' : ''}`}>
                    {formatPnl(s.pnlUsd, s.retPct)}
                  </span>
                </div>
                <div className="se-metric-row">
                  <span className="se-metric-lbl">Max Drawdown</span>
                  <span className={`se-metric-val ${s.mddPct ? 'neg' : ''}`}>
                    {formatMdd(s.mddPct)}
                  </span>
                </div>
                <div className="se-metric-row">
                  <span className="se-metric-lbl">Sharpe Ratio</span>
                  <span className="se-metric-val">
                    {formatSharpe(s.sharpe)}
                  </span>
                </div>
                <div className="se-metric-row">
                  <span className="se-metric-lbl">Win-rate</span>
                  <span className="se-metric-val">
                    {formatWinRate(s.winRate)}
                  </span>
                </div>
              </div>

              {isOpening && <Spinner />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
