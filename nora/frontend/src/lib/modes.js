// Chế độ chạy Cơ bản / Nâng cao (docs/ui_contract.md §7): hằng số, kiểm tham số phía client khớp lược đồ, ánh xạ lỗi 422 theo trường.
import { paramLabel } from './params'

export const MODES = [{ value: 'basic', label: 'Cơ bản' }, { value: 'advanced', label: 'Nâng cao' }]
export const modeText = (m) => (m === 'advanced' ? 'Nâng cao' : 'Cơ bản')

export const CUSTOM_BADGE = 'Cấu hình tuỳ chỉnh — không xuất bản được'
export const CUSTOM_REASON = 'Cổng khác chuẩn (ngưỡng, kịch bản cực xấu hoặc dưới 10.000 mô phỏng) nên kết quả chỉ để thử nghiệm: không xuất bản / promote được.'

// Backend (backend/api/modes.py): WFA chỉ nhận khoá thuộc `space`; step_days / sims / mc_seed trả 422 cho tới khi cờ này bật.
// API chưa công bố cờ, nên đây là hằng số phía giao diện: đổi thành true khi backend hỗ trợ (chỗ khác không cần sửa).
export const WFA_SCHEMA_KEYS_SUPPORTED = false
export const WFA_PENDING_NOTE = 'chưa hỗ trợ ở WFA (đang làm)'

export const WFA_STD = { train_days: 120, test_days: 30 }
export const MC_STD = { simulations: 10000, block_days: 5, horizon_days: 365, ruin_threshold_pct: 30, seed: 7, scale: 1, stress_max_mdd_pct: 50 }
export const STRESS = [
  { name: 'worst_days_first', label: 'Ngày lỗ tệ nhất đến trước' },
  { name: 'reversed_order', label: 'Đảo ngược lịch sử' },
  { name: 'crash_day', label: 'Ngày sập (2× ngày xấu nhất)' },
  { name: 'cost_x2', label: 'Phí gấp đôi' },
  { name: 'longest_losing_streak_x2', label: 'Chuỗi ngày lỗ dài nhất lặp 2 lần' },
  { name: 'worst_bootstrap', label: 'Bootstrap tệ nhất' },
]
export const STRESS_ALL = STRESS.map((s) => s.name)

/** MC có đổi cổng so với chuẩn không (khớp rm.mc_standard của backend). */
export function mcIsCustom(f) {
  const subset = f.stress || STRESS_ALL
  return !(Number(f.simulations) >= MC_STD.simulations && Number(f.ruin_threshold_pct) === MC_STD.ruin_threshold_pct
    && Number(f.stress_max_mdd_pct) === MC_STD.stress_max_mdd_pct && STRESS_ALL.every((n) => subset.includes(n)))
}

// ---- preset ----
const flag = (v) => (v === true ? true : v === false ? false : null)   // presets.json ghi bool thật (P0.9)
export const SOURCE_KIND = { book: 'Sổ đã xuất bản', stage_a: 'Lần tối ưu gần nhất (stage A)', default: 'Mặc định — chưa tối ưu' }

/** Gom thông tin hiển thị của preset: nguồn, có phải mặc định chưa tối ưu không, kết quả kiểm chứng dev2. */
export function presetInfo(preset) {
  const ev = preset?.evidence || null
  const isDefault = preset?.source_kind === 'default' || !ev
  const accepted = ev ? flag(ev.accepted) : null
  const dev2Pass = ev ? flag(ev.dev2_pass) : null
  // kiểm chứng dev2 trượt: dev2_verified=false (stage A không có cấu hình top-K qua dev2), dev2_pass=false,
  // hoặc accepted=false khi không có dev2_pass
  const failedDev2 = !isDefault && (ev.dev2_verified === false || dev2Pass === false || (dev2Pass == null && accepted === false))
  return {
    isDefault, failedDev2, accepted, dev2Pass, timeframe: preset?.timeframe || null,
    sourceText: preset?.source || SOURCE_KIND[preset?.source_kind] || '—',
    kindText: SOURCE_KIND[preset?.source_kind] || '',
    dev1: ev?.dev1 || null, dev2Level: ev?.dev2_level || null, dev2Extreme: ev?.dev2_extreme || null,
    stability: ev?.stability || null, holdoutPass: ev ? flag(ev.holdout_pass) : null, bookStatus: ev?.book_status || null,
  }
}

