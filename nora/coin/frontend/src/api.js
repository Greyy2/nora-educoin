// Lớp gọi API v2 theo docs/ui_contract.md.
// Nhóm theo 5 router backend: alpha, optimize, data, live, process (1 hàm / route).
// Không có dữ liệu giả lập: mất kết nối / lỗi máy chủ -> ApiError (production thử lại 1 lần với GET).

import { parseJobParams, jobLabel } from './lib/jobs'
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
  if (params.owner_id) q.set('owner_id', params.owner_id)
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

/** Xoá vĩnh viễn alpha người dùng. */
export const deleteUserAlpha = (alphaId) =>
  request(`/api/studio/alphas/user/${enc(alphaId)}`, { method: 'DELETE' })
    .then((r) => { invalidateResource('alphas'); invalidateResource('meta'); return r })

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

/** Khởi chạy job backtest sổ chiến lược (book_backtest). */
export const postBacktest = (body) => request('/api/studio/book/backtest', { method: 'POST', body })

/** Khởi chạy job Walk-Forward Analysis sổ chiến lược (book_wfa). */
export const postWfa = (body) => request('/api/studio/book/wfa', { method: 'POST', body })

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

// ═════════════════════════════════════════════════════════════════════════════
// 3. DATA ROUTER (backend/routes/data.py)
//    Thị trường, regime thị trường, API vận hành dữ liệu
// ═════════════════════════════════════════════════════════════════════════════

/** Regime hiện tại + lịch sử từng tài sản (nến 15m đã đóng) + chiến lược đang bật theo bảng regime của sổ. */
export const getMarketRegime = (o = {}) => request(`/api/studio/market/regime?${_qs(o)}`)

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
export const getLiveTrades = (mode = 'paper', venue = 'okx', limit = 200, book = 'main', engine) =>
  request(`/api/studio/live/trades${qs({ mode, venue, limit, book, engine })}`)

/** Lệnh sàn (khớp thật) ghép với lệnh paper bóng cùng nến: {summary, pairs, only_exec, only_paper}. */
export const getLiveCompare = (mode = 'demo', venue = 'okx', book = 'main', engine) =>
  request(`/api/studio/live/compare${qs({ mode, venue, book, engine })}`)

/** Đối soát cấp sự kiện cho bot exec/unified (lệch bps theo loại lệnh, độ trễ, dải SL, slippage hiệu chỉnh). */
export const getLiveCompareEvents = (mode = 'demo', venue = 'okx', book = 'main', engine) =>
  request(`/api/studio/live/compare_events${qs({ mode, venue, book, engine })}`)

/** Các bot cũ (đã dừng) còn dữ liệu trên đĩa: {bots:[{tab: paper|testnet|live, mode, book, equity, start_equity, pnl_pct, mdd_pct, trades, started, ended}]}. */
export const getLiveArchive = () => request('/api/studio/live/archive')

/** Đọc trạng thái bot live hiện tại (PID, tiến trình, config). */
export const getLiveBot = () => request('/api/studio/live/bot')

/** Khởi động bot live (Paper / Testnet / Live). */
export const postLiveBot = (body) => request('/api/studio/live/bot', { method: 'POST', body })

/** Chiến lược đã backtest có lãi để chọn chạy bot: {candidates:[{id,name,source,timeframe,symbols,ret_pct,...,wfa,mc}], n}. */
export const getLiveCandidates = () => request('/api/studio/live/candidates')

/** Chạy backtest cho cấu hình tuỳ chỉnh từ bộ chọn trước khi bật bot. */
export const postCandidateBacktest = (body) => request('/api/studio/live/candidate_backtest', { method: 'POST', body })

/** Trường tham số chỉnh được của chiến lược ở khung tín hiệu: {kind, fields:{khoá: spec}, defaults}. Cùng resolve_strategy với backtest/bot. */
export const getCandidateSchema = (alphaId, signalTf, bookSource) => request(`/api/studio/live/candidate_schema${qs({ alpha_id: alphaId, signal_tf: signalTf, book_source: bookSource })}`)

/** Danh sách các bot live/paper/testnet. */
export const listLiveBots = (mode) => request(`/api/studio/live/bots${mode ? `?mode=${enc(mode)}` : ''}`)

/** Tổng hợp bot theo nhóm paper / live. */
export const getLiveSummary = () => request('/api/studio/live/summary')

