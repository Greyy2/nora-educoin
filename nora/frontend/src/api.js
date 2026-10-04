// Lớp gọi API v2 theo docs/ui_contract.md.
// Khi mất kết nối (lỗi mạng / 502-504) và đang chạy `npm run dev` với `?mock=1` trên URL, trả dữ liệu mẫu trong ./mock
// (ưu tiên *.sample.json do backend sinh, nếu chưa có thì dùng *.mock.json viết tay). Ngoại lệ duy nhất ở bản production:
// API phễu không kết nối được -> dữ liệu mẫu phễu, và trang Phễu BẮT BUỘC hiện biểu ngữ "dữ liệu mẫu" (mockNoticeStore).
import { parseJobParams, jobLabel } from './lib/jobs'
import { normRun, normRuns, normStats, normAlphaPage, normAlphaDetail, normTrades } from './lib/funnel'

const mockModules = import.meta.glob('./mock/*.json') // nạp lười: không vào bundle chính

export class ApiError extends Error {
  // fields: lỗi theo trường của 422 kiểu FastAPI ([{ field, msg }]); [] nếu không có
  constructor(message, status, fields = []) { super(message); this.status = status; this.fields = fields }
}

// ---- dữ liệu mẫu: chỉ khi không kết nối được API; luôn có biểu ngữ "dữ liệu mẫu" (xem useMockNotice) ----
let mockNotice = null // { since, reason } khi trang đang dùng dữ liệu mẫu
const mockListeners = new Set()
function setMockNotice(reason) {
  if (mockNotice) return
  mockNotice = { since: Date.now(), reason }
  mockListeners.forEach((f) => f())
}
export const mockNoticeStore = {
  subscribe: (f) => { mockListeners.add(f); return () => mockListeners.delete(f) },
  get: () => mockNotice,
  clear: () => { mockNotice = null; mockListeners.forEach((f) => f()) },
}

export function mockEnabled() {
  if (!import.meta.env.DEV) return false
  try {
    const q = new URLSearchParams(window.location.search).get('mock')
    if (q === '1') sessionStorage.setItem('nora-mock', '1')
    else if (q === '0') sessionStorage.removeItem('nora-mock')
    return sessionStorage.getItem('nora-mock') === '1'
  } catch (e) { return false }
}

async function mockFile(name) {
  const s = mockModules[`./mock/${name}.sample.json`]
  const m = mockModules[`./mock/${name}.mock.json`]
  const mod = await (s || m)()
  return mod.default
}

// ---- mô phỏng job (hàng đợi -> chạy -> xong) khi dùng mock ----
const mockStarts = {}
const MOCK_RESULT = { 'mock-wfa': 'wfa', 'mock-build': 'build' }
function mockJobStatus(id) {
  const t0 = mockStarts[id]
  const age = t0 ? (Date.now() - t0) / 1000 : 99
  const status = age < 1.5 ? 'queued' : age < 4 ? 'running' : 'done'
  const kind = id.startsWith('mock-wfa') ? 'book_wfa' : id.startsWith('mock-build') ? 'book_build' : id.startsWith('mock-funnel') ? 'funnel_run' : 'book_backtest'
  if (id === 'mock-funnel-run') { // lượt phễu đang chạy dở (dữ liệu mẫu cố định)
    const t = Date.now() / 1000
    return { job_id: id, kind, status: 'running', created: t - 1800, started: t - 1750, finished: null, exit_code: null, waiting_in_queue: false,
      progress: { done: 41200, total: 100000, stage: 'S1_backtest', rate: 23.5, eta_s: 2494, peak_rss_mb: 2310, status: 'running' },
      log_tail: ['[mock] S1_backtest 41.200/100.000 alpha'] }
  }
  return { job_id: id, kind, status, created: (t0 || Date.now() - 20000) / 1000, started: status === 'queued' ? null : (t0 || Date.now() - 20000) / 1000 + 1.5,
    finished: status === 'done' ? (t0 || Date.now()) / 1000 + 4 : null, exit_code: status === 'done' ? 0 : null,
    log_tail: ['[mock] dữ liệu mẫu — không có job thật', `[mock] trạng thái ${status}`], waiting_in_queue: status === 'queued' }
}

