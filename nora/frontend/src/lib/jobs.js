import { toMs, fmtDateTime } from './format'

// args của job là danh sách CLI (["--start","2025-01-01",...]) ở backend hiện tại, hoặc object ở bản sau.
export function parseJobArgs(args) {
  if (!args) return {}
  if (!Array.isArray(args)) return args
  const o = {}
  for (let i = 0; i < args.length; i++) {
    if (typeof args[i] === 'string' && args[i].startsWith('--')) { o[args[i].slice(2)] = args[i + 1]; i++ }
  }
  let strategies
  try { strategies = o.strategies ? JSON.parse(o.strategies) : undefined } catch (e) { strategies = undefined }
  return {
    strategies,
    symbols: o.symbols ? o.symbols.split(',') : undefined,
    start: o.start,
    end: o.end,
    risk_per_trade_pct: o['risk-per-trade'] != null ? Number(o['risk-per-trade']) : undefined,
    stop_fill: o['stop-fill'],
    // chỉ có ở job WFA
    train_days: o['train-days'] != null ? Number(o['train-days']) : undefined,
    test_days: o['test-days'] != null ? Number(o['test-days']) : undefined,
    n: o.n != null ? Number(o.n) : undefined,
    fixed: o['strategies-json'] != null ? true : (o.candidates != null || o.report != null ? false : undefined),
  }
}

export function jobLabel(j) {
  const a = parseJobArgs(j.args)
  const ids = a.strategies ? a.strategies.map((s) => s.id).join(' + ') : 'sổ hiện tại'
  const win = a.start && a.end ? ` · ${a.start} → ${a.end}` : ''
  return `${ids}${win}`
}

export const JOB_STATUS = {
  queued: { text: 'Đang chờ hàng đợi', cls: 'warn' },
  running: { text: 'Đang chạy', cls: 'info' },
  done: { text: 'Hoàn tất', cls: 'ok' },
  failed: { text: 'Thất bại', cls: 'bad' },
  cancelled: { text: 'Đã huỷ', cls: 'warn' },
}

export const jobWhen = (j) => fmtDateTime(toMs(j.created))

export const JOB_KIND = {
  book_backtest: { text: 'Backtest', short: 'Backtest' },
  book_wfa: { text: 'Walk-forward', short: 'WFA' },
  book_build: { text: 'Alpha · tối ưu', short: 'Alpha' },
  funnel_run: { text: 'Phễu kiểm duyệt', short: 'Phễu' },
}
export const jobKindText = (k) => JOB_KIND[k]?.text || String(k || '—')

/** Đường dẫn mở đúng trang/bước của một job (deep link). */
export function jobLink(j) {
  const id = encodeURIComponent(j.job_id || j.id)
  if (String(j.kind || '').startsWith('funnel')) {
    const rid = j.run_id || parseJobArgs(j.args)['run-id'] || parseJobArgs(j.args).run_id
    return rid ? `/funnel/${encodeURIComponent(rid)}` : '/funnel'
  }
  if (j.kind === 'book_wfa') return `/backtest?wfa=${id}&step=2`
  if (j.kind === 'book_build') return `/alpha?build=${id}`
  return `/backtest?job=${id}`
}

export const isActiveJob = (j) => j.status === 'running' || j.status === 'queued'

/** Thời gian của job (giây): đang chạy = từ lúc bắt đầu tới nay, xong = lúc chạy thực tế, đang chờ = đã chờ bao lâu. */
export function jobElapsed(j, now = Date.now()) {
  const created = toMs(j.created)
  const started = toMs(j.started)
  const finished = toMs(j.finished)
  const from = started || created
  if (!from) return null
  return Math.max(0, ((finished || now) - from) / 1000)
}

/** Nhãn job bỏ phần tên loại ở đầu ("Backtest · …"), ngày đổi sang dd/mm/yyyy. */
export function jobDetail(j) {
  const parts = String(j.label || '').split(' · ')
  const body = (parts.length > 1 ? parts.slice(1).join(' · ') : parts[0]) || j.job_id || ''
  return body.replace(/(\d{4})-(\d{2})-(\d{2})/g, '$3/$2/$1').replace(/→/g, ' → ')
}

/** Tiến độ job tối ưu lớn từ progress.json (backend/optimize/progress.py): {pct, rate, eta, stage, done, total} hoặc null. */
export function jobProgress(j) {
  const p = j?.progress
  if (!p || !(p.total > 0)) return null
  const done = Math.max(0, Math.min(p.done || 0, p.total))
  return { pct: Math.round((done / p.total) * 1000) / 10, done, total: p.total, stage: p.stage || '', rate: p.rate || 0, eta: p.eta_s ?? null,
    peakMb: p.peak_rss_mb ?? null, status: p.status }
}

/** Tốc độ dễ đọc: >= 1/giây -> "x/giây", ngược lại "y/phút". */
export function fmtRate(rate) {
  if (!(rate > 0)) return '—'
  return rate >= 1 ? `${rate.toFixed(1)}/giây` : `${(rate * 60).toFixed(rate * 60 >= 10 ? 0 : 1)}/phút`
}