/** Snapshot Master Portfolio (10,000 USDT Master Wallet, vốn phân bổ linh hoạt cho các bot). */
export const getMasterPortfolio = (mode = 'paper') => request(`/api/studio/portfolio/master?mode=${enc(mode)}`)

/** Chi tiết 1 bot live. */
export const getLiveBotDetail = (botId) => request(`/api/studio/live/bot/${enc(botId)}`)

/** Dừng bot live. */
export const stopLiveBot = (botId, close = true) => request(`/api/studio/live/bot/${enc(botId)}/stop?close=${close}`, { method: 'POST' })

/** Xoá bot đã dừng + dữ liệu (409 nếu đang chạy). */
export const deleteLiveBot = (botId, mode) => request(`/api/studio/live/bot/${enc(botId)}${mode ? `?mode=${enc(mode)}` : ''}`, { method: 'DELETE' })

/** Lịch sử trades của bot live. */
export const getLiveBotTrades = (botId) => request(`/api/studio/live/bot/${enc(botId)}/trades`)

/** Biểu đồ bot: nến + lệnh khớp thật + tín hiệu (+ replay backtest khi replay=true). */
export const getLiveBotChart = (botId, frame, replay = false) => request(`/api/studio/live/bot/${enc(botId)}/chart${qs({ frame, replay: replay ? 1 : undefined })}`)

/** Đối chiếu bot live với backtest replay. */
export const getLiveBotCompare = (botId) => request(`/api/studio/live/bot/${enc(botId)}/compare`)

/** Nhật ký hoạt động trực tiếp của bot (nautilus.log, events, signals). */
export const getLiveBotLogs = (botId, lines = 150) => request(`/api/studio/live/bot/${enc(botId)}/logs?lines=${lines}`)

/** Nhật ký tổng hợp từ toàn bộ bot đang chạy (portfolio live logs). */
export const getLiveAggregateLogs = (lines = 300, mode = '') => request(`/api/studio/live/logs/aggregate?lines=${lines}${mode ? `&mode=${enc(mode)}` : ''}`)

/** Chạy lại bot đã dừng (resume). */
export const resumeLiveBot = (botId) => request(`/api/studio/live/bot/${enc(botId)}/resume`, { method: 'POST' })

/** Trạng thái tài nguyên: số bot đang chạy, giới hạn, RAM. */
export const getLiveResourceStatus = () => request('/api/studio/live/resource_status')

/** Dừng nhiều bot cùng lúc. */
export const batchStopLiveBots = (botIds, close = true) => request('/api/studio/live/bots/stop', { method: 'POST', body: { bot_ids: botIds, close } })

/** Xoá nhiều bot đã dừng cùng lúc. */
export const batchDeleteLiveBots = (botIds, mode) => request('/api/studio/live/bots', { method: 'DELETE', body: { bot_ids: botIds, mode } })


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

/** Huỷ một job đang chạy (SIGTERM tới nhóm tiến trình). */
export const postCancel = (id) => request(`/api/studio/book/jobs/${enc(id)}/cancel`, { method: 'POST' }).then(normJob)

/** Metadata duy nhất từ backend (nguồn sự thật tập trung cho UI). */
export const getStudioMeta = () => request('/api/studio/meta')

// ═════════════════════════════════════════════════════════════════════════════
// 6. USERS & HOME (backend/routes/users.py, backend/routes/home.py)
// ═════════════════════════════════════════════════════════════════════════════

/** Danh sách user công khai: [{handle, display_name, avatar, bio, role, n_strategies}]. */
export const getUsers = () => request('/api/users')

/** Tạo user mới: {handle, display_name, bio?}. */
export const createUser = (body) => request('/api/users', { method: 'POST', body })

/** Chi tiết 1 user: {id, handle, display_name, avatar, bio, role, created_at}. */
export const getUser = (handle) => request(`/api/users/${enc(handle)}`)

/** Danh sách chiến lược của user: {handle, strategies: [...]}. */
export const getUserStrategies = (handle) => request(`/api/users/${enc(handle)}/strategies`)

/** Đọc phiên hiện tại: {user: User|null}. */
export const getMe = () => request('/api/me')

/** Đăng nhập theo handle và password: {ok: true, user: User}. */
export const login = (handle, password) => request('/api/me/login', { method: 'POST', body: { handle, password } })

/** Đổi mật khẩu tài khoản đang đăng nhập. */
export const changePassword = (currentPassword, newPassword) =>
  request('/api/me/password', { method: 'POST', body: { current_password: currentPassword, new_password: newPassword } })

