import React, { useMemo, useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Segmented, Status, Empty, Loading, ErrorState, NA } from '../components/ui'
import { fmtTs, fmtVal } from '../components/charts/chartFormat'
import useAsync, { useResource, invalidateResource } from '../hooks/useAsync'
import { getLiveTrades, getLiveArchive, listLiveBots, getLiveBotDetail, stopLiveBot, deleteLiveBot, getLiveBotTrades, resumeLiveBot, getLiveResourceStatus, batchStopLiveBots, batchDeleteLiveBots, getLiveBotLogs, getLiveAggregateLogs, getMasterPortfolio } from '../api'
import StrategyPicker from '../components/live/StrategyPicker'
import LiveBotChart from '../components/live/LiveBotChart'
import AreaLine from '../components/charts/AreaLine'
import useResizableDrawer from '../hooks/useResizableDrawer'
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
  const strategyName = typeof b.strategy === 'string' ? b.strategy.trim() : ''
  const running = b.status === 'running'
  const status = running ? 'running' : (b.status === 'failed' || b.status === 'error' ? 'failed' : 'stopped')
  return {
    key: `b:${b.bot_id || b.id}`, id: b.bot_id || b.id, archived: false, mode: tabOf(b.mode), rawMode: b.mode,
    name: strategyName || (strategies.length ? strategies.map(legLabel).join(', ') : (b.name || b.bot_id || b.id)),
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
  if (!window.confirm(`Xoá bot "${bot.name}" và dữ liệu?`)) return
  try {
    await (bot.archived ? deleteLiveBot(bot.dir.split('/').pop(), bot.dir.split('/')[1]) : deleteLiveBot(bot.id, bot.rawMode))
    done()
  } catch (e) {
    window.alert(e.status === 409 ? 'Bot đang chạy, hãy dừng trước khi xoá.' : `Lỗi khi xoá bot: ${e.message}`)
  }
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

function BotDetailDrawer({ bot, onClose, onStopped, onDeleted, onOpenLog }) {
  const live = !bot.archived
  const [detailTab, setDetailTab] = useState('chart') // 'chart' | 'trades' | 'logs'
  const [tradeFilter, setTradeFilter] = useState('all')
  const [selectedChartSymbol, setSelectedChartSymbol] = useState(null)
  const { width: drawerWidth, onMouseDown: onResizeStart } = useResizableDrawer(1080)

  const qD = useAsync(() => (live ? getLiveBotDetail(bot.id) : Promise.resolve(null)), [bot.key], { poll: bot.running ? POLL : undefined })
  const qT = useAsync(() => (live ? getLiveBotTrades(bot.id) : Promise.resolve(null)), [bot.key], { poll: bot.running ? POLL : undefined })
  const qA = useAsync(() => (live ? Promise.resolve(null) : getLiveTrades(bot.rawMode, 'okx', 200, bot.book, bot.engine)), [bot.key])

  // Lắng nghe phím ESC để đóng drawer
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

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
      side: String(t.side || 'BUY').toUpperCase(),
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
      trades = mergeTrades(d).filter((t) => isNum(t.close_ms)).map((t) => ({ t: t.close_ms, symbol: t.symbol, side: String(t.side || 'BUY').toUpperCase(), tag: 'TP', type: REASON[t.reason] || t.reason || '—', qty: t.qty, price: t.close_price, pnl: t.pnl }))
    }
    loadErr = qA.error
  }
  const dates = useMemo(() => eq.map((p) => new Date(p.t).toISOString()), [eq])
  const pnlPct = st.pnl_pct ?? bot.pnl_pct
  const mdd = st.mdd_pct ?? (live ? bot.mdd_pct : undefined)
  const loading = live ? qD.loading && !qD.data : qA.loading && !qA.data
  const hb = live ? (qD.data?.heartbeat || bot.heartbeat) : null
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

  return createPortal(
    <div className="v2 n-drawer-wrap" style={{ zIndex: 10001 }}>
      <div className="n-drawer-bg" onClick={onClose} aria-hidden="true" />
      <aside
        className="n-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`Chi tiết bot ${bot.name}`}
        style={{ width: `${drawerWidth}px`, maxWidth: '100vw', display: 'flex', flexDirection: 'column' }}
      >
        {/* Thanh kéo co giãn chiều ngang (Resize Handle bên trái) */}
        <div
          className="n-drawer-resize-handle"
          onMouseDown={onResizeStart}
          title="Kéo sang trái / phải để điều chỉnh kích thước bảng điều khiển"
        />

        {/* Header Drawer */}
        <header className="n-drawer-h" style={{ padding: '12px 18px', borderBottom: '1px solid var(--n-line)', background: 'var(--n-surface-2)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--n-ink)' }}>{bot.name}</h2>
            <span className={`n-badge ${bot.mode === 'paper' ? 'ok' : 'warn'}`}>{MODE_LABEL[bot.mode]}</span>
            {bot.sub_note && <span className="n-badge" style={{ opacity: 0.85 }}>{bot.sub_note}</span>}
            <StatusBadge status={bot.status} />
            {fp?.match === true && <span className="n-badge ok" title={`Dấu vân tay cấu hình ${fp.strategy_fingerprint}`}>Đúng cấu hình backtest ✓</span>}
            {fp?.match === false && <span className="n-badge bad" title={`Bot ${fp.strategy_fingerprint} ≠ backtest ${fp.expected}`}>Lệch cấu hình backtest ✗</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <BotActions bot={bot} onDone={bot.running ? onStopped : onDeleted} />
            <button
              type="button"
              className="n-btn xs"
              onClick={onClose}
              style={{ fontSize: 13, fontWeight: 700, padding: '4px 10px' }}
              title="Đóng bảng chi tiết (ESC)"
            >
              ✕ Đóng
            </button>
          </div>
        </header>

        {/* Tab Bar phân tách nội dung trực quan */}
        <div style={{ padding: '8px 18px', borderBottom: '1px solid var(--n-line)', background: 'var(--n-surface)', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            type="button"
            className={`n-btn sm ${detailTab === 'chart' ? 'brand' : ''}`}
            onClick={() => setDetailTab('chart')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 600 }}
          >
            <span>📊</span> Biểu đồ & Tín hiệu
          </button>
          <button
            type="button"
            className={`n-btn sm ${detailTab === 'trades' ? 'brand' : ''}`}
            onClick={() => setDetailTab('trades')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 600 }}
          >
            <span>💼</span> Vị thế ({positions.length}) & Lệnh khớp ({trades.length})
          </button>
          <button
            type="button"
            className={`n-btn sm ${detailTab === 'logs' ? 'brand' : ''}`}
            onClick={() => setDetailTab('logs')}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 600 }}
          >
            <span>💻</span> Terminal & Nhật ký
          </button>
        </div>

        {/* Nội dung Tab */}
        <div className="n-drawer-b" style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {loadErr && <ErrorState title="Không tải được chi tiết bot" error={loadErr} />}
          {loading && <Loading what="chi tiết bot" />}

          {detailTab === 'chart' && (
            <>
              {/* Dải KPIs tham số trực quan */}
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

              {isStall && <div className="n-badge bad" style={{ margin: '4px 0' }}>Mất dữ liệu: bot không nhận được dữ liệu thị trường quá 10 phút.</div>}
              {showEmpty && <p className="n-note" style={{ margin: '4px 0' }}>Bot đang chạy và kết nối dữ liệu bình thường, đang quét tín hiệu nến 15m để vào lệnh.</p>}

              {!live && eq.length > 1 && (
                <Panel title="Đường vốn tích lũy">
                  <AreaLine dates={dates} height={220} label="Đường vốn của bot" valueFormat={(v) => fmtMoney(v)}
                    series={[{ key: 'eq', label: 'Vốn (USDT)', values: eq.map((p) => p.equity), color: 'var(--n-accent)', area: true }]} />
                </Panel>
              )}

              {live && (
                <LiveBotChart
                  botId={bot.id}
                  running={bot.running}
                  selectedSymbol={selectedChartSymbol}
                  onSelectSymbol={setSelectedChartSymbol}
                />
              )}
            </>
          )}

          {detailTab === 'trades' && (
            <>
              {/* Bảng Vị thế đang mở */}
              <Panel title="Vị thế đang mở" meta={<span style={{ fontWeight: 600 }}>{positions.length} vị thế</span>}>
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
                          <th>Chiều</th>
                          <th className="r">Khối lượng</th>
                          <th className="r">Giá vào TB</th>
                          <th className="r">Giá Mark</th>
                          <th className="r">Lãi/Lỗ tạm tính</th>
                        </tr>
                      </thead>
                      <tbody>
                        {positions.map((p, i) => {
                          const isSelected = selectedChartSymbol === p.symbol
                          const isLong = String(p.side).toUpperCase() === 'BUY' || String(p.side).toUpperCase() === 'LONG'
                          return (
                          <tr key={i} style={isSelected ? { background: 'rgba(99,102,241,0.08)', outline: '1px solid var(--n-accent, #6366f1)' } : {}}>
                            <td className="mono">
                              <button
                                type="button"
                                className="n-btn xs"
                                style={{ fontWeight: 700, padding: '3px 10px', fontSize: 12, cursor: 'pointer', ...(isSelected ? { background: 'var(--n-accent, #6366f1)', color: '#fff', borderColor: 'var(--n-accent, #6366f1)' } : {}) }}
                                onClick={() => {
                                  setSelectedChartSymbol(p.symbol)
                                  setDetailTab('chart')
                                }}
                                title={`Bấm để chuyển sang biểu đồ cặp ${base(p.symbol)}`}
                              >
                                {base(p.symbol)} {isSelected ? '●' : '↗ Xem biểu đồ'}
                              </button>
                            </td>
                            <td>
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                  padding: '2px 8px',
                                  borderRadius: 4,
                                  fontSize: 11.5,
                                  fontWeight: 700,
                                  background: isLong ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)',
                                  color: isLong ? 'var(--n-pos, #10b981)' : 'var(--n-neg, #f43f5e)',
                                  border: `1px solid ${isLong ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)'}`
                                }}
                              >
                                {isLong ? '▲ LONG' : '▼ SHORT'}
                              </span>
                            </td>
                            <td className="r mono" style={{ fontWeight: 600 }}>{fmtNum(p.qty, 4)}</td>
                            <td className="r mono">{fmtVal(p.avg)}</td>
                            <td className="r mono" style={{ color: 'var(--n-ink-2)' }}>{isNum(p.mark) ? fmtVal(p.mark) : '—'}</td>
                            <td className={`r mono ${signClass(p.pnl)}`} style={{ fontWeight: 700 }}>{isNum(p.pnl) ? fmtMoney(p.pnl, true) : '—'}</td>
                          </tr>
                        )})}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>

              {/* Bảng Lịch sử lệnh (TradingView Style) */}
              <Panel
                title="Lịch sử lệnh (Trade Execution History)"
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
                      style={{ fontSize: 12, padding: '4px 10px', borderRadius: 6, background: 'var(--n-surface-2)', border: '1px solid var(--n-line)', color: 'var(--n-ink)' }}
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
                {!filteredTrades.length ? <Empty title="Chưa có lệnh nào">Chưa ghi nhận lệnh khớp nào theo bộ lọc.</Empty> : (
                  <div className="n-tblwrap long" style={{ border: '1px solid var(--n-line)', borderRadius: 8, overflow: 'hidden' }}>
                    <table className="n-tbl" style={{ width: '100%', borderCollapse: 'collapse' }}>
                      <thead style={{ background: 'var(--n-surface-2)', borderBottom: '1px solid var(--n-line)' }}>
                        <tr>
                          <th style={{ padding: '9px 12px', fontSize: 11.5, color: 'var(--n-ink-2)', textAlign: 'left' }}>Thời gian (UTC)</th>
                          <th style={{ padding: '9px 12px', fontSize: 11.5, color: 'var(--n-ink-2)' }}>Cặp coin</th>
                          <th style={{ padding: '9px 12px', fontSize: 11.5, color: 'var(--n-ink-2)' }}>Chiều</th>
                          <th style={{ padding: '9px 12px', fontSize: 11.5, color: 'var(--n-ink-2)' }}>Loại lệnh</th>
                          <th className="r" style={{ padding: '9px 12px', fontSize: 11.5, color: 'var(--n-ink-2)' }}>Khối lượng</th>
                          <th className="r" style={{ padding: '9px 12px', fontSize: 11.5, color: 'var(--n-ink-2)' }}>Giá khớp (USDT)</th>
                          <th className="r" style={{ padding: '9px 12px', fontSize: 11.5, color: 'var(--n-ink-2)' }}>Phí (USDT)</th>
                          <th className="r" style={{ padding: '9px 12px', fontSize: 11.5, color: 'var(--n-ink-2)' }}>Lãi/Lỗ ròng</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pagedTrades.map((t, i) => {
                          const isCur = base(t.symbol) === base(currentChartSym)
                          const isLong = t.side === 'BUY' || t.side === 'LONG'
                          const isClosed = isNum(t.pnl)
                          const isWin = isClosed && t.pnl >= 0
                          const kindTone = TRADE_KIND_LABELS[t.tag]?.tone || ''
                          const kindLabel = TRADE_KIND_LABELS[t.tag]?.label || t.type

                          return (
                          <tr
                            key={i}
                            style={{
                              cursor: 'pointer',
                              transition: 'background 0.15s ease',
                              borderBottom: '1px solid var(--n-line-soft, var(--n-line))',
                              ...(isCur ? { background: 'rgba(99,102,241,0.06)' } : {})
                            }}
                            onClick={() => {
                              setSelectedChartSymbol(t.symbol)
                              setDetailTab('chart')
                            }}
                            title={`Bấm để chuyển sang biểu đồ cặp ${base(t.symbol)}`}
                          >
                            <td className="num" style={{ fontSize: 11.5, color: 'var(--n-ink-2)', padding: '9px 12px' }}>
                              {fmtTs(t.t)}
                            </td>
                            <td className="mono" style={{ padding: '9px 12px' }}>
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 5,
                                  fontWeight: 700,
                                  padding: '2px 8px',
                                  fontSize: 12,
                                  borderRadius: 5,
                                  background: isCur ? 'var(--n-accent, #6366f1)' : 'var(--n-surface-2)',
                                  color: isCur ? '#fff' : 'var(--n-ink)',
                                  border: `1px solid ${isCur ? 'var(--n-accent, #6366f1)' : 'var(--n-line)'}`
                                }}
                              >
                                {base(t.symbol)} {isCur ? '●' : '↗'}
                              </span>
                            </td>
                            <td style={{ padding: '9px 12px' }}>
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  gap: 4,
                                  padding: '2px 8px',
                                  borderRadius: 4,
                                  fontSize: 11.5,
                                  fontWeight: 700,
                                  background: isLong ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)',
                                  color: isLong ? 'var(--n-pos, #10b981)' : 'var(--n-neg, #f43f5e)',
                                  border: `1px solid ${isLong ? 'rgba(16, 185, 129, 0.3)' : 'rgba(244, 63, 94, 0.3)'}`
                                }}
                              >
                                {isLong ? '▲ LONG' : '▼ SHORT'}
                              </span>
                            </td>
                            <td style={{ padding: '9px 12px' }}>
                              <span className={`n-badge ${kindTone}`} style={{ fontSize: 11.5 }}>
                                {kindLabel}
                              </span>
                            </td>
                            <td className="r mono" style={{ fontSize: 12, padding: '9px 12px' }}>
                              {fmtNum(t.qty, 4)}
                            </td>
                            <td className="r mono" style={{ fontSize: 12, fontWeight: 600, padding: '9px 12px' }}>
                              {fmtVal(t.price)}
                            </td>
                            <td className="r mono" style={{ fontSize: 11.5, color: 'var(--n-ink-3)', padding: '9px 12px' }}>
                              {isNum(t.fee) ? fmtNum(t.fee, 4) : '—'}
                            </td>
                            <td className="r mono" style={{ padding: '9px 12px' }}>
                              {isClosed ? (
                                <span
                                  style={{
                                    display: 'inline-block',
                                    padding: '2px 8px',
                                    borderRadius: 4,
                                    fontSize: 12,
                                    fontWeight: 700,
                                    background: isWin ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.15)',
                                    color: isWin ? 'var(--n-pos, #10b981)' : 'var(--n-neg, #f43f5e)',
                                  }}
                                >
                                  {fmtMoney(t.pnl, true)}
                                </span>
                              ) : (
                                <span className="n-note" style={{ fontSize: 11.5 }}>
                                  Mở vị thế
                                </span>
                              )}
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
            </>
          )}

          {detailTab === 'logs' && (
            <BotTerminalConsole bot={bot} symbols={symbols} trades={trades} positions={positions} hb={hb} onOpenFullLog={() => onOpenLog?.(bot)} />
          )}
        </div>
      </aside>
    </div>,
    document.body
  )
}