/** Chế độ Cơ bản: các preset đã chọn được tối ưu ở khung khác khung chạy -> [{ id, timeframe }] (khớp timeframe_mismatch của backend).
 *  Preset mặc định (timeframe null) không tính. */
export function timeframeMismatch(ids, byId, timeframe) {
  return ids.map((id) => ({ id, timeframe: byId[id]?.preset?.timeframe || null }))
    .filter((x) => x.timeframe && x.timeframe !== timeframe)
}

// ---- kiểm tham số theo lược đồ (khớp backend/core/strategy/run_modes.py: kiểu, khoảng, tập chọn) ----
const isBlank = (v) => v === '' || v == null
const fmtN = (n) => String(+Number(n).toFixed(4))

/** Lỗi của một ô theo spec; null nếu hợp lệ. */
export function validateValue(spec, v) {
  if (spec.type === 'choice') return spec.choices.includes(v) ? null : `Phải là một trong: ${spec.choices.join(', ')}`
  if (isBlank(v)) return 'Nhập một số'
  const n = Number(v)
  if (!Number.isFinite(n)) return 'Phải là một số'
  if (spec.type === 'int' && !Number.isInteger(n)) return 'Phải là số nguyên'
  const unit = spec.unit ? ` ${spec.unit}` : ''
  if (n < spec.min || n > spec.max) return `Phải nằm trong khoảng ${fmtN(spec.min)} đến ${fmtN(spec.max)}${unit}`
  return null
}

/** { [khoá]: thông báo } cho cả một chiến lược (kể cả ràng buộc chéo EMA nhanh < EMA chậm). */
export function validateStrategy(schema, params) {
  const errs = {}
  Object.entries(schema).forEach(([k, spec]) => {
    const e = validateValue(spec, params[k])
    if (e) errs[k] = e
  })
  const f = Number(params['sig.ema_fast'])
  const s = Number(params['sig.ema_slow'])
  if (!errs['sig.ema_fast'] && !errs['sig.ema_slow'] && 'sig.ema_fast' in schema && 'sig.ema_slow' in schema && f >= s) {
    errs['sig.ema_fast'] = `${paramLabel('sig.ema_fast')} phải nhỏ hơn ${paramLabel('sig.ema_slow')} (${fmtN(s)})`
  }
  return errs
}

/** Chuỗi gõ trong ô -> số cho int/float; chuỗi khung thời gian giữ nguyên. Ô trống / không phải số giữ nguyên để backend báo lỗi. */
export function coerceParams(schema, params) {
  const out = {}
  Object.entries(schema).forEach(([k, spec]) => {
    const v = params[k]
    out[k] = spec.type === 'choice' || isBlank(v) || !Number.isFinite(Number(v)) ? v : Number(v)
  })
  return out
}

export const sameValue = (a, b) => (typeof a === 'string' && Number.isNaN(Number(a)) ? a === b : Number(a) === Number(b))

/** Preset đầy đủ cho một chiến lược (bản sao để sửa). */
export const presetParams = (strat) => ({ ...(strat.preset?.params || {}) })

/** Khoá thay đổi so với preset. */
export function changedKeys(schema, params, preset) {
  return Object.keys(schema).filter((k) => !sameValue(params[k], preset[k]))
}

// ---- lỗi 422 theo trường ----
/**
 * fields: [{field, msg}] (ApiError.fields); ids: id chiến lược theo đúng thứ tự đã gửi.
 * -> { per: { [id]: { [khoá]: msg, '': lỗi chung của chiến lược } }, general: [msg] }
 */
export function splitServerErrors(fields, ids) {
  const per = {}
  const general = []
  ;(fields || []).forEach(({ field, msg }) => {
    const m = /^strategies\[(\d+)\](?:\.(?:params|configs\[\d+\]))?(?:\.(.*))?$/.exec(field || '')
    if (m && ids[Number(m[1])]) {
      const id = ids[Number(m[1])]
      per[id] = { ...(per[id] || {}), [m[2] ?? '']: msg }
    } else general.push(field && !/^(body|strategies)$/.test(field) ? `${field}: ${msg}` : msg)
  })
  return { per, general }
}

/** Lỗi theo trường của body phẳng (MC, WFA): { [tên]: msg } + phần còn lại. */
export function flatServerErrors(fields) {
  const byName = {}
  const rest = []
  ;(fields || []).forEach(({ field, msg }) => { if (field && /^[a-z_]+$/.test(field)) byName[field] = msg; else rest.push(msg) })
  return { byName, rest }
}
