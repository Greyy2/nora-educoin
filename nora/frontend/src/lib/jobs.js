import { toMs, fmtDateTime } from './format'

// params của job (job.json): dict tham số mà API đã kiểm, cùng tên khoá với run_job(params) của backend.
export function parseJobParams(p) {
  if (!p || typeof p !== 'object' || Array.isArray(p)) return {}
  const list = (v) => (v == null ? undefined : Array.isArray(v) ? v : String(v).split(',').filter(Boolean))
  return {
    strategies: Array.isArray(p.strategies) ? p.strategies : undefined,
    symbols: list(p.symbols),
    start: p.start,
    end: p.end,
    risk_per_trade_pct: p.risk_per_trade != null ? Number(p.risk_per_trade) : undefined,
    stop_fill: p.stop_fill,
    timeframe: p.timeframe,
    // chỉ có ở job WFA
    train_days: p.train_days != null ? Number(p.train_days) : undefined,
    test_days: p.test_days != null ? Number(p.test_days) : undefined,
    n: p.n != null ? Number(p.n) : undefined,
    fixed: Array.isArray(p.strategies) && p.strategies.some((s) => s && s.configs) ? true : (p.candidates != null || p.report != null ? false : undefined),
    run_id: p.run_id || p.resume,
  }
}

export function jobLabel(j) {
  const a = parseJobParams(j.params)
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
  funnel_recompute: { text: 'Phễu · tính lại lệnh', short: 'Phễu' },
  presets_build: { text: 'Dựng preset', short: 'Preset' },
  data_crawl: { text: 'Tải dữ liệu', short: 'Dữ liệu' },
  data_promote: { text: 'Đưa dữ liệu vào kho', short: 'Dữ liệu' },
}
export const jobKindText = (k) => JOB_KIND[k]?.text || String(k || '—')

/** Đường dẫn mở đúng trang/bước của một job (deep link). */
export function jobLink(j) {
  const id = encodeURIComponent(j.job_id || j.id)
  if (String(j.kind || '').startsWith('funnel')) {
    const rid = j.run_id || parseJobParams(j.params).run_id
    return rid ? `/alpha/funnel/${encodeURIComponent(rid)}` : '/alpha/funnel'
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