/** Đăng xuất (xoá cookie). */
export const enterByName = (name) => request('/api/me/enter', { method: 'POST', body: { name } })

// Đăng xuất
export const logout = () => request('/api/me/logout', { method: 'POST' })

/** Đăng nhập qua mạng xã hội (Google Identity Services). */
export const socialLogin = (credential, provider = 'google') =>
  request('/api/me/social-login', { method: 'POST', body: { credential, provider } })

/** Sửa thông tin cá nhân: {display_name?, avatar?, bio?}. */
export const updateMe = (body) => request('/api/me', { method: 'PUT', body })

/** Tóm tắt hệ thống cho trang Home: {edu: {...}, coin: {...}}. */
export const getHomeSummary = () => request('/api/home/summary')



// ═════════════════════════════════════════════════════════════════════════════
// Education Market (backend/routes/edu.py)
// ═════════════════════════════════════════════════════════════════════════════

/** Lưới user kèm tổng hợp: {users: [{handle, display_name, avatar, bio, n_strategies, total_pnl_usd, max_mdd_pct, best}]}. sort: pnl | new | name. */
const _eduCache = { market: {}, user: {} }
export const eduMarketCached = (sort = 'pnl') => _eduCache.market[sort]
export const eduUserCached = (handle) => _eduCache.user[handle]
export const getEduMarket = (params = 'pnl') => {
  const p = typeof params === 'string' ? { sort: params } : (params || {})
  const sort = p.sort || 'pnl'
  const qs = new URLSearchParams({ sort })
  if (p.rankedOnly) qs.set('ranked_only', 'true')
  if (p.timeframe && p.timeframe !== 'all') qs.set('timeframe', p.timeframe)
  if (p.symbol && p.symbol !== 'all') qs.set('symbol', p.symbol)
  const key = qs.toString()
  return request(`/api/edu/market?${key}`).then((d) => (_eduCache.market[key] = d))
}

/** Hồ sơ + chiến lược của 1 user: {user, summary, strategies: [{id, name, category, ret_pct, mdd_pct, sharpe, win_rate, trades, pnl_usd}]}. */
export const getEduUser = (handle) => request(`/api/edu/users/${enc(handle)}`).then((d) => (_eduCache.user[handle] = d))
export const prefetchEduUser = (handle) => { if (!_eduCache.user[handle]) getEduUser(handle).catch(() => {}) }

/** Chi tiết công khai (chỉ đọc) của 1 chiến lược: {id, name, code, result, card, owner}. */
export const getEduStrategy = (id) => request(`/api/edu/strategies/${enc(id)}`)

/** Mẫu hiển thị trong Studio Education: {show_samples, samples: [1 mẫu hướng dẫn]}. */
export const getEduSamplesVisible = () => request('/api/edu/samples/visible')

/** Sao chép (fork) chiến lược về bản nháp của user hiện tại. */
export const postForkStrategy = (alphaId) => request(`/api/edu/strategies/${enc(alphaId)}/fork`, { method: 'POST' })

// Helper chung cho các trang mới (research)
export const apiGet = (path) => request(path)
export const apiPost = (path, body) => request(path, { method: 'POST', body })
export const apiDelete = (path) => request(path, { method: 'DELETE' })

/** Tổng hợp mọi lần backtest đã xong: {runs, pnl_usd, capital, pnl_pct, mdd_pct, trades, last, recent[]}. */
export const getBacktestSummary = () => request('/api/studio/book/backtest_summary')

/** Tổng hợp chung Backtest + Paper + Live (tính ở backend). */
export const getOverview = () => request('/api/studio/overview')
export const getOverviewSeries = () => request('/api/studio/overview/series')

// ═════════════════════════════════════════════════════════════════════════════
// Universe Scan (backend/routes/scan.py)
// ═════════════════════════════════════════════════════════════════════════════
export const postUniverseScan = (body) => request('/api/studio/scan/universe', { method: 'POST', body })
export const getUniverseScan = (runId = 'latest') => request(`/api/studio/scan/universe/${encodeURIComponent(runId)}`)
export const getUniverseRuns = () => request('/api/studio/scan/runs')
export const getUniverseInfo = () => request('/api/studio/scan/universe_info')
export const getLatestSweep = () => request('/api/studio/scan/sweep/latest')
export const getLatestWfaCarlo = () => request('/api/studio/scan/wfa_carlo/latest')
