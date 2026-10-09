// Phễu kiểm duyệt: tên tầng, nhãn chỉ số và bộ chuẩn hoá payload (docs/funnel_contract.md).
// Hợp đồng mới ghi rõ hình dạng của /stats; các phần còn lại (danh sách, chi tiết, lệnh) được chuẩn hoá khoan dung
// để UI không gãy khi backend thêm/đổi tên trường nhỏ.
import { isNum, fmtMetric as fmtMetricCore, metricTone as metricToneCore } from './format'

// Meta hiện hành (MetaProvider đăng ký khi nạp /api/studio/meta): dùng khi nơi gọi (api.js chuẩn hoá payload, định dạng ô) không có `meta` trong tay.
let _meta = null
export const registerFunnelMeta = (meta) => { _meta = meta || null }

export const stageName = (s, meta) => {
  if ((meta || _meta)?.funnel?.stages) {
    const st = (meta || _meta).funnel.stages.find((x) => x.id === s)
    if (st?.label) return st.label
  }
  return String(s || '—')
}

export const stageShort = (s, meta) => {
  if ((meta || _meta)?.funnel?.stages) {
    const st = (meta || _meta).funnel.stages.find((x) => x.id === s)
    if (st?.short) return st.short
  }
  return String(s || '—')
}

export const stageRule = (s, meta) => {
  if (!(meta || _meta)?.funnel?.gates) return ''
  const gates = (meta || _meta).funnel.gates.filter((g) => g.stage === s)
  if (!gates.length) return ''
  return gates.map((g) => {
    const d = meta.metrics?.defs?.[g.key]
    const label = d?.label_vi || g.key
    const unit = d?.unit ? ` ${d.unit}` : ''
    return `${label}: ${g.value}${unit}`
  }).join('; ')
}

export const getAllFunnelStages = (meta) => {
  if ((meta || _meta)?.funnel?.stages) {
    return (meta || _meta).funnel.stages.map((x) => x.id)
  }
  return []
}

export const getFunnelStages = (meta) => {
  if ((meta || _meta)?.funnel?.stages) {
    return (meta || _meta).funnel.stages.filter((x) => !x.legacy).map((x) => x.id)
  }
  return []
}

export const stageIdx = (s, meta) => {
  const all = getAllFunnelStages(meta)
  return all.indexOf(s)
}

/** Tầng có dữ liệu thống kê phân phối / lệnh (S0 chỉ có số lượng). */
export const stageHasTrades = (s, meta) => {
  if ((meta || _meta)?.funnel?.stages) {
    const st = (meta || _meta).funnel.stages.find((x) => x.id === s)
    if (st) return Boolean(st.has_trades)
  }
  return false
}

export const getFunnelGates = (meta) => (meta || _meta)?.funnel?.gates || []

export const RUN_STATUS = {
  queued: { text: 'Đang chờ', cls: 'warn' }, running: { text: 'Đang chạy', cls: 'info' }, done: { text: 'Hoàn tất', cls: 'ok' },
  failed: { text: 'Thất bại', cls: 'bad' }, cancelled: { text: 'Đã huỷ', cls: 'warn' },
}

// ---- chỉ số: nhãn / đơn vị / định dạng đều lấy từ meta.metrics.defs; ở đây chỉ giữ phần thuần giao diện ----
// term = khoá glossary, tone = tô màu theo dấu. Khoá không có trong bảng này không hiện ở ma trận chỉ số theo tầng.
export const METRICS = {
  ret_pct: { tone: true }, mdd_pct: { term: 'mdd' }, sharpe: { term: 'sharpe' }, sortino: { term: 'sortino' }, trades: {}, win_rate: {},
  profit_factor: { term: 'profit_factor' }, symbols_positive: {}, dsr: { term: 'dsr' }, neighbor_ratio: { term: 'neighbor' },
  pbo_strategy: { term: 'pbo' }, pbo_flag: {}, folds: { term: 'fold' }, folds_profitable: {}, positive_ratio: {}, traded_folds: {}, fold_t: {},
  oos_ex_best_pct: { tone: true }, worst_fold_mdd: {}, is_ret_avg: { term: 'is', tone: true }, p_mdd_ge_30: { term: 'p_mdd' },
  stress_max_mdd: { term: 'stress' }, mdd_p95: {}, simulations: {}, final_scale: { term: 'scale_s' }, search_steps: {},
  cagr_pct: { tone: true }, calmar: {}, cvar95_pct: {}, max_dd_days: {}, payoff: {}, mdd_intrabar_pct: {}, mdd_daily_pct: {},
  mdd_basis: {}, fees_usd: {}, funding_usd: {}, n_days: {}, halted: {},
}
const defsOf = (meta) => meta?.metrics?.defs || (meta && !meta.metrics && typeof meta === 'object' ? meta : null) || _meta?.metrics?.defs || null
export const metricLabel = (k, meta) => defsOf(meta)?.[k]?.label_vi || ''
export const metricUnit = (k, meta) => defsOf(meta)?.[k]?.unit || ''
export const metricHelp = (k, meta) => defsOf(meta)?.[k]?.help_vi || ''
export const metricTone = (k, v, meta) => metricToneCore(k, v, defsOf(meta))