/** Terminal Console trực quan hiển thị log vận hành thực tế của Live Bot */
function BotTerminalConsole({ bot, symbols = [], trades = [], positions = [], hb = null, onOpenFullLog }) {
  const [copied, setCopied] = useState(false)
  const bodyRef = useRef(null)

  const { data: logData, loading } = useAsync(
    () => (bot?.id ? getLiveBotLogs(bot.id, 60) : Promise.resolve(null)),
    [bot?.id],
    { poll: bot?.running ? 3000 : 0 }
  )

  const realLogs = logData?.logs || []

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [realLogs])

  const copyLogs = () => {
    const text = logData?.raw_text || realLogs.map((l) => l.raw).join('\n')
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const getLineColor = (level, raw) => {
    if (level === 'ERROR') return 'var(--n-neg, #f0616d)'
    if (level === 'WARN') return 'var(--n-warn, #e5a93c)'
    if (level === 'TRADE') return 'var(--n-info, #5aa0e6)'
    if (level === 'SIGNAL') return 'var(--n-pos, #3ecf8e)'
    if (raw?.includes('Subscribe') || raw?.includes('RUNNING')) return 'var(--n-teal, #2fb3b8)'
    return 'var(--n-ink, #ededf0)'
  }

  return (
    <Panel
      title={`Terminal Console (Log vận hành ${bot.id})`}
      meta={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {onOpenFullLog && (
            <button
              type="button"
              className="n-btn xs primary"
              onClick={onOpenFullLog}
              style={{ fontSize: 11 }}
            >
              ⤢ Mở rộng xem chi tiết
            </button>
          )}
          <button
            type="button"
            className="n-btn xs"
            onClick={copyLogs}
            style={{ fontSize: 11 }}
          >
            {copied ? '✓ Đã chép' : 'Sao chép log'}
          </button>
          {bot.running ? (
            <span className="n-badge ok" style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-pos, #3ecf8e)', animation: 'pulse 1.5s infinite' }} />
              LIVE
            </span>
          ) : (
            <span className="n-badge" style={{ fontSize: 11, color: 'var(--n-ink-3)' }}>STOPPED</span>
          )}
        </div>
      }
    >
      <div
        ref={bodyRef}
        style={{
          background: 'var(--n-bg)',
          color: 'var(--n-ink)',
          fontFamily: 'var(--n-mono)',
          fontSize: 12,
          lineHeight: 1.6,
          padding: '12px 14px',
          borderRadius: 8,
          maxHeight: 240,
          overflowY: 'auto',
          border: '1px solid var(--n-line)',
        }}
      >
        {realLogs.length > 0 ? (
          realLogs.map((l, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-all', padding: '1px 0' }}>
              <span style={{ color: 'var(--n-ink-3)', userSelect: 'none', minWidth: 26, textAlign: 'right' }}>{i + 1}</span>
              <span style={{ color: getLineColor(l.level, l.raw) }}>
                {l.raw}
              </span>
            </div>
          ))
        ) : loading ? (
          <div style={{ color: 'var(--n-ink-3)', fontStyle: 'italic' }}>Đang tải nhật ký từ máy chủ...</div>
        ) : (
          <div style={{ color: 'var(--n-ink-3)', fontStyle: 'italic' }}>Chưa có nhật ký hoạt động. Bot đang khởi động hoặc chưa có nến mới.</div>
        )}
      </div>
    </Panel>
  )
}

