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
}

export const jobWhen = (j) => fmtDateTime(toMs(j.created))
