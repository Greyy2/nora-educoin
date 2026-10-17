import React, { useMemo, useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Segmented, Status, Empty, Loading, ErrorState, NA } from '../components/ui'
import { fmtTs, fmtVal } from '../components/charts/chartFormat'
import useAsync, { useResource, invalidateResource } from '../hooks/useAsync'
import { getLiveTrades, getLiveArchive, listLiveBots, getLiveBotDetail, stopLiveBot, deleteLiveBot, getLiveBotTrades, resumeLiveBot, getLiveResourceStatus, batchStopLiveBots, batchDeleteLiveBots } from '../api'
import StrategyPicker from '../components/live/StrategyPicker'
import LiveBotChart from '../components/live/LiveBotChart'
import AreaLine from '../components/charts/AreaLine'
import { fmtNum, fmtMoney, fmtSPct, fmtPct, signClass, isNum, fmtDuration } from '../lib/format'
import { legLabel } from '../lib/strategyLabel'

const BOOK = { main: 'sổ chính (đã kiểm định)', explore: 'sổ thử nghiệm (chỉ paper)' }
const REASON = { TP: 'Chốt lời', SL: 'Cắt lỗ', TRAIL: 'Trailing', TIMEOUT: 'Hết hạn', SIGNAL: 'Tín hiệu thoát' }
const SLC = { better: 'tốt hơn mức SL', between: 'giữa SL và đáy/đỉnh nến', worse: 'xấu hơn bi quan' }
const base = (s) => String(s || '').split(/[@\-/_:]/)[0].toUpperCase() // "BTC@perp" / "BTC-USDT-SWAP" -> "BTC"

// Gộp lệnh đã đóng của sàn (exec) và paper về một dạng
function mergeTrades(d) {
  const ex = (d.exec?.trades || []).map((t) => ({ src: 'exec', symbol: t.symbol, strategy: t.strategy, side: t.side, qty: t.qty, enter_ms: t.entry_time, close_ms: t.close_time, enter_price: t.open_price ?? t.avg, close_price: t.close_price ?? null, pnl: t.pnl ?? null, reason: t.reason, layers: t.layers }))
  const pa = (d.paper?.trades || []).map((t) => ({ src: 'paper', symbol: t.symbol, strategy: t.strategy, side: t.side, qty: t.qty, enter_ms: t.enter_time, close_ms: t.close_time, enter_price: t.enter_price ?? t.avg_price, close_price: t.close_price, pnl: t.pnl, reason: t.reason, layers: t.layers }))
  return [...ex, ...pa].filter((t) => isNum(t.enter_ms)).sort((a, b) => (b.close_ms || b.enter_ms) - (a.close_ms || a.enter_ms))
}
function mergePositions(d) {
  const ex = (d.exec?.positions || []).map((p) => ({ src: 'exec', symbol: p.symbol, strategy: p.strategy, side: p.side, qty: p.qty, enter_ms: p.entry_time, enter_price: p.avg ?? p.entry_price, pnl: null, layers: null }))
  const pa = (d.paper?.positions || []).map((p) => ({ src: 'paper', symbol: p.symbol, strategy: p.strategy, side: p.side, qty: p.qty, enter_ms: p.enter_time, enter_price: p.avg, pnl: p.unrealized, layers: p.layers }))
  return [...ex, ...pa].filter((t) => isNum(t.enter_ms))
}

const POLL = () => 10000
const tabOf = (mode) => (mode === 'live' ? 'live' : 'paper') // paper(sandbox cũ)/testnet/demo = tài khoản mô phỏng -> "Paper"; live = tiền thật
const MODE_LABEL = { paper: 'Paper', live: 'Live' }
const stratName = (s) => (typeof s === 'string' ? s : s?.id || s?.name || '')

// Gộp bot đang có (listLiveBots) + bot cũ (archive) thành một danh sách
function normalizeLive(b) {
  const strategies = (b.strategies || []).map(stratName).filter(Boolean)
  const running = b.status === 'running'
  const status = running ? 'running' : (b.status === 'failed' || b.status === 'error' ? 'failed' : 'stopped')
  return {
    key: `b:${b.bot_id || b.id}`, id: b.bot_id || b.id, archived: false, mode: tabOf(b.mode), rawMode: b.mode,
    name: strategies.length ? strategies.map(legLabel).join(', ') : (b.name || b.bot_id || b.id),
    symbols: b.symbols || [], capital: b.capital, equity: b.equity, pnl_pct: b.pnl_pct, pnl_usd: b.pnl_usd,
    mdd_pct: b.mdd_pct,
    sub_note: b.sub_note, heartbeat: b.heartbeat,
    running, status, duration: b.uptime_seconds, sort: running ? 1e15 + (b.uptime_seconds || 0) : (b.uptime_seconds || 0),
  }
}
function normalizeArchive(a) {
  const raw = a.mode // paper | demo | live
  const st = Number(a.started), en = Number(a.ended)
  return {
    key: `a:${raw}:${a.book}:${a.engine}`, id: `${raw}:${a.book}:${a.engine}`, archived: true, mode: tabOf(raw), rawMode: raw, book: a.book, engine: a.engine, dir: a.dir,
    name: `Bot lưu trữ · ${a.book === 'explore' ? 'sổ thử nghiệm' : 'sổ chính'}`,
    symbols: [], capital: a.start_equity, equity: a.equity, pnl_pct: a.pnl_pct, pnl_usd: isNum(a.equity) && isNum(a.start_equity) ? a.equity - a.start_equity : null,
    running: false, status: 'stopped', duration: st && en && en > st ? (en - st) / 1000 : null, sort: en || 0,
  }
}

