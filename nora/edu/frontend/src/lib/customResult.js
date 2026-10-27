// Chuẩn hoá result.json của job custom_backtest (docs/bmad/p7_python_strategies.md §6, p8_education_user_alpha.md) cho giao diện: CHỈ đổi tên khoá / đơn vị để hiển thị,
// KHÔNG tính chỉ số nào (mọi con số do backend tính; thiếu -> null -> giao diện hiện "—").
//   - MỘT bộ chỉ số (metrics.simulate / train / test): năm = 365 ngày; khoá có hậu tố _pct là phần trăm (win_rate_trades cũng là phần trăm 0-100).
//   - Chuỗi vẽ biểu đồ: series.stages.{all,train,test} do backend tính trên dữ liệu ngày đầy đủ (equity, pnl, drawdown_pct, ret_pct, benchmark) và hạ mẫu chỉ để vẽ.
import { isNum, toMs } from './format'

const pick = (o, keys) => {
  for (const k of keys) if (o && isNum(o[k])) return o[k]
  return null
}

/** Một khối chỉ số (train / test / simulate) -> số hiển thị, null nếu thiếu. mdd luôn âm. */
export function normMetrics(m) {
  if (!m || typeof m !== 'object') return null
  const mdd = pick(m, ['mdd_pct'])
  return {
    ret: pick(m, ['ret_pct']),
    cagr: pick(m, ['cagr_pct']),
    days: pick(m, ['days', 'oos_days']),
    sharpe: pick(m, ['sharpe']),
    sortino: pick(m, ['sortino', 'sortino_ratio']),
    mdd: isNum(mdd) ? -Math.abs(mdd) : null,
    calmar: pick(m, ['calmar', 'calmar_ratio']),
    winTrades: pick(m, ['win_rate_trades']),
    pfTrades: pick(m, ['profit_factor_trades', 'profit_factor']),
    pfNote: m.profit_factor_note || null,
    trades: pick(m, ['trades']),
    fees: pick(m, ['fees_usd']),
    volAnn: pick(m, ['vol_ann_pct']),
    var95: pick(m, ['var95_pct']),
    cvar95: pick(m, ['cvar95_pct']),
    winDays: pick(m, ['win_days_pct']),
    bestDay: pick(m, ['best_day_pct']),
    worstDay: pick(m, ['worst_day_pct']),
    payoff: pick(m, ['payoff']),
    payoffNote: m.payoff_note || null,
    expectancyPct: pick(m, ['expectancy_pct']),
    feeDrag: pick(m, ['fee_drag_pct']),
    maxDdDays: pick(m, ['max_dd_days']),
    maxConsecLosses: pick(m, ['max_consec_losses', 'max_consecutive_losses']),
    top5Share: pick(m, ['top5_share_pct']),
    maeWorst: pick(m, ['mae_worst_pct']),
    liqProximity: pick(m, ['liq_proximity_max_pct']),
    liquidations: pick(m, ['liquidations']),
  }
}

/** Bảng theo năm: [{ year, stage, days, cagr %, sharpe, mdd %, pf, calmar }] (cùng bộ chỉ số phẳng). */
export function normYearly(rows) {
  return (Array.isArray(rows) ? rows : []).map((r) => {
    const mdd = pick(r, ['mdd_pct'])
    return {
      year: r.year ?? '',
      stage: r.stage || '',
      days: pick(r, ['days']),
      cagr: pick(r, ['cagr_pct']),
      sharpe: pick(r, ['sharpe']),
      mdd: isNum(mdd) ? -Math.abs(mdd) : null,
      pf: pick(r, ['profit_factor_trades']),
      calmar: pick(r, ['calmar']),
    }
  })
}

const iso = (t) => { const ms = toMs(t); return ms == null ? '' : new Date(ms).toISOString().slice(0, 10) }

/** Cảnh báo có thể là chuỗi hoặc { message, line }. */
export const normWarnings = (w) => (Array.isArray(w) ? w : []).map((x) => (typeof x === 'string' ? x : x?.message || JSON.stringify(x))).filter(Boolean)

const normalizeSymbol = (symbol) => String(symbol).trim().replace(/@perp$/i, '').replace(/-USDT$/i, '').toUpperCase()
const normalizeOverrides = (overrides) => Object.fromEntries(
  Object.entries(overrides || {})
    .filter(([, value]) => value !== '' && value != null)
    .map(([key, value]) => [key, Number.isFinite(Number(value)) && value !== '' ? Number(value) : value])
    .sort(([left], [right]) => left.localeCompare(right)),
)