async function mockRequest(path, method, body) {
  const url = new URL(path, 'http://x')
  const p = url.pathname.replace(/\/$/, '')
  if (p.startsWith('/api/studio/funnel/')) { setMockNotice(mockEnabled() ? 'mock' : 'unreachable'); return (await import('./lib/funnelMock')).funnelMock(p, url, method, body) }
  if (p === '/api/studio/book' && method === 'GET') return mockFile('catalog')
  if (p === '/api/studio/alphas') return mockFile('alphas')
  if (p === '/api/studio/book/jobs' && method === 'GET') {
    const j = await mockFile('jobs')
    const kind = url.searchParams.get('kind')
    return { jobs: j.jobs.filter((x) => !kind || x.kind === kind) }
  }
  const cm = p.match(/^\/api\/studio\/book\/jobs\/(.+)\/cancel$/)
  if (cm && method === 'POST') { mockStarts[cm[1]] = Date.now() - 99000; return { ...mockJobStatus(cm[1]), status: 'cancelled' } }
  const jm = p.match(/^\/api\/studio\/book\/jobs\/(.+)$/)
  if (jm) {
    const st = mockJobStatus(jm[1])
    if (st.status === 'done') {
      const key = jm[1].startsWith('mock-wfa') ? 'wfa' : jm[1].startsWith('mock-build') ? 'build' : null
      if (key) { const r = await mockFile(key); st.result = r.result || r } else st.result = { ok: true }
    } else st.result = null
    return st
  }
  if (p === '/api/studio/book/backtest' && method === 'POST') { mockStarts['mock-bt-run'] = Date.now(); return { job_id: 'mock-bt-run' } }
  if (p === '/api/studio/book/wfa' && method === 'POST') { mockStarts['mock-wfa-run'] = Date.now(); return { job_id: 'mock-wfa-run' } }
  if (p === '/api/studio/book/build' && method === 'POST') { mockStarts['mock-build-run'] = Date.now(); return { job_id: 'mock-build-run' } }
  if (p === '/api/studio/book/publish' && method === 'POST') return { published: true, job_id: (body || {}).job_id, status: 'HOLDOUT_FAILED', holdout_pass: false, strategies: [], written: [], testnet_removed: false }
  if (p === '/api/studio/book/mc' && method === 'POST') return mockFile('mc')
  if (p === '/api/studio/portfolio/dashboard') {
    const d = await mockFile('dashboard')
    const base = { ...d, period: url.searchParams.get('period') || d.period }
    return { ...base, positions: base.positions || [] }
  }
  throw new ApiError(`mock: chưa có ${method} ${path}`, 404)
}

const FUNNEL_PREFIX = '/api/studio/funnel/'

async function request(path, { method = 'GET', body } = {}) {
  let res
  try {
    res = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
  } catch (e) {
    if (mockEnabled() || path.startsWith(FUNNEL_PREFIX)) return mockRequest(path, method, body) // phễu: không kết nối được -> dữ liệu mẫu CÓ biểu ngữ
    throw new ApiError('Không kết nối được máy chủ API.', 0)
  }
  if (res.status >= 500 && mockEnabled()) return mockRequest(path, method, body)
  // proxy báo cổng API không có (502/503/504): với phễu coi như không kết nối được
  if ([502, 503, 504].includes(res.status) && path.startsWith(FUNNEL_PREFIX)) return mockRequest(path, method, body)
  // backend chưa có API phễu (route chưa đăng ký): dùng dữ liệu mẫu; khi API thật có mặt sẽ tự dùng API thật
  if ((res.status === 404 || res.status === 405) && mockEnabled() && path.startsWith('/api/studio/funnel/') && await res.clone().text().then((t) => /"detail"\s*:\s*"(Not Found|API endpoint not found|Method Not Allowed)"/.test(t), () => false)) return mockRequest(path, method, body)
  if (!res.ok) {
    let msg = `Lỗi ${res.status}`
    let fields = []
    try {
      const j = await res.json()
      if (typeof j.detail === 'string') msg = j.detail
      else if (Array.isArray(j.detail)) {
        // 422: mỗi phần tử {loc, msg, field?}; field = đường dẫn dễ đọc do backend thêm vào
        fields = j.detail.map((d) => ({ field: d.field || (Array.isArray(d.loc) ? d.loc.filter((x) => x !== 'body').join('.') : ''), msg: d.msg || d.message || String(d) }))
        msg = fields.map((f) => f.msg).join('; ') || msg
      } else if (j.detail) msg = JSON.stringify(j.detail)
    } catch (e) { /* giữ thông báo mặc định */ }
    throw new ApiError(msg, res.status, fields)
  }
  return res.json()
}