export function fmtMetric(k, v, defs) {
  if (v == null) return '—'
  const metricDefs = defsOf(defs)
  const def = metricDefs?.[k]
  if (typeof v === 'boolean') return v ? 'Có' : 'Không'
  // backend ghi rõ "thang 0–1 (nhân 100 khi hiển thị)" trong help_vi của chỉ số
  if (isNum(v) && def?.unit === '%' && /thang 0[–-]1/.test(def.help_vi || '')) v = v * 100
  return fmtMetricCore(k, v, metricDefs)
}

/** Sáu chỉ số phân phối dùng cho biểu đồ chồng nhóm vào/ra. */
export const DIST_KEYS = ['ret_pct', 'mdd_pct', 'sharpe', 'trades', 'win_rate', 'profit_factor']

// ---- chuẩn hoá ----
const arr = (...c) => { for (const x of c) if (Array.isArray(x)) return x; return [] }
const num = (v) => (isNum(v) ? v : (v != null && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null))

const isLegacyStage = (st, meta) => !!(meta || _meta)?.funnel?.stages?.find((x) => x.id === st)?.legacy

export function normCounts(counts, meta) {
  const list = Array.isArray(counts) ? counts : Object.entries(counts || {}).map(([stage, c]) => ({ stage, ...(typeof c === 'object' ? c : { passed: c }) }))
  const by = Object.fromEntries(list.map((c) => [c.stage, c]))
  const allStages = getAllFunnelStages(meta)
  const stagesToUse = allStages.length ? allStages : list.map((c) => c.stage)
  return stagesToUse.filter((st) => !isLegacyStage(st, meta) || by[st]).map((st, i) => {
    const c = by[st]
    if (!c) return { stage: st, input: null, passed: null, top_reject: null }
    const passed = num(c.passed ?? c.out ?? c.count)
    const input = num(c.input ?? c.in ?? (i === 0 ? passed : null))
    return { stage: st, input, passed, top_reject: c.top_reject || null }
  })
}

/** Tách số đếm của một lượt thành luồng chính (`counts`) và tầng cũ (`legacy_counts`, theo cờ legacy của meta). Gọi lúc render với meta hiện hành
 *  (không dựa vào lúc chuẩn hoá payload, khi meta có thể chưa nạp). Tầng cũ không nằm trong luồng chuyển đổi chính. */
export function splitLegacy(run, meta) {
  if (!run) return run
  const all = run.all_counts || run.counts
  return { ...run, all_counts: all, counts: all.filter((c) => !isLegacyStage(c.stage, meta)), legacy_counts: all.filter((c) => isLegacyStage(c.stage, meta)) }
}

export function normRun(r) {
  if (!r) return null
  const cfg = r.config || {}
  const counts = normCounts(r.counts || r.stages)
  return {
    ...r,
    run_id: r.run_id || r.id,
    job_id: r.job_id || null,
    status: r.status || (r.finished ? 'done' : 'running'),
    created: r.created ?? r.created_at ?? null,
    strategies: arr(r.strategies, cfg.strategies).map((s) => (typeof s === 'string' ? s : s.id)),
    n_per_strategy: r.n_per_strategy ?? cfg.n_per_strategy ?? null,
    full_grid: r.full_grid ?? cfg.full_grid ?? false,
    seed: r.seed ?? cfg.seed ?? null,
    symbols: arr(r.symbols, cfg.symbols),
    windows: r.windows || cfg.windows || null,
    total_alphas: num(r.total_alphas) ?? counts[0].passed ?? null,
    counts,
    all_counts: counts,
    progress: r.progress || null,
  }
}
export const normRuns = (raw) => arr(raw, raw?.runs, raw?.items).map(normRun)

/** Dải bin -> [{lo,hi,count}] từ [{lo,hi,count}] hoặc {edges,counts} hoặc [counts] + edges. */
export function normBins(b, edges) {
  if (!b) return []
  if (Array.isArray(b) && b.length && typeof b[0] === 'object') return b.map((x) => ({ lo: x.lo ?? x.x0 ?? x.from, hi: x.hi ?? x.x1 ?? x.to, count: x.count ?? x.n ?? 0 }))
  const e = b.edges || edges
  const c = b.counts || (Array.isArray(b) ? b : null)
  if (e && c && e.length === c.length + 1) return c.map((n, i) => ({ lo: e[i], hi: e[i + 1], count: n }))
  return []
}
export function normDist(d) {
  if (!d) return null
  const side = (s) => (s ? { bins: normBins(s.bins ?? s, s.edges ?? d.edges), p5: s.p5 ?? null, p50: s.p50 ?? null, p95: s.p95 ?? null, n: s.n ?? null } : null)
  const i = side(d.in)
  const o = side(d.out)
  if (!i?.bins.length && !o?.bins.length) return null
  return { in: i, out: o }
}
export function normStats(s) {
  if (!s) return null
  const dist = {}
  Object.entries(s.distributions || {}).forEach(([k, d]) => { const n = normDist(d); if (n) dist[k] = n })
  return { ...s, distributions: dist, reject_reasons: s.reject_reasons || [], by_strategy: s.by_strategy || [], param_survival: s.param_survival || [], top: s.top || [] }
}

