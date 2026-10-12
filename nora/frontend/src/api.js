// Lớp gọi API v2 theo docs/ui_contract.md.
// Nhóm theo 5 router backend: alpha, optimize, data, live, process (1 hàm / route).
// Không có dữ liệu giả lập: mất kết nối / lỗi máy chủ -> ApiError (production thử lại 1 lần với GET).

import { parseJobParams, jobLabel } from './lib/jobs'
import { normRun, normRuns, normStats, normAlphaPage, normAlphaDetail, normTrades } from './lib/funnel'
import { invalidateResource } from './lib/bus'
import { registerParamSchema } from './lib/params'

export class ApiError extends Error {
  // fields: lỗi theo trường của 422 kiểu FastAPI ([{ field, msg }]); [] nếu không có
  constructor(message, status, fields = [], detail = null, code = null) {
    super(message)
    this.status = status
    this.fields = fields
    this.detail = detail
    this.code = code
  }
}

const TIMEOUT_MS = 95000 // ngay dưới giới hạn 100 giây của Cloudflare (524)
const RETRY_MS = 1500    // API khởi động lại sau proxy: 502/503/504 thoáng qua
const inflight = new Map() // GET đang bay theo đường dẫn: nhiều nơi mount cùng lúc dùng chung 1 request

async function fetchOnce(path, method, body) {
  const ctl = new AbortController()
  let timedOut = false
  const t = setTimeout(() => { timedOut = true; ctl.abort() }, TIMEOUT_MS)
  try {
    return await fetch(path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctl.signal,
    })
  } catch (e) {
    if (timedOut) throw new ApiError(`Máy chủ không phản hồi sau ${TIMEOUT_MS / 1000} giây (quá thời gian chờ). Thử lại sau ít phút.`, 408)
    throw e
  } finally {
    clearTimeout(t)
  }
}

async function request(path, { method = 'GET', body } = {}) {
  if (method !== 'GET') return requestImpl(path, method, body)
  let p = inflight.get(path)
  if (!p) {
    p = requestImpl(path, method, body).finally(() => inflight.delete(path))
    inflight.set(path, p)
  }
  return p
}

async function requestImpl(path, method, body) {
  let res
  // production + GET: một lần thử lại sau ~1.5 giây khi 502/503/504 hoặc đứt kết nối (không thử lại POST: có thể đã chạy)
  const retry = import.meta.env.PROD && method === 'GET'
  try {
    res = await fetchOnce(path, method, body)
    if (retry && [502, 503, 504].includes(res.status)) {
      await new Promise((r) => setTimeout(r, RETRY_MS))
      res = await fetchOnce(path, method, body)
    }
  } catch (e) {
    if (e instanceof ApiError) throw e
    if (retry) {
      try {
        await new Promise((r) => setTimeout(r, RETRY_MS))
        res = await fetchOnce(path, method, body)
      } catch (e2) {
        e = e2
      }
    }
    if (!res) {
      if (e instanceof ApiError) throw e
      throw new ApiError('Không kết nối được máy chủ API.', 0)
    }
  }
  if (res.status === 204) return null
  if (!res.ok) {
    let msg = [502, 503, 504].includes(res.status)
      ? `Máy chủ API tạm thời không phản hồi (${res.status}). Thử lại sau giây lát.`
      : `Lỗi ${res.status}`
    let fields = []
    let detail = null
    let code = null
    try {
      const j = await res.json()
      if (j.detail && typeof j.detail === 'object' && !Array.isArray(j.detail)) {
        detail = j.detail
        code = j.detail.code || null
      }
      if (code === 'EPHEMERAL_GONE') {
        msg = 'Kết quả tạm đã mất (API khởi động lại) — vui lòng chạy lại.'
      } else if (code === 'SHA_CONFLICT') {
        msg = 'Xung đột phiên bản mã chiến lược — vui lòng kiểm tra lại.'
      } else if (code === 'LIVE_BOT_RUNNING') {
        msg = 'Bot giao dịch trực tiếp đang chạy — không thể thực hiện thao tác.'
      } else if (typeof j.detail === 'string') {
        msg = j.detail
      } else if (Array.isArray(j.detail)) {
        // 422: mỗi phần tử {loc, msg, field?}; field = đường dẫn dễ đọc do backend thêm vào
        fields = j.detail.map((d) => ({
          field: d.field || (Array.isArray(d.loc) ? d.loc.filter((x) => x !== 'body').join('.') : ''),
          msg: d.msg || d.message || String(d),
        }))
        msg = fields.map((f) => f.msg).join('; ') || msg
      } else if (j.detail) {
        msg = (typeof j.detail === 'object' && j.detail.message) || JSON.stringify(j.detail)
      }
    } catch {
      /* giữ thông báo mặc định */
    }
    throw new ApiError(msg, res.status, fields, detail, code)
  }
  return res.json()
}

