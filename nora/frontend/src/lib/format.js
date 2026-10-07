// Định dạng số / ngày cho giao diện v2. Dấu thập phân là dấu chấm, phân nghìn bằng dấu phẩy (khớp bản mẫu).
export const isNum = (v) => typeof v === 'number' && Number.isFinite(v)

export function fmtNum(v, d = 2) {
  if (!isNum(v)) return '—'
  const out = v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
  return /^-0(\.0+)?$/.test(out) ? out.slice(1) : out // không hiện "-0.00"
}

export function fmtSigned(v, d = 2, suffix = '') {
  if (!isNum(v)) return '—'
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
  if (Number(s.replace(/,/g, '')) === 0) return `${s}${suffix}`
  return `${v > 0 ? '+' : '−'}${s}${suffix}`
}

export const fmtPct = (v, d = 2) => (isNum(v) ? `${fmtNum(v, d)}%` : '—')
export const fmtSPct = (v, d = 2) => (isNum(v) ? fmtSigned(v, d, '%') : '—')

// Tiền USDT: ≥ 1M rút gọn thành M, còn lại hai chữ số thập phân.
export function fmtMoney(v, signed = false) {
  if (!isNum(v)) return '—'
  const a = Math.abs(v)
  const body = a >= 1e6 ? `${(a / 1e6).toFixed(2)}M` : a.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (!signed) return `${v < 0 ? '−' : ''}${body}`
  if (a < 0.005) return body
  return `${v > 0 ? '+' : '−'}${body}`
}

export function signClass(v) {
  if (!isNum(v) || v === 0) return ''
  return v > 0 ? 'pos' : 'neg'
}
export const arrow = (v) => (!isNum(v) || v === 0 ? '' : v > 0 ? '▲' : '▼')

// Nhãn tick trục: số chữ số thập phân theo bước tick.
export function fmtTick(v, step = 1) {
  if (!isNum(v)) return ''
  const dec = step >= 1 ? 0 : Math.min(4, Math.ceil(-Math.log10(step)))
  return v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec }).replace('-', '−')
}

export function compact(v) {
  if (!isNum(v)) return '—'
  const a = Math.abs(v)
  const sign = v < 0 ? '−' : ''
  if (a >= 1e9) return `${sign}${(a / 1e9).toFixed(1)}B`
  if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(1)}M`
  if (a >= 1e4) return `${sign}${(a / 1e3).toFixed(1)}K`
  return `${sign}${a.toLocaleString('en-US', { maximumFractionDigits: a < 10 ? 2 : 0 })}`
}

// 'YYYY-MM-DD' -> 'd/M'
export function dmy(s) {
  if (typeof s !== 'string' || s.length < 10) return ''
  return `${Number(s.slice(8, 10))}/${Number(s.slice(5, 7))}`
}
export const my = (s) => (typeof s === 'string' && s.length >= 10 ? `${Number(s.slice(8, 10))}/${Number(s.slice(5, 7))}/${s.slice(2, 4)}` : '')
export const fullDate = (s) => (typeof s === 'string' && s.length >= 10 ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : '')

// Thời gian job: giây (float) hoặc ms hoặc ISO -> ms
export function toMs(t) {
  if (t == null) return null
  if (typeof t === 'string') { const d = Date.parse(t); return Number.isNaN(d) ? null : d }
  if (!isNum(t)) return null
  return t < 1e11 ? t * 1000 : t
}

export function fmtDateTime(ms) {
  const t = toMs(ms)
  if (t == null) return '—'
  const d = new Date(t)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
}

export function fmtDuration(sec) {
  if (!isNum(sec) || sec < 0) return '—'
  const s = Math.floor(sec)
  const m = Math.floor(s / 60)
  const h = Math.floor(m / 60)
  const p = (n) => String(n).padStart(2, '0')
  return h ? `${h}:${p(m % 60)}:${p(s % 60)}` : `${m}:${p(s % 60)}`
}

export const finite = (a) => (Array.isArray(a) ? a.filter(isNum) : [])