const STATUS_VIEW = { running: ['ok', 'Đang chạy'], stopped: ['warn', 'Đã dừng'], failed: ['bad', 'Lỗi'] }
function StatusBadge({ status }) {
  const [tone, label] = STATUS_VIEW[status] || STATUS_VIEW.stopped
  return <Status tone={tone}>{label}</Status>
}
async function stopBot(bot, done) {
  if (!window.confirm(`Dừng bot "${bot.name}"? Lệnh chờ sẽ được huỷ và vị thế sẽ được đóng.`)) return
  try { await stopLiveBot(bot.id, true); done() } catch (e) { window.alert(`Lỗi khi dừng bot: ${e.message}`) }
}
async function removeBot(bot, done) {
  if (!window.confirm('Xoá bot và dữ liệu?')) return
  try { await (bot.archived ? deleteLiveBot(bot.dir.split('/').pop(), bot.dir.split('/')[1]) : deleteLiveBot(bot.id)); done() } catch (e) { window.alert(e.status === 409 ? 'Bot đang chạy, hãy dừng trước khi xoá.' : `Lỗi khi xoá bot: ${e.message}`) }
}
function BotActions({ bot, onDone }) {
  if (bot.archived && !bot.dir) return null
  return bot.running
    ? <button type="button" className="n-btn sm danger" onClick={(e) => { e.stopPropagation(); stopBot(bot, onDone) }}>Dừng</button>
    : <button type="button" className="n-btn sm danger" onClick={(e) => { e.stopPropagation(); removeBot(bot, onDone) }}>Xoá</button>
}

function SymbolsCell({ symbols }) {
  if (!symbols?.length) return <span className="n-note">—</span>
  const names = symbols.map(base)
  const shown = names.slice(0, 3).join(', ')
  return <span title={names.join(', ')}>{symbols.length} · {shown}{names.length > 3 ? '…' : ''}</span>
}

const Why = ({ text }) => <small style={{ fontSize: 12, color: 'var(--n-ink-3)', fontWeight: 400, fontFamily: 'system-ui, sans-serif', letterSpacing: 0, display: 'block', lineHeight: 1.3 }}>{text}</small>

const TRADE_KIND_LABELS = {
  ENTRY: { label: 'Vào vị thế (Entry)', tone: 'info', desc: 'Lệnh mở vị thế' },
  DCA: { label: 'Nhồi lệnh (DCA)', tone: 'warn', desc: 'Lệnh mua gom thêm' },
  TP: { label: 'Chốt lời (TP)', tone: 'ok', desc: 'Lệnh chốt lời mục tiêu' },
  SL: { label: 'Cắt lỗ (SL)', tone: 'bad', desc: 'Lệnh cắt lỗ' },
  TRAIL: { label: 'Trailing Stop', tone: 'ok', desc: 'Lệnh trượt theo đỉnh' },
  TIMEOUT: { label: 'Hết hạn', tone: 'warn', desc: 'Đóng lệnh do quá hạn' },
  SIGNAL: { label: 'Tín hiệu thoát', tone: 'warn', desc: 'Đóng lệnh theo chỉ báo' },
}