const qs = (o) => {
  const q = new URLSearchParams()
  Object.entries(o || {}).forEach(([k, v]) => {
    if (v != null && v !== '') q.set(k, String(v))
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}
const _qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== '')).toString()
const enc = encodeURIComponent
const mid = (arr) => arr[Math.floor(arr.length / 2)]

// ═════════════════════════════════════════════════════════════════════════════
// 1. ALPHA ROUTER (backend/routes/alpha.py)
//    Thư viện alpha, DSL chiến lược, trợ lý code AST, alpha người dùng, mẫu education
// ═════════════════════════════════════════════════════════════════════════════

/** Thư viện chiến lược: { sources: [{ key, label, strategies: [{ key, name, side, idea, plain, math, summary, stats }] }] }. */
export const getAlphaCatalog = () => request('/api/studio/alphas/catalog')

/** Top agent trade (10 bot copy-trade OKX implied fit + OOS). */
export const getTopAgents = () => request('/api/studio/alphas/top_agents')

let strategiesP = null
/** Các chiến lược lõi: params_schema, preset {params, source, source_kind, evidence}, frames_allowed. Có đệm theo phiên trang; `force` tải lại. */
export function getStrategies(force = false) {
  if (!strategiesP || force) {
    strategiesP = request('/api/studio/strategies').then((res) => {
      registerParamSchema(res)
      return res
    }).catch((e) => {
      strategiesP = null
      throw e
    })
  }
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

/** Kiểm code (không chạy, không lưu): { ok, program_hash, meta: { timeframe, features, legs, position_levels, warmup_bars }, warnings, error?: { line, col, message } }. */
export const postCompileStrategy = (code) => request('/api/studio/strategies/compile', { method: 'POST', body: { code } })

/** Giải thích từng dòng code thành chú thích: as_comments -> {annotated_code} (dòng `# ▸` trên từng dòng, idempotent); strip -> {stripped_code} (gỡ các dòng `# ▸`). */
export const postAnnotate = (code, opts = {}) => request('/api/studio/strategies/annotate', { method: 'POST', body: { code, ...opts } })

/** Trợ lý code: danh mục gợi ý toán tử/chỉ báo. */
export const getAssistCatalog = () => request('/api/studio/strategies/assist/catalog')

/** Trợ lý code: kiểm tra cú pháp AST nhanh (không chạy compiler). */
export const postAssistCheck = (code) => request('/api/studio/strategies/assist/check', { method: 'POST', body: { code } })

/** Trợ lý code: gợi ý hoàn thiện tại vị trí con trỏ (line, col). */
export const postAssistComplete = (code, line, col) => request('/api/studio/strategies/assist/complete', { method: 'POST', body: { code, line, col } })

/** Trợ lý code: thông tin tooltip khi hover tại vị trí (line, col). */
export const postAssistHover = (code, line, col) => request('/api/studio/strategies/assist/hover', { method: 'POST', body: { code, line, col } })

/** Lấy mã nguồn chiến lược hệ thống để chỉnh sửa. */
export const getStrategySource = (id) => request(`/api/studio/strategies/source/${enc(id)}`)

/** Cập nhật mã nguồn chiến lược hệ thống. */
export const putStrategySource = (id, code, sha256) => request(`/api/studio/strategies/source/${enc(id)}`, { method: 'PUT', body: { code, sha256 } })

/** Tra cứu tài liệu DSL chiến lược: các cột data pv_*, chỉ báo feat.*, toán tử op.*. */
export const getDslReference = () => request('/api/studio/strategies/dsl')

/** Giải thích cấu trúc chiến lược từ cây biểu thức đã biên dịch. */
export const postStrategyExplain = (body) => request('/api/studio/strategies/explain', { method: 'POST', body })

/** Dựng lại presets.json từ sổ đã chốt (job nền presets_build). */
export const postBuildPresets = () => request('/api/studio/strategies/presets', { method: 'POST' })

/** Danh sách alpha người dùng đã lưu trong kho. */
export const getUserAlphas = (params = {}) => {
  const q = new URLSearchParams()
  if (params.sort) q.set('sort', params.sort)
  if (params.status) q.set('status', params.status)
  const qsStr = q.toString()
  return request(`/api/studio/alphas/user${qsStr ? `?${qsStr}` : ''}`)
}

/** Chi tiết alpha người dùng gồm kết quả đã lưu. */
export const getUserAlphaDetail = (alphaId) => request(`/api/studio/alphas/user/${enc(alphaId)}`)

/** Mã của alpha đã lưu để nạp vào trình soạn: { id, code, version, program_hash, sha256, name, note }. */
export const getUserAlphaCode = (alphaId) => request(`/api/studio/alphas/user/${enc(alphaId)}/code`)

/** Lịch sử phiên bản của alpha người dùng. */
export const getUserAlphaVersions = (alphaId) => request(`/api/studio/alphas/user/${enc(alphaId)}/versions`)

/** Mã nguồn của một phiên bản cụ thể của alpha người dùng. */
export const getUserAlphaVersionCode = (alphaId, version) => request(`/api/studio/alphas/user/${enc(alphaId)}/versions/${enc(version)}`)

/** Kiểm lại alpha trong kho bằng engine hiện hành (job nền alpha_revalidate). */
export const postRevalidateAlpha = (alphaId, apply = false) =>
  request(`/api/studio/alphas/${enc(alphaId)}/revalidate?apply=${apply ? 'true' : 'false'}`, { method: 'POST' })

/** Lưu alpha người dùng: server đọc kết quả từ job_id, kiểm tra program_hash. */
export const postSaveUserAlpha = ({ job_id, code, name, note = '', source = 'alpha-create', alpha_id }) =>
  request('/api/studio/alphas/user', { method: 'POST', body: { job_id, code, name, note, source, ...(alpha_id ? { alpha_id } : {}) } })
    .then((r) => { invalidateResource('alphas'); invalidateResource('meta'); return r })

/** Lưu trữ (archive) alpha người dùng. */
export const postArchiveUserAlpha = (alphaId) =>
  request(`/api/studio/alphas/user/${enc(alphaId)}/archive`, { method: 'POST' })
    .then((r) => { invalidateResource('alphas'); return r })

/** Cập nhật trạng thái alpha người dùng (active/candidate/archived). */
export const postUpdateUserAlphaStatus = (alphaId, status) =>
  request(`/api/studio/alphas/user/${enc(alphaId)}/status`, { method: 'POST', body: { status } })
    .then((r) => { invalidateResource('alphas'); return r })

/** Mặc định form chạy từ kho dữ liệu OKX: { symbols, start, end, train_ratio, initial_capital }. */
export const getRunDefaults = () => request('/api/studio/custom/defaults')

/** Khởi chạy backtest chiến lược Python: job loại custom_backtest. */
export const postCustomBacktest = (body) => request('/api/studio/custom/backtest', { method: 'POST', body })

/** Danh sách 50 mẫu chiến lược giáo dục chuẩn từ backend. */
export const getEducationSamples = () => request('/api/studio/education/samples')

/** Lấy kết quả backtest chuẩn của 1 mẫu giáo dục cụ thể. */
export const getEducationSampleResult = (key) => request(`/api/studio/education/samples/${encodeURIComponent(key)}/result`)

// ═════════════════════════════════════════════════════════════════════════════
// 2. OPTIMIZE ROUTER (backend/routes/optimize.py)
//    Sổ chiến lược, backtest danh mục, WFA, Monte Carlo, phễu kiểm duyệt, biểu đồ lệnh
// ═════════════════════════════════════════════════════════════════════════════

/** Sổ chiến lược hiện tại + các ứng viên cấu hình. */
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
    assets: raw.assets || [], // [{symbol, venue cex|dex, market, candles, ticks|null, network, fee_rate}] — DEX cho backtest
  }
}

