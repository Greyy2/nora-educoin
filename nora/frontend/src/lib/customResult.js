// Chuẩn hoá result.json của job custom_backtest (docs/bmad/p7_python_strategies.md §6, p8_education_user_alpha.md) cho giao diện: CHỈ đổi tên khoá / đơn vị để hiển thị,
// KHÔNG tính chỉ số nào (mọi con số do backend tính; thiếu -> null -> giao diện hiện "—").
//   - Bộ chỉ số xnoquant (quy năm 252 kỳ): cagr, annual_return, max_drawdown, win_rate, total_return là PHÂN SỐ (0,41 = 41 %).
//   - Bộ chỉ số Nora (quy năm 365 ngày): khoá có hậu tố _pct là phần trăm; win_rate_trades cũng là phần trăm (0-100, trade_stats).
//   - Chuỗi vẽ biểu đồ: series.stages.{all,train,test} do backend tính trên dữ liệu ngày đầy đủ (equity, pnl, drawdown_pct, ret_pct, benchmark) và hạ mẫu chỉ để vẽ.
import { isNum, toMs } from './format'

const pick = (o, keys) => {
  for (const k of keys) if (o && isNum(o[k])) return o[k]
  return null
}
const times100 = (v) => (isNum(v) ? v * 100 : null)
const firstNum = (...vs) => vs.find(isNum) ?? null

/** Một khối chỉ số (train / test / simulate) -> số đã đổi về phần trăm / số thực, null nếu thiếu. */
export function normMetrics(m) {
  if (!m || typeof m !== 'object') return null
  // backend trả { xno, nora }: chỉ số theo ngày (sharpe, sortino, calmar, win_rate, profit_factor) lấy bộ xno; lãi, MDD, lệnh, phí lấy bộ Nora
  const sharpeNora = m.nora ? pick(m.nora, ['sharpe']) : null      // Sharpe khối Nora (quy năm 365 ngày); `sharpe` bên dưới là khối xno (252 kỳ)
  if (m.xno || m.nora) m = { ...(m.nora || {}), ...(m.xno || {}) }
  const mdd = firstNum(pick(m, ['mdd_pct']), times100(pick(m, ['max_drawdown'])))
  return {
    ret: firstNum(pick(m, ['ret_pct']), times100(pick(m, ['total_return', 'cumulative_return']))),
    cagr: pick(m, ['cagr_pct']),                                   // CAGR (365 ngày), khối Nora — KHÔNG trộn với quy ước 252 kỳ của xnoquant
    cagrXno: times100(pick(m, ['annual_return', 'cagr'])),         // CAGR xno (252 kỳ)
    sharpe: pick(m, ['sharpe']),
    sharpeNora,
    sortino: pick(m, ['sortino']),
    mdd: isNum(mdd) ? -Math.abs(mdd) : null,
    calmar: pick(m, ['calmar']),
    winDays: times100(pick(m, ['win_rate'])),
    winTrades: pick(m, ['win_rate_trades']),                       // phần trăm (0-100) theo lệnh đã đóng
    pfDays: pick(m, ['profit_factor']),
    pfTrades: pick(m, ['profit_factor_trades']),
    trades: pick(m, ['trades', 'total_closed_trades']),
    fees: pick(m, ['fees_usd']),
  }
}

/** Bảng theo năm: [{ year, stage, cagr %, sharpe, mdd %, pf, calmar }]. */
export function normYearly(rows) {
  return (Array.isArray(rows) ? rows : []).map((r) => ({
    year: r.year ?? r.time ?? '',
    stage: r.stage || '',
    cagr: times100(pick(r, ['cagr', 'annual_return'])),
    sharpe: pick(r, ['sharpe']),
    mdd: (() => { const v = times100(pick(r, ['max_drawdown'])); return isNum(v) ? -Math.abs(v) : null })(),
    pf: pick(r, ['profit_factor']),
    calmar: pick(r, ['calmar']),
  }))
}

const iso = (t) => { const ms = toMs(t); return ms == null ? '' : new Date(ms).toISOString().slice(0, 10) }

/** Cảnh báo có thể là chuỗi hoặc { message, line }. */
export const normWarnings = (w) => (Array.isArray(w) ? w : []).map((x) => (typeof x === 'string' ? x : x?.message || JSON.stringify(x))).filter(Boolean)

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
  { keys: ['enter_time', 'entry_time', 'open_time'], label: 'Vào lúc', kind: 'time' },
  { keys: ['close_time', 'exit_time'], label: 'Ra lúc', kind: 'time' },
  { keys: ['symbol', 'sym'], label: 'Tài sản', kind: 'sym' },
  { keys: ['side'], label: 'Chiều', kind: 'side' },
  { keys: ['enter_price', 'entry_price', 'avg_price'], label: 'Giá vào', kind: 'price', r: true },
  { keys: ['close_price', 'exit_price'], label: 'Giá ra', kind: 'price', r: true },
  { keys: ['qty', 'size', 'quantity'], label: 'Khối lượng', kind: 'qty', r: true },
  { keys: ['ret_pct', 'return_pct', 'pnl_pct'], label: 'Lãi/lỗ %', kind: 'spct', r: true },
  { keys: ['pnl', 'net_pnl', 'pnl_usd'], label: 'Lãi/lỗ (USDT)', kind: 'money', r: true },
  { keys: ['fee', 'fee_usd', 'fees'], label: 'Phí', kind: 'num', r: true },
]
export const SYMBOL_COLS = [
  { keys: ['symbol', 'sym'], label: 'Tài sản', kind: 'sym' },
  { keys: ['weight', 'weight_pct'], label: 'Tỉ trọng', kind: 'num', r: true },
  { keys: ['trades', 'n_trades'], label: 'Số lệnh', kind: 'int', r: true },
  { keys: ['wins'], label: 'Lệnh thắng', kind: 'int', r: true },
  { keys: ['ret_pct', 'return_pct'], label: 'Lãi/lỗ %', kind: 'spct', r: true },
  { keys: ['pnl', 'pnl_usd', 'net_pnl'], label: 'Lãi/lỗ (USDT)', kind: 'money', r: true },
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
