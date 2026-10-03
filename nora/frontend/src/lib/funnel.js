// Phễu kiểm duyệt: tên tầng, nhãn chỉ số và bộ chuẩn hoá payload (docs/funnel_contract.md).
// Hợp đồng mới ghi rõ hình dạng của /stats; các phần còn lại (danh sách, chi tiết, lệnh) được chuẩn hoá khoan dung
// để UI không gãy khi backend thêm/đổi tên trường nhỏ.
import { isNum, fmtNum, fmtPct, fmtSPct } from './format'

export const STAGES = ['S0_generate', 'S1_backtest', 'S2_antiluck', 'S3_wfa', 'S4_montecarlo', 'S5_sizing', 'S6_holdout', 'FINAL']

export const STAGE_META = {
  S0_generate: { short: 'S0', name: 'Sinh alpha', data: 'Không gian tham số', rule: 'Hợp lệ (vd. ngân sách DCA); mỗi alpha có mã riêng' },
  S1_backtest: { short: 'S1', name: 'Backtest sàng lọc', data: 'dev1', rule: 'Lãi > 0, MDD ≤ 30%, đủ số lệnh, đủ số tài sản có lãi' },
  S2_antiluck: { short: 'S2', name: 'Chống ăn may', data: 'dev1 + lân cận', rule: 'DSR ≥ 0,95; lân cận tham số có lãi ≥ 60%; PBO chiến lược ≤ 0,5' },
  S3_wfa: { short: 'S3', name: 'Walk-forward', data: 'dev2', rule: '≥ 5 fold, ≥ 60% fold OOS lãi, lãi kép OOS > 0, MDD fold xấu nhất ≤ 30%' },
  S4_montecarlo: { short: 'S4', name: 'Monte Carlo', data: 'chuỗi ngày OOS', rule: '≥ 10.000 kịch bản, P(MDD ≥ 30%) ≤ 5%, mọi kịch bản cực xấu MDD < 50%' },
  S5_sizing: { short: 'S5', name: 'Khối lượng sống sót', data: 'như S4', rule: 'Hệ số vốn lớn nhất s sống sót qua S4, xác nhận bằng backtest + WFA + MC; s ≥ 0,2' },
  S6_holdout: { short: 'S6', name: 'Holdout', data: '20% cuối', rule: 'Ở hệ số s: lãi > 0, MDD ≤ 30% (đúng mức và giá xấu nhất)' },
  FINAL: { short: 'FINAL', name: 'Đủ điều kiện testnet', data: '', rule: 'Qua mọi tầng; ghi vào kho alpha kèm s và bằng chứng' },
}
export const stageName = (s) => STAGE_META[s]?.name || String(s || '—')
export const stageShort = (s) => STAGE_META[s]?.short || String(s || '—')
export const stageIdx = (s) => STAGES.indexOf(s)
/** Tầng có dữ liệu thống kê phân phối / lệnh (S0 chỉ có số lượng). */
export const stageHasTrades = (s) => ['S1_backtest', 'S2_antiluck', 'S3_wfa', 'S4_montecarlo', 'S5_sizing', 'S6_holdout'].includes(s)

export const RUN_STATUS = {
  queued: { text: 'Đang chờ', cls: 'warn' }, running: { text: 'Đang chạy', cls: 'info' }, done: { text: 'Hoàn tất', cls: 'ok' },
  failed: { text: 'Thất bại', cls: 'bad' }, cancelled: { text: 'Đã huỷ', cls: 'warn' },
}

