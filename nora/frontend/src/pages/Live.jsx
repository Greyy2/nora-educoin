import React, { useEffect, useMemo, useState } from 'react'
import { PageHead, Panel, Segmented, Status, Empty, Loading, ErrorState } from '../components/ui'
import SignalChart from '../components/chart/SignalChart'
import SignalExplainPanel from '../components/chart/SignalExplainPanel'
import TradeChartDrawer from '../components/chart/TradeChartDrawer'
import { fmtTs, fmtVal } from '../components/chart/chartUtil'
import useAsync from '../hooks/useAsync'
import { getLiveTrades, getLiveCompare, explainChart } from '../api'
import AreaLine from '../components/charts/AreaLine'
import { fmtNum, fmtMoney, fmtSPct, fmtPct, signClass, isNum } from '../lib/format'
import { legLabel } from '../lib/strategyLabel'

// Bot đang chạy: chế độ + sổ. Sổ thử nghiệm (khung 15m) chỉ chạy paper, song song sổ chính.
const TABS = [{ value: 'paper', label: 'Paper · sổ chính' }, { value: 'demo', label: 'Demo OKX · sổ chính' }, { value: 'paper_explore', label: 'Paper · thử nghiệm 15m' }]
const TAB = { paper: ['paper', 'main'], demo: ['demo', 'main'], paper_explore: ['paper', 'explore'] }
const BOOK = { main: 'sổ chính (đã kiểm định)', explore: 'sổ thử nghiệm (chỉ paper)' }
const SRC = { exec: 'Sàn', paper: 'Paper' }
const REASON = { TP: 'Chốt lời', SL: 'Cắt lỗ', TRAIL: 'Trailing', TIMEOUT: 'Hết hạn', SIGNAL: 'Tín hiệu thoát' }
const DAY = 86400e3
const base = (s) => String(s || '').split(/[@\-/_:]/)[0].toUpperCase() // "BTC@perp" / "BTC-USDT-SWAP" -> "BTC"

// Gộp lệnh đã đóng của sàn (exec) và paper về một dạng
function mergeTrades(d) {
  const ex = (d.exec?.trades || []).map((t) => ({ src: 'exec', symbol: t.symbol, strategy: t.strategy, side: t.side, qty: t.qty, enter_ms: t.entry_time, close_ms: t.close_time, enter_price: t.open_price ?? t.avg, close_price: t.close_price ?? null, pnl: t.pnl ?? null, reason: t.reason, layers: t.layers }))
  const pa = (d.paper?.trades || []).map((t) => ({ src: 'paper', symbol: t.symbol, strategy: t.strategy, side: t.side, qty: t.qty, enter_ms: t.enter_time, close_ms: t.close_time, enter_price: t.enter_price ?? t.avg_price, close_price: t.close_price, pnl: t.pnl, reason: t.reason, layers: t.layers }))
  return [...ex, ...pa].filter((t) => isNum(t.enter_ms)).sort((a, b) => (b.close_ms || b.enter_ms) - (a.close_ms || a.enter_ms))
}
function mergePositions(d) {
  const ex = (d.exec?.positions || []).map((p) => ({ src: 'exec', symbol: p.symbol, strategy: p.strategy, side: p.side, qty: p.qty, enter_ms: p.entry_time, enter_price: p.avg ?? p.entry_price, pnl: null, layers: null }))
  const pa = (d.paper?.positions || []).map((p) => ({ src: 'paper', symbol: p.symbol, strategy: p.strategy, side: p.side, qty: p.qty, enter_ms: p.entry_time, enter_price: p.avg, pnl: p.unrealized, layers: p.layers }))
  return [...ex, ...pa].filter((t) => isNum(t.enter_ms))
}

// MDD (%) của đường vốn: sụt giảm lớn nhất từ đỉnh
function maxDrawdownPct(vals) {
  let peak = -Infinity
  let mdd = 0
  vals.forEach((v) => { peak = Math.max(peak, v); if (peak > 0) mdd = Math.max(mdd, (peak - v) / peak * 100) })
  return mdd
}

