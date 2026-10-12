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
/** Rút gọn số liệu thẻ từ một bản ghi (mẫu hoặc alpha đã lưu). Không có metrics (NOT_READY) -> ready=false, không có số nào. */
function cardStats(item, savedRec, fallbackCapital) {
  const result = item.result || savedRec?.result || null
  const m = item.metrics || savedRec?.metrics || result?.metrics || null
  const sim = m ? (m.simulate || m.test || null) : null
  if (!sim || item.result_status === 'NOT_READY') return { ready: false, result }
  const retPct = sim.ret_pct ?? sim.return_pct
  const capital = item.initial_capital ?? savedRec?.initial_capital ?? result?.config?.initial_capital ?? fallbackCapital
  const finalEq = item.final_equity ?? result?.final_equity
  const pnlUsd = item.pnl_usd ?? savedRec?.pnl_usd
    ?? (isNum(finalEq) && isNum(capital) ? finalEq - capital : (isNum(retPct) && isNum(capital) ? (capital * retPct) / 100 : null))
  return {
    ready: true, result, metrics: m, pnlUsd, retPct,
    mddPct: sim.mdd_pct ?? sim.max_drawdown_pct,
    sharpe: sim.sharpe,
    winRate: sim.win_rate_trades ?? sim.win_rate,
  }
}

export default function SamplesPane({ samples, onUse, saved, onOpenSaved, openingId = '', activeId = '', defaultCapital = null }) {
  const savedItems = (Array.isArray(saved?.data) ? saved.data : []).filter((s) => s.status !== 'ARCHIVED')

  // Đối chiếu bản ghi đã lưu: ưu tiên id / khoá của mẫu, dự phòng theo tên
  const norm = (v) => String(v || '').toLowerCase().trim()
  const savedById = new Map(savedItems.filter((i) => i.id).map((i) => [norm(i.id), i]))
  const savedByName = new Map(savedItems.filter((i) => i.name).map((i) => [norm(i.name), i]))
  const matchedSavedIds = new Set()

  const sampleEntries = samples.map((s) => {
    const savedRec = (s.key && savedById.get(norm(s.key))) || (s.name && savedByName.get(norm(s.name))) || null
    if (savedRec) matchedSavedIds.add(savedRec.id)
    return {
      key: s.key || s.name,
      name: s.name,
      summary: s.summary || s.note,
      code: s.code,
      ...cardStats(s, savedRec, defaultCapital),
      savedRec,
      isSample: true,
    }
  })

  // Các chiến lược người dùng lưu mà không trùng mẫu nào
  const userEntries = savedItems
    .filter((item) => !matchedSavedIds.has(item.id))
    .map((item) => ({
      key: item.id,
      name: item.name || item.id,
      summary: `Chiến lược người dùng · Cập nhật ${item.updated_at ? String(item.updated_at).slice(0, 10) : ''}`,
      code: item.code,
      ...cardStats(item, null, defaultCapital),
      savedRec: item,
      isUserAlpha: true,
    }))

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

              {s.ready ? (
                <div className="se-card-metrics">
                  <div className="se-metric-row">
                    <span className="se-metric-lbl">PNL</span>
                    <span className={`se-metric-val ${s.retPct > 0 ? 'pos' : s.retPct < 0 ? 'neg' : ''}`}>{formatPnl(s.pnlUsd, s.retPct)}</span>
                  </div>
                  <div className="se-metric-row">
                    <span className="se-metric-lbl">Max Drawdown</span>
                    <span className={`se-metric-val ${s.mddPct ? 'neg' : ''}`}>{formatMdd(s.mddPct)}</span>
                  </div>
                  <div className="se-metric-row">
                    <span className="se-metric-lbl">Sharpe Ratio</span>
                    <span className="se-metric-val">{formatSharpe(s.sharpe)}</span>
                  </div>
                  <div className="se-metric-row">
                    <span className="se-metric-lbl">Win-rate</span>
                    <span className="se-metric-val">{formatWinRate(s.winRate)}</span>
                  </div>
                </div>
              ) : (
                <div className="se-card-metrics"><span className="muted">Chưa có kết quả</span></div>
              )}

              {isOpening && <Spinner />}
            </div>
          )
        })}
      </div>
    </div>
  )
}
