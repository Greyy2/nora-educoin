import React, { useEffect, useState } from 'react'
import { Panel, Empty, Spinner } from './ui'
import Term from './Term'
import { getPortfolioTrades, portfolioTradesCsvUrl, getMarketSignals, getMarketRegime } from '../api'
import { fmtNum, fmtMoney, fmtPct, fmtSPct, signClass, arrow, fmtDateTime, isNum } from '../lib/format'

/* ─── Thống kê theo HỌ chiến lược (gộp mọi bộ tham số / alpha cùng chiến lược) ─────────────────────────────── */
export function FamilyStatsPanel({ rows = [], period }) {
  if (!rows.length) return null
  return (
    <Panel title="Thống kê theo chiến lược" meta={<span>gộp mọi bộ tham số của cùng chiến lược · lệnh đã đóng trong kỳ {period}</span>}>
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
                  <td className="r">{fmtPct(t.win_rate, 1)}{t.breakeven ? <span className="muted"> · {t.breakeven} hoà</span> : null}</td>
                  <td className="r">{fmtNum(t.profit_factor)}</td>
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
const PAGE = 50
const COLS = [
  ['close_time', 'Đóng'], ['enter_time', 'Mở'], ['symbol', 'Tài sản'], ['strategy', 'Chiến lược'], [null, 'Chiều'],
  [null, 'Giá vào → ra'], ['notional', 'Danh nghĩa'], [null, 'Tầng'], ['mae_pct', 'Lỗ treo'], ['pnl', 'Lãi/lỗ'], ['pnl_pct', '% vốn'], [null, 'Lý do đóng'],
]

export function TradesPanel({ source, jobId, period }) {
  const [f, setF] = useState({ strategy: '', symbol: '', side: '', outcome: '', sort: '-close_time', offset: 0 })
  const [st, setSt] = useState({ loading: true, data: null, error: null })
  const q = { source, job_id: jobId || undefined, period, ...Object.fromEntries(Object.entries(f).filter(([, v]) => v !== '')), limit: PAGE }

  useEffect(() => { setF((x) => ({ ...x, offset: 0 })) }, [source, jobId, period])
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
    <Panel title="Danh sách lệnh" meta={<>
      <span>{st.loading ? <Spinner /> : `${total} lệnh`}</span>
      <a className="n-btn sm" href={portfolioTradesCsvUrl({ ...q, limit: undefined, offset: undefined })}>Tải CSV</a>
    </>}>
      <div className="n-filters">
        <select className="n-sel" aria-label="Chiến lược" value={f.strategy} onChange={(e) => set({ strategy: e.target.value })}>
          <option value="">Mọi chiến lược</option>
          {(d?.families || []).map((x) => <option key={`f-${x}`} value={x}>{x} (cả họ)</option>)}
          {(d?.strategies || []).filter((x) => !(d?.families || []).includes(x)).map((x) => <option key={x} value={x}>{x}</option>)}
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
      {d && (
        <div className="n-tblwrap n-sticky">
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
                  <td className="mono">{t.strategy}</td>
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
      {total > PAGE && (
        <div className="n-pager">
          <button type="button" className="n-btn sm" disabled={f.offset === 0} onClick={() => set({ offset: Math.max(0, f.offset - PAGE) })}>‹ Trước</button>
          <span className="mono">{f.offset + 1}–{Math.min(total, f.offset + PAGE)} / {total}</span>
          <button type="button" className="n-btn sm" disabled={f.offset + PAGE >= total} onClick={() => set({ offset: f.offset + PAGE })}>Sau ›</button>
        </div>
      )}
    </Panel>
  )
}

/* ─── Tín hiệu thị trường (nến 1m đã đóng cuối; cùng đường tính với backtest; dùng lại cho Live/Testnet) ─────── */
function Cond({ c }) {
  return (
    <div className={`n-cond ${c.pass ? 'ok' : 'no'}`}>
      <span className="mono">{c.left}</span> <b className="mono">{fmtNum(c.left_value, 4)}</b> <span>{c.op}</span> <span className="mono">{c.right}</span>
      {c.right_value !== null && c.right !== String(c.right_value) && <b className="mono"> {fmtNum(c.right_value, 4)}</b>}
      <span className="n-cond-mark">{c.pass ? '✓' : '✗'}</span>
    </div>
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

export function RegimePanel() {
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
    <Panel title="Regime thị trường" meta={
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
                    <td>{r.strategies_on.length ? r.strategies_on.map((id) => <span key={id} className="n-badge" style={{ marginRight: 4 }}>{id}</span>) : <span className="muted">không chiến lược nào</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="n-rglegend">
            {(d.names || []).filter((n) => n !== 'UNKNOWN').map((n) => <span key={n}><i className={`n-rg-${n}`} />{labels[n] || n}</span>)}
          </div>
          <p className="n-note">Chiến lược đang bật = được phép vào lệnh ở regime hiện tại theo bảng regime của sổ (chỉ áp khi chạy với regime bật).
            Báo cáo P2.4: bảng tĩnh chưa khớp dữ liệu — WFA dùng chế độ "học trên train" thay vì bảng này.</p>
        </>
      )}
    </Panel>
  )
}

export function MarketSignalsPanel() {
  const [st, setSt] = useState({ loading: true, data: null, error: null })
  const [open, setOpen] = useState(null)
  useEffect(() => {
    let dead = false
    getMarketSignals().then((data) => !dead && setSt({ loading: false, data, error: null }), (e) => !dead && setSt({ loading: false, data: null, error: e.message }))
    return () => { dead = true }
  }, [])
  const rows = st.data?.symbols || []
  const ids = rows.find((r) => r.strategies?.length)?.strategies.map((s) => [s.id, s.side]) || []
  const asOf = rows.map((r) => r.as_of).filter(Boolean)
  return (
    <Panel title="Tín hiệu thị trường" meta={<span>{st.loading ? <Spinner /> : asOf.length ? `nến 1m đã đóng lúc ${fmtDateTime(Math.min(...asOf))}` : ''} · tham số = preset từng chiến lược</span>}>
      {st.error && <Empty title="Không tải được tín hiệu">{st.error}</Empty>}
      {rows.length > 0 && (
        <div className="n-tblwrap">
          <table className="n-tbl n-sig">
            <thead><tr><th>Tài sản</th><th className="r">Giá</th>{ids.map(([id, side]) => <th key={id}>{id}<span className={`n-badge ${String(side).toLowerCase()}`}>{side}</span></th>)}</tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.symbol}>
                  <td><b>{r.symbol.replace('@perp', '')}</b></td>
                  <td className="mono r">{fmtNum(r.close, 4)}</td>
                  {(r.strategies || []).map((s) => {
                    const k = `${r.symbol}|${s.id}`
                    const tone = s.exit ? 'exit' : s.entry ? 'entry' : 'idle'
                    return (
                      <td key={s.id}>
                        <button type="button" className={`n-sigchip ${tone}`} aria-expanded={open === k} onClick={() => setOpen(open === k ? null : k)}
                          title={s.entry_since ? `giữ trạng thái từ ${fmtDateTime(s.entry_since)}` : undefined}>
                          {s.exit ? 'Thoát' : s.entry ? 'Vào' : '—'}
                        </button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && (() => {
        const [sym, id] = open.split('|')
        const s = rows.find((r) => r.symbol === sym)?.strategies.find((x) => x.id === id)
        if (!s) return null
        return (
          <div className="n-sigdetail">
            <h4>{sym.replace('@perp', '')} · {id} — {s.entry ? 'có tín hiệu VÀO' : 'chưa có tín hiệu vào'}{s.exit ? ' · có tín hiệu THOÁT' : ''}</h4>
            <div className="n-sigcols">
              <div><h5>Điều kiện vào (đạt một khối là đủ)</h5>{s.entry_blocks.map((b, i) => <div key={i} className={`n-block ${b.pass ? 'ok' : ''}`}>{b.conditions.map((c, j) => <Cond key={j} c={c} />)}</div>)}</div>
              <div><h5>Điều kiện thoát</h5>{s.exit_blocks.length ? s.exit_blocks.map((b, i) => <div key={i} className={`n-block ${b.pass ? 'ok' : ''}`}>{b.conditions.map((c, j) => <Cond key={j} c={c} />)}</div>) : <span className="muted">Không có (thoát bằng SL/TP/trailing/thời gian).</span>}</div>
            </div>
          </div>
        )
      })()}
    </Panel>
  )
}