// Tổng quan của bot live: KPI + đường vốn, toàn bộ số liệu lấy từ bot đang chạy (OKX paper/demo), không lẫn backtest
function LiveOverview({ d, trades, positions }) {
  const main = d.mode === 'paper' ? 'paper' : 'exec'   // demo/live: số liệu chính là lệnh sàn; paper bóng chỉ để đối chiếu
  const eq = d.equity_series || []
  const first = eq[0]?.equity
  const last = isNum(d.equity) ? d.equity : eq[eq.length - 1]?.equity
  const pnlPct = isNum(first) && isNum(last) && first > 0 ? (last / first - 1) * 100 : null
  const mdd = eq.length > 1 ? maxDrawdownPct(eq.map((p) => p.equity)) : null
  const dates = useMemo(() => eq.map((p) => new Date(p.t).toISOString()), [eq])
  const tiles = [
    isNum(last) && { k: 'cap', l: 'Vốn hiện tại', v: <>{fmtMoney(last)}<small> USDT</small></>, sub: eq.length ? `từ ${fmtMoney(first)} USDT` : null },
    isNum(pnlPct) && { k: 'pnl', l: 'Lãi/lỗ từ đầu', v: <span className={signClass(pnlPct)}>{fmtSPct(pnlPct)}</span>, sub: isNum(first) && isNum(last) ? `${fmtMoney(last - first, true)} USDT` : null },
    { k: 'pos', l: 'Vị thế đang mở', v: positions.filter((p) => p.src === main).length },
    { k: 'trd', l: 'Lệnh đã đóng', v: trades.filter((t) => t.src === main && isNum(t.close_ms)).length },
    main === 'exec' && { k: 'shadow', l: 'Paper bóng (đối chiếu)', v: trades.filter((t) => t.src === 'paper' && isNum(t.close_ms)).length, sub: 'lệnh mô phỏng cùng nến' },
    isNum(mdd) && { k: 'mdd', l: 'MDD', v: <span className={mdd > 0 ? 'neg' : ''}>{fmtPct(mdd)}</span>, sub: `${eq.length} nến` },
  ].filter(Boolean)
  return (
    <Panel title="Tổng quan bot" meta={<span>Dữ liệu bot live ({String(d.venue).toUpperCase()} {d.mode})</span>}>
      <div className="n-lv-kpis">
        {tiles.map((t) => (
          <div key={t.k} className="n-tile"><div className="l">{t.l}</div><div className="v">{t.v}</div>{t.sub && <div className="l">{t.sub}</div>}</div>
        ))}
      </div>
      {eq.length > 1 ? (
        <div style={{ marginTop: 12 }}>
          <AreaLine dates={dates} height={200} label="Đường vốn của bot live" valueFormat={(v) => fmtMoney(v)}
            series={[{ key: 'eq', label: 'Vốn (USDT)', values: eq.map((p) => p.equity), color: 'var(--n-accent)', area: true }]} />
        </div>
      ) : <p className="n-note" style={{ marginTop: 10 }}>Chưa đủ điểm để vẽ đường vốn (bot cần chạy thêm ít nhất hai nến).</p>}
    </Panel>
  )
}