// ---- chỉ số: nhãn + định dạng. `k` là khoá glossary nếu có ----
const f1 = (v) => fmtNum(v, 1)
export const METRICS = {
  ret_pct: { label: 'Lãi', fmt: (v) => fmtSPct(v, 1), tone: true },
  mdd_pct: { label: 'MDD', term: 'mdd', fmt: (v) => fmtPct(v, 1) },
  sharpe: { label: 'Sharpe', term: 'sharpe', fmt: (v) => fmtNum(v, 2) },
  sortino: { label: 'Sortino', term: 'sortino', fmt: (v) => fmtNum(v, 2) },
  trades: { label: 'Số lệnh', fmt: (v) => fmtNum(v, 0) },
  win_rate: { label: 'Tỉ lệ thắng', fmt: (v) => fmtPct(v, 1) },
  profit_factor: { label: 'Profit factor', term: 'profit_factor', fmt: (v) => fmtNum(v, 2) },
  symbols_positive: { label: 'Tài sản có lãi', fmt: (v) => fmtNum(v, 0) },
  dsr: { label: 'DSR', term: 'dsr', fmt: (v) => fmtNum(v, 3) },
  neighbor_ratio: { label: 'Lân cận có lãi', term: 'neighbor', fmt: (v) => fmtPct(v * 100, 0) },
  pbo_strategy: { label: 'PBO (chiến lược)', term: 'pbo', fmt: (v) => fmtNum(v, 2) },
  pbo_flag: { label: 'Cờ PBO', fmt: (v) => (v ? 'Có' : 'Không') },
  folds: { label: 'Số fold', term: 'fold', fmt: (v) => fmtNum(v, 0) },
  folds_profitable: { label: 'Fold lãi', fmt: (v) => fmtNum(v, 0) },
  positive_ratio: { label: 'Tỉ lệ fold lãi (fold có lệnh)', fmt: (v) => fmtPct(v * 100, 0) },
  traded_folds: { label: 'Fold có lệnh', fmt: (v) => fmtNum(v, 0) },
  fold_t: { label: 't-stat lãi theo fold', fmt: (v) => fmtNum(v, 2) },
  oos_ex_best_pct: { label: 'Lãi OOS bỏ fold tốt nhất', fmt: (v) => fmtSPct(v, 2), tone: true },
  worst_fold_mdd: { label: 'MDD fold xấu nhất', fmt: (v) => fmtPct(v, 1) },
  is_ret_avg: { label: 'Lãi IS trung bình', term: 'is', fmt: (v) => fmtSPct(v, 1), tone: true },
  p_mdd_ge_30: { label: 'P(MDD ≥ 30%)', term: 'p_mdd', fmt: (v) => fmtPct(v, 1) },
  stress_max_mdd: { label: 'MDD kịch bản cực xấu', term: 'stress', fmt: (v) => fmtPct(v, 1) },
  mdd_p95: { label: 'MDD P95', fmt: (v) => fmtPct(v, 1) },
  simulations: { label: 'Số mô phỏng', fmt: (v) => fmtNum(v, 0) },
  final_scale: { label: 'Hệ số s', term: 'scale_s', fmt: (v) => fmtNum(v, 2) },
  search_steps: { label: 'Bước tìm s', fmt: (v) => fmtNum(v, 0) },
}
export const metricLabel = (k) => METRICS[k]?.label || k
export function fmtMetric(k, v) {
  if (v == null) return '—'
  const m = METRICS[k]
  if (m) return m.fmt(v)
  return isNum(v) ? fmtNum(v, Math.abs(v) >= 100 ? 0 : 2) : String(v)
}

/** Sáu chỉ số phân phối dùng cho biểu đồ chồng nhóm vào/ra. */
export const DIST_KEYS = ['ret_pct', 'mdd_pct', 'sharpe', 'trades', 'win_rate', 'profit_factor']
export const DIST_UNIT = { ret_pct: '%', mdd_pct: '%', win_rate: '%' }

// ---- chuẩn hoá ----
const arr = (...c) => { for (const x of c) if (Array.isArray(x)) return x; return [] }
const num = (v) => (isNum(v) ? v : (v != null && v !== '' && Number.isFinite(Number(v)) ? Number(v) : null))

export function normCounts(counts) {
  const list = Array.isArray(counts) ? counts : Object.entries(counts || {}).map(([stage, c]) => ({ stage, ...(typeof c === 'object' ? c : { passed: c }) }))
  const by = Object.fromEntries(list.map((c) => [c.stage, c]))
  // luôn đủ 8 tầng theo thứ tự; tầng chưa có số liệu để null
  return STAGES.map((st, i) => {
    const c = by[st]
    if (!c) return { stage: st, input: null, passed: null, top_reject: null }
    const passed = num(c.passed ?? c.out ?? c.count)
    const input = num(c.input ?? c.in ?? (i === 0 ? passed : null))
    return { stage: st, input, passed, top_reject: c.top_reject || null }
  })
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
export function normAlphaDetail(raw) {
  if (!raw) return null
  const a = normAlpha(raw)
  const metricsBy = raw.stage_metrics || raw.metrics_by_stage || (a.metrics && STAGES.some((s) => a.metrics[s]) ? a.metrics : {})
  const reachedI = stageIdx(a.stage_reached)
  const rejI = stageIdx(a.rejected_stage)
  let stages = arr(raw.stages, raw.journey)
  if (!stages.length) {
    stages = STAGES.slice(1).map((st, k) => {
      const i = k + 1
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