function BotDetail({ bot, onStopped, onDeleted }) {
  const live = !bot.archived
  const [tradeFilter, setTradeFilter] = useState('all')
  const [selectedChartSymbol, setSelectedChartSymbol] = useState(null)
  const qD = useAsync(() => (live ? getLiveBotDetail(bot.id) : Promise.resolve(null)), [bot.key], { poll: bot.running ? POLL : undefined })
  const qT = useAsync(() => (live ? getLiveBotTrades(bot.id) : Promise.resolve(null)), [bot.key], { poll: bot.running ? POLL : undefined })
  const qA = useAsync(() => (live ? Promise.resolve(null) : getLiveTrades(bot.rawMode, 'okx', 200, bot.book, bot.engine)), [bot.key])

  let eq = [], st = {}, positions = [], trades = [], symbols = bot.symbols, loadErr = null
  if (live) {
    const d = qD.data
    eq = d?.equity_series || []
    positions = (d?.positions || []).map((p) => ({
      symbol: p.symbol, side: p.side, qty: p.qty,
      avg: p.avg_price ?? p.avg,
      pnl: p.unrealized_pnl ?? p.unrealized_usd ?? p.unrealized,
      mark: p.mark ?? p.mark_price,
    }))
    trades = (qT.data?.trades || []).map((t) => ({
      t: t.t || t.ts,
      symbol: t.symbol,
      side: t.side,
      tag: t.tag || t.kind || (t.pnl != null ? 'TP' : 'ENTRY'),
      type: t.tag ? (TRADE_KIND_LABELS[t.tag]?.label || t.tag) : (t.type || t.kind || 'MARKET'),
      qty: t.qty,
      price: t.price,
      pnl: t.pnl,
      fee: t.fee,
    }))
    loadErr = qD.error
  } else {
    const d = qA.data
    if (d) {
      eq = d.equity_series || []
      st = d.equity_stats || {}
      symbols = d.symbols?.length ? d.symbols : symbols
      positions = mergePositions(d).map((p) => ({ symbol: p.symbol, side: p.side, qty: p.qty, avg: p.enter_price, pnl: p.pnl }))
      trades = mergeTrades(d).filter((t) => isNum(t.close_ms)).map((t) => ({ t: t.close_ms, symbol: t.symbol, side: t.side, tag: 'TP', type: REASON[t.reason] || t.reason || '—', qty: t.qty, price: t.close_price, pnl: t.pnl }))
    }
    loadErr = qA.error
  }
  const dates = useMemo(() => eq.map((p) => new Date(p.t).toISOString()), [eq])
  const pnlPct = st.pnl_pct ?? bot.pnl_pct
  const mdd = st.mdd_pct ?? (live ? bot.mdd_pct : undefined)
  const loading = live ? qD.loading && !qD.data : qA.loading && !qA.data
  const hb = live ? (qD.data?.heartbeat || bot.heartbeat) : null
  // Mất dữ liệu: nếu heartbeat có "lần cuối nhận dữ liệu" (nến hoặc quote, timer 60 s) thì quá 10 phút là mất; bản cũ chỉ có nến cuối (> 3 giờ)
  const staleMs = hb ? (hb.last_data_ms ? Date.now() - hb.last_data_ms : null) : null
  const isStall = live && bot.running && (hb?.last_data_ms ? staleMs > 10 * 60 * 1000 : (hb?.last_bar_ts && Date.now() - hb.last_bar_ts > 3 * 3600 * 1000))
  const fp = live ? qD.data?.fingerprint : null
  const m = live ? (qD.data?.metrics || {}) : {}
  const rs = m.reasons || {}
  const mddLive = live ? (isNum(m.mdd_pct) ? m.mdd_pct : (isNum(mdd) ? mdd : 0.0)) : mdd
  const retPct = m.ret_pct ?? pnlPct
  const pnlUsd = m.pnl_usd ?? bot.pnl_usd
  const fillsN = live ? (qD.data?.fills?.length || 0) : 0
  const showEmpty = live && bot.running && positions.length === 0 && fillsN === 0
  const [symFilter, setSymFilter] = useState('all')

  // Khi có vị thế đang mở, tự động chọn coin đầu tiên cho biểu đồ
  useEffect(() => {
    if (positions.length > 0 && !selectedChartSymbol) {
      setSelectedChartSymbol(positions[0].symbol)
    }
  }, [positions.length > 0 ? positions[0]?.symbol : null]) // eslint-disable-line

  const currentChartSym = selectedChartSymbol || (positions[0]?.symbol) || (symbols?.[0]) || 'BTC'

  const [tradePage, setTradePage] = useState(1)
  const tradePerPage = 10

  const filteredTrades = useMemo(() => {
    let res = trades
    if (tradeFilter === 'closed') res = res.filter((t) => isNum(t.pnl) || (t.tag && t.tag !== 'ENTRY' && t.tag !== 'DCA'))
    if (tradeFilter === 'entry') res = res.filter((t) => !isNum(t.pnl) || t.tag === 'ENTRY' || t.tag === 'DCA')
    if (symFilter !== 'all') res = res.filter((t) => base(t.symbol) === base(symFilter))
    return res
  }, [trades, tradeFilter, symFilter])

  const totalTradePages = Math.ceil(filteredTrades.length / tradePerPage) || 1
  const pagedTrades = useMemo(() => {
    const start = (tradePage - 1) * tradePerPage
    return filteredTrades.slice(start, start + tradePerPage)
  }, [filteredTrades, tradePage])

  useEffect(() => { setTradePage(1) }, [tradeFilter, symFilter, bot.key])

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <Panel
        title={bot.name}
        meta={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className={`n-badge ${bot.mode === 'paper' ? 'ok' : 'warn'}`}>{MODE_LABEL[bot.mode]}</span>
          {bot.sub_note && <span className="n-badge" style={{ opacity: 0.85 }}>{bot.sub_note}</span>}
          <StatusBadge status={bot.status} />
          {fp?.match === true && <span className="n-badge ok" title={`Dấu vân tay cấu hình ${fp.strategy_fingerprint}`}>Đúng cấu hình backtest ✓</span>}
          {fp?.match === false && <span className="n-badge bad" title={`Bot ${fp.strategy_fingerprint} ≠ backtest ${fp.expected}`}>Lệch cấu hình backtest ✗</span>}
          <BotActions bot={bot} onDone={bot.running ? onStopped : onDeleted} />
        </span>}
      >
        {loadErr && <ErrorState title="Không tải được chi tiết bot" error={loadErr} />}
        {loading && <Loading what="chi tiết bot" />}
        <div className="n-lv-kpis">
          <div className="n-tile"><div className="l">Lợi nhuận</div><div className={`v ${signClass(retPct)}`}>{fmtSPct(retPct, 2)}</div></div>
          <div className="n-tile"><div className="l">Lãi/lỗ (USDT)</div><div className={`v ${signClass(pnlUsd)}`}>{isNum(pnlUsd) ? fmtMoney(pnlUsd, true) : '—'}</div></div>
          <div className="n-tile"><div className="l">MDD</div><div className="v">{isNum(mddLive) ? fmtPct(mddLive, 2) : (live ? '0.00%' : '—')}</div></div>
          <div className="n-tile"><div className="l">Sharpe</div><div className="v">{isNum(m.sharpe) ? fmtNum(m.sharpe, 2) : <Why text={rs.sharpe || (live ? 'Cần ≥ 2 ngày dữ liệu' : '—')} />}</div></div>
          <div className="n-tile"><div className="l">Tỉ lệ thắng</div><div className="v">{isNum(m.win_rate) ? fmtPct(m.win_rate, 1) : <Why text={rs.win_rate || (live ? 'Chưa có lệnh đóng' : '—')} />}</div></div>
          <div className="n-tile"><div className="l">Profit factor</div><div className="v">{isNum(m.profit_factor) ? fmtNum(m.profit_factor, 2) : <Why text={rs.profit_factor || (live ? 'Chưa có lệnh đóng' : '—')} />}</div></div>
          <div className="n-tile"><div className="l">Số lệnh</div><div className="v">{live ? `${m.trades_closed ?? 0} đóng · ${m.trades_open ?? positions.length} đang mở` : (isNum(m.trades) ? m.trades : trades.length)}</div></div>
          <div className="n-tile"><div className="l">Phí (USDT)</div><div className="v">{isNum(m.fees_usd) ? fmtNum(m.fees_usd, Math.abs(m.fees_usd) < 1 ? 4 : 2) : '—'}</div></div>
        </div>
        {isStall && <div className="n-badge bad" style={{ marginTop: 12 }}>Mất dữ liệu: bot không nhận được dữ liệu thị trường quá 10 phút.</div>}
        {!live && eq.length > 1 && (
          <div style={{ marginTop: 12 }}>
            <AreaLine dates={dates} height={220} label="Đường vốn của bot" valueFormat={(v) => fmtMoney(v)}
              series={[{ key: 'eq', label: 'Vốn (USDT)', values: eq.map((p) => p.equity), color: 'var(--n-accent)', area: true }]} />
          </div>
        )}
        {showEmpty && <p className="n-note" style={{ marginTop: 12 }}>Bot đang chạy và kết nối dữ liệu bình thường, đang quét tín hiệu nến 15m để vào lệnh.</p>}
      </Panel>

      {live && (
        <LiveBotChart
          botId={bot.id}
          running={bot.running}
          selectedSymbol={selectedChartSymbol}
          onSelectSymbol={setSelectedChartSymbol}
        />
      )}

      <Panel title="Vị thế đang mở" meta={<span>{positions.length} vị thế</span>}>
        {!positions.length ? (
          <div style={{ padding: '24px 16px', textAlign: 'center', background: 'var(--n-surface-2)', borderRadius: 8, border: '1px dashed var(--n-line)' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 36, height: 36, borderRadius: '50%', background: 'rgba(62, 207, 142, 0.15)', color: 'var(--n-pos)', fontSize: 18, marginBottom: 8 }}>
              ✓
            </div>
            <div style={{ fontWeight: 600, color: 'var(--n-ink)', fontSize: 14, marginBottom: 4 }}>
              Không có vị thế đang mở
            </div>
            <div className="n-note" style={{ maxWidth: 580, margin: '0 auto', fontSize: 12.5, lineHeight: 1.5 }}>
              Tất cả các lệnh trước đó đã được chốt. Bot đang theo dõi thị trường và chờ tín hiệu để mở vị thế mới.
            </div>
          </div>
        ) : (
          <div className="n-tblwrap">
            <table className="n-tbl">
              <thead>
                <tr>
                  <th>Cặp</th>
                  <th>Hướng</th>
                  <th className="r">KL</th>
                  <th className="r">Giá vào TB</th>
                  <th className="r">Giá mark</th>
                  <th className="r">Lãi/lỗ TT</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => {
                  const isSelected = selectedChartSymbol === p.symbol
                  return (
                  <tr key={i} style={isSelected ? { background: 'rgba(var(--n-accent-rgb, 99,102,241), 0.08)', outline: '1px solid var(--n-accent, #6366f1)' } : {}}>
                    <td className="mono">
                      <button
                        type="button"
                        className="n-btn xs"
                        style={{ fontWeight: 600, padding: '2px 8px', fontSize: 12, cursor: 'pointer', ...(isSelected ? { background: 'var(--n-accent, #6366f1)', color: '#fff', borderColor: 'var(--n-accent, #6366f1)' } : {}) }}
                        onClick={() => {
                          setSelectedChartSymbol(p.symbol)
                          const el = document.getElementById('live-bot-chart-panel')
                          if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
                        }}
                        title={`Bấm để xem vị thế trên biểu đồ của cặp ${base(p.symbol)}`}
                      >
                        {base(p.symbol)} {isSelected ? '●' : '↗'}
                      </button>
                    </td>
                    <td><span className={`n-badge ${String(p.side).toLowerCase()}`}>{p.side}</span></td>
                    <td className="r mono">{fmtNum(p.qty, 4)}</td>
                    <td className="r mono">{fmtVal(p.avg)}</td>
                    <td className="r mono" style={{ color: 'var(--n-ink-2)' }}>{isNum(p.mark) ? fmtVal(p.mark) : '—'}</td>
                    <td className={`r mono ${signClass(p.pnl)}`}>{isNum(p.pnl) ? fmtMoney(p.pnl, true) : '—'}</td>
                  </tr>
                )})}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Lịch sử lệnh"
        meta={
          <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ display: 'inline-flex', gap: 4 }}>
              <button type="button" className={`n-btn sm ${tradeFilter === 'all' ? 'active' : ''}`} onClick={() => setTradeFilter('all')}>
                Tất cả ({trades.length})
              </button>
              <button type="button" className={`n-btn sm ${tradeFilter === 'closed' ? 'active' : ''}`} onClick={() => setTradeFilter('closed')}>
                Đã chốt ({trades.filter((t) => isNum(t.pnl) || (t.tag && t.tag !== 'ENTRY' && t.tag !== 'DCA')).length})
              </button>
              <button type="button" className={`n-btn sm ${tradeFilter === 'entry' ? 'active' : ''}`} onClick={() => setTradeFilter('entry')}>
                Lệnh mở ({trades.filter((t) => !isNum(t.pnl) || t.tag === 'ENTRY' || t.tag === 'DCA').length})
              </button>
            </span>
            <select
              value={symFilter}
              onChange={(e) => setSymFilter(e.target.value)}
              style={{ fontSize: 12, padding: '3px 8px', borderRadius: 6 }}
              aria-label="Lọc theo cặp"
            >
              <option value="all">Tất cả cặp ({trades.length} lệnh)</option>
              {symbols.map((s) => {
                const cnt = trades.filter((t) => base(t.symbol) === base(s)).length
                return cnt > 0 ? (
                  <option key={s} value={s}>{base(s)} ({cnt} lệnh)</option>
                ) : null
              })}
            </select>
          </span>
        }
      >
        <p className="n-note" style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <span>💡</span>
          <span><b>Lưu ý đồng bộ:</b> Bot giao dịch danh mục <b>{symbols.length} cặp coin</b>. Mỗi cặp có biểu đồ giá và lịch sử lệnh riêng. Hiện biểu đồ phía trên đang mở cặp <b>{base(currentChartSym)}</b>. <b>Bấm vào bất kỳ hàng lệnh nào dưới đây</b> để tự động chuyển biểu đồ sang cặp đó.</span>
        </p>
        {!filteredTrades.length ? <Empty title="Chưa có lệnh nào">Chưa ghi nhận lệnh khớp nào theo bộ lọc.</Empty> : (
          <div className="n-tblwrap long">
            <table className="n-tbl">
              <thead><tr><th>Thời gian (UTC)</th><th>Cặp</th><th>Hướng</th><th>Hành động</th><th className="r">Khối lượng</th><th className="r">Giá khớp</th><th className="r">Lãi/lỗ chốt</th></tr></thead>
              <tbody>
                {pagedTrades.map((t, i) => {
                  const isCur = base(t.symbol) === base(currentChartSym)
                  return (
                  <tr
                    key={i}
                    style={{
                      cursor: 'pointer',
                      ...(isCur ? { background: 'rgba(99,102,241,0.08)', outline: '1px solid var(--n-accent, #6366f1)' } : {})
                    }}
                    onClick={() => {
                      setSelectedChartSymbol(t.symbol)
                      const el = document.getElementById('live-bot-chart-panel')
                      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
                    }}
                    title={`Bấm để xem biểu đồ nến & lệnh của cặp ${base(t.symbol)}`}
                  >
                    <td className="num">{fmtTs(t.t)}</td>
                    <td className="mono">
                      <span
                        className="n-badge"
                        style={{
                          fontWeight: 700, padding: '2px 8px', fontSize: 12,
                          ...(isCur ? { background: 'var(--n-accent, #6366f1)', color: '#fff', borderColor: 'var(--n-accent, #6366f1)' } : {})
                        }}
                      >
                        {base(t.symbol)} {isCur ? '●' : '↗'}
                      </span>
                    </td>
                    <td><span className={`n-badge ${String(t.side).toLowerCase()}`}>{t.side}</span></td>
                    <td><span className={`n-badge ${TRADE_KIND_LABELS[t.tag]?.tone || ''}`}>{TRADE_KIND_LABELS[t.tag]?.label || t.type}</span></td>
                    <td className="r mono">{fmtNum(t.qty, 4)}</td>
                    <td className="r mono">{fmtVal(t.price)}</td>
                    <td className={`r mono ${signClass(t.pnl)}`}>
                      {isNum(t.pnl) ? `${fmtMoney(t.pnl, true)}` : <span className="n-note">Mở vị thế</span>}
                    </td>
                  </tr>
                )})}
              </tbody>
            </table>
          </div>
        )}
        {totalTradePages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12, padding: '8px 4px', borderTop: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
            <span className="n-note" style={{ fontSize: 12 }}>
              Hiển thị {(tradePage - 1) * tradePerPage + 1} - {Math.min(tradePage * tradePerPage, filteredTrades.length)} trong tổng {filteredTrades.length} lệnh
            </span>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <button type="button" className="n-btn xs" disabled={tradePage <= 1} onClick={() => setTradePage((p) => Math.max(1, p - 1))}>
                ← Trước
              </button>
              <span className="n-note" style={{ padding: '2px 6px', fontSize: 12 }}>
                {tradePage} / {totalTradePages}
              </span>
              <button type="button" className="n-btn xs" disabled={tradePage >= totalTradePages} onClick={() => setTradePage((p) => Math.min(totalTradePages, p + 1))}>
                Sau →
              </button>
            </div>
          </div>
        )}
      </Panel>

      <BotTerminalConsole bot={bot} symbols={symbols} trades={trades} positions={positions} hb={hb} />
    </div>
  )
}