export function normAlpha(a) {
  if (!a) return null
  return {
    ...a,
    alpha_id: a.alpha_id || a.id,
    params: a.params || (a.params_json ? safeJson(a.params_json) : {}),
    metrics: a.metrics || (a.metrics_json ? safeJson(a.metrics_json) : {}),
    stage_reached: a.stage_reached || null,
    rejected_stage: a.rejected_stage || null,
    final_scale: num(a.final_scale),
  }
}
function safeJson(s) { try { return typeof s === 'string' ? JSON.parse(s) : s } catch (e) { return {} } }

export function normAlphaPage(raw) {
  const items = arr(raw, raw?.items, raw?.alphas, raw?.rows).map(normAlpha)
  return { items, total: num(raw?.total ?? raw?.count) ?? items.length }
}

/** Chi tiết alpha -> { ...alpha, stages: [{stage, status:'pass'|'fail'|'none', code, msg, metrics}], nav:{stage:{dates,values}}, mc } */
export function normAlphaDetail(raw, meta) {
  if (!raw) return null
  const a = normAlpha(raw)
  const allStages = getAllFunnelStages(meta)
  const metricsBy = raw.stage_metrics || raw.metrics_by_stage || (a.metrics && allStages.some((s) => a.metrics[s]) ? a.metrics : {})
  const reachedI = stageIdx(a.stage_reached, meta)
  const rejI = stageIdx(a.rejected_stage, meta)
  let stages = arr(raw.stages, raw.journey)
  if (!stages.length) {
    stages = allStages.slice(1).filter((st) => {
      const stMeta = (meta || _meta)?.funnel?.stages?.find((x) => x.id === st)
      return !stMeta?.legacy || metricsBy[st] || rejI === stageIdx(st, meta)
    }).map((st) => {
      const i = stageIdx(st, meta)
      let status = 'none'
      if (rejI === i) status = 'fail'
      else if (reachedI > i || (reachedI === i && rejI < 0)) status = 'pass'
      else if (reachedI >= i && rejI < 0) status = 'pass'
      return { stage: st, status, metrics: metricsBy[st] || null, code: status === 'fail' ? a.reject_code : null, msg: status === 'fail' ? a.reject_msg : null }
    })
  } else {
    stages = stages.map((s) => ({
      ...s, status: s.status || (s.passed === true ? 'pass' : s.passed === false ? 'fail' : 'none'),
      metrics: s.metrics || metricsBy[s.stage] || null, code: s.reject_code ?? s.code ?? null, msg: s.reject_msg ?? s.msg ?? null,
    }))
  }
  const nav = {}
  Object.entries(raw.nav || raw.nav_curves || {}).forEach(([st, v]) => {
    const n = normNav(v)
    if (n) nav[st] = n
  })
  const isFinal = a.stage_reached === 'FINAL' && !a.rejected_stage
  return { ...a, stages, nav, mc: raw.mc || null, scale_search: raw.scale_search || raw.mc?.scale_search || null, isFinal, promoted: !!(raw.promoted || raw.in_registry) }
}
function normNav(v) {
  if (!v) return null
  if (Array.isArray(v) && v.length && typeof v[0] === 'object') return { dates: v.map((p) => p.date ?? p.t ?? p.d), values: v.map((p) => p.nav ?? p.value ?? p.v) }
  if (v.dates && (v.values || v.nav)) return { dates: v.dates, values: v.values || v.nav }
  return null
}

export function normTrades(raw) {
  const items = arr(raw, raw?.items, raw?.trades, raw?.rows)
  const stored = raw?.stored ?? raw?.available ?? (raw?.recompute_required === true ? false : true)
  return { items, total: num(raw?.total ?? raw?.count) ?? items.length, folds: raw?.folds || null, stored: stored !== false, recomputed: !!raw?.recomputed, totals: raw?.totals || null, raw }
}

/** Rút gọn mã alpha để hiển thị (8 ký tự đầu). */
export const shortId = (id) => (id ? String(id).slice(0, 8) : '—')

export function fmtEta(sec) {
  if (!isNum(sec) || sec < 0) return '—'
  const m = Math.round(sec / 60)
  if (m < 1) return '< 1 phút'
  if (m < 90) return `${m} phút`
  const h = Math.floor(m / 60)
  return `${h} giờ ${String(m % 60).padStart(2, '0')} phút`
}
export const fmtCount = (n) => (isNum(n) ? n.toLocaleString('en-US') : '—')