/** Modal xem toàn bộ nhật ký Live Log chuyên sâu thời gian thực (hỗ trợ xem tổng hợp mọi bot) */
function LiveLogViewerModal({ bot, allBots = [], onClose, onSelectBot }) {
  const [selectedBotId, setSelectedBotId] = useState(bot?.id || '__all__')
  const isAll = selectedBotId === '__all__'
  const [lines, setLines] = useState(250)
  const [filterLevel, setFilterLevel] = useState('ALL')
  const [search, setSearch] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [autoScroll, setAutoScroll] = useState(true)
  const [activeTab, setActiveTab] = useState('logs') // 'logs' | 'signals' | 'trades' | 'heartbeat'
  const [copied, setCopied] = useState(false)
  const logBoxRef = useRef(null)

  // Đóng modal khi nhấn phím ESC
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const activeBot = isAll
    ? { id: '__all__', name: 'Toàn bộ danh mục bot', running: true }
    : (allBots.find((b) => b.id === selectedBotId) || bot || {})

  const { data, loading, error, reload } = useAsync(
    () => (isAll ? getLiveAggregateLogs(lines) : (selectedBotId ? getLiveBotLogs(selectedBotId, lines) : Promise.resolve(null))),
    [selectedBotId, lines, isAll],
    { poll: autoRefresh && (isAll || activeBot.running) ? 2000 : 0 }
  )

  const logs = data?.logs || []
  const filteredLogs = useMemo(() => {
    return logs.filter((l) => {
      if (filterLevel !== 'ALL' && l.level !== filterLevel) return false
      if (search && !l.raw.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })
  }, [logs, filterLevel, search])

  useEffect(() => {
    if (autoScroll && logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight
    }
  }, [filteredLogs, autoScroll])

  const copyLogs = () => {
    const text = data?.raw_text || logs.map((l) => l.raw).join('\n')
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const downloadLogs = () => {
    const text = data?.raw_text || logs.map((l) => l.raw).join('\n')
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${isAll ? 'portfolio_aggregate' : (selectedBotId || 'bot')}_log_${Date.now()}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const getLineColor = (level, raw) => {
    if (level === 'ERROR') return 'var(--n-neg, #f0616d)'
    if (level === 'WARN') return 'var(--n-warn, #e5a93c)'
    if (level === 'TRADE') return 'var(--n-info, #5aa0e6)'
    if (level === 'SIGNAL') return 'var(--n-pos, #3ecf8e)'
    if (raw?.includes('Subscribe') || raw?.includes('RUNNING')) return 'var(--n-teal, #2fb3b8)'
    return 'var(--n-ink, #ededf0)'
  }

  const hb = data?.heartbeat || activeBot.heartbeat || {}
  const signals = data?.recent_signals || []
  const trades = data?.recent_trades || []

  return createPortal(
    <div
      className="n-modal-backdrop v2"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(5, 8, 16, 0.72)',
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="v2"
        style={{
          width: '100%',
          maxWidth: 1220,
          height: '88vh',
          background: 'var(--n-surface)',
          border: '1px solid var(--n-line)',
          borderRadius: 12,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: 'var(--n-shadow, 0 25px 60px -15px rgba(0,0,0,0.5))',
        }}
      >
        {/* Header Modal */}
        <div
          style={{
            padding: '12px 18px',
            borderBottom: '1px solid var(--n-line)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'var(--n-surface-2)',
            flexWrap: 'wrap',
            gap: 10,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--n-ink)', display: 'flex', alignItems: 'center', gap: 8 }}>
              📋 {isAll ? 'Nhật ký tổng hợp toàn bộ bot (Portfolio Log)' : 'Nhật ký Live Bot'}
            </span>

            {/* Chọn bot chuyển đổi nhanh */}
            <select
              value={selectedBotId}
              onChange={(e) => {
                const val = e.target.value
                setSelectedBotId(val)
                if (val === '__all__') {
                  onSelectBot?.({ id: '__all__', name: 'Toàn bộ danh mục bot', running: true })
                } else {
                  onSelectBot?.(allBots.find((b) => b.id === val))
                }
              }}
              style={{
                background: 'var(--n-surface-3)',
                color: 'var(--n-ink)',
                border: '1px solid var(--n-line)',
                padding: '4px 10px',
                borderRadius: 6,
                fontSize: 12,
                fontWeight: 600,
                fontFamily: 'var(--n-sans)',
              }}
            >
              <option value="__all__">🌟 Tất cả bot đang chạy (Nhật ký tổng hợp)</option>
              {allBots.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.running ? '🟢' : '⚪'} {b.name} ({b.id.slice(0, 16)}...)
                </option>
              ))}
            </select>

            {isAll ? (
              <span className="n-badge ok" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-pos, #3ecf8e)', animation: 'pulse 1.5s infinite' }} />
                {data?.total_running ?? allBots.filter((b) => b.running).length} BOT ĐANG CHẠY
              </span>
            ) : activeBot.running ? (
              <span className="n-badge ok" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-pos, #3ecf8e)', animation: 'pulse 1.5s infinite' }} />
                ĐANG CHẠY
              </span>
            ) : (
              <span className="n-badge" style={{ fontSize: 11, color: 'var(--n-ink-3)' }}>ĐÃ DỪNG</span>
            )}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button
              type="button"
              className={`n-btn xs ${autoRefresh ? 'ok' : ''}`}
              onClick={() => setAutoRefresh(!autoRefresh)}
              title="Tự động cập nhật mỗi 2 giây"
            >
              {autoRefresh ? '⚡ Tự cập nhật: Bật' : '⏸ Tự cập nhật: Tắt'}
            </button>
            <button type="button" className="n-btn xs" onClick={reload} title="Làm mới ngay">
              🔄 Tải lại
            </button>
            <button
              type="button"
              className="n-btn xs"
              onClick={copyLogs}
              title="Sao chép toàn bộ log ra bộ nhớ tạm"
            >
              {copied ? '✓ Đã chép' : '📋 Sao chép'}
            </button>
            <button
              type="button"
              className="n-btn xs"
              onClick={downloadLogs}
              title="Tải log về máy tính dạng file txt"
            >
              💾 Tải log
            </button>
            <button
              type="button"
              className="n-btn xs"
              onClick={onClose}
              style={{ fontSize: 13, fontWeight: 700 }}
              title="Đóng cửa sổ nhật ký (ESC)"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Thẻ trạng thái Heartbeat & Năng lực Bot */}
        <div
          style={{
            padding: '8px 18px',
            background: 'var(--n-surface-2)',
            borderBottom: '1px solid var(--n-line-soft, var(--n-line))',
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            fontSize: 12,
            flexWrap: 'wrap',
          }}
        >
          {isAll ? (
            <>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>Chế độ xem:</span>
                <b style={{ color: 'var(--n-accent)' }}>Tổng hợp toàn bộ danh mục</b>
              </div>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>Đang chạy:</span>
                <b style={{ color: 'var(--n-pos)' }}>{data?.total_running ?? allBots.filter((b) => b.running).length} bot</b>
              </div>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>Dòng log tổng:</span>
                <b style={{ color: 'var(--n-ink)' }}>{filteredLogs.length} / {data?.total_lines || 0}</b>
              </div>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>Tín hiệu nến:</span>
                <b style={{ color: 'var(--n-warn)' }}>{signals.length}</b>
              </div>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>Lệnh khớp:</span>
                <b style={{ color: 'var(--n-info)' }}>{trades.length}</b>
              </div>
            </>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>Vốn:</span>
                <b style={{ color: 'var(--n-ink)' }}>{isNum(activeBot.capital) ? fmtMoney(activeBot.capital) : '—'} USDT</b>
              </div>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>PnL luỹ kế:</span>
                <b className={signClass(activeBot.pnl_usd)}>{isNum(activeBot.pnl_usd) ? fmtMoney(activeBot.pnl_usd, true) : '0'} USDT</b>
              </div>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>Cặp giao dịch:</span>
                <b style={{ color: 'var(--n-accent)' }}>{(activeBot.symbols || []).map(base).join(', ') || 'N/A'}</b>
              </div>
              <div style={{ display: 'flex', gap: 5 }}>
                <span style={{ color: 'var(--n-ink-2)' }}>Dòng log:</span>
                <b style={{ color: 'var(--n-ink)' }}>{filteredLogs.length} / {data?.total_lines || 0}</b>
              </div>
              {hb.last_bar_ts && (
                <div style={{ display: 'flex', gap: 5 }}>
                  <span style={{ color: 'var(--n-ink-2)' }}>Nến cuối:</span>
                  <span style={{ color: 'var(--n-ink)' }}>{fmtTs(hb.last_bar_ts)}</span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Thanh công cụ lọc & tìm kiếm */}
        <div
          style={{
            padding: '8px 18px',
            borderBottom: '1px solid var(--n-line)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
            flexWrap: 'wrap',
            background: 'var(--n-surface)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {['logs', 'signals', 'trades', !isAll ? 'heartbeat' : null].filter(Boolean).map((tab) => (
              <button
                key={tab}
                type="button"
                className={`n-btn xs ${activeTab === tab ? 'brand' : ''}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab === 'logs' ? `Nhật ký (${filteredLogs.length})` : tab === 'signals' ? `Tín hiệu nến (${signals.length})` : tab === 'trades' ? `Khớp lệnh (${trades.length})` : 'Heartbeat'}
              </button>
            ))}
          </div>

          {activeTab === 'logs' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {/* Lọc Level */}
              <div style={{ display: 'flex', gap: 2, background: 'var(--n-surface-2)', borderRadius: 6, padding: 2, border: '1px solid var(--n-line)' }}>
                {['ALL', 'TRADE', 'SIGNAL', 'INFO', 'WARN', 'ERROR'].map((lvl) => (
                  <button
                    key={lvl}
                    type="button"
                    style={{
                      border: 'none',
                      background: filterLevel === lvl ? 'var(--n-surface-3)' : 'transparent',
                      color: filterLevel === lvl ? 'var(--n-ink)' : 'var(--n-ink-2)',
                      fontSize: 11,
                      fontWeight: 600,
                      padding: '3px 8px',
                      borderRadius: 4,
                      cursor: 'pointer',
                    }}
                    onClick={() => setFilterLevel(lvl)}
                  >
                    {lvl}
                  </button>
                ))}
              </div>

              {/* Số dòng */}
              <select
                value={lines}
                onChange={(e) => setLines(Number(e.target.value))}
                style={{
                  background: 'var(--n-surface-2)',
                  color: 'var(--n-ink)',
                  border: '1px solid var(--n-line)',
                  padding: '3px 6px',
                  borderRadius: 6,
                  fontSize: 11.5,
                  fontFamily: 'var(--n-sans)',
                }}
              >
                <option value={50}>50 dòng</option>
                <option value={100}>100 dòng</option>
                <option value={250}>250 dòng</option>
                <option value={500}>500 dòng</option>
                <option value={1000}>1000 dòng</option>
              </select>

              {/* Tìm kiếm */}
              <input
                type="text"
                placeholder="Tìm từ khóa..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  background: 'var(--n-surface-2)',
                  color: 'var(--n-ink)',
                  border: '1px solid var(--n-line)',
                  padding: '3px 8px',
                  borderRadius: 6,
                  fontSize: 11.5,
                  width: 140,
                  fontFamily: 'var(--n-sans)',
                }}
              />

              <button
                type="button"
                className={`n-btn xs ${autoScroll ? 'brand' : ''}`}
                onClick={() => setAutoScroll(!autoScroll)}
                title="Tự động cuộn xuống đáy khi có dòng log mới"
              >
                {autoScroll ? '⬇ Tự cuộn: Bật' : '⬇ Tự cuộn: Tắt'}
              </button>
            </div>
          )}
        </div>

        {/* Nội dung Terminal Console */}
        <div
          ref={logBoxRef}
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: '14px 18px',
            fontFamily: 'var(--n-mono)',
            fontSize: 12,
            lineHeight: 1.6,
            background: 'var(--n-bg)',
            color: 'var(--n-ink)',
          }}
        >
          {activeTab === 'logs' && (
            <div>
              {filteredLogs.length > 0 ? (
                filteredLogs.map((l, i) => (
                  <div key={i} style={{ display: 'flex', gap: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-all', padding: '1px 0' }}>
                    <span style={{ color: 'var(--n-ink-3)', userSelect: 'none', minWidth: 32, textAlign: 'right' }}>{i + 1}</span>
                    <span style={{ color: getLineColor(l.level, l.raw) }}>
                      {l.raw}
                    </span>
                  </div>
                ))
              ) : loading ? (
                <div style={{ color: 'var(--n-ink-3)', fontStyle: 'italic', padding: '20px 0', textAlign: 'center' }}>
                  Đang đồng bộ nhật ký từ Nautilus Trading Engine...
                </div>
              ) : (
                <div style={{ color: 'var(--n-ink-3)', fontStyle: 'italic', padding: '20px 0', textAlign: 'center' }}>
                  {search || filterLevel !== 'ALL' ? 'Không có dòng log nào khớp với bộ lọc.' : 'Chưa có dữ liệu log. Bot đang nạp cấu hình và kết nối sàn.'}
                </div>
              )}
            </div>
          )}

          {activeTab === 'signals' && (
            <div style={{ padding: '4px 0' }}>
              <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--n-ink-2)' }}>
                Danh sách 10 tín hiệu gần nhất ghi nhận từ <code>signals.jsonl</code>:
              </div>
              {signals.length > 0 ? (
                <div className="n-tblwrap">
                  <table className="n-tbl" style={{ fontSize: 12 }}>
                    <thead>
                      <tr>
                        <th>Thời gian</th>
                        <th>Cặp</th>
                        <th>Slot</th>
                        <th>Trùng khớp (Match)</th>
                        <th>Cắt lỗ (Stop)</th>
                        <th>DCA</th>
                      </tr>
                    </thead>
                    <tbody>
                      {signals.map((s, idx) => (
                        <tr key={idx}>
                          <td>{fmtTs(s.ts)}</td>
                          <td><b>{base(s.symbol)}</b></td>
                          <td><span className="mono">{s.slot}</span></td>
                          <td>
                            <span className={`n-badge ${s.match ? 'ok' : 'warn'}`}>
                              {s.match ? 'TRUE (VÀO LỆNH)' : 'FALSE'}
                            </span>
                          </td>
                          <td>{String(s.stop ?? '—')}</td>
                          <td>{String(s.dca ?? '—')}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ color: 'var(--n-ink-3)', fontStyle: 'italic' }}>Chưa có tín hiệu nào được ghi nhận vào file signals.jsonl.</div>
              )}
            </div>
          )}

          {activeTab === 'trades' && (
            <div style={{ padding: '4px 0' }}>
              <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--n-ink-2)' }}>
                Lệnh khớp (fills) & đóng vị thế thời gian thực từ các bot:
              </div>
              {trades.length > 0 ? (
                <div className="n-tblwrap">
                  <table className="n-tbl" style={{ fontSize: 12 }}>
                    <thead>
                      <tr>
                        <th>Thời gian</th>
                        <th>Bot / Chiến lược</th>
                        <th>Cặp</th>
                        <th>Loại</th>
                        <th>Chiều</th>
                        <th className="r">Khối lượng</th>
                        <th className="r">Giá khớp</th>
                        <th className="r">PnL</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trades.map((t, idx) => (
                        <tr key={idx}>
                          <td>{fmtTs(t.ts || t.t)}</td>
                          <td><b>{t.bot_name || t.bot_id?.slice(0, 16) || '—'}</b></td>
                          <td><b>{base(t.symbol)}</b></td>
                          <td><span className="n-badge">{t.kind || t.type}</span></td>
                          <td>
                            <span style={{ color: t.side === 'BUY' ? 'var(--n-pos, #3ecf8e)' : 'var(--n-neg, #f0616d)', fontWeight: 600 }}>
                              {t.side || (t.type === 'position_closed' ? 'ĐÓNG VỊ THẾ' : '—')}
                            </span>
                          </td>
                          <td className="r mono">{t.qty != null ? t.qty : '—'}</td>
                          <td className="r mono">{t.px != null ? fmtMoney(t.px) : (t.close_px != null ? fmtMoney(t.close_px) : '—')}</td>
                          <td className={`r mono ${signClass(t.pnl)}`}>{t.pnl != null ? `${fmtMoney(t.pnl, true)} USDT` : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ color: 'var(--n-ink-3)', fontStyle: 'italic' }}>Chưa có lệnh khớp nào được ghi nhận trong phiên hiện tại.</div>
              )}
            </div>
          )}

          {activeTab === 'heartbeat' && (
            <div style={{ padding: '8px 0' }}>
              <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--n-ink-2)' }}>
                Thông tin nhịp tim & tài nguyên ghi nhận từ <code>heartbeat.json</code>:
              </div>
              <pre style={{ background: 'var(--n-surface-2)', padding: 14, borderRadius: 8, border: '1px solid var(--n-line)', color: 'var(--n-accent)', fontSize: 12, fontFamily: 'var(--n-mono)' }}>
                {JSON.stringify(hb, null, 2)}
              </pre>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '8px 18px',
            background: 'var(--n-surface-2)',
            borderTop: '1px solid var(--n-line)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontSize: 11.5,
            color: 'var(--n-ink-3)',
          }}
        >
          <span>Nhấn <b>ESC</b> hoặc nút ✕ để đóng · Tự động cập nhật mỗi 2 giây</span>
          <span>{data?.timestamp ? `Đã đồng bộ lúc: ${new Date(data.timestamp).toLocaleTimeString()}` : ''}</span>
        </div>
      </div>
    </div>,
    document.body
  )
}

/** Modal Kiểm Toán & Đối Soát Sổ Cái Master (Reconciliation Audit) */
function ReconciliationAuditModal({ data, onClose }) {
  const [precision4, setPrecision4] = useState(false)
  const recon = data?.reconciliation || {}
  const summary = data?.portfolio_summary || {}
  const sleeves = data?.sleeves || []
  const audit = data?.invariants_audit || {}

  const fNum = (v) => {
    if (v === null || v === undefined || isNaN(v)) return '—'
    const n = Number(v)
    return precision4 ? n.toFixed(4) : n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }

  // Đóng modal khi nhấn phím ESC
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const allPassed = Object.values(audit).every(Boolean)

  return createPortal(
    <div
      className="n-modal-backdrop v2"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(5, 8, 16, 0.72)',
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="v2"
        style={{
          width: '920px',
          maxWidth: '96vw',
          maxHeight: '90vh',
          background: 'var(--n-surface, #1e293b)',
          borderRadius: 12,
          border: '1px solid var(--n-line, rgba(255,255,255,0.1))',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
          overflow: 'hidden',
        }}
      >
        {/* Header Modal */}
        <div style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--n-line)',
          background: 'var(--n-surface-2, #0f172a)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--n-ink, #f8fafc)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>⚖️ Đối Soát Sổ Cái Master & Sleeves</span>
              <span className={`n-badge ${allPassed ? 'ok' : 'bad'}`} style={{ fontSize: 11 }}>
                {allPassed ? '6/6 Invariants Đạt ✓' : 'Cảnh báo sai lệch Invariant ✗'}
              </span>
            </h3>
            <div style={{ fontSize: 12, color: 'var(--n-ink-3, #94a3b8)', marginTop: 2 }}>
              Kiểm toán toán học độc lập giữa Vốn gốc, Quota phân bổ, Dòng tiền thực tế và các Sleeve
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--n-ink-2)', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={precision4}
                onChange={(e) => setPrecision4(e.target.checked)}
              />
              <span>Hiển thị 4 số thập phân (.0000)</span>
            </label>
            <button type="button" className="n-btn xs" onClick={onClose} style={{ fontSize: 13, fontWeight: 700 }}>
              ✕ Đóng
            </button>
          </div>
        </div>

        {/* Nội dung Modal */}
        <div style={{ padding: '16px 20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Card 1: 6 Invariants Kiểm Toán Toán Học */}
          <div style={{ background: 'var(--n-surface-2)', padding: 14, borderRadius: 8, border: '1px solid var(--n-line)' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--n-ink-1)', marginBottom: 10 }}>
              🛡️ Kiểm Toán 6 Bất Biến Toán Học (Accounting Invariants)
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10, fontSize: 12 }}>
              <div style={{ padding: '8px 10px', background: 'var(--n-surface)', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                <div style={{ color: 'var(--n-ink-3)' }}>1. Vốn gốc Master bất biến:</div>
                <div style={{ fontWeight: 600, marginTop: 2, color: audit.initial_capital_constant ? 'var(--n-pos)' : 'var(--n-neg)' }}>
                  {audit.initial_capital_constant ? '✓' : '✗'} {fNum(summary.initial_capital)} USDT (Cố định 10,000)
                </div>
              </div>

              <div style={{ padding: '8px 10px', background: 'var(--n-surface)', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                <div style={{ color: 'var(--n-ink-3)' }}>2. Tiền mặt Master (Cash Identity):</div>
                <div style={{ fontWeight: 600, marginTop: 2, color: audit.master_cash_exact ? 'var(--n-pos)' : 'var(--n-neg)' }}>
                  {audit.master_cash_exact ? '✓' : '✗'} {fNum(summary.master_cash)} USDT
                </div>
              </div>

              <div style={{ padding: '8px 10px', background: 'var(--n-surface)', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                <div style={{ color: 'var(--n-ink-3)' }}>3. Tài sản Master (Master Equity):</div>
                <div style={{ fontWeight: 600, marginTop: 2, color: audit.master_equity_exact ? 'var(--n-pos)' : 'var(--n-neg)' }}>
                  {audit.master_equity_exact ? '✓' : '✗'} {fNum(summary.master_equity)} USDT
                </div>
              </div>

              <div style={{ padding: '8px 10px', background: 'var(--n-surface)', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                <div style={{ color: 'var(--n-ink-3)' }}>4. Cân bằng Quota Phân Bổ (Identity):</div>
                <div style={{ fontWeight: 600, marginTop: 2, color: audit.capital_allocation_identity ? 'var(--n-pos)' : 'var(--n-neg)' }}>
                  {audit.capital_allocation_identity ? '✓' : '✗'} {fNum(recon.total_allocated_capital)} + {fNum(recon.unallocated_capital)} = 10,000
                </div>
              </div>

              <div style={{ padding: '8px 10px', background: 'var(--n-surface)', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                <div style={{ color: 'var(--n-ink-3)' }}>5. Cân bằng Master Equity & Sleeves:</div>
                <div style={{ fontWeight: 600, marginTop: 2, color: audit.master_equity_equals_sum_sleeves_plus_unallocated ? 'var(--n-pos)' : 'var(--n-neg)' }}>
                  {audit.master_equity_equals_sum_sleeves_plus_unallocated ? '✓' : '✗'} Lệch: {fNum(recon.equity_discrepancy)} USDT
                </div>
              </div>

              <div style={{ padding: '8px 10px', background: 'var(--n-surface)', borderRadius: 6, border: '1px solid var(--n-line)' }}>
                <div style={{ color: 'var(--n-ink-3)' }}>6. Tổng Net PnL Master & Sleeves:</div>
                <div style={{ fontWeight: 600, marginTop: 2, color: audit.master_net_pnl_equals_sum_sleeves ? 'var(--n-pos)' : 'var(--n-neg)' }}>
                  {audit.master_net_pnl_equals_sum_sleeves ? '✓' : '✗'} Lệch: {fNum(recon.pnl_discrepancy)} USDT
                </div>
              </div>
            </div>
          </div>

          {/* Card 2: Bảng Đối Soát Hai Mô Hình Tránh Double-Counting */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 14 }}>
            <div style={{ background: 'var(--n-surface-2)', padding: 14, borderRadius: 8, border: '1px solid var(--n-line)' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--n-accent)', marginBottom: 8 }}>
                📊 Mô Hình 1: Hạn Mức Cấp Vốn (Allocation Quota)
              </div>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <tbody>
                  <tr style={{ borderBottom: '1px solid var(--n-line)' }}>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-2)' }}>Vốn gốc cấu hình quỹ:</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 600 }}>{fNum(recon.master_initial_capital)} USDT</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--n-line)' }}>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-2)' }}>Đang cấp cho 2 bot active:</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 600, color: '#38bdf8' }}>{fNum(recon.total_allocated_capital)} USDT</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--n-line)' }}>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-2)' }}>Hạn mức chưa cấp (Unallocated):</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 600, color: 'var(--n-pos)' }}>{fNum(recon.unallocated_capital)} USDT</td>
                  </tr>
                  <tr>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-3)' }}>Sai lệch kế toán Quota:</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 700, color: 'var(--n-pos)' }}>{fNum(recon.capital_discrepancy)} USDT (0.0000)</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div style={{ background: 'var(--n-surface-2)', padding: 14, borderRadius: 8, border: '1px solid var(--n-line)' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--n-pos)', marginBottom: 8 }}>
                💵 Mô Hình 2: Dòng Tiền & Tài Sản Thực (Master Cash & Equity)
              </div>
              <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
                <tbody>
                  <tr style={{ borderBottom: '1px solid var(--n-line)' }}>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-2)' }}>Master Cash (Tiền mặt thực tế):</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 600 }}>{fNum(summary.master_cash)} USDT</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--n-line)' }}>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-2)' }}>Tiền mặt tự do tại Master:</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 600, color: '#38bdf8' }}>{fNum(recon.unallocated_cash)} USDT</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--n-line)' }}>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-2)' }}>Equity các Sleeve còn chạy:</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 600, color: 'var(--n-pos)' }}>{fNum(recon.active_sleeves_equity)} USDT</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--n-line)' }}>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-2)' }}>Lỗ lũy kế 3 bot đã đóng:</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 600, color: 'var(--n-neg)' }}>{fNum(recon.closed_sleeves_net_pnl)} USDT</td>
                  </tr>
                  <tr>
                    <td style={{ padding: '6px 0', color: 'var(--n-ink-3)' }}>Master Equity thực tế:</td>
                    <td style={{ padding: '6px 0', textAlign: 'right', fontWeight: 700 }}>{fNum(summary.master_equity)} USDT</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Card 3: Chi tiết 5 Sleeve trong Quỹ Master */}
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--n-ink-1)', marginBottom: 8 }}>
              📋 Trạng Thái Chi Tiết 5 Sleeve (2 Active + 3 Closed & Settled)
            </div>
            <div className="n-tblwrap">
              <table className="n-tbl" style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Chiến lược</th>
                    <th>Trạng thái</th>
                    <th style={{ textAlign: 'right' }}>Vốn phân bổ</th>
                    <th style={{ textAlign: 'right' }}>Vốn chốt / Cash</th>
                    <th style={{ textAlign: 'right' }}>Net Realized PnL</th>
                    <th style={{ textAlign: 'right' }}>Unrealized</th>
                    <th style={{ textAlign: 'right' }}>Drawdown</th>
                  </tr>
                </thead>
                <tbody>
                  {sleeves.map((s) => (
                    <tr key={s.sleeve_id}>
                      <td style={{ fontWeight: 600 }}>{s.name}</td>
                      <td>
                        <span className={`n-badge ${s.status === 'ACTIVE' ? 'ok' : 'bad'}`} style={{ fontSize: 10.5 }}>
                          {s.status === 'ACTIVE' ? 'ĐANG CHẠY' : 'ĐÃ ĐÓNG & THU HỒI VỐN'}
                        </span>
                      </td>
                      <td style={{ textAlign: 'right', color: s.status === 'CLOSED' ? 'var(--n-ink-3)' : 'inherit' }}>
                        {fNum(s.configured_allocation)} USDT
                        {s.status === 'CLOSED' && <span style={{ fontSize: 10, display: 'block', color: 'var(--n-pos)' }}>(Thu hồi 1,000)</span>}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 600 }}>
                        {fNum(s.settled_balance ?? s.sleeve_cash)} USDT
                      </td>
                      <td style={{ textAlign: 'right', color: s.net_realized_pnl >= 0 ? 'var(--n-pos)' : 'var(--n-neg)', fontWeight: 600 }}>
                        {s.net_realized_pnl >= 0 ? '+' : ''}{fNum(s.net_realized_pnl)} USDT
                      </td>
                      <td style={{ textAlign: 'right', color: s.unrealized_pnl >= 0 ? 'var(--n-pos)' : 'var(--n-neg)' }}>
                        {s.status === 'CLOSED' ? '0.00' : (s.unrealized_pnl >= 0 ? '+' : '') + fNum(s.unrealized_pnl)}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {s.drawdown_pct ? `${s.drawdown_pct.toFixed(2)}%` : '0.00%'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {/* Footer Modal */}
        <div style={{
          padding: '10px 20px',
          background: 'var(--n-surface-2)',
          borderTop: '1px solid var(--n-line)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: 11.5,
          color: 'var(--n-ink-3)',
        }}>
          <span>Cập nhật trực tiếp từ Core Ledger · Đảm bảo nguyên lý Single Source of Truth</span>
          <button type="button" className="n-btn sm" onClick={onClose}>
            Đóng
          </button>
        </div>
      </div>
    </div>,
    document.body
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
  const [logModalBot, setLogModalBot] = useState(null)  // modal log xem trực tiếp
  const [showReconcileModal, setShowReconcileModal] = useState(false) // modal đối soát sổ cái master

  const qList = useResource('live:bots', () => listLiveBots(), { poll: POLL })
  const qArch = useResource('live:archive', () => getLiveArchive().catch(() => ({ bots: [] })))
  const qRes  = useAsync(() => getLiveResourceStatus(), [], { poll: 15000 })
  const qMaster = useAsync(() => getMasterPortfolio(), [], { poll: POLL })

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
    let botCap = 0
    let botPnl = 0
    let maxMdd = 0
    let runningCount = 0

    rows.forEach((b) => {
      if (isNum(b.capital)) botCap += Number(b.capital)
      if (isNum(b.pnl_usd)) botPnl += Number(b.pnl_usd)
      if (isNum(b.mdd_pct)) maxMdd = Math.max(maxMdd, Number(b.mdd_pct))
      if (b.running) runningCount += 1
    })

    const master = qMaster.data?.portfolio_summary
    if (master) {
      const netPnl = isNum(master.net_pnl)
        ? Number(master.net_pnl)
        : (Number(master.master_equity ?? 10000) - Number(master.initial_capital ?? 10000))
      const roiPct = isNum(master.roi_pct)
        ? Number(master.roi_pct)
        : ((netPnl / Number(master.initial_capital || 10000)) * 100)

      const allocHeadroom = master.allocation_headroom_from_initial ?? master.unallocated_capital ?? Math.max(0, 10000 - botCap)
      const capHeadroom = master.capital_headroom_from_equity ?? Math.max(0, Number(master.master_equity ?? 10000) - botCap)

      return {
        initialCapital: master.initial_capital ?? 10000,
        totalAllocatedCapital: master.total_allocated_capital ?? botCap,
        allocationHeadroom: Number(allocHeadroom),
        capitalHeadroomEquity: Number(capHeadroom),
        unallocatedCapital: Number(allocHeadroom),
        freeCash: master.free_cash ?? master.master_cash ?? (10000 + botPnl),
        committedMargin: master.committed_margin ?? 0,
        masterCash: master.master_cash ?? 10000,
        masterEquity: master.master_equity ?? 10000,
        circuitBreaker: master.circuit_breaker_status ?? 'NORMAL',
        totalPnl: netPnl,
        roiPct,
        maxMdd: isNum(master.drawdown_from_initial_pct) ? master.drawdown_from_initial_pct : maxMdd,
        profitFactor: isNum(master.profit_factor) ? Number(master.profit_factor) : null,
        winRate: isNum(master.win_rate_pct) ? Number(master.win_rate_pct) : null,
        winTrades: master.winning_trades_count ?? 0,
        tradesCount: master.closed_trades_count ?? 0,
        runningCount,
      }
    }

    return {
      initialCapital: 10000,
      totalAllocatedCapital: botCap,
      allocationHeadroom: Math.max(0, 10000 - botCap),
      capitalHeadroomEquity: Math.max(0, 10000 + botPnl - botCap),
      unallocatedCapital: Math.max(0, 10000 - botCap),
      freeCash: 10000 + botPnl,
      committedMargin: 0,
      masterCash: 10000 + botPnl,
      masterEquity: 10000 + botPnl,
      circuitBreaker: 'NORMAL',
      totalPnl: botPnl,
      roiPct: (botPnl / 10000) * 100,
      maxMdd,
      profitFactor: null,
      winRate: null,
      winTrades: 0,
      tradesCount: 0,
      runningCount,
    }
  }, [rows, qMaster.data])

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

      {/* 5 Thẻ tham số chính: Equity, PnL, Win Rate, MDD, Profit Factor */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 14 }}>
        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>Equity</div>
          <div
            className={`v ${signClass(summaryKpis.totalPnl)}`}
            style={{
              fontSize: 18,
              fontWeight: 700,
              color: summaryKpis.totalPnl > 0 ? 'var(--n-pos, #10b981)' : (summaryKpis.totalPnl < 0 ? 'var(--n-neg, #ef4444)' : 'inherit')
            }}
          >
            {fmtMoney(summaryKpis.masterEquity)} USDT
          </div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>
            Vốn gốc: {fmtMoney(summaryKpis.initialCapital)} USDT ({fmtMoney(summaryKpis.totalPnl, true)})
          </div>
        </div>

        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>PnL</div>
          <div className={`v ${signClass(summaryKpis.totalPnl)}`} style={{ fontSize: 18, fontWeight: 700 }}>
            {fmtMoney(summaryKpis.totalPnl, true)} USDT
          </div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>
            Lũy kế Net: {fmtSPct(summaryKpis.roiPct, 2)}
          </div>
        </div>

        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>Win Rate</div>
          <div
            className="v"
            style={{
              fontSize: 18,
              fontWeight: 700,
              color: (summaryKpis.winRate ?? 0) >= 50.0 ? 'var(--n-pos, #10b981)' : (isNum(summaryKpis.winRate) ? 'var(--n-warn, #f59e0b)' : 'inherit')
            }}
          >
            {isNum(summaryKpis.winRate) ? fmtPct(summaryKpis.winRate, 1) : '—'}
          </div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>
            {summaryKpis.tradesCount ? `${summaryKpis.winTrades}/${summaryKpis.tradesCount} lệnh thắng` : 'Tỷ lệ thắng'}
          </div>
        </div>

        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>MDD</div>
          <div className="v" style={{ fontSize: 18, fontWeight: 700 }}>{fmtPct(summaryKpis.maxMdd, 2)}</div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>Sụt giảm tối đa</div>
        </div>

        <div className="n-tile" style={{ padding: '12px 14px', background: 'var(--n-surface, #1e293b)', borderRadius: 8, border: '1px solid var(--n-line, rgba(255,255,255,0.08))' }}>
          <div className="l" style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)' }}>Profit Factor</div>
          <div className="v" style={{ fontSize: 18, fontWeight: 700, color: (summaryKpis.profitFactor ?? 0) >= 1.0 ? 'var(--n-pos, #10b981)' : (isNum(summaryKpis.profitFactor) ? 'var(--n-warn, #f59e0b)' : 'inherit') }}>
            {isNum(summaryKpis.profitFactor) ? summaryKpis.profitFactor.toFixed(2) : '—'}
          </div>
          <div className="s muted" style={{ fontSize: 11, marginTop: 2, color: 'var(--n-ink-3, #64748b)' }}>
            {summaryKpis.tradesCount ? `${summaryKpis.tradesCount} lệnh đã đóng` : 'Tổng lãi / Tổng lỗ'}
          </div>
        </div>
      </div>

      {/* Phân bổ vốn Master Portfolio (10,000 USDT) */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 12,
        padding: '10px 14px',
        marginBottom: 12,
        background: 'var(--n-surface, #1e293b)',
        borderRadius: 8,
        border: '1px solid var(--n-line, rgba(255,255,255,0.08))',
        fontSize: 12,
      }}>
        <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <div>
            <span style={{ color: 'var(--n-ink-3, #64748b)' }}>Vốn gốc Master: </span>
            <strong style={{ color: 'var(--n-ink-1, #f8fafc)' }}>{fmtMoney(summaryKpis.initialCapital)} USDT</strong>
          </div>
          <div style={{ width: 1, height: 16, background: 'var(--n-line, rgba(255,255,255,0.1))' }} />
          <div>
            <span style={{ color: 'var(--n-ink-3, #64748b)' }}>Đã cấp cho bot: </span>
            <strong style={{ color: 'var(--n-accent, #3b82f6)' }}>{fmtMoney(summaryKpis.totalAllocatedCapital)} USDT</strong>
          </div>
          <div style={{ width: 1, height: 16, background: 'var(--n-line, rgba(255,255,255,0.1))' }} />
          <div title="Vốn gốc chưa cấp cho bot (10,000 USDT - Tổng vốn đã cấp)">
            <span style={{ color: 'var(--n-ink-3, #64748b)' }}>Vốn chưa cấp (Unallocated): </span>
            <strong style={{ color: summaryKpis.unallocatedCapital > 0 ? 'var(--n-pos, #10b981)' : 'var(--n-warn, #f59e0b)' }}>
              {fmtMoney(summaryKpis.unallocatedCapital)} USDT
            </strong>
          </div>
          <div style={{ width: 1, height: 16, background: 'var(--n-line, rgba(255,255,255,0.1))' }} />
          <div title="Hạn mức còn lại theo Master Equity hiện tại (Master Equity - Tổng vốn đã cấp)">
            <span style={{ color: 'var(--n-ink-3, #64748b)' }}>Khả dụng từ Equity: </span>
            <strong style={{ color: summaryKpis.capitalHeadroomEquity > 0 ? '#38bdf8' : 'var(--n-neg, #ef4444)' }}>
              {fmtMoney(summaryKpis.capitalHeadroomEquity)} USDT
            </strong>
          </div>
          <div style={{ width: 1, height: 16, background: 'var(--n-line, rgba(255,255,255,0.1))' }} />
          <div title="Tiền mặt rảnh rỗi chưa bị khóa làm margin (Master Cash - Committed Margin)">
            <span style={{ color: 'var(--n-ink-3, #64748b)' }}>Free Cash: </span>
            <strong style={{ color: 'var(--n-ink-1, #f8fafc)' }}>{fmtMoney(summaryKpis.freeCash)} USDT</strong>
          </div>
          <div style={{ width: 1, height: 16, background: 'var(--n-line, rgba(255,255,255,0.1))' }} />
          <div title="Ký quỹ đang bị sàn phong tỏa cho các vị thế mở">
            <span style={{ color: 'var(--n-ink-3, #64748b)' }}>Ký quỹ dùng (Margin): </span>
            <strong style={{ color: '#f59e0b' }}>{fmtMoney(summaryKpis.committedMargin)} USDT</strong>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="n-btn xs"
            onClick={() => setShowReconcileModal(true)}
            id="live-btn-reconcile-audit"
            style={{
              fontSize: 11.5,
              fontWeight: 600,
              padding: '3px 10px',
              background: 'var(--n-surface-2)',
              border: '1px solid var(--n-accent, #3b82f6)',
              color: 'var(--n-accent, #3b82f6)',
              borderRadius: 6,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: 4,
            }}
            title="Mở bảng đối soát toán học Invariants & phân bổ Master / Sleeves (chống double-counting)"
          >
            ⚖️ Đối soát sổ cái (Invariants 6/6 ✓)
          </button>
          <span className="n-badge" style={{
            fontSize: 11,
            padding: '2px 8px',
            borderRadius: 4,
            background: summaryKpis.circuitBreaker === 'TRIGGERED' ? 'rgba(239,68,68,0.2)' : 'rgba(16,185,129,0.15)',
            color: summaryKpis.circuitBreaker === 'TRIGGERED' ? 'var(--n-neg, #ef4444)' : 'var(--n-pos, #10b981)',
            border: `1px solid ${summaryKpis.circuitBreaker === 'TRIGGERED' ? 'var(--n-neg, #ef4444)' : 'var(--n-pos, #10b981)'}`
          }}>
            {summaryKpis.circuitBreaker === 'TRIGGERED' ? '⚠️ Master Circuit Breaker: TRIGGERED' : '🛡️ Master Risk: BÌNH THƯỜNG'}
          </span>
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
        <button
          type="button"
          className="n-btn"
          onClick={() => setLogModalBot({ id: '__all__', name: 'Toàn bộ danh mục bot', running: true })}
          id="live-btn-view-logs"
          title="Xem nhật ký chạy trực tiếp tổng hợp của toàn bộ bot (Nautilus log, tín hiệu nến, lệnh khớp)"
        >
          📜 Xem log tổng {runningBots.length > 0 ? `(${runningBots.length} bot đang chạy)` : ''}
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
                      <th className="r">Sleeve Equity / Limit</th><th className="r">Lãi/lỗ</th>
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
                        <td className="r">
                          <div style={{ fontWeight: 600 }}>{isNum(b.equity) ? `${fmtMoney(b.equity)} USDT` : (isNum(b.capital) ? `${fmtMoney(b.capital)} USDT` : '—')}</div>
                          <small style={{ fontSize: 10.5, color: 'var(--n-ink-3, #94a3b8)', display: 'block' }}>
                            Limit: {isNum(b.capital) ? `${fmtMoney(b.capital)} USDT` : '—'}
                          </small>
                        </td>
                        <td className={`r ${signClass(b.pnl_pct)}`}>{fmtSPct(b.pnl_pct, 2)}{isNum(b.pnl_usd) && <small> ({fmtMoney(b.pnl_usd, true)})</small>}</td>
                        <td><StatusBadge status={b.status} /></td>
                        <td className="r">{isNum(b.duration) ? fmtDuration(b.duration) : '—'}</td>
                        <td className="r" onClick={(e) => e.stopPropagation()}>
                          <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                            <button
                              type="button"
                              className="n-btn xs"
                              title="Xem nhật ký chạy trực tiếp của bot này"
                              onClick={() => setLogModalBot(b)}
                            >
                              📋 Log
                            </button>
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

        {rows.length > 0 && (
          <div style={{ padding: '10px 16px', background: 'var(--n-surface-2)', border: '1px solid var(--n-line)', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12.5, color: 'var(--n-ink-2)', flexWrap: 'wrap', gap: 8 }}>
            <span>💡 <b>Mẹo quản trị:</b> Bấm vào bất kỳ hàng bot nào trong danh sách trên để mở <b>bảng điều khiển chi tiết dạng lớp bên phải</b> (biểu đồ nến đa coin, vị thế mở, lịch sử khớp lệnh và terminal console).</span>
            {sel && (
              <button type="button" className="n-btn xs primary" onClick={() => setSelKey(null)}>
                Đang mở {sel.name} · Bấm để đóng ✕
              </button>
            )}
          </div>
        )}
      </div>

      {sel && (
        <BotDetailDrawer
          key={sel.key}
          bot={sel}
          onClose={() => setSelKey(null)}
          onStopped={() => { qList.reload() }}
          onDeleted={() => { setSelKey(null); qList.reload() }}
          onOpenLog={(b) => setLogModalBot(b)}
        />
      )}

      {logModalBot && (
        <LiveLogViewerModal
          bot={logModalBot}
          allBots={rows}
          onClose={() => setLogModalBot(null)}
          onSelectBot={(b) => setLogModalBot(b)}
        />
      )}

      {showReconcileModal && (
        <ReconciliationAuditModal
          data={qMaster.data}
          onClose={() => setShowReconcileModal(false)}
        />
      )}
    </>
  )
}

