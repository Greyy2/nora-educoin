// Lớp gọi API v2 theo docs/ui_contract.md.
// Khi mất kết nối (lỗi mạng / 502-504) và đang chạy `npm run dev` với `?mock=1` trên URL, trả dữ liệu mẫu trong ./mock
// (ưu tiên *.sample.json do backend sinh, nếu chưa có thì dùng *.mock.json viết tay). Bản build production không bao giờ dùng mock.
import { parseJobArgs, jobLabel } from './lib/jobs'

const mockModules = import.meta.glob('./mock/*.json') // nạp lười: không vào bundle chính

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status }
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
  const kind = id.startsWith('mock-wfa') ? 'book_wfa' : id.startsWith('mock-build') ? 'book_build' : 'book_backtest'
  return { job_id: id, kind, status, created: (t0 || Date.now() - 20000) / 1000, started: status === 'queued' ? null : (t0 || Date.now() - 20000) / 1000 + 1.5,
    finished: status === 'done' ? (t0 || Date.now()) / 1000 + 4 : null, exit_code: status === 'done' ? 0 : null,
    log_tail: ['[mock] dữ liệu mẫu — không có job thật', `[mock] trạng thái ${status}`], waiting_in_queue: status === 'queued' }
}

async function mockRequest(path, method, body) {
  const url = new URL(path, 'http://x')
  const p = url.pathname.replace(/\/$/, '')
  if (p === '/api/studio/book' && method === 'GET') return mockFile('catalog')
  if (p === '/api/studio/alphas') return mockFile('alphas')
  if (p === '/api/studio/book/jobs' && method === 'GET') {
    const j = await mockFile('jobs')
    const kind = url.searchParams.get('kind')
    return { jobs: j.jobs.filter((x) => !kind || x.kind === kind) }
  }
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
  if (p === '/api/studio/book/mc' && method === 'POST') return mockFile('mc')
  if (p === '/api/studio/portfolio/dashboard') {
    const src = url.searchParams.get('source')
    if (src && src !== 'backtest') return { available: false, reason: `Chưa kết nối tài khoản ${src} (mock).` }
    const d = await mockFile('dashboard')
    return { ...d, period: url.searchParams.get('period') || d.period }
  }
  throw new ApiError(`mock: chưa có ${method} ${path}`, 404)
}

async function request(path, { method = 'GET', body } = {}) {
  let res
  try {
    res = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined })
  } catch (e) {
    if (mockEnabled()) return mockRequest(path, method, body)
    throw new ApiError('Không kết nối được máy chủ API.', 0)
  }
  if (res.status >= 500 && mockEnabled()) return mockRequest(path, method, body)
  if (!res.ok) {
    let msg = `Lỗi ${res.status}`
    try {
      const j = await res.json()
      if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch (e) { /* giữ thông báo mặc định */ }
    throw new ApiError(msg, res.status)
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
  return (r.jobs || []).filter((j) => !j.kind || j.kind === kind).map((j) => ({ ...normJob(j), label: j.label || jobLabel(j), parsed: parseJobArgs(j.args) }))
}
// backend hiện trả khoá `id`; hợp đồng ghi `job_id` — chấp nhận cả hai
const normJob = (j) => ({ ...j, job_id: j.job_id || j.id })
export const getJob = (id) => request(`/api/studio/book/jobs/${encodeURIComponent(id)}`).then(normJob)
export const postBacktest = (body) => request('/api/studio/book/backtest', { method: 'POST', body })
export const postWfa = (body) => request('/api/studio/book/wfa', { method: 'POST', body })
export const postBuild = (body) => request('/api/studio/book/build', { method: 'POST', body })
export const postMc = (body) => request('/api/studio/book/mc', { method: 'POST', body })

export function getDashboard({ source, jobId, period }) {
  const q = new URLSearchParams({ source })
  if (jobId) q.set('job_id', jobId)
  if (period) q.set('period', period)
  return request(`/api/studio/portfolio/dashboard?${q}`)
}

export async function getNode() { return request('/api/node') }