const mid = (arr) => arr[Math.floor(arr.length / 2)]

// ---- danh mục chiến lược / sổ ----
export async function getCatalog() {
  const raw = await request('/api/studio/book/')
  const catalog = (raw.catalog || raw.candidates || []).map((c) => ({
    ...c,
    default_params: c.default_params || Object.fromEntries(Object.entries(c.space || {}).map(([k, a]) => [k, mid(a)])),
  }))
  const book = raw.book || null
  return {
    book,
    latestWfa: raw.latest_wfa || raw.wfa || null,
    catalog,
    universe: raw.universe || book?.universe || [],
    windows: raw.windows || book?.windows || null,
  }
}
export const getAlphas = () => request('/api/studio/alphas')

// ---- job ----
export async function listJobs(kind, limit = 20) {
  const r = await request(`/api/studio/book/jobs?kind=${encodeURIComponent(kind)}&limit=${limit}`)
  // bản backend chưa lọc theo kind thì lọc phía client
  return (r.jobs || []).filter((j) => !j.kind || j.kind === kind).map((j) => ({ ...normJob(j), label: j.label || jobLabel(j), parsed: parseJobParams(j.params) }))
}
// mọi loại job (khay công việc, trang Lịch sử chạy)
export async function listAllJobs(limit = 20) {
  const r = await request(`/api/studio/book/jobs?limit=${limit}`)
  return (r.jobs || []).map((j) => ({ ...normJob(j), label: j.label || jobLabel(j), parsed: parseJobParams(j.params) }))
}
// backend hiện trả khoá `id`; hợp đồng ghi `job_id` — chấp nhận cả hai
const normJob = (j) => ({ ...j, job_id: j.job_id || j.id })
export const getJob = (id) => request(`/api/studio/book/jobs/${encodeURIComponent(id)}`).then(normJob)
export const postCancel = (id) => request(`/api/studio/book/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }).then(normJob)
export const postBacktest = (body) => request('/api/studio/book/backtest', { method: 'POST', body })
export const postWfa = (body) => request('/api/studio/book/wfa', { method: 'POST', body })
export const postBuild = (body) => request('/api/studio/book/build', { method: 'POST', body })
export const postPublish = (jobId) => request('/api/studio/book/publish', { method: 'POST', body: { job_id: jobId } })
export const postMc = (body) => request('/api/studio/book/mc', { method: 'POST', body })

// ---- chiến lược: lược đồ tham số + preset (docs/ui_contract.md §7.1) ----
let strategiesP = null
/** Các chiến lược lõi: params_schema, preset {params, source, source_kind, evidence}, frames_allowed. Có đệm theo phiên trang; `force` tải lại. */
export function getStrategies(force = false) {
  if (!strategiesP || force) strategiesP = request('/api/studio/strategies').catch((e) => { strategiesP = null; throw e })
  return strategiesP
}
let strategyCatalogP = null
/** Danh mục 3 chiến lược cho lựa chọn mới: [{ id, name, kind, description, legs: { LONG, SHORT }, coming? }]. Có đệm theo phiên trang. */
export function getStrategyCatalog(force = false) {
  if (!strategyCatalogP || force) strategyCatalogP = request('/api/studio/strategies/catalog').catch((e) => { strategyCatalogP = null; throw e })
  return strategyCatalogP
}
/** Kiểm tham số một chiến lược (không chạy job): { ok, errors: [{field, message}], resolved }. field có dạng "params.sig.ema_fast". */
export const postValidateStrategy = (id, params) => request('/api/studio/strategies/validate', { method: 'POST', body: { id, params } })

export function getDashboard({ jobId, period }) {
  const q = new URLSearchParams()
  if (jobId) q.set('job_id', jobId)
  if (period) q.set('period', period)
  return request(`/api/studio/portfolio/dashboard?${q}`)
}

const _qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString()
/** Danh sách lệnh đã đóng của một job backtest: {items, total, strategies, families, symbols}. */
export const getPortfolioTrades = (o) => request(`/api/studio/portfolio/trades?${_qs(o)}`)
export const portfolioTradesCsvUrl = (o) => `/api/studio/portfolio/trades?${_qs({ ...o, format: 'csv' })}`
/** Regime hiện tại + lịch sử từng tài sản (nến 15m đã đóng) + chiến lược đang bật theo bảng regime của sổ. */
export const getMarketRegime = (o = {}) => request(`/api/studio/market/regime?${_qs(o)}`)

// ---- phễu kiểm duyệt (docs/funnel_contract.md §4) ----
const qs = (o) => {
  const q = new URLSearchParams()
  Object.entries(o || {}).forEach(([k, v]) => { if (v != null && v !== '') q.set(k, String(v)) })
  const s = q.toString()
  return s ? `?${s}` : ''
}
const FR = '/api/studio/funnel/runs'
const enc = encodeURIComponent
export const listFunnelRuns = () => request(FR).then(normRuns)
export const getFunnelRun = (id) => request(`${FR}/${enc(id)}`).then(normRun)
export const postFunnelRun = (body) => request(FR, { method: 'POST', body })
export const getFunnelStats = (id, stage) => request(`${FR}/${enc(id)}/stages/${enc(stage)}/stats`).then(normStats)
export const getFunnelAlphas = (id, o) => request(`${FR}/${enc(id)}/alphas${qs(o)}`).then(normAlphaPage)
export const getFunnelAlpha = (id, alphaId) => request(`${FR}/${enc(id)}/alphas/${enc(alphaId)}`).then(normAlphaDetail)
export const getFunnelTrades = (id, alphaId, o) => request(`${FR}/${enc(id)}/alphas/${enc(alphaId)}/trades${qs(o)}`).then(normTrades)
export const postFunnelPromote = (id, alphaId, note) => request(`${FR}/${enc(id)}/alphas/${enc(alphaId)}/promote`, { method: 'POST', body: { confirm: true, ...(note ? { note } : {}) } })
/** Ước tính thời gian S1 trước khi chạy: { per_strategy, total_alphas, sec_per_backtest, workers, s1_eta_s }. */
export const getFunnelEstimate = ({ strategies, nPerStrategy, fullGrid, workers, timeframe, regime }) =>
  request(`/api/studio/funnel/estimate${qs({ strategies: strategies.join(','), n_per_strategy: fullGrid ? '' : nPerStrategy, full_grid: fullGrid ? 'true' : '', workers, timeframe, regime })}`)

// ---- biểu đồ giải thích tín hiệu + bot live ----
/** Nến + đường chỉ báo + tín hiệu vào/thoát kèm giá trị từng điều kiện (POST /api/studio/chart/explain). */
export const explainChart = (body) => request('/api/studio/chart/explain', { method: 'POST', body })
/** Lệnh + vị thế của bot live theo chế độ (paper/demo/live): sàn + paper, sổ đang chạy, danh sách chiến lược/cặp. */
export const getLiveTrades = (mode = 'paper', venue = 'okx', limit = 200) => request(`/api/studio/live/trades${qs({ mode, venue, limit })}`)
