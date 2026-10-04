import React, { useEffect, useMemo, useState } from 'react'
import { PageHead, Panel, Segmented, Status, Empty, Loading, ErrorState } from '../components/ui'
import SignalChart from '../components/chart/SignalChart'
import SignalExplainPanel from '../components/chart/SignalExplainPanel'
import TradeChartDrawer from '../components/chart/TradeChartDrawer'
import { fmtTs, fmtVal } from '../components/chart/chartUtil'
import useAsync from '../hooks/useAsync'
import { getLiveTrades, explainChart } from '../api'
import { fmtNum, fmtMoney, signClass, isNum } from '../lib/format'

const MODES = [{ value: 'paper', label: 'Paper' }, { value: 'demo', label: 'Demo OKX' }]
const BOOK = { main: 'sổ chính (đã kiểm định)', explore: 'sổ thử nghiệm (9 chiến lược)' }
const SRC = { exec: 'Sàn', paper: 'Paper' }
const REASON = { TP: 'Chốt lời', SL: 'Cắt lỗ', TRAIL: 'Trailing', TIMEOUT: 'Hết hạn', SIGNAL: 'Tín hiệu thoát' }
const DAY = 86400e3
const base = (s) => String(s || '').split(/[@\-/_:]/)[0].toUpperCase() // "BTC@perp" / "BTC-USDT-SWAP" -> "BTC"

// Gộp lệnh đã đóng của sàn (exec) và paper về một dạng
function mergeTrades(d) {
  const ex = (d.exec?.trades || []).map((t) => ({ src: 'exec', symbol: t.symbol, strategy: t.strategy, side: t.side, qty: t.qty, enter_ms: t.entry_time, close_ms: t.close_time, enter_price: t.avg, close_price: null, pnl: null, reason: t.reason, layers: t.layers }))
  const pa = (d.paper?.trades || []).map((t) => ({ src: 'paper', symbol: t.symbol, strategy: t.strategy, side: t.side, qty: t.qty, enter_ms: t.enter_time, close_ms: t.close_time, enter_price: t.enter_price ?? t.avg_price, close_price: t.close_price, pnl: t.pnl, reason: t.reason, layers: t.layers }))
  return [...ex, ...pa].filter((t) => isNum(t.enter_ms)).sort((a, b) => (b.close_ms || b.enter_ms) - (a.close_ms || a.enter_ms))
}
function mergePositions(d) {
  const ex = (d.exec?.positions || []).map((p) => ({ src: 'exec', symbol: p.symbol, strategy: p.strategy, side: p.side, qty: p.qty, enter_ms: p.entry_time, enter_price: p.avg ?? p.entry_price, pnl: null, layers: null }))
  const pa = (d.paper?.positions || []).map((p) => ({ src: 'paper', symbol: p.symbol, strategy: p.strategy, side: p.side, qty: p.qty, enter_ms: p.entry_time, enter_price: p.avg, pnl: p.unrealized, layers: p.layers }))
  return [...ex, ...pa].filter((t) => isNum(t.enter_ms))
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
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.id} · {s.side}{s.unvalidated ? ' · chưa kiểm định' : ''}</option>)}
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

export default function Live() {
  const [mode, setMode] = useState('paper')
  const [sel, setSel] = useState(null) // { trade, title, strategy, symbol }
  const q = useAsync(() => getLiveTrades(mode, 'okx', 200), [mode], { poll: () => 60000 })
  const d = q.data
  const trades = useMemo(() => (d ? mergeTrades(d) : []), [d])
  const positions = useMemo(() => (d ? mergePositions(d) : []), [d])
  const open = (t, open_) => setSel({ strategy: t.strategy, symbol: base(t.symbol), title: `${base(t.symbol)} ${t.side} · ${t.strategy} · ${fmtTs(t.enter_ms)}`,
    trade: { enter_ms: t.enter_ms, close_ms: open_ ? null : t.close_ms, enter_price: t.enter_price, close_price: t.close_price, side: t.side, reason: REASON[t.reason] || t.reason, pnl: t.pnl } })

  return (
    <>
      <PageHead kicker="Giao dịch tự động" title="Bot live · paper / demo" subtitle="Lệnh và vị thế của bot trên OKX (paper hoặc demo), kèm biểu đồ giải thích vì sao chiến lược vào lệnh. Danh sách tự làm mới mỗi 60 giây.">
        <Segmented label="Chế độ" value={mode} onChange={setMode} options={MODES} />
      </PageHead>

      {q.error && <ErrorState title="Không tải được dữ liệu bot live" error={q.error} onRetry={q.reload} />}
      {!q.error && !d && <Loading what="dữ liệu bot live" />}
      {d && (
        <div className="n-lv" style={{ opacity: q.loading ? 0.7 : 1 }}>
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
                        <td><span className="n-badge">{SRC[p.src]}</span></td><td>{base(p.symbol)}</td><td className="mono">{p.strategy}</td>
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
                        <td>{base(t.symbol)}</td><td className="mono">{t.strategy}</td>
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