function Explorer({ d, trades }) {
  const strategies = d.strategies || []
  const symbols = d.symbols || []
  const [sid, setSid] = useState('')
  const [sym, setSym] = useState('')
  const [selT, setSelT] = useState(null)
  const curS = strategies.find((s) => s.id === sid) ? sid : strategies[0]?.id || ''
  const curY = symbols.includes(sym) ? sym : symbols[0] || ''
  const q = useAsync(curS && curY ? () => { const now = Date.now(); return explainChart({ book: d.book_kind, strategy_id: curS, symbol: curY, source: 'okx', start: now - 60 * DAY, end: now }) } : null, [d.book_kind, curS, curY])
  const cd = q.data
  useEffect(() => { setSelT(cd?.signals?.length ? cd.signals[cd.signals.length - 1].t : null) }, [cd])
  const selected = useMemo(() => cd?.signals?.find((s) => s.t === selT) || null, [cd, selT])
  const own = useMemo(() => trades.filter((t) => t.strategy === curS && base(t.symbol) === curY).map((t) => ({ ...t, reason: REASON[t.reason] || t.reason })), [trades, curS, curY])
  return (
    <Panel title="Xem tín hiệu" meta={<button type="button" className="n-btn sm" onClick={q.reload} disabled={q.loading}>Làm mới</button>}>
      <p className="n-note" style={{ marginBottom: 8 }}>Chọn chiến lược và cặp để xem 60 ngày nến OKX gần nhất cùng các tín hiệu hiện có, kể cả khi bot chưa có lệnh nào.</p>
      <div className="n-lv-sel">
        <div className="n-field"><label htmlFor="lv-strat">Chiến lược</label>
          <select id="lv-strat" className="n-sel" value={curS} onChange={(e) => setSid(e.target.value)}>
            {strategies.map((s) => <option key={s.id} value={s.id}>{legLabel(s.id)}{s.unvalidated ? ' · chưa kiểm định' : ''}</option>)}
          </select></div>
        <div className="n-field"><label htmlFor="lv-sym">Cặp</label>
          <select id="lv-sym" className="n-sel" value={curY} onChange={(e) => setSym(e.target.value)}>
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select></div>
      </div>
      {q.error && <ErrorState title="Không dựng được biểu đồ" error={q.error} onRetry={q.reload} />}
      {!q.error && !cd && <Loading what="biểu đồ" />}
      {cd && (
        <div style={{ display: 'grid', gap: 12, opacity: q.loading ? 0.6 : 1 }}>
          <SignalChart data={cd} trades={own} selectedT={selT} onSelectSignal={(s) => setSelT(s.t)} />
          {cd.signals.length === 0 && <p className="n-note">Không có tín hiệu nào trong 60 ngày gần nhất.</p>}
          <SignalExplainPanel data={cd} selected={selected} />
        </div>
      )}
    </Panel>
  )
}