/** Compare form inputs with the worker's actual run config; null means no detected mismatch. */
export function runConfigDiff(currentForm, config, defaultMode = 'fast') {
  if (!currentForm || !config) return null
  const configSymbols = config.data_symbols || config.symbols
  if (Array.isArray(currentForm.symbols) && Array.isArray(configSymbols)) {
    const formSyms = currentForm.symbols.map(normalizeSymbol).sort()
    const resultSyms = configSymbols.map(normalizeSymbol).sort()
    if (JSON.stringify(formSyms) !== JSON.stringify(resultSyms)) return 'cặp tài sản'
  }
  if (currentForm.start && config.start && currentForm.start !== config.start) return 'ngày bắt đầu'
  if (currentForm.end && config.end && currentForm.end !== config.end) return 'ngày kết thúc'
  if (currentForm.train_ratio != null && config.train_ratio != null && Number(currentForm.train_ratio) !== Number(config.train_ratio)) return 'tỉ lệ train'
  if (currentForm.capital != null && config.initial_capital != null && Number(currentForm.capital) !== Number(config.initial_capital)) return 'vốn ban đầu'
  const mode = currentForm.exec_mode || defaultMode
  const expectedFrame = mode === 'standard' ? '1m' : config.timeframe
  if (expectedFrame && config.run_frame && expectedFrame !== config.run_frame) return 'khung nến'
  if (config.position_overrides && JSON.stringify(normalizeOverrides(currentForm.pos)) !== JSON.stringify(normalizeOverrides(config.position_overrides))) {
    return 'tham số quản lý vị thế'
  }
  return null
}

/** Lỗi biên dịch -> { line, col, message } từ object `error`, hoặc từ thông báo HTTP dạng JSON / "dòng N". */
export function parseCompileError(err) {
  if (!err) return null
  if (typeof err === 'object') return { line: Number(err.line) || null, col: Number(err.col) || null, message: err.message || err.msg || 'Lỗi biên dịch' }
  let o = null
  try { o = JSON.parse(err) } catch (e) { /* không phải JSON */ }
  if (o && typeof o === 'object') return parseCompileError(o.error || o)
  const m = /(?:dòng|line)\s*(\d+)(?:\D+(?:cột|col)\D*(\d+))?/i.exec(String(err))
  return { line: m ? Number(m[1]) : null, col: m && m[2] ? Number(m[2]) : null, message: String(err) }
}

