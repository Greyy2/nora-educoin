import { useEffect, useState } from 'react'
import { getJob } from '../api'

const TERMINAL = new Set(['done', 'failed', 'cancelled'])
const MAX_DELAY = 10000 // job chạy lâu: giãn dần 2s -> 4s -> 8s -> 10s

// Kho mức module theo job id: N component cùng theo dõi một job = một vòng poll duy nhất.
const stores = new Map()

// dấu vân tay trạng thái/tiến độ: đổi => đặt lại nhịp poll về `base`
const sig = (j) => `${j.status}|${j.progress?.done ?? ''}|${j.progress?.stage ?? ''}|${j.log_tail?.length ?? ''}`

function makeStore(jobId) {
  const st = { subs: new Map(), state: { job: null, error: null }, timer: null, dead: false, step: 0, last: '', fails: 0, inflight: false }
  const base = () => Math.min(...[...st.subs.values()])
  const emit = () => st.subs.forEach((_, cb) => cb(st.state))
  const schedule = () => {
    clearTimeout(st.timer)
    if (st.dead || document.hidden) return // tab ẩn: dừng, hiện lại sẽ hỏi ngay
    const delay = Math.min(base() * 2 ** st.step, Math.max(MAX_DELAY, base()))
    st.timer = setTimeout(tick, delay)
  }
  async function tick() {
    if (st.dead || st.inflight) return
    st.inflight = true
    let stop = false
    try {
      const j = await getJob(jobId)
      if (st.dead) return
      st.fails = 0
      const s = sig(j)
      if (s !== st.last) { st.last = s; st.step = 0 } else st.step += 1
      st.state = { job: j, error: null }
      emit()
      stop = TERMINAL.has(j.status)
    } catch (e) {
      if (st.dead) return
      st.fails += 1
      st.step += 1
      if (st.fails >= 5 || e.status === 404 || e.status === 410 || e.status === 422) { st.state = { ...st.state, error: e.message, errorStatus: e.status }; emit(); stop = true }
    } finally { st.inflight = false }
    if (!stop) schedule()
  }
  st.onVis = () => { if (!document.hidden && !st.dead) { st.step = 0; clearTimeout(st.timer); tick() } else clearTimeout(st.timer) }
  st.start = () => { document.addEventListener('visibilitychange', st.onVis); tick() }
  st.stop = () => { st.dead = true; clearTimeout(st.timer); document.removeEventListener('visibilitychange', st.onVis) }
  return st
}

function subscribe(jobId, interval, cb) {
  let st = stores.get(jobId)
  const fresh = !st
  if (fresh) { st = makeStore(jobId); stores.set(jobId, st) }
  st.subs.set(cb, interval)
  if (!fresh && (st.state.job || st.state.error)) cb(st.state) // người đến sau nhận ngay kết quả đã có
  if (fresh) st.start()
  return () => {
    st.subs.delete(cb)
    if (!st.subs.size) { st.stop(); if (stores.get(jobId) === st) stores.delete(jobId) }
  }
}

/**
 * Theo dõi GET /api/studio/book/jobs/{id} cho tới khi done/failed/cancelled; dừng khi unmount hoặc đổi id.
 * Nhịp `interval` ms (mặc định 1,5s), giãn dần tới 10s nếu trạng thái/tiến độ không đổi; tab ẩn thì tạm dừng, hiện lại hỏi ngay.
 * Nhiều component cùng id dùng chung một vòng poll. Trả { job, error, errorStatus, status } (errorStatus = mã HTTP của lỗi cuối, vd 404/410 = kết quả tạm đã mất).
 * status: 'loading' (chưa có phản hồi đầu) | queued | running | done | failed | cancelled | null (không có id).
 */
export default function useJob(jobId, { interval = 1500 } = {}) {
  const [state, setState] = useState({ job: null, error: null, errorStatus: null })
  useEffect(() => {
    setState({ job: null, error: null, errorStatus: null })
    if (!jobId) return undefined
    return subscribe(jobId, interval, setState)
  }, [jobId, interval])
  const status = state.job?.status || (jobId && !state.error ? 'loading' : null)
  return { ...state, status }
}