/** Danh sách alpha hiện tại của sổ. */
export const getAlphas = () => request('/api/studio/alphas')

/** Khởi chạy job backtest sổ chiến lược (book_backtest). */
export const postBacktest = (body) => request('/api/studio/book/backtest', { method: 'POST', body })

/** Khởi chạy job Walk-Forward Analysis sổ chiến lược (book_wfa). */
export const postWfa = (body) => request('/api/studio/book/wfa', { method: 'POST', body })

/** Khởi chạy job dựng sổ alpha (book_build). */
export const postBuild = (body) => request('/api/studio/book/build', { method: 'POST', body })

/** Xuất bản sổ alpha từ kết quả job dựng sổ (book_build). */
export const postPublish = (jobId) =>
  request('/api/studio/book/publish', { method: 'POST', body: { job_id: jobId } })
    .then((r) => { invalidateResource('catalog'); invalidateResource('meta'); return r })

/** Khởi chạy phân tích Monte Carlo (book_mc). */
export const postMc = (body) => request('/api/studio/book/mc', { method: 'POST', body })

/** Bảng điều khiển danh mục đầu tư (dashboard). */
export function getDashboard({ jobId, period }) {
  const q = new URLSearchParams()
  if (jobId) q.set('job_id', jobId)
  if (period) q.set('period', period)
  return request(`/api/studio/portfolio/dashboard?${q}`)
}

