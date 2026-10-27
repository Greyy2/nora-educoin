import React, { useEffect, useState } from 'react'
import { Panel, Empty, Spinner, NA } from '../ui'
import Term from '../ui/Term'
import { getPortfolioTrades, portfolioTradesCsvUrl, getMarketRegime } from '../../api'
import { fmtNum, fmtMoney, fmtPct, fmtSPct, signClass, arrow, fmtDateTime, isNum } from '../../lib/format'
import { legLabel } from '../../lib/strategyLabel'

/* ─── Thống kê theo HỌ chiến lược (gộp mọi bộ tham số / alpha cùng chiến lược) ─────────────────────────────── */
export function FamilyStatsPanel({ rows = [], period, bare = false }) {
  if (!rows.length) return null
  return (
    <Panel className={bare ? 'pf-bare' : ''} title={bare ? null : 'Thống kê theo chiến lược'} meta={<span>gộp mọi bộ tham số của cùng chiến lược · lệnh đã đóng trong kỳ {period}</span>}>
      <div className="n-tblwrap">
        <table className="n-tbl">
          <thead>
            <tr>
              <th>Chiến lược</th><th className="r">Lệnh</th><th className="r">Win rate</th><th className="r"><Term k="profit_factor">PF</Term></th>
              <th className="r"><Term k="payoff">Payoff</Term></th><th className="r"><Term k="expectancy">Kỳ vọng/lệnh</Term></th>
              <th className="r">Lãi/lỗ</th><th className="r">Đóng góp</th><th className="r"><Term k="sharpe">Sharpe</Term></th>
              <th className="r"><Term k="mdd">MDD</Term></th><th className="r">Chuỗi thua</th><th className="r"><Term k="mae">Lỗ treo tệ nhất</Term></th>
              <th className="r"><Term k="fee_drag">Phí/lãi</Term></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => {
              const t = f.trades || {}
              return (
                <tr key={f.family}>
                  <td>
                    <b className="mono">{f.family}</b>
                    <div className="muted" style={{ fontSize: 11.5 }}>{f.ids.length > 1 ? `${f.ids.length} bộ tham số · ` : ''}{f.symbols.map((s) => s.replace('@perp', '')).join(', ')}</div>
                  </td>
                  <td className="r">{t.trades}</td>
                  <td className="r">{isNum(t.win_rate) ? fmtPct(t.win_rate, 1) : <NA note={t.win_rate_note} />}{t.breakeven ? <span className="muted"> · {t.breakeven} hoà</span> : null}</td>
                  <td className="r">{isNum(t.profit_factor) ? fmtNum(t.profit_factor) : <NA note={t.profit_factor_note} />}</td>
                  <td className="r">{fmtNum(t.payoff)}</td>
                  <td className={`r ${signClass(t.expectancy_usd)}`}>{fmtMoney(t.expectancy_usd, true)}</td>
                  <td className={`r ${signClass(f.pnl)}`}>{arrow(f.pnl)} {fmtMoney(f.pnl, true)}</td>
                  <td className={`r ${signClass(f.contribution_pct)}`}>{fmtSPct(f.contribution_pct)}</td>
                  <td className="r">{fmtNum(f.sharpe)}</td>
                  <td className="r neg">{fmtSPct(f.mdd_pct)}</td>
                  <td className="r">{t.max_consec_losses}</td>
                  <td className="r neg">{fmtSPct(t.mae_worst_pct)}</td>
                  <td className="r">{fmtPct(t.fee_drag_pct, 0)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

/* ─── Danh sách lệnh (lọc / sắp / phân trang / CSV) ──────────────────────────────────────────────────────────── */
const PAGE = 50   // lệnh mỗi trang
const COLS = [
  ['close_time', 'Đóng'], ['enter_time', 'Mở'], ['symbol', 'Tài sản'], ['strategy', 'Chiến lược'], [null, 'Chiều'],
  [null, 'Giá vào → ra'], ['notional', 'Danh nghĩa'], [null, 'Tầng'], ['mae_pct', 'Lỗ treo'], ['pnl', 'Lãi/lỗ'], ['pnl_pct', '% vốn'], [null, 'Lý do đóng'],
]

function Pager({ total, offset, onPage }) {
  return (
    <div className="n-pager">
      <button type="button" className="n-btn sm" disabled={offset === 0} onClick={() => onPage(Math.max(0, offset - PAGE))}>‹ Trước</button>
      <span className="mono">{offset + 1}–{Math.min(total, offset + PAGE)} / {total}</span>
      <button type="button" className="n-btn sm" disabled={offset + PAGE >= total} onClick={() => onPage(offset + PAGE)}>Sau ›</button>
    </div>
  )
}

export function TradesPanel({ jobId, period, bare = false }) {
  const [f, setF] = useState({ strategy: '', symbol: '', side: '', outcome: '', sort: '-close_time', offset: 0 })
  const [st, setSt] = useState({ loading: true, data: null, error: null })
  const q = { job_id: jobId || undefined, period, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v !== '')), limit: PAGE }

  useEffect(() => { setF((x) => ({ ...x, offset: 0 })) }, [jobId, period])
  useEffect(() => {
    let dead = false
    setSt((s) => ({ ...s, loading: true }))
    getPortfolioTrades(q).then((data) => !dead && setSt({ loading: false, data, error: null }), (e) => !dead && setSt({ loading: false, data: null, error: e.message }))
    return () => { dead = true }
  }, [JSON.stringify(q)]) // eslint-disable-line react-hooks/exhaustive-deps

  const set = (patch) => setF((x) => ({ ...x, ...patch, offset: patch.offset ?? 0 }))
  const sortBy = (k) => k && set({ sort: f.sort === `-${k}` ? k : `-${k}` })
  const d = st.data
  const total = d?.total || 0
  return (
    <Panel className={bare ? 'pf-bare' : ''} title={bare ? null : 'Danh sách lệnh'} meta={<>
      <span>{st.loading ? <Spinner /> : `${total} lệnh`}</span>
      <a className="n-btn sm" href={portfolioTradesCsvUrl({ ...q, limit: undefined, offset: undefined })}>Tải CSV</a>
    </>}>
      <div className="n-filters">
        <select className="n-sel" aria-label="Chiến lược" value={f.strategy} onChange={(e) => set({ strategy: e.target.value })}>
          <option value="">Mọi chiến lược</option>
          {(d?.families || []).map((x) => <option key={`f-${x}`} value={x}>{x} (cả họ)</option>)}
          {(d?.strategies || []).filter((x) => !(d?.families || []).includes(x)).map((x) => <option key={x} value={x}>{legLabel(x)}</option>)}
        </select>
        <select className="n-sel" aria-label="Tài sản" value={f.symbol} onChange={(e) => set({ symbol: e.target.value })}>
          <option value="">Mọi tài sản</option>
          {(d?.symbols || []).map((x) => <option key={x} value={x}>{x.replace('@perp', '')}</option>)}
        </select>
        <select className="n-sel" aria-label="Chiều" value={f.side} onChange={(e) => set({ side: e.target.value })}>
          <option value="">Long + Short</option><option value="LONG">Long</option><option value="SHORT">Short</option>
        </select>
        <select className="n-sel" aria-label="Kết quả" value={f.outcome} onChange={(e) => set({ outcome: e.target.value })}>
          <option value="">Thắng + thua + hoà</option><option value="win">Thắng</option><option value="loss">Thua</option><option value="breakeven">Hoà</option>
        </select>
      </div>
      {st.error && <Empty title="Không tải được danh sách lệnh">{st.error}</Empty>}
      {total > PAGE && <Pager total={total} offset={f.offset} onPage={(o) => set({ offset: o })} />}
      {d && (
        <div className="n-tblwrap n-sticky pf-trades-scroll">
          <table className="n-tbl">
            <thead>
              <tr>{COLS.map(([k, label]) => (
                <th key={label} className={k ? 'sortable' : ''} onClick={() => sortBy(k)}
                  aria-sort={k && f.sort.replace('-', '') === k ? (f.sort.startsWith('-') ? 'descending' : 'ascending') : undefined}>
                  {label}{k && f.sort.replace('-', '') === k ? (f.sort.startsWith('-') ? ' ↓' : ' ↑') : ''}
                </th>
              ))}</tr>
            </thead>
            <tbody>
              {d.items.map((t, i) => (
                <tr key={`${t.close_time}-${t.symbol}-${t.strategy}-${i}`}>
                  <td className="mono">{fmtDateTime(t.close_time)}</td>
                  <td className="mono muted">{fmtDateTime(t.enter_time)}</td>
                  <td>{String(t.symbol).replace('@perp', '')}</td>
                  <td title={t.strategy}>{legLabel(t.strategy)}</td>
                  <td><span className={`n-badge ${String(t.side).toLowerCase()}`}>{t.side}</span></td>
                  <td className="mono">{fmtNum(t.avg_price ?? t.enter_price, 4)} → {fmtNum(t.close_price, 4)}</td>
                  <td className="mono r">{fmtMoney(t.notional)}</td>
                  <td className="r">{isNum(t.layers) ? t.layers : '—'}</td>
                  <td className="r neg">{fmtSPct(t.mae_pct)}</td>
                  <td className={`r ${signClass(t.pnl)}`}>{fmtMoney(t.pnl, true)}</td>
                  <td className={`r ${signClass(t.pnl_pct)}`}>{fmtSPct(t.pnl_pct, 3)}</td>
                  <td className="muted">{t.close_reason}</td>
                </tr>
              ))}
              {!d.items.length && <tr><td colSpan={COLS.length} className="muted">Không có lệnh khớp bộ lọc.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {total > PAGE && <Pager total={total} offset={f.offset} onPage={(o) => set({ offset: o })} />}
    </Panel>
  )
}

/* ─── Regime thị trường: thang đo có dấu 0 trung tâm, chỉ báo live & stale handling (DEC-05) ──────────── */

export const REGIME_SPECTRUM = [
  { state: 'CRASH', value: -2, label: 'Sập mạnh', short: 'Sập mạnh (-2)', color: 'var(--n-accent, #e11d48)' },
  { state: 'TREND_DOWN', value: -1, label: 'Xu hướng giảm', short: 'Giảm (-1)', color: 'var(--n-neg, #f0616d)' },
  { state: 'RANGE', value: 0, label: 'Đi ngang', short: '0 · Đi ngang', color: 'var(--n-ink-3, #94a3b8)' },
  { state: 'TREND_UP', value: 1, label: 'Xu hướng tăng', short: 'Tăng (+1)', color: 'var(--n-pos, #10b981)' },
  { state: 'SURGE', value: 2, label: 'Tăng thẳng đứng', short: 'Tăng sốc (+2)', color: 'var(--n-teal, #06b6d4)' },
]

export function RegimeScale({ state, label, asOf, isStale: explicitStale, compact = false, showLabel = true }) {
  const match = REGIME_SPECTRUM.find((s) => s.state === state)
  const isVol = state === 'VOL_EXPANSION'
  const isUnknown = state === 'UNKNOWN' || (!match && !isVol)
  const activeValue = match ? match.value : 0
  const displayLabel = label || match?.label || (isVol ? 'Biến động bùng nổ' : 'Chưa đủ dữ liệu')
  const isStale = explicitStale !== undefined ? explicitStale : Boolean(asOf && (Date.now() - asOf > 30 * 60 * 1000))

  if (compact) {
    return (
      <div
        className={`n-rgscale-compact ${isStale ? 'is-stale' : ''}`}
        role="meter"
        aria-label={`Regime: ${displayLabel}`}
        aria-valuenow={match ? activeValue : undefined}
        aria-valuemin="-2"
        aria-valuemax="2"
        aria-valuetext={displayLabel}
        title={`${displayLabel}${asOf ? ` · Cập nhật: ${fmtDateTime(asOf)}` : ''}${isStale ? ' · Dữ liệu cũ' : ''}`}
      >
        <div className="n-rgscale-mini-track" style={isStale ? { opacity: 0.6 } : undefined}>
          {REGIME_SPECTRUM.map((seg) => {
            const isActive = seg.state === state
            return (
              <div
                key={seg.state}
                className={`n-rgscale-mini-seg ${isActive ? 'active' : ''}`}
                style={{
                  backgroundColor: isActive ? seg.color : undefined,
                  opacity: isActive ? 1 : 0.22,
                }}
              />
            )
          })}
        </div>
        {isVol && <span className="n-rgchip n-rg-VOL_EXPANSION" style={{ fontSize: 10, padding: '1px 5px', marginLeft: 2 }}>Biến động</span>}
        {isUnknown && <span className="n-rgchip n-rg-UNKNOWN" style={{ fontSize: 10, padding: '1px 5px', marginLeft: 2 }}>Khởi động</span>}
        {isStale && <span className="n-badge bad" style={{ fontSize: 9.5, padding: '0 4px', marginLeft: 2 }}>Cũ</span>}
        {showLabel && (
          <span className={`n-rgscale-mini-lbl ${match ? (activeValue < 0 ? 'neg' : activeValue > 0 ? 'pos' : 'muted') : 'muted'}`}>
            {displayLabel}
          </span>
        )}
      </div>
    )
  }

  return (
    <div
      className={`n-rgscale-featured ${isStale ? 'is-stale' : ''}`}
      role="meter"
      aria-label={`Thang đo regime thị trường: ${displayLabel}`}
      aria-valuenow={match ? activeValue : undefined}
      aria-valuemin="-2"
      aria-valuemax="2"
      aria-valuetext={displayLabel}
    >
      <div className="n-rgscale-header">
        <div className="n-rgscale-title-group">
          <span className="n-rgscale-kicker">Chỉ báo Regime (Thang ngang Âm đỏ ← 0 Trung tính → Dương xanh)</span>
          <div className="n-rgscale-badge-row">
            <span className={`n-rgchip n-rg-${state || 'UNKNOWN'}`}>
              {displayLabel}
            </span>
            {isVol && (
              <span className="n-badge warn" title="Biến động BBWP bùng nổ, rủi ro co giãn biên độ lớn">
                ⚡ Biến động cao (BBWP mở rộng)
              </span>
            )}
            {isStale && (
              <span className="n-badge bad" title="Dữ liệu cũ hơn 30 phút hoặc mất kết nối live feed (DEC-05)">
                ⏳ DỮ LIỆU CŨ / MẤT KẾT NỐI (Feed Stale)
              </span>
            )}
            {isUnknown && (
              <span className="n-badge" title="Chưa đủ nến để xác định xu hướng">
                ℹ️ Chưa đủ dữ liệu / Đang khởi động
              </span>
            )}
          </div>
        </div>
        <div className="n-rgscale-meta-group">
          {asOf ? (
            <span className="n-rgscale-asof muted">Thời điểm cập nhật: <span className="mono">{fmtDateTime(asOf)}</span></span>
          ) : (
            <span className="muted">Chưa có mốc thời gian</span>
          )}
        </div>
      </div>

      <div className="n-rgscale-track-wrap">
        <div className="n-rgscale-axis">
          <span>← Âm (Bán mạnh / Sập giá)</span>
          <span className="n-rgscale-zero">0 · Trung tính (Đi ngang)</span>
          <span>Dương (Tăng giá / Tăng sốc) →</span>
        </div>

        <div className="n-rgscale-track" style={isStale ? { opacity: 0.72 } : undefined}>
          {REGIME_SPECTRUM.map((seg) => {
            const isActive = seg.state === state
            return (
              <div
                key={seg.state}
                className={`n-rgscale-zone ${isActive ? 'active' : ''}`}
                style={{
                  color: seg.color,
                }}
              >
                <div
                  className="n-rgscale-fill"
                  style={{
                    backgroundColor: seg.color,
                    opacity: isActive ? 0.95 : 0.16,
                  }}
                />
                <span className="n-rgscale-zone-lbl" style={{ color: isActive ? '#fff' : undefined, fontWeight: isActive ? 700 : 500 }}>
                  {seg.short}
                </span>
                {isActive && (
                  <div className="n-rgscale-pointer" style={{ backgroundColor: seg.color }}>
                    <span className="n-rgscale-pointer-pulse" style={{ borderColor: seg.color }} />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export function calculateRegimeScore(state, sharePct = {}) {
  switch (state) {
    case 'CRASH':
      return -0.92
    case 'TREND_DOWN': {
      const downPct = sharePct?.TREND_DOWN || 20
      return -Math.min(0.85, 0.40 + (downPct / 100) * 0.45)
    }
    case 'RANGE':
      return 0.0
    case 'TREND_UP': {
      const upPct = sharePct?.TREND_UP || 20
      return Math.min(0.85, 0.40 + (upPct / 100) * 0.45)
    }
    case 'SURGE':
      return 0.92
    case 'VOL_EXPANSION':
      return 0.0
    default:
      return 0.0
  }
}

export function RegimeBar({ score = 0, state = 'RANGE', label, isStale = false, symbol = '' }) {
  const isNeg = score < 0
  const isPos = score > 0
  const isZero = score === 0 || state === 'RANGE'
  const isVol = state === 'VOL_EXPANSION'
  const fillWidth = Math.min(50, Math.abs(score) * 50)

  return (
    <div
      className={`n-rg-bar-track ${isStale ? 'is-stale' : ''}`}
      role="meter"
      aria-label={`${symbol || 'Regime'}: ${label || state}`}
      aria-valuenow={score}
      aria-valuemin="-1"
      aria-valuemax="1"
      title={`${symbol}: ${label || state} (${score > 0 ? `+${(score * 100).toFixed(0)}%` : `${(score * 100).toFixed(0)}%`})`}
    >
      {/* 0 center divider line */}
      <div className="n-rg-bar-center-line" />

      {/* Negative / Short (extends left from 50%) */}
      {isNeg && (
        <div
          className="n-rg-bar-fill is-short"
          style={{
            right: '50%',
            width: `${fillWidth}%`,
          }}
        />
      )}

      {/* Positive / Long (extends right from 50%) */}
      {isPos && (
        <div
          className="n-rg-bar-fill is-long"
          style={{
            left: '50%',
            width: `${fillWidth}%`,
          }}
        />
      )}

      {/* Center 0 pip for Sideway / Volatility */}
      {(isZero || isVol) && (
        <div className={`n-rg-bar-center-pip ${isVol ? 'is-vol' : ''}`} />
      )}
    </div>
  )
}

export function RegimeMarketList({ symbols = [], labelsVi = {}, asOf, isStale }) {
  if (!symbols || !symbols.length) return null

  const cleanSym = (s) => (s ? s.split('@')[0].split('-')[0].toUpperCase() : '')

  return (
    <div className="n-rg-market-container" data-testid="regime-scale">
      {/* Subheader / Legend bar */}
      <div className="n-rg-legend-bar">
        <div className="n-rg-legend-axis">
          <span className="n-rg-legend-side is-short">← Short (Đỏ)</span>
          <span className="n-rg-legend-mid">0 · Sideway (Đi ngang)</span>
          <span className="n-rg-legend-side is-long">Long (Xanh) →</span>
        </div>
      </div>

      {/* Market Rows */}
      <div className="n-rg-market-table">
        {symbols.map((item) => {
          const symName = cleanSym(item.symbol)
          const state = item.current?.state || item.regime || 'UNKNOWN'
          const label = item.current?.label || labelsVi[state] || state
          const score = calculateRegimeScore(state, item.share_pct)
          const hasError = Boolean(item.error)
          const itemStale = hasError || item.is_stale || isStale

          // Badge configuration
          let tagClass = 'n-rg-tag-muted'
          let tagText = label
          if (state === 'CRASH') { tagClass = 'n-rg-tag-crash'; tagText = 'Sập mạnh (-2)' }
          else if (state === 'TREND_DOWN') { tagClass = 'n-rg-tag-short'; tagText = 'Short (-1)' }
          else if (state === 'RANGE') { tagClass = 'n-rg-tag-range'; tagText = 'Sideway (0)' }
          else if (state === 'TREND_UP') { tagClass = 'n-rg-tag-long'; tagText = 'Long (+1)' }
          else if (state === 'SURGE') { tagClass = 'n-rg-tag-surge'; tagText = 'Tăng sốc (+2)' }
          else if (state === 'VOL_EXPANSION') { tagClass = 'n-rg-tag-vol'; tagText = 'Biến động' }
          else if (hasError) { tagClass = 'n-rg-tag-muted'; tagText = 'Chưa sẵn sàng' }

          return (
            <div key={item.symbol} className="n-rg-market-row">
              {/* Col 1: Symbol */}
              <div className="n-rg-col-sym">
                <span className="n-rg-sym-name">{symName}</span>
                <span className="n-rg-sym-badge">PERP</span>
              </div>

              {/* Col 2: Regime Badge */}
              <div className="n-rg-col-tag">
                <span className={`n-rg-tag ${tagClass}`}>
                  {tagText}
                </span>
                {itemStale && !hasError && (
                  <span className="n-badge bad" style={{ fontSize: 9.5, padding: '1px 4px' }} title="Dữ liệu cũ hoặc chậm">
                    Cũ
                  </span>
                )}
              </div>

              {/* Col 3: The Center-Split Regime Bar */}
              <div className="n-rg-col-bar">
                <RegimeBar
                  score={score}
                  state={state}
                  label={label}
                  isStale={itemStale}
                  symbol={symName}
                />
              </div>

              {/* Col 4: Score / Percentage Bias */}
              <div className="n-rg-col-score">
                <span className={`n-rg-score-text ${score < 0 ? 'neg' : score > 0 ? 'pos' : 'muted'}`}>
                  {score < 0 ? `${Math.round(score * 100)}%` : score > 0 ? `+${Math.round(score * 100)}%` : '0%'}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

let REGIME_MEMO = null

export function RegimePanel({ bare = false }) {
  const [st, setSt] = useState(() => ({ loading: !REGIME_MEMO, data: REGIME_MEMO, error: null }))

  useEffect(() => {
    let dead = false
    if (!REGIME_MEMO) setSt((x) => ({ ...x, loading: true }))
    getMarketRegime().then(
      (data) => {
        if (!dead) {
          REGIME_MEMO = data
          setSt({ loading: false, data, error: null })
        }
      },
      (e) => !dead && setSt((x) => ({ ...x, loading: false, error: x.data ? null : e.message })),
    )
    return () => { dead = true }
  }, [])

  const d = st.data
  const allSymbols = d?.symbols || []
  const asOfVal = d?.as_of || null
  const isStale = d?.is_stale

  // Compute market summary
  const bearCount = allSymbols.filter((s) => s.current?.state === 'TREND_DOWN' || s.current?.state === 'CRASH').length
  const bullCount = allSymbols.filter((s) => s.current?.state === 'TREND_UP' || s.current?.state === 'SURGE').length
  const rangeCount = allSymbols.filter((s) => s.current?.state === 'RANGE').length

  let summaryText = 'Đang phân tích...'
  if (allSymbols.length) {
    if (bearCount > bullCount) summaryText = `Thiên hướng Short (${bearCount}/${allSymbols.length} cặp giảm)`
    else if (bullCount > bearCount) summaryText = `Thiên hướng Long (${bullCount}/${allSymbols.length} cặp tăng)`
    else summaryText = `Đi ngang cân bằng (${rangeCount}/${allSymbols.length} cặp sideway)`
  }

  return (
    <Panel
      className={`regime-scale ${bare ? 'pf-bare' : ''}`}
      data-testid="regime-scale"
      title={bare ? null : (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
          <span>Regime thị trường</span>
          <span className="n-badge" style={{ fontSize: 11, fontWeight: 500, background: 'rgba(255,255,255,0.06)' }}>
            {summaryText}
          </span>
        </span>
      )}
      meta={
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          {st.loading && <Spinner />}
          {asOfVal && <span className="mono muted" style={{ fontSize: 12 }}>{fmtDateTime(asOfVal)}</span>}
          {isStale && <span className="n-badge bad" style={{ fontSize: 10 }}>Feed Cũ</span>}
        </span>
      }
    >
      {st.error && <Empty title="Không tải được regime">{st.error}</Empty>}
      {!st.loading && !st.error && !allSymbols.length && (
        <Empty title="Chưa có dữ liệu regime">Chưa tìm thấy dữ liệu thị trường trực tiếp.</Empty>
      )}
      {Boolean(allSymbols.length) && (
        <RegimeMarketList
          symbols={allSymbols}
          labelsVi={d?.labels_vi || {}}
          asOf={asOfVal}
          isStale={isStale}
        />
      )}
    </Panel>
  )
}