// Sàn vs paper: lệnh khớp thật trên OKX ghép với lệnh mô phỏng cùng nến -> đo độ lệch của giả lập (giá vào/đóng, tầng DCA, lệnh lệch)
function CompareFills({ book }) {
  const q = useAsync(() => getLiveCompare('demo', 'okx', book), [book], { poll: () => 120000 })
  const c = q.data
  const s = c?.summary
  const bps = (v) => (isNum(v) ? `${v > 0 ? '+' : ''}${fmtNum(v, 1)} bps` : '—')
  return (
    <Panel title="Sàn thật so với paper" meta={<span>dương = sàn khớp kém hơn giả lập</span>}>
      {q.error && <ErrorState title="Chưa so được" error={q.error} onRetry={q.reload} />}
      {s && (s.matched + s.only_exec + s.only_paper === 0
        ? <Empty title="Chưa có lệnh để so">Khi bot demo có lệnh đóng, mỗi lệnh sàn được ghép với lệnh paper cùng nến để đo chênh lệch khớp lệnh.</Empty>
        : (
          <>
            <div className="n-lv-kpis">
              <div className="n-tile"><div className="l">Cặp ghép được</div><div className="v">{s.matched}</div></div>
              <div className="n-tile"><div className="l">Chỉ paper khớp</div><div className="v">{s.only_paper}</div><div className="l">giả lập lạc quan nếu nhiều</div></div>
              <div className="n-tile"><div className="l">Chỉ sàn khớp</div><div className="v">{s.only_exec}</div></div>
              <div className="n-tile"><div className="l">Chênh giá vào TB</div><div className="v">{bps(s.entry_bps_mean)}</div></div>
              <div className="n-tile"><div className="l">Chênh giá đóng TB</div><div className="v">{bps(s.close_bps_mean)}</div></div>
              <div className="n-tile"><div className="l">Lệch số tầng DCA</div><div className="v">{s.layers_diff}</div></div>
              <div className="n-tile"><div className="l">Lãi/lỗ (% danh nghĩa)</div><div className="v"><span className={signClass(s.ret_pct_exec)}>{fmtSPct(s.ret_pct_exec, 2)}</span> sàn · <span className={signClass(s.ret_pct_paper)}>{fmtSPct(s.ret_pct_paper, 2)}</span> paper</div></div>
            </div>
            {c.pairs.length > 0 && (
              <div className="n-tblwrap" style={{ marginTop: 10 }}>
                <table className="n-tbl">
                  <thead><tr><th>Vào lúc (UTC)</th><th>Cặp</th><th>Chiến lược</th><th className="r">Chênh giá vào</th><th className="r">Chênh giá đóng</th><th className="r">Tầng (sàn / paper)</th><th className="r">Lãi % (sàn / paper)</th><th>Thoát (sàn / paper)</th></tr></thead>
                  <tbody>
                    {c.pairs.map((p, i) => (
                      <tr key={i}>
                        <td className="num">{fmtTs(p.entry_time)}</td><td>{base(p.symbol)}</td><td>{legLabel(p.strategy)}</td>
                        <td className="r">{bps(p.entry_bps)}</td><td className="r">{bps(p.close_bps)}</td>
                        <td className="r">{p.layers[0] ?? '—'} / {p.layers[1] ?? '—'}</td>
                        <td className="r">{fmtSPct(p.ret_pct[0], 2)} / {fmtSPct(p.ret_pct[1], 2)}</td>
                        <td>{REASON[p.reason[0]] || p.reason[0] || '—'} / {REASON[p.reason[1]] || p.reason[1] || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ))}
    </Panel>
  )
}

export default function Live() {
  const [tab, setTab] = useState('paper')
  const [mode, book] = TAB[tab]
  const [sel, setSel] = useState(null) // { trade, title, strategy, symbol }
  const q = useAsync(() => getLiveTrades(mode, 'okx', 200, book), [mode, book], { poll: () => 60000 })
  const d = q.data
  const trades = useMemo(() => (d ? mergeTrades(d) : []), [d])
  const positions = useMemo(() => (d ? mergePositions(d) : []), [d])
  const open = (t, open_) => setSel({ strategy: t.strategy, symbol: base(t.symbol), title: `${base(t.symbol)} ${t.side} · ${legLabel(t.strategy)} · ${fmtTs(t.enter_ms)}`,
    trade: { enter_ms: t.enter_ms, close_ms: open_ ? null : t.close_ms, enter_price: t.enter_price, close_price: t.close_price, side: t.side, reason: REASON[t.reason] || t.reason, pnl: t.pnl } })

  return (
    <>
      <PageHead kicker="Giao dịch tự động" title="Bot live · paper / demo" subtitle="Lệnh và vị thế của bot trên OKX (paper hoặc demo), kèm biểu đồ giải thích vì sao chiến lược vào lệnh. Danh sách tự làm mới mỗi 60 giây.">
        <Segmented label="Bot" value={tab} onChange={setTab} options={TABS} />
      </PageHead>

      {q.error && <ErrorState title="Không tải được dữ liệu bot live" error={q.error} onRetry={q.reload} />}
      {!q.error && !d && <Loading what="dữ liệu bot live" />}
      {d && (
        <div className="n-lv" style={{ opacity: q.loading ? 0.7 : 1 }}>
          <LiveOverview d={d} trades={trades} positions={positions} />
          {mode === 'demo' && <CompareFills book={book} />}

          <Panel title="Tóm tắt" meta={<button type="button" className="n-btn sm" onClick={q.reload} disabled={q.loading}>Làm mới</button>}>
            <dl className="n-ex-kv n-lv-sum">
              <div><dt>Trạng thái</dt><dd>{d.running?.length ? <Status tone="ok">đang chạy <span className="mono">{d.running.join(', ')}</span></Status> : <Status tone="warn">không chạy</Status>}</dd></div>
              <div><dt>Vốn</dt><dd className="mono">{isNum(d.equity) ? `${fmtMoney(d.equity)} USDT` : '—'}</dd></div>
              <div><dt>Sổ chiến lược</dt><dd>{BOOK[d.book_kind] || d.book_kind}</dd></div>
              <div><dt>Khung · Cặp</dt><dd className="mono">{d.timeframe} · {d.symbols?.length || 0} cặp</dd></div>
              <div><dt>Sàn · Chế độ</dt><dd className="mono">{d.venue} · {d.mode}</dd></div>
            </dl>
          </Panel>

          <Panel title="Vị thế đang mở" meta={<span>{positions.length} vị thế</span>}>
            {!positions.length ? <Empty title="Chưa có vị thế đang mở">Bot chưa vào lệnh nào. Dùng mục “Xem tín hiệu” bên dưới để xem tín hiệu hiện tại.</Empty> : (
              <div className="n-tblwrap">
                <table className="n-tbl">
                  <thead><tr><th>Nguồn</th><th>Cặp</th><th>Chiến lược</th><th>Hướng</th><th className="r">Khối lượng</th><th className="r">Giá vào</th><th>Vào lúc (UTC)</th><th className="r">Lãi/lỗ tạm</th><th>Biểu đồ</th></tr></thead>
                  <tbody>
                    {positions.map((p, i) => (
                      <tr key={`${p.src}${i}`}>
                        <td><span className="n-badge">{SRC[p.src]}</span></td><td>{base(p.symbol)}</td><td title={p.strategy}>{legLabel(p.strategy)}</td>
                        <td><span className={`n-badge ${String(p.side).toLowerCase()}`}>{p.side}</span></td>
                        <td className="r">{fmtNum(p.qty, 4)}</td><td className="r">{fmtVal(p.enter_price)}</td><td className="num">{fmtTs(p.enter_ms)}</td>
                        <td className={`r ${signClass(p.pnl)}`}>{isNum(p.pnl) ? fmtMoney(p.pnl, true) : '—'}</td>
                        <td><button type="button" className="n-btn sm" onClick={() => open(p, true)}>Biểu đồ</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Lệnh đã đóng" meta={<span>{trades.length} lệnh</span>}>
            {!trades.length ? <Empty title="Chưa có lệnh nào">Bot mới chạy nên chưa có lệnh đã đóng.</Empty> : (
              <div className="n-tblwrap long">
                <table className="n-tbl">
                  <thead><tr><th>Nguồn</th><th>Vào lúc (UTC)</th><th>Đóng lúc (UTC)</th><th>Cặp</th><th>Chiến lược</th><th>Hướng</th><th className="r">Giá vào</th><th className="r">Giá ra</th><th className="r">Khối lượng</th><th className="r">Lãi/lỗ (USD)</th><th>Thoát</th><th className="r">Lớp</th><th>Biểu đồ</th></tr></thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <tr key={`${t.src}${i}`}>
                        <td><span className="n-badge">{SRC[t.src]}</span></td><td className="num">{fmtTs(t.enter_ms)}</td><td className="num">{fmtTs(t.close_ms)}</td>
                        <td>{base(t.symbol)}</td><td title={t.strategy}>{legLabel(t.strategy)}</td>
                        <td><span className={`n-badge ${String(t.side).toLowerCase()}`}>{t.side}</span></td>
                        <td className="r">{fmtVal(t.enter_price)}</td><td className="r">{fmtVal(t.close_price)}</td><td className="r">{fmtNum(t.qty, 4)}</td>
                        <td className={`r ${signClass(t.pnl)}`}>{isNum(t.pnl) ? fmtMoney(t.pnl, true) : '—'}</td>
                        <td>{REASON[t.reason] || t.reason || '—'}</td><td className="r">{t.layers ?? '—'}</td>
                        <td><button type="button" className="n-btn sm" onClick={() => open(t, false)}>Biểu đồ</button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Explorer d={d} trades={trades} />
        </div>
      )}

      {sel && (
        <TradeChartDrawer open onClose={() => setSel(null)} title={sel.title} trade={sel.trade}
          request={{ book: d?.book_kind, strategy_id: sel.strategy, symbol: sel.symbol, source: 'okx' }} />
      )}
    </>
  )
}