/** Danh sách lệnh đã đóng của một job backtest: {items, total, strategies, families, symbols}. */
export const getPortfolioTrades = (o) => request(`/api/studio/portfolio/trades?${_qs(o)}`)

/** URL tải CSV danh sách lệnh danh mục. */
export const portfolioTradesCsvUrl = (o) => `/api/studio/portfolio/trades?${_qs({ ...o, format: 'csv' })}`

/** Nến + đường chỉ báo + tín hiệu vào/thoát kèm giá trị từng điều kiện (POST /api/studio/chart/explain). */
export const explainChart = (body) => request('/api/studio/chart/explain', { method: 'POST', body })

// ── Phễu kiểm duyệt (Funnel) ──
const FR = '/api/studio/funnel/runs'

/** Danh sách các đợt chạy phễu kiểm duyệt. */
export const listFunnelRuns = () => request(FR).then(normRuns)

/** Chi tiết một đợt chạy phễu. */
export const getFunnelRun = (id) => request(`${FR}/${enc(id)}`).then(normRun)

/** Khởi chạy đợt phễu mới (funnel_run). */
export const postFunnelRun = (body) => request(FR, { method: 'POST', body })

/** Thống kê chi tiết một tầng trong phễu. */
export const getFunnelStats = (id, stage) => request(`${FR}/${enc(id)}/stages/${enc(stage)}/stats`).then(normStats)

/** Danh sách alpha qua tầng phân trang trong phễu. */
export const getFunnelAlphas = (id, o) => request(`${FR}/${enc(id)}/alphas${qs(o)}`).then(normAlphaPage)

/** Chi tiết một alpha trong phễu. */
export const getFunnelAlpha = (id, alphaId) => request(`${FR}/${enc(id)}/alphas/${enc(alphaId)}`).then(normAlphaDetail)

/** Danh sách lệnh của một alpha trong phễu. */
export const getFunnelTrades = (id, alphaId, o) => request(`${FR}/${enc(id)}/alphas/${enc(alphaId)}/trades${qs(o)}`).then(normTrades)

/** Thăng hạng alpha từ phễu vào sổ / kho alpha. */
export const postFunnelPromote = (id, alphaId, note) =>
  request(`${FR}/${enc(id)}/alphas/${enc(alphaId)}/promote`, { method: 'POST', body: { confirm: true, ...(note ? { note } : {}) } })
    .then((r) => { invalidateResource('alphas'); invalidateResource('catalog'); invalidateResource('meta'); return r })

/** Dựng sổ trực tiếp từ đợt chạy phễu (funnel_book). */
export const postFunnelBook = (runId, body = {}) =>
  request(`${FR}/${enc(runId)}/book`, { method: 'POST', body })
    .then((r) => { invalidateResource('catalog'); invalidateResource('meta'); return r })

/** Huỷ một đợt chạy phễu đang chạy. */
export const postFunnelCancel = (runId) =>
  request(`${FR}/${enc(runId)}/cancel`, { method: 'POST' })

/** Ước tính thời gian S1 trước khi chạy phễu: { per_strategy, total_alphas, sec_per_backtest, workers, s1_eta_s }. */
export const getFunnelEstimate = ({ strategies, nPerStrategy, fullGrid, workers, timeframe, regime }) =>
  request(`/api/studio/funnel/estimate${qs({ strategies: strategies.join(','), n_per_strategy: fullGrid ? '' : nPerStrategy, full_grid: fullGrid ? 'true' : '', workers, timeframe, regime })}`)

// ═════════════════════════════════════════════════════════════════════════════
// 3. DATA ROUTER (backend/routes/data.py)
//    Thị trường, regime thị trường, API vận hành dữ liệu
// ═════════════════════════════════════════════════════════════════════════════

/** Regime hiện tại + lịch sử từng tài sản (nến 15m đã đóng) + chiến lược đang bật theo bảng regime của sổ. */
export const getMarketRegime = (o = {}) => request(`/api/studio/market/regime?${_qs(o)}`)

