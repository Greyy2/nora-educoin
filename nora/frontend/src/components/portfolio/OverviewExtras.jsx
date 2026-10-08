import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
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

/* ─── Regime thị trường: hiện tại, lịch sử, chiến lược đang bật ─────────────────────────────── */
const REGIME_DAYS = [7, 30, 90]

function RegimeBar({ segs, from, to, labels }) {
  const span = Math.max(1, to - from)
  return (
    <div className="n-rgbar" role="img" aria-label="Lịch sử regime">
      {segs.map(([a, b, st], i) => (
        <span key={i} className={`n-rg-${st}`} style={{ left: `${((a - from) / span) * 100}%`, width: `${Math.max(0.15, ((b - a) / span) * 100)}%` }}
          title={`${labels[st] || st}: ${fmtDateTime(a)} → ${fmtDateTime(b)}`} />
      ))}
    </div>
  )
}

export function RegimePanel({ bare = false }) {
  const [days, setDays] = useState(30)
  const [st, setSt] = useState({ loading: true, data: null, error: null })
  useEffect(() => {
    let dead = false
    setSt((x) => ({ ...x, loading: true }))
    getMarketRegime({ days }).then((data) => !dead && setSt({ loading: false, data, error: null }), (e) => !dead && setSt({ loading: false, data: null, error: e.message }))
    return () => { dead = true }
  }, [days])
  const d = st.data
  const rows = (d?.symbols || []).filter((r) => !r.error)
  const labels = d?.labels_vi || {}
  const to = Math.max(0, ...rows.map((r) => r.as_of || 0))
  const from = to - days * 86400000
  return (
    <Panel className={bare ? 'pf-bare' : ''} title={bare ? null : 'Regime thị trường'} meta={
      <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        {st.loading && <Spinner />}
        {REGIME_DAYS.map((n) => <button key={n} type="button" className={`n-btn sm ${days === n ? 'on' : ''}`} aria-pressed={days === n} onClick={() => setDays(n)}>{n} ngày</button>)}
      </span>}>
      {st.error && <Empty title="Không tải được regime">{st.error}</Empty>}
      {rows.length > 0 && (
        <>
          <div className="n-tblwrap">
            <table className="n-tbl n-rg">
              <thead><tr><th>Tài sản</th><th>Hiện tại</th><th>Từ</th><th>Lịch sử {days} ngày (nến {d.frame})</th><th>Chiến lược đang bật</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol}>
                    <td><b>{r.symbol.replace('@perp', '')}</b></td>
                    <td><span className={`n-rgchip n-rg-${r.current.state}`}>{r.current.label}</span></td>
                    <td className="mono">{r.current.since ? fmtDateTime(r.current.since) : '—'}</td>
                    <td style={{ minWidth: 220 }}><RegimeBar segs={r.segments} from={from} to={to} labels={labels} /></td>
                    <td>{r.strategies_on.length ? r.strategies_on.map((id) => <span key={id} className="n-badge" style={{ marginRight: 4 }} title={id}>{legLabel(id)}</span>) : <span className="muted">không chiến lược nào</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="n-rglegend">
            {(d.names || []).filter((n) => n !== 'UNKNOWN').map((n) => <span key={n}><i className={`n-rg-${n}`} />{labels[n] || n}</span>)}
          </div>
          <p className="n-note">Chiến lược đang bật = được phép vào lệnh ở regime hiện tại theo bảng regime của sổ (chỉ áp khi chạy với regime bật):
            LONG không vào khi xu hướng giảm / sập mạnh, SHORT không vào khi xu hướng tăng / tăng thẳng đứng.</p>
        </>
      )}
    </Panel>
  )
}

/* ─── Thẻ dẫn sang trang Live: tín hiệu của sổ đang chạy (kèm biểu đồ và giải thích từng điều kiện) nằm ở đó ─── */
export function LiveBotCard() {
  return (
    <Panel title="Tín hiệu & bot live" className="pf-live">
      <p>Tín hiệu live của sổ đang chạy, kèm biểu đồ nến và giải thích từng điều kiện vào/thoát, nằm ở trang Live.</p>
      <Link to="/live" className="n-btn">Mở trang Live</Link>
    </Panel>
  )
}
