import { fmtNum } from './format'

// Nguồn duy nhất cho nhãn / đơn vị / cách hiển thị tham số chiến lược, đồng bộ từ params_schema của backend.
const num = (v) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v ?? '—')
  return fmtNum(n, 2)
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

let _schemaRegistry = {}

/** Đăng ký lược đồ tham số từ backend (khi nạp /api/studio/strategies). */
export function registerParamSchema(schemaOrList) {
  if (!schemaOrList) return
  if (Array.isArray(schemaOrList)) {
    schemaOrList.forEach((st) => {
      if (st?.params_schema) {
        Object.assign(_schemaRegistry, st.params_schema)
      }
    })
  } else if (typeof schemaOrList === 'object') {
    Object.assign(_schemaRegistry, schemaOrList)
  }
}

// Chỉ nhãn / đơn vị của các trường hệ thống (WFA / MC) hiển thị ngoài lược đồ chiến lược. KHÔNG chứa số liệu hay ngưỡng:
// min / max / mặc định / mô tả của các trường Monte Carlo lấy từ meta.limits.book_mc (xem bookMcSpec trong lib/modes.js).
const SYSTEM_PARAM_LABELS = {
  step_days: { label_vi: 'Bước trượt fold', unit: 'ngày', help_vi: 'Mỗi fold trượt bấy nhiêu ngày (mặc định bằng số ngày test)' },
  sims: { label_vi: 'Số kịch bản MC của WFA', unit: 'kịch bản' },
  mc_seed: { label_vi: 'Seed MC của WFA', unit: '' },
  simulations: { label_vi: 'Số mô phỏng', unit: 'kịch bản' },
  block_days: { label_vi: 'Độ dài khối (ngày)', unit: 'ngày' },
  horizon_days: { label_vi: 'Chân trời (ngày)', unit: 'ngày' },
  seed: { label_vi: 'Seed', unit: '' },
  scale: { label_vi: 'Hệ số quy mô', unit: '×' },
  ruin_threshold_pct: { label_vi: 'Ngưỡng phá sản MDD (%)', unit: '%' },
  stress_max_mdd_pct: { label_vi: 'MDD tối đa của kịch bản cực xấu (%)', unit: '%' },
  extra_cost_daily_pct: { label_vi: 'Phí bổ sung kịch bản phí gấp đôi (%/ngày)', unit: '%/ngày', help_vi: 'Bỏ trống = dùng hằng số bảo thủ của backend' },
  order_size_pct: { label_vi: 'Cỡ lệnh (% vốn)', unit: '%' },
  market: { label_vi: 'Thị trường', unit: '' },
}

function findSpec(key, schema) {
  if (schema) {
    if (schema[key]) return schema[key]
    if (schema[`sig.${key}`]) return schema[`sig.${key}`]
    if (typeof key === 'string' && key.startsWith('sig.') && schema[key.slice(4)]) return schema[key.slice(4)]
  }
  if (_schemaRegistry[key]) return _schemaRegistry[key]
  if (_schemaRegistry[`sig.${key}`]) return _schemaRegistry[`sig.${key}`]
  if (typeof key === 'string' && key.startsWith('sig.') && _schemaRegistry[key.slice(4)]) return _schemaRegistry[key.slice(4)]
  if (SYSTEM_PARAM_LABELS[key]) return SYSTEM_PARAM_LABELS[key]
  return null
}

export function paramLabel(key, schema) {
  const s = findSpec(key, schema)
  return s?.label_vi || s?.label || String(key)
}

export function paramUnit(key, schema) {
  const s = findSpec(key, schema)
  return s?.unit || ''
}

export function paramHint(key, schema) {
  const s = findSpec(key, schema)
  return s?.help_vi || s?.hint || ''
}

/** Tiêu đề cột / nhãn có đơn vị: "Cắt lỗ (× ATR)". Đơn vị đã nằm trong nhãn thì không thêm lần nữa. */
export function paramHeader(key, schema) {
  const lbl = paramLabel(key, schema)
  const u = paramUnit(key, schema)
  return u && !lbl.includes('(') && !['phút', '%'].includes(u) ? `${lbl} (${u})` : lbl
}

/** Giá trị đã định dạng, KHÔNG kèm đơn vị (dùng dưới tiêu đề cột đã có đơn vị). */
export function fmtParam(key, v, schema) {
  if (v == null) return '—'
  if (key === 'timeout') return fmtTimeout(v)
  if ((key === 'take_profit_rate' || key === 'trailing_stop') && Number(v) === 0) return 'Tắt'
  if (key === 'trailing_activation_pct' && Number(v) === 0) return 'Ngay'
  const s = findSpec(key, schema)
  if (s?.zero && Number(v) === 0) return s.zero
  return num(v)
}

/** Giá trị kèm đơn vị: "2.5× ATR", "7 ngày", "Ngay". */
export function fmtParamFull(key, v, schema) {
  const base = fmtParam(key, v, schema)
  const u = paramUnit(key, schema)
  const lbl = paramLabel(key, schema)
  if (key === 'timeout' || (['take_profit_rate', 'trailing_stop', 'trailing_activation_pct'].includes(key) && Number(v) === 0)) return base
  if (!u || lbl.includes('(')) return base
  return u.startsWith('×') ? `${base}${u}` : `${base} ${u}`
}

/** "Cắt lỗ 2.5× ATR" */
export const paramText = (key, v, schema) => `${paramLabel(key, schema)} ${fmtParamFull(key, v, schema)}`

/** Hai bộ tham số có giống nhau không (so theo giá trị số). */
export function sameParams(a, b) {
  const ka = Object.keys(a || {})
  const kb = Object.keys(b || {})
  if (ka.length !== kb.length) return false
  return ka.every((k) => b && k in b && Number(a[k]) === Number(b[k]))
}

export const DEFAULT_GROUP_LABELS = {
  signal: 'Tín hiệu vào lệnh',
  dca: 'Dồn lệnh (DCA)',
  exit: 'Thoát lệnh',
  risk: 'Rủi ro và vốn',
}

/** Gom nhóm tham số động từ `params_schema[k].group`. */
export function getParamGroups(schema) {
  if (!schema) return []
  const order = ['signal', 'dca', 'exit', 'risk']
  const map = new Map()
  Object.entries(schema).forEach(([k, spec]) => {
    const g = spec?.group || 'other'
    if (!map.has(g)) map.set(g, [])
    map.get(g).push(k)
  })
  const sorted = Array.from(map.keys()).sort((a, b) => {
    const ia = order.indexOf(a)
    const ib = order.indexOf(b)
    if (ia !== -1 && ib !== -1) return ia - ib
    if (ia !== -1) return -1
    if (ib !== -1) return 1
    return a.localeCompare(b)
  })
  return sorted.map((g) => ({
    key: g,
    label: DEFAULT_GROUP_LABELS[g] || g,
    keys: map.get(g),
  }))
}
