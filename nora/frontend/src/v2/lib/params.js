// Nguồn duy nhất cho nhãn / đơn vị / cách hiển thị tham số chiến lược. Khoá thô vẫn được giữ làm tooltip cho người dùng chuyên sâu.
const num = (v) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v ?? '—')
  return String(+n.toFixed(2))
}

// timeout tính bằng phút: 0 = không giới hạn; < 2 ngày hiện theo giờ, còn lại theo ngày
export function fmtTimeout(v) {
  const m = Number(v)
  if (!Number.isFinite(m)) return String(v ?? '—')
  if (m === 0) return 'Không giới hạn'
  if (m % 1440 === 0 && m >= 2880) return `${m / 1440} ngày`
  if (m % 60 === 0) return `${m / 60} giờ`
  return `${num(m)} phút`
}

export const PARAMS = {
  stop_loss_rate: { label: 'Cắt lỗ', unit: '× ATR', hint: 'Khoảng cách cắt lỗ, tính bằng bội số ATR' },
  take_profit_rate: { label: 'Chốt lời', unit: '× ATR', hint: 'Khoảng cách chốt lời, tính bằng bội số ATR' },
  trailing_stop: { label: 'Trailing', unit: '× ATR', hint: 'Khoảng bám đuôi của lệnh cắt lỗ động' },
  trailing_activation_pct: { label: 'Kích hoạt trailing', unit: '× ATR', zero: 'Ngay', hint: 'Lãi tối thiểu (bội số ATR) trước khi trailing bắt đầu bám; 0 = ngay' },
  timeout: { label: 'Giữ tối đa', unit: '', fmt: fmtTimeout, hint: 'Thời gian giữ lệnh tối đa; 0 = không giới hạn' },
  'sig.adx_min': { label: 'ADX tối thiểu', unit: '' },
  'sig.roc_min': { label: 'ROC 24h tối thiểu (%)', unit: '%' },
  'sig.rsi_lo': { label: 'RSI dưới', unit: '' },
  'sig.rsi_hi': { label: 'RSI trên', unit: '' },
  'sig.er_max': { label: 'ER tối đa (đi ngang)', unit: '' },
  cooldown: { label: 'Chờ sau khi thoát (phút)', unit: 'phút' },
  // thông số vị thế hay gặp ở kho alpha
  order_size_pct: { label: 'Cỡ lệnh (% vốn)', unit: '%' },
  leverage: { label: 'Đòn bẩy', unit: '×' },
  market: { label: 'Thị trường', unit: '', fmt: (v) => String(v) },
}

// `adx_min` (kho alpha) và `sig.adx_min` (danh mục) là cùng một tham số
function meta(key) {
  return PARAMS[key] || PARAMS[`sig.${key}`] || null
}

export const paramLabel = (key) => meta(key)?.label || String(key)

export function paramUnit(key) {
  const u = meta(key)?.unit
  return u || ''
}

/** Tiêu đề cột / nhãn có đơn vị: "Cắt lỗ (× ATR)". Đơn vị đã nằm trong nhãn thì không thêm lần nữa. */
export function paramHeader(key) {
  const m = meta(key)
  if (!m) return String(key)
  const u = m.unit
  return u && !m.label.includes('(') && !['phút', '%'].includes(u) ? `${m.label} (${u})` : m.label
}

/** Giá trị đã định dạng, KHÔNG kèm đơn vị (dùng dưới tiêu đề cột đã có đơn vị). */
export function fmtParam(key, v) {
  const m = meta(key)
  if (v == null) return '—'
  if (m?.fmt) return m.fmt(v)
  if (m?.zero && Number(v) === 0) return m.zero
  return num(v)
}

/** Giá trị kèm đơn vị: "2.5× ATR", "7 ngày", "Ngay". */
export function fmtParamFull(key, v) {
  const m = meta(key)
  const base = fmtParam(key, v)
  if (!m || m.fmt || (m.zero && Number(v) === 0) || !m.unit || m.label.includes('(')) return base
  return m.unit.startsWith('×') ? `${base}${m.unit}` : `${base} ${m.unit}`
}

/** "Cắt lỗ 2.5× ATR" */
export const paramText = (key, v) => `${paramLabel(key)} ${fmtParamFull(key, v)}`

/** Hai bộ tham số có giống nhau không (so theo giá trị số). */
export function sameParams(a, b) {
  const ka = Object.keys(a || {})
  const kb = Object.keys(b || {})
  if (ka.length !== kb.length) return false
  return ka.every((k) => b && k in b && Number(a[k]) === Number(b[k]))
}
