// Máy chủ giả cho trang Phễu: chỉ dùng khi không kết nối được API (hoặc `?mock=1` ở `npm run dev`); trang luôn hiện biểu ngữ "dữ liệu mẫu" (xem api.js). Nạp lười.
// Dữ liệu nằm ở src/v2/mock/funnel.*.mock.json (sinh xác định, nhất quán với nhau: đếm theo tầng khớp bảng alpha).
const mods = import.meta.glob('../mock/funnel.*.mock.json')
const cache = {}
async function load(name) {
  if (!cache[name]) cache[name] = (await mods[`../mock/funnel.${name}.mock.json`]()).default
  return cache[name]
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const mockStarts = {}

const STAGES = ['S0_generate', 'S1_backtest', 'S2_antiluck', 'S3_wfa', 'S4_montecarlo', 'S5_sizing', 'S6_holdout', 'FINAL']
const idx = (s) => STAGES.indexOf(s)
const inStage = (a, st) => { // alpha đã vào tầng st (đã qua tầng trước)
  const i = idx(st)
  if (i <= 0) return true
  const r = idx(a.stage_reached)
  return r > i - 1 || (r === i - 1 && !a.rejected_stage)
}
const passedStage = (a, st) => { const i = idx(st); const r = idx(a.stage_reached); return r > i || (r === i && !a.rejected_stage) }

export async function funnelMock(p, url, method, body) {
  await sleep(120)
  if (p === '/api/studio/funnel/estimate') {
    const ids = (url.searchParams.get('strategies') || '').split(',').filter(Boolean)
    const n = Number(url.searchParams.get('n_per_strategy') || 100)
    const per = Object.fromEntries(ids.map((i) => [i, n]))
    return { per_strategy: per, total_alphas: n * ids.length, sec_per_backtest: 32, workers: 6, s1_eta_s: Math.round((n * ids.length * 32) / 6) }
  }
  const m = p.match(/^\/api\/studio\/funnel\/runs(?:\/([^/]+))?(?:\/(.*))?$/)
  if (!m) throw new Error('mock: đường dẫn phễu không hợp lệ')
  const [, runId, rest] = m

  if (!runId) {
    if (method === 'POST') {
      const id = 'fr-mock-new'
      mockStarts[id] = Date.now()
      mockStarts['mock-funnel-new'] = Date.now()
      return { run_id: id, job_id: 'mock-funnel-new', total_alphas: (body?.n_per_strategy || 200) * (body?.strategies?.length || 1) }
    }
    return load('runs')
  }
  const runs = await load('run')
  if (!rest) {
    if (runId === 'fr-mock-new') {
      const age = (Date.now() - (mockStarts[runId] || 0)) / 1000
      const base = { ...runs.running, run_id: runId, job_id: 'mock-funnel-new' }
      return age < 6 ? { ...base, progress: { done: Math.round(age * 6500), total: 40000, stage: 'S1_backtest', rate: 6500, eta_s: Math.max(0, 6 - age) * 1 } } : { ...runs.done, run_id: runId, job_id: 'mock-funnel-new' }
    }
    const r = Object.values(runs).find((x) => x.run_id === runId)
    if (!r) { const e = new Error('Không tìm thấy lượt chạy'); e.status = 404; throw e }
    return r
  }
  const sm = rest.match(/^stages\/([^/]+)\/stats$/)
  if (sm) {
    const stats = await load('stats')
    if (!stats[sm[1]]) { const e = new Error('Tầng không hợp lệ'); e.status = 404; throw e }
    return stats[sm[1]]
  }
  const { items } = await load('alphas')
  if (rest === 'alphas') {
    const q = url.searchParams
    const stage = q.get('stage')
    const status = q.get('status')
    const strat = q.get('strategy')
    const sort = q.get('sort')
    const off = Number(q.get('offset') || 0)
    const lim = Number(q.get('limit') || 50)
    let rows = items.filter((a) => (!stage || inStage(a, stage)) && (!strat || a.strategy === strat))
    if (stage && status === 'passed') rows = rows.filter((a) => passedStage(a, stage))
    if (stage && status === 'rejected') rows = rows.filter((a) => a.rejected_stage === stage)
    const st = stage && stage !== 'S0_generate' ? stage : 'S1_backtest'
    const metOf = (a) => a.metrics[st] || a.metrics.S1_backtest || {}
    if (sort) {
      const desc = sort.startsWith('-')
      const k = sort.replace(/^[-+]/, '')
      rows = [...rows].sort((a, b) => ((metOf(a)[k] ?? -1e18) - (metOf(b)[k] ?? -1e18)) * (desc ? -1 : 1))
    }
    return { total: rows.length, offset: off, limit: lim, items: rows.slice(off, off + lim).map((a) => ({ ...a, metrics: metOf(a) })) }
  }
  const am = rest.match(/^alphas\/([^/]+)(?:\/(trades|promote))?$/)
  if (am) {
    const a = items.find((x) => x.alpha_id === am[1])
    if (!a) { const e = new Error('Không tìm thấy alpha'); e.status = 404; throw e }
    if (am[2] === 'promote') {
      if (method !== 'POST') throw new Error('mock: cần POST')
      return { promoted: true, alpha_id: a.alpha_id, final_scale: a.final_scale, registry: 'data/alphas/registry.json', testnet_config: 'data/alphas/testnet.json' }
    }
    if (am[2] === 'trades') {
      const q = url.searchParams
      const stage = q.get('stage') || 'S1_backtest'
      const fold = q.get('fold')
      const recompute = q.get('recompute') === 'true'
      const off = Number(q.get('offset') || 0)
      const lim = Number(q.get('limit') || 50)
      const tr = await load('trades')
      const notStored = stage === 'S1_backtest' && a.rejected_stage === 'S1_backtest'
      if (notStored && !recompute) return { alpha_id: a.alpha_id, stage, stored: false, recompute_available: true, total: 0, items: [] }
      let rows = (tr[stage] || tr.S1_backtest).map((t) => ({ ...t, alpha_id: a.alpha_id, stage }))
      const folds = [...new Set(rows.map((t) => t.fold).filter((f) => f != null))]
      if (fold) rows = rows.filter((t) => String(t.fold) === String(fold))
      return { alpha_id: a.alpha_id, stage, stored: !notStored, recomputed: notStored && recompute, folds: folds.length ? folds : null, total: rows.length, offset: off, limit: lim, items: rows.slice(off, off + lim) }
    }
    const [nav, mcPack] = await Promise.all([load('nav'), load('mc')])
    const reached = idx(a.stage_reached)
    const k = (a.metrics.S1_backtest?.ret_pct || 10) / 40
    const navOut = {}
    Object.entries(nav).forEach(([st, v]) => {
      if (idx(st) > reached) return
      if (st === 'S5_sizing' && reached < idx('S5_sizing')) return
      const first = v.values[0]
      navOut[st] = { dates: v.dates, values: v.values.map((x) => +(first + (x - first) * (0.4 + k)).toFixed(2)) }
    })
    const hasMc = reached >= idx('S4_montecarlo')
    return { ...a, nav: navOut, stage_metrics: a.metrics, mc: hasMc ? mcPack.mc : null, scale_search: reached >= idx('S5_sizing') ? mcPack.scale_search : null, verified: mcPack.verified,
      metrics: undefined }
  }
  throw new Error(`mock: chưa có ${method} ${p}`)
}