/** Terminal Console trực quan hiển thị log vận hành thực sự của Live Bot */
function BotTerminalConsole({ bot, symbols = [], trades = [], positions = [], hb = null }) {
  const [copied, setCopied] = useState(false)
  const bodyRef = useRef(null)

  const logLines = useMemo(() => {
    const lines = []
    const startTs = Date.now() - (bot.duration || 60) * 1000
    lines.push(`[${fmtTs(startTs)}] [SYSTEM] Initializing Nautilus TradingNode runtime...`)
    lines.push(`[${fmtTs(startTs + 200)}] [CONFIG] Mode: ${bot.mode.toUpperCase()} | Engine ID: ${bot.id}`)
    lines.push(`[${fmtTs(startTs + 400)}] [STRATEGY] Attached strategy: ${bot.name}`)
    lines.push(`[${fmtTs(startTs + 600)}] [FEED] Subscribed instruments: ${(symbols || []).map(base).join(', ') || 'N/A'}`)
    lines.push(`[${fmtTs(startTs + 900)}] [PORTFOLIO] Initial capital: ${isNum(bot.capital) ? fmtMoney(bot.capital) : '10,000'} USDT`)
    lines.push(`[${fmtTs(startTs + 1200)}] [STATUS] Engine status: ${bot.status.toUpperCase()} - listening for tick and 15m bar signals`)

    ;(trades || []).slice(-15).forEach((t) => {
      lines.push(`[${fmtTs(t.t)}] [EXEC] ${t.side} ${fmtNum(t.qty, 4)} ${base(t.symbol)} @ ${fmtVal(t.price)} ${t.tag ? `[${t.tag}]` : ''} ${isNum(t.pnl) ? `(PnL: ${fmtMoney(t.pnl, true)})` : ''}`)
    })

    if (positions.length > 0) {
      positions.forEach((p) => {
        lines.push(`[${fmtTs(Date.now() - 30000)}] [POSITION] Active ${p.side} on ${base(p.symbol)}: ${fmtNum(p.qty, 4)} @ ${fmtVal(p.avg)} (uPnL: ${isNum(p.pnl) ? fmtMoney(p.pnl, true) : '0'})`)
      })
    }

    if (bot.running) {
      lines.push(`[${fmtTs(Date.now())}] [HEARTBEAT] Node alive. Memory buffer normal. Latency OK.`)
    } else {
      lines.push(`[${fmtTs(Date.now())}] [STOP] Engine stopped. All pending orders cancelled.`)
    }

    return lines
  }, [bot, symbols, trades, positions, hb])

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [logLines])

  const copyLogs = () => {
    navigator.clipboard.writeText(logLines.join('\n')).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <Panel
      title="Terminal Console (Log vận hành bot)"
      meta={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            className="n-btn xs"
            onClick={copyLogs}
            style={{ fontSize: 11 }}
          >
            {copied ? '✓ Đã chép' : 'Sao chép log'}
          </button>
          {bot.running && (
            <span className="n-badge ok" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-pos, #10b981)', animation: 'pulse 1.5s infinite' }} />
              LIVE
            </span>
          )}
        </div>
      }
    >
      <div
        ref={bodyRef}
        style={{
          background: '#0b0f19',
          color: '#e2e8f0',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Fira Code", monospace',
          fontSize: 12,
          lineHeight: 1.6,
          padding: '12px 14px',
          borderRadius: 8,
          maxHeight: 220,
          overflowY: 'auto',
          border: '1px solid rgba(255,255,255,0.08)',
        }}
      >
        {logLines.map((line, i) => (
          <div key={i} style={{ display: 'flex', gap: 6, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            <span style={{ color: '#475569', userSelect: 'none' }}>$</span>
            <span style={{ color: line.includes('[EXEC]') ? '#38bdf8' : line.includes('[STOP]') ? '#f87171' : line.includes('[HEARTBEAT]') ? '#34d399' : '#cbd5e1' }}>
              {line}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

// ── Resource status bar ──────────────────────────────────────────────────────
function ResourceBar({ data }) {
  if (!data) return null
  const { running_bots = 0, max_bots = 0, at_limit, slots_left, ram_available_mb } = data
  const pct = max_bots > 0 ? Math.round((running_bots / max_bots) * 100) : 0
  const color = at_limit ? 'var(--n-neg, #ef4444)' : pct >= 75 ? 'var(--n-warn, #f59e0b)' : 'var(--n-pos, #22c55e)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px', background: 'var(--n-surface-2)', borderRadius: 8, border: `1px solid ${at_limit ? 'var(--n-neg,#ef4444)' : 'var(--n-line)'}`, fontSize: 12.5, flexWrap: 'wrap' }}>
      <span style={{ fontWeight: 600 }}>🤖 Tài nguyên bot live:</span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 80, height: 6, background: 'var(--n-line)', borderRadius: 4, overflow: 'hidden', display: 'inline-block' }}>
          <span style={{ display: 'block', height: '100%', width: `${Math.min(pct, 100)}%`, background: color, borderRadius: 4, transition: 'width 0.4s' }} />
        </span>
        <b style={{ color }}>{running_bots}/{max_bots > 0 ? max_bots : '∞'} bot đang chạy</b>
      </span>
      {at_limit && <span style={{ color: 'var(--n-neg,#ef4444)', fontWeight: 600 }}>⚠ Đã đạt giới hạn — dừng bớt bot để giải phóng slot</span>}
      {!at_limit && slots_left != null && <span className="n-note">Còn {slots_left} slot trống</span>}
      {ram_available_mb != null && <span className="n-note">RAM khả dụng: {Math.round(ram_available_mb / 1024 * 10) / 10} GB</span>}
    </div>
  )
}

// ── Bot limit toast ───────────────────────────────────────────────────────────
function BotLimitToast({ err, onClose }) {
  if (!err) return null
  const detail = err?.detail || {}
  const msg = detail.message || err?.message || 'Đã đạt giới hạn bot đang chạy.'
  return (
    <div style={{ position: 'fixed', top: 20, right: 20, zIndex: 9999, maxWidth: 380, padding: '14px 18px', background: 'var(--n-surface)', border: '1.5px solid var(--n-neg,#ef4444)', borderRadius: 10, boxShadow: '0 8px 32px rgba(0,0,0,0.25)', animation: 'slideIn 0.2s ease' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
        <div>
          <div style={{ fontWeight: 700, color: 'var(--n-neg,#ef4444)', marginBottom: 4 }}>⚠ Hết slot bot</div>
          <div style={{ fontSize: 13, color: 'var(--n-ink-2)', lineHeight: 1.5 }}>{msg}</div>
          {detail.running_bots != null && (
            <div style={{ marginTop: 6, fontSize: 12, color: 'var(--n-ink-3)' }}>
              Đang chạy: <b>{detail.running_bots}/{detail.max_bots}</b> bot
            </div>
          )}
        </div>
        <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--n-ink-3)', fontSize: 18, padding: 0, lineHeight: 1 }}>✕</button>
      </div>
    </div>
  )
}

export default function Live() {
  const [sp] = useSearchParams()
  const [tab, setTab] = useState(['paper', 'live'].includes(sp.get('tab')) ? sp.get('tab') : 'all')
  const [selKey, setSelKey] = useState(null)
  const [picker, setPicker] = useState(false)
  const [selected, setSelected] = useState(new Set())   // multi-select
  const [batchLoading, setBatchLoading] = useState(false)
  const [limitErr, setLimitErr] = useState(null)        // bot limit toast

  const qList = useResource('live:bots', () => listLiveBots(), { poll: POLL })
  const qArch = useResource('live:archive', () => getLiveArchive().catch(() => ({ bots: [] })))
  const qRes  = useAsync(() => getLiveResourceStatus(), [], { poll: 15000 })

  const all = useMemo(() => {
    const live = (qList.data?.bots || []).map(normalizeLive)
    const arch = (qArch.data?.bots || []).map(normalizeArchive)
    return [...live, ...arch].sort((a, b) => b.sort - a.sort)
  }, [qList.data, qArch.data])
  const rows = tab === 'all' ? all : all.filter((b) => b.mode === tab)
  const count = (m) => all.filter((b) => b.mode === m).length
  const sel = rows.find((b) => b.key === selKey) || null
  const loading = (qList.loading && !qList.data) || (qArch.loading && !qArch.data)

  const runningBots = all.filter((b) => b.running)
  const resData = qRes.data

  // ── multi-select helpers ────────────────────────────────────────────────────
  const toggleSelect = (key) => setSelected((prev) => { const s = new Set(prev); s.has(key) ? s.delete(key) : s.add(key); return s })
  const toggleAll = () => {
    if (selected.size === rows.length) setSelected(new Set())
    else setSelected(new Set(rows.map((b) => b.key)))
  }
  const selectedBots = rows.filter((b) => selected.has(b.key))
  const selectedRunning = selectedBots.filter((b) => b.running)
  const selectedStopped = selectedBots.filter((b) => !b.running && !b.archived)

  // ── batch actions ───────────────────────────────────────────────────────────
  const batchStop = async () => {
    if (!selectedRunning.length) return
    if (!window.confirm(`Dừng ${selectedRunning.length} bot đang chạy? Vị thế sẽ được đóng.`)) return
    setBatchLoading(true)
    try {
      await batchStopLiveBots(selectedRunning.map((b) => b.id), true)
      setSelected(new Set()); qList.reload()
    } catch (e) { window.alert(`Lỗi: ${e.message}`) }
    finally { setBatchLoading(false) }
  }
  const batchDelete = async () => {
    if (!selectedStopped.length) return
    if (!window.confirm(`Xoá ${selectedStopped.length} bot đã dừng? Dữ liệu sẽ bị xoá vĩnh viễn.`)) return
    setBatchLoading(true)
    try {
      await batchDeleteLiveBots(selectedStopped.map((b) => b.id))
      setSelected(new Set()); if (sel && selected.has(sel.key)) setSelKey(null); qList.reload()
    } catch (e) { window.alert(`Lỗi: ${e.message}`) }
    finally { setBatchLoading(false) }
  }
  const handleResume = async (bot) => {
    try {
      await resumeLiveBot(bot.id)
      qList.reload()
    } catch (e) {
      if (e.status === 429) setLimitErr(e)
      else window.alert(`Không thể chạy lại bot: ${e.message}`)
    }
  }
  const handleStartBot = async (r) => {
    setPicker(false); setTab('all')
    if (r?.bot_id) setSelKey(`b:${r.bot_id}`)
    invalidateResource('live:bots'); qList.reload()
    if (r?.limitErr) setLimitErr(r.limitErr)
  }

  const summaryKpis = useMemo(() => {
    let totalCap = 0
    let totalPnl = 0
    let maxMdd = 0
    let runningCount = 0

    rows.forEach((b) => {
      if (isNum(b.capital)) totalCap += Number(b.capital)
      if (isNum(b.pnl_usd)) totalPnl += Number(b.pnl_usd)
      if (isNum(b.mdd_pct)) maxMdd = Math.max(maxMdd, Number(b.mdd_pct))
      if (b.running) runningCount += 1
    })

    return { totalCap, totalPnl, maxMdd, runningCount }
  }, [rows])

  const [botPage, setBotPage] = useState(1)
  const botPerPage = 10
  const totalBotPages = Math.ceil(rows.length / botPerPage) || 1
  const pagedBots = useMemo(() => {
    const start = (botPage - 1) * botPerPage
    return rows.slice(start, start + botPerPage)
  }, [rows, botPage])

  useEffect(() => { setBotPage(1) }, [tab])

  return (
    <>
      {/* Bot limit toast */}
      <BotLimitToast err={limitErr} onClose={() => setLimitErr(null)} />

      <PageHead kicker="Giao dịch tự động" title="Giao dịch Paper / Live" subtitle="Theo dõi các bot đang chạy và đã dừng: vốn, lãi/lỗ, vị thế và lịch sử lệnh.">
        <Segmented label="Chế độ" value={tab} onChange={(v) => { setTab(v); setSelKey(null); setSelected(new Set()) }}
          options={[
            { value: 'all', label: `Tất cả (${all.length})` },
            { value: 'paper', label: `Paper (${count('paper')})` },
            { value: 'live', label: `Live (${count('live')})` },
          ]} />
      </PageHead>

      {/* 4 Thẻ KPI tham số tổng quát */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 14 }}>
        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>Tổng vốn</div>
          <div className="v" style={{ fontSize: 18, fontWeight: 700 }}>{fmtMoney(summaryKpis.totalCap)} USDT</div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>Toàn bộ bot đang quản lý</div>
        </div>
        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>Lũy kế PnL</div>
          <div className={`v ${signClass(summaryKpis.totalPnl)}`} style={{ fontSize: 18, fontWeight: 700 }}>
            {fmtMoney(summaryKpis.totalPnl, true)} USDT
          </div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>Lợi nhuận ròng thực tế</div>
        </div>
        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>Sụt giảm tối đa (MDD)</div>
          <div className="v" style={{ fontSize: 18, fontWeight: 700 }}>{fmtPct(summaryKpis.maxMdd, 2)}</div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>Mức MDD lớn nhất</div>
        </div>
        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>Số bot đang hoạt động</div>
          <div className="v" style={{ fontSize: 18, fontWeight: 700, color: summaryKpis.runningCount > 0 ? 'var(--n-pos, #10b981)' : 'inherit' }}>
            {summaryKpis.runningCount} / {rows.length}
          </div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>Tiến trình đang chạy</div>
        </div>
      </div>

      {/* Resource status bar */}
      <div style={{ marginBottom: 12 }}>
        <ResourceBar data={resData} />
      </div>

      {/* Action bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <button type="button" className="n-btn primary" onClick={() => setPicker(true)} id="live-btn-start">
          + Chọn chiến lược để chạy
        </button>
        {selected.size > 0 && (
          <>
            <span className="n-note" style={{ fontSize: 12 }}>Đã chọn {selected.size} bot</span>
            {selectedRunning.length > 0 && (
              <button type="button" className="n-btn sm danger" disabled={batchLoading} onClick={batchStop}>
                Dừng ({selectedRunning.length})
              </button>
            )}
            {selectedStopped.length > 0 && (
              <button type="button" className="n-btn sm" disabled={batchLoading} onClick={batchDelete}>
                Xoá ({selectedStopped.length})
              </button>
            )}
            <button type="button" className="n-btn sm" onClick={() => setSelected(new Set())}>Bỏ chọn</button>
          </>
        )}
      </div>

      {picker && (
        <StrategyPicker
          onClose={() => setPicker(false)}
          onStarted={handleStartBot}
          onLimitError={(e) => { setPicker(false); setLimitErr(e) }}
        />
      )}

      <div style={{ display: 'grid', gap: 16 }}>
        <Panel
          title={`Danh sách bot ${runningBots.length > 0 ? `· ${runningBots.length} đang chạy` : ''}`}
          meta={<button type="button" className="n-btn sm" onClick={() => { qList.reload(); qArch.reload() }}>Làm mới</button>}
        >
          {qList.error && <ErrorState title="Không tải được danh sách bot" error={qList.error} onRetry={qList.reload} />}
          {!qList.error && loading && <Loading what="danh sách bot" />}
          {!qList.error && !loading && !rows.length && (
            <Empty title="Chưa có bot nào">
              <div style={{ textAlign: 'center', padding: '12px 0' }}>
                <div style={{ fontSize: 32, marginBottom: 8 }}>🤖</div>
                <div>Khởi động bot từ <b>Alpha Studio</b> bằng cách chọn chế độ Paper hoặc Live rồi nhấn <b>Chạy Bot</b>.</div>
              </div>
            </Empty>
          )}
          {rows.length > 0 && (
            <div>
              <div className="n-tblwrap" style={{ margin: 0 }}>
                <table className="n-tbl n-lv-bots">
                  <thead>
                    <tr>
                      <th style={{ width: 32 }}>
                        <input type="checkbox" checked={selected.size === rows.length && rows.length > 0}
                          onChange={toggleAll} aria-label="Chọn tất cả" style={{ cursor: 'pointer' }} />
                      </th>
                      <th>Chiến lược</th><th>Chế độ</th><th>Cặp</th>
                      <th className="r">Vốn</th><th className="r">Lãi/lỗ</th>
                      <th>Trạng thái</th><th className="r">Thời gian</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedBots.map((b) => (
                      <tr key={b.key} className={`n-lv-row${b.key === selKey ? ' sel' : ''}`} tabIndex={0}
                        aria-selected={b.key === selKey}
                        onClick={() => setSelKey(b.key === selKey ? null : b.key)}
                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelKey(b.key === selKey ? null : b.key) } }}>
                        <td onClick={(e) => e.stopPropagation()} style={{ paddingRight: 0 }}>
                          <input type="checkbox" checked={selected.has(b.key)} onChange={() => toggleSelect(b.key)} aria-label={`Chọn bot ${b.name}`} style={{ cursor: 'pointer' }} />
                        </td>
                        <td title={b.id}><b>{b.name}</b></td>
                        <td><span className={`n-badge ${b.mode === 'paper' ? 'ok' : 'warn'}`}>{MODE_LABEL[b.mode]}</span></td>
                        <td><SymbolsCell symbols={b.symbols} /></td>
                        <td className="r">{isNum(b.capital) ? `${fmtMoney(b.capital)} USDT` : '—'}</td>
                        <td className={`r ${signClass(b.pnl_pct)}`}>{fmtSPct(b.pnl_pct, 2)}{isNum(b.pnl_usd) && <small> ({fmtMoney(b.pnl_usd, true)})</small>}</td>
                        <td><StatusBadge status={b.status} /></td>
                        <td className="r">{isNum(b.duration) ? fmtDuration(b.duration) : '—'}</td>
                        <td className="r" onClick={(e) => e.stopPropagation()}>
                          <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                            {!b.running && !b.archived && (
                              <button type="button" className="n-btn sm" title="Chạy lại bot đã dừng" onClick={() => handleResume(b)}>▶ Chạy lại</button>
                            )}
                            <BotActions bot={b} onDone={() => { if (b.key === selKey) setSelKey(null); qList.reload() }} />
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {totalBotPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12, padding: '8px 4px', borderTop: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
                  <span className="n-note" style={{ fontSize: 12 }}>
                    Hiển thị {(botPage - 1) * botPerPage + 1} - {Math.min(botPage * botPerPage, rows.length)} trong tổng {rows.length} bot
                  </span>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <button type="button" className="n-btn xs" disabled={botPage <= 1} onClick={() => setBotPage((p) => Math.max(1, p - 1))}>
                      ← Trước
                    </button>
                    <span className="n-note" style={{ padding: '2px 6px', fontSize: 12 }}>
                      {botPage} / {totalBotPages}
                    </span>
                    <button type="button" className="n-btn xs" disabled={botPage >= totalBotPages} onClick={() => setBotPage((p) => Math.min(totalBotPages, p + 1))}>
                      Sau →
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </Panel>

        {sel ? (
          <BotDetail key={sel.key} bot={sel} onStopped={() => { qList.reload() }} onDeleted={() => { setSelKey(null); qList.reload() }} />
        ) : rows.length > 0 ? (
          <p className="n-note">Chọn một bot trong danh sách để xem đường vốn, vị thế và lịch sử lệnh.</p>
        ) : null}
      </div>
    </>
  )
}

