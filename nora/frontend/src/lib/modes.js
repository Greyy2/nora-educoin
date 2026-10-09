// Chế độ chạy Cơ bản / Nâng cao (docs/ui_contract.md §7): hằng số, kiểm tham số phía client khớp lược đồ, ánh xạ lỗi 422 theo trường.
import { paramLabel } from './params'
import { fmtNum } from './format'

export const MODES = [{ value: 'basic', label: 'Cơ bản' }, { value: 'advanced', label: 'Nâng cao' }]
export const modeText = (m) => (m === 'advanced' ? 'Nâng cao' : 'Cơ bản')

export const CUSTOM_BADGE = 'Cấu hình tuỳ chỉnh — không xuất bản được'
export const CUSTOM_REASON = 'Cổng khác chuẩn (ngưỡng, kịch bản cực xấu hoặc ít mô phỏng hơn mức chuẩn) nên kết quả chỉ để thử nghiệm: không xuất bản / promote được.'

// Khớp backend/routes/modes.py (WFA_SCHEMA_KEYS_SUPPORTED = True từ P0.3b): WFA nâng cao nhận mọi khoá của lược đồ (chu kỳ, khung)
// cùng step_days / sims / mc_seed. Trước đây cờ phía giao diện bị bỏ quên ở false nên các ô này bị khoá dù máy chủ đã hỗ trợ.
export const WFA_SCHEMA_KEYS_SUPPORTED = true
export const WFA_PENDING_NOTE = 'chưa hỗ trợ ở WFA (đang làm)'

export function getWfaStd(meta) {
  const lim = meta?.limits?.book_wfa
  if (!lim?.train_days?.default || !lim?.test_days?.default) return null
  return {
    train_days: lim.train_days.default,
    test_days: lim.test_days.default,
  }
}

export function getMcStd(meta) {
  const lim = meta?.limits?.book_mc
  const gates = meta?.funnel?.gates || []
  const findGate = (k) => gates.find((g) => g.key === k)?.value
  const simulations = findGate('MC_MIN_SIMULATIONS') ?? lim?.simulations?.default
  const ruin_threshold_pct = findGate('MC_RUIN_THRESHOLD_PCT') ?? lim?.ruin_threshold_pct?.default
  const stress_max_mdd_pct = findGate('STRESS_MAX_MDD_PCT') ?? lim?.stress_max_mdd_pct?.default
  if (simulations == null || ruin_threshold_pct == null) return null
  return {
    simulations,
    block_days: lim?.block_days?.default,
    horizon_days: lim?.horizon_days?.default,
    ruin_threshold_pct,
    max_ruin_pct: findGate('MC_MAX_RUIN_PCT'),
    seed: lim?.seed?.default,
    scale: lim?.scale?.default,
    stress_max_mdd_pct,
  }
}

/** Kịch bản cực xấu từ meta.stress: [{ name, label, default_on, needs_positions }]. Chưa có meta -> []. */
export function getStressScenarios(meta) {
  return (meta?.stress || []).map((x) => ({ name: x.key, label: x.label_vi, default_on: !!x.default_on, needs_positions: !!x.needs_positions }))
}

/** Spec ô nhập cho một trường book_mc: min/max/help từ meta.limits.book_mc (exclusiveMinimum -> minExclusive). */
export function bookMcSpec(meta, key, type, extra = {}) {
  const l = meta?.limits?.book_mc?.[key] || {}
  const exclusive = l.minimum == null && l.exclusiveMinimum != null
  return { type, min: l.minimum ?? l.exclusiveMinimum, minExclusive: exclusive, max: l.maximum, help_vi: l.help_vi, ...extra }
}

/** MC có đổi cổng so với chuẩn không (khớp rm.mc_standard của backend). */
export function mcIsCustom(f, meta) {
  const std = getMcStd(meta)
  if (!std) return false
  const allStress = getStressScenarios(meta).map((s) => s.name)
  const subset = f.stress || allStress
  return !(Number(f.simulations) >= std.simulations && Number(f.ruin_threshold_pct) === std.ruin_threshold_pct
    && Number(f.stress_max_mdd_pct) === std.stress_max_mdd_pct && allStress.every((n) => subset.includes(n)))
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

// ---- kiểm tham số theo lược đồ (khớp backend/optimize/book/build.py::check_value: kiểu, khoảng, tập chọn) ----
const isBlank = (v) => v === '' || v == null
const fmtN = (n) => fmtNum(Number(n), 4)

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