/** Tạo báo cáo phân tích chế độ thị trường (job nền regime_report). */
export const postRegimeReport = (body = {}) => request('/api/studio/market/regime/report', { method: 'POST', body })

/** API vận hành: Tải dữ liệu nến sàn vào kho staging (job data_crawl). */
export const postDataCrawl = (body) => request('/api/data/crawl', { method: 'POST', body })

/** API vận hành: Chuyển dữ liệu staging vào kho chính thức (job data_promote). */
export const postDataPromote = (body) => request('/api/data/promote', { method: 'POST', body })

/** API vận hành: Tải dữ liệu tick sàn (job data_crawl_ticks). */
export const postDataTicksCrawl = (body) => request('/api/data/ticks/crawl', { method: 'POST', body })

/** API vận hành: Độ phủ dữ liệu tick theo tài sản/ngày. */
export const getDataTicksCoverage = (o = {}) => request(`/api/data/ticks/coverage?${_qs(o)}`)

// ═════════════════════════════════════════════════════════════════════════════
// 4. LIVE ROUTER (backend/routes/live.py)
//    Giao dịch bot live/paper/demo, đối chiếu khớp lệnh
// ═════════════════════════════════════════════════════════════════════════════

/** Lệnh + vị thế của bot live theo chế độ (paper/demo/live): sàn + paper, sổ đang chạy, danh sách chiến lược/cặp. */
export const getLiveTrades = (mode = 'paper', venue = 'okx', limit = 200, book = 'main') =>
  request(`/api/studio/live/trades${qs({ mode, venue, limit, book })}`)

/** Lệnh sàn (khớp thật) ghép với lệnh paper bóng cùng nến: {summary, pairs, only_exec, only_paper}. */
export const getLiveCompare = (mode = 'demo', venue = 'okx', book = 'main') =>
  request(`/api/studio/live/compare${qs({ mode, venue, book })}`)

/** Đối soát cấp sự kiện cho bot exec/unified (lệch bps theo loại lệnh, độ trễ, dải SL, slippage hiệu chỉnh). */
export const getLiveCompareEvents = (mode = 'demo', venue = 'okx', book = 'main') =>
  request(`/api/studio/live/compare_events${qs({ mode, venue, book })}`)

/** Đọc trạng thái bot live hiện tại (PID, tiến trình, config). */
export const getLiveBot = () => request('/api/studio/live/bot')

/** Khởi động / điều khiển bot live (start, stop). */
export const postLiveBot = (body) => request('/api/studio/live/bot', { method: 'POST', body })

// ═════════════════════════════════════════════════════════════════════════════
// 5. PROCESS ROUTER (backend/routes/process.py)
//    Vòng đời công việc nền (jobs), metadata trung tâm cho UI
// ═════════════════════════════════════════════════════════════════════════════

const normJob = (j) => ({ ...j, job_id: j.job_id || j.id })

/** Danh sách job theo loại: {jobs: [...]}. */
export async function listJobs(kind, limit = 20) {
  const r = await request(`/api/studio/book/jobs?kind=${enc(kind)}&limit=${limit}`)
  return (r.jobs || []).filter((j) => !j.kind || j.kind === kind).map((j) => ({
    ...normJob(j),
    label: j.label || jobLabel(j),
    parsed: parseJobParams(j.params),
  }))
}

/** Danh sách mọi loại job (khay công việc, trang Lịch sử chạy). */
export async function listAllJobs(limit = 20) {
  const r = await request(`/api/studio/book/jobs?limit=${limit}`)
  return (r.jobs || []).map((j) => ({
    ...normJob(j),
    label: j.label || jobLabel(j),
    parsed: parseJobParams(j.params),
  }))
}

/** Đọc trạng thái + kết quả một job (?lite=1 bỏ trade_list lớn). */
export const getJob = (id) => request(`/api/studio/book/jobs/${enc(id)}?lite=1`).then(normJob)

/** Đọc kết quả Stage A của job dựng sổ (book_build). */
export const getJobStageA = (id) => request(`/api/studio/book/jobs/${enc(id)}/stage_a`)

/** Huỷ một job đang chạy (SIGTERM tới nhóm tiến trình). */
export const postCancel = (id) => request(`/api/studio/book/jobs/${enc(id)}/cancel`, { method: 'POST' }).then(normJob)

/** Metadata duy nhất từ backend (nguồn sự thật tập trung cho UI). */
export const getStudioMeta = () => request('/api/studio/meta')