// ---- bảng lệnh / theo tài sản: tên cột chưa chốt nên mỗi cột có danh sách khoá thay thế ----
export const TRADE_COLS = [
  { keys: ['trade_no', 'no', 'index'], label: '#', kind: 'int' },
  { keys: ['enter_time', 'entry_time', 'open_time'], label: 'Vào lúc', kind: 'time' },
  { keys: ['close_time', 'exit_time'], label: 'Ra lúc', kind: 'time' },
  { keys: ['symbol', 'sym'], label: 'Tài sản', kind: 'sym' },
  { keys: ['side'], label: 'Chiều', kind: 'side' },
  { keys: ['enter_price', 'entry_price', 'avg_price'], label: 'Giá vào', kind: 'price', r: true },
  { keys: ['close_price', 'exit_price'], label: 'Giá ra', kind: 'price', r: true },
  { keys: ['qty', 'size', 'quantity'], label: 'Khối lượng', kind: 'qty', r: true },
  { keys: ['ret_pct', 'return_pct', 'pnl_pct'], label: 'Lãi/lỗ %', kind: 'spct', r: true },
  { keys: ['pnl', 'net_pnl', 'pnl_usd'], label: 'Lãi/lỗ (USDT)', kind: 'money', r: true },
  { keys: ['cum_pnl'], label: 'PnL tích lũy', kind: 'money', r: true },
  { keys: ['fee', 'fee_usd', 'fees_usd', 'fees'], label: 'Phí', kind: 'num', r: true },
  { keys: ['funding_usd', 'funding'], label: 'Funding', kind: 'num', r: true },
  { keys: ['status'], label: 'Trạng thái', kind: 'side' },
  { keys: ['close_reason', 'reason'], label: 'Lý do đóng', kind: 'text' },
  { keys: ['leverage'], label: 'Đòn bẩy', kind: 'num', r: true },
  { keys: ['mae_pct'], label: 'MAE', kind: 'spct', r: true },
  { keys: ['entry_equity'], label: 'Vốn lúc vào', kind: 'money', r: true },
]
export const SYMBOL_COLS = [
  { keys: ['symbol', 'sym'], label: 'Tài sản', kind: 'sym' },
  { keys: ['weight', 'weight_pct'], label: 'Tỉ trọng %', kind: 'num', r: true },
  { keys: ['trades', 'n_trades'], label: 'Số lệnh', kind: 'int', r: true },
  { keys: ['wins'], label: 'Lệnh thắng', kind: 'int', r: true },
  { keys: ['ret_pct', 'return_pct'], label: 'Lãi/lỗ %', kind: 'spct', r: true },
  { keys: ['pnl', 'pnl_usd', 'net_pnl'], label: 'Lãi/lỗ (USDT)', kind: 'money', r: true },
  { keys: ['open_pnl_usd', 'unrealized_pnl'], label: 'Vị thế mở (USDT)', kind: 'money', r: true },
  { keys: ['fees_usd', 'fee', 'fees'], label: 'Phí', kind: 'num', r: true },
]
export const POSITION_COLS = [
  { keys: ['symbol', 'sym'], label: 'Tài sản', kind: 'sym' },
  { keys: ['side'], label: 'Chiều', kind: 'side' },
  { keys: ['enter_time', 'entry_time', 'open_time', 'opened'], label: 'Mở lúc', kind: 'time' },
  { keys: ['enter_price', 'entry_price', 'avg_price'], label: 'Giá vào', kind: 'price', r: true },
  { keys: ['mark_price', 'last_price'], label: 'Giá hiện tại', kind: 'price', r: true },
  { keys: ['qty', 'size', 'quantity'], label: 'Khối lượng', kind: 'qty', r: true },
  { keys: ['unrealized_pnl', 'pnl'], label: 'Lãi/lỗ chưa chốt', kind: 'money', r: true },
]

/** Chọn cột có dữ liệu trong `rows`; không khớp cột nào thì hiện mọi khoá nguyên thuỷ của dòng đầu. */
export function resolveCols(rows, spec) {
  const first = rows.slice(0, 50)
  const cols = spec.map((c) => ({ ...c, key: c.keys.find((k) => first.some((r) => r && r[k] != null)) })).filter((c) => c.key)
  if (cols.length) return cols
  const r0 = rows[0] && typeof rows[0] === 'object' ? rows[0] : {}
  return Object.keys(r0).filter((k) => typeof r0[k] !== 'object').map((k) => ({ key: k, label: k, kind: typeof r0[k] === 'number' ? 'num' : 'text', r: typeof r0[k] === 'number' }))
}

/**
 * Chuỗi vẽ của một giai đoạn ('all' | 'train' | 'test') từ series.stages do BACKEND tính (không tính lại ở trình duyệt):
 * { dates, equity, pnl, dd (%, <= 0), ret (% ngày), splitIdx (vạch Train|Test, chỉ ở 'all'), n, downsample, bench: { equity, pnl, label } | null } hoặc null khi không có.
 * Test = lần chạy lại từ vốn đầu tại mốc chia, benchmark của nó cũng được backend chạy lại cùng cửa sổ (không co dãn).
 */
export function stagePlot(series, stage) {
  const b = series?.stages?.[stage]
  const n = Array.isArray(b?.times) ? b.times.length : 0
  if (!n || !['equity', 'pnl', 'drawdown_pct', 'ret_pct'].every((k) => Array.isArray(b[k]) && b[k].length === n)) return null
  const split = toMs(series.stage_split)
  const bm = b.benchmark && Array.isArray(b.benchmark.equity) && b.benchmark.equity.length === n && Array.isArray(b.benchmark.pnl) && b.benchmark.pnl.length === n
    ? { equity: b.benchmark.equity, pnl: b.benchmark.pnl, label: b.benchmark.label || null } : null
  return {
    dates: b.times.map(iso), equity: b.equity, pnl: b.pnl, dd: b.drawdown_pct, ret: b.ret_pct, n, downsample: b.downsample || null, bench: bm,
    splitIdx: stage === 'all' && split != null ? b.times.findIndex((t) => toMs(t) >= split) : -1,
  }
}
