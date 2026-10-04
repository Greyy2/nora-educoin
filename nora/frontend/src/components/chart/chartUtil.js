import { isNum } from '../../lib/format'

// Giờ UTC dạng dd/mm/yyyy HH:MM từ giây hoặc ms
export function fmtTs(v) {
  if (!isNum(v)) return '—'
  const d = new Date(v < 1e11 ? v * 1000 : v)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
}

// Số chữ số thập phân theo độ lớn (giá coin nhỏ cần nhiều chữ số hơn)
export const decFor = (v) => { const a = Math.abs(v); return a >= 1000 ? 2 : a >= 100 ? 2 : a >= 1 ? 3 : a >= 0.01 ? 5 : 7 }
export const fmtVal = (v) => (isNum(v) ? v.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: decFor(v) }) : '—')

// Thời điểm nến gần nhất (mảng `times` đã tăng dần)
export function snapTime(times, t) {
  if (!times.length) return t
  let lo = 0
  let hi = times.length - 1
  while (lo < hi) {
    const m = (lo + hi) >> 1
    if (times[m] < t) lo = m + 1
    else hi = m
  }
  if (lo > 0 && Math.abs(times[lo - 1] - t) <= Math.abs(times[lo] - t)) lo -= 1
  return times[lo]
}

// Cửa sổ nến quanh một lệnh (mili giây); mặc định khung 1 giờ. Server giới hạn 5000 nến.
export function tradeWindow(enterMs, closeMs, barMs = 3600e3, before = 200, after = 60) {
  const end = (closeMs || enterMs) + after * barMs
  return { start: Math.round(enterMs - before * barMs), end: Math.round(end) }
}

// Tín hiệu vào gây ra lệnh: tín hiệu `entry` gần nhất có t <= thời điểm vào lệnh (giây)
export function signalForTrade(signals, enterMs) {
  const e = enterMs / 1000
  let best = null
  ;(signals || []).forEach((s) => { if (s.kind === 'entry' && s.t <= e && (!best || s.t > best.t)) best = s })
  return best
}
