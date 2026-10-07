import { useCallback, useEffect, useMemo, useState } from 'react'
import { listAllJobs } from '../api'
import { isActiveJob } from '../lib/jobs'

// Kho mức module: mọi component dùng useJobList (khay công việc, trang Lịch sử…) chung một vòng poll,
// hỏi với limit lớn nhất đang có người đăng ký; mỗi người nhận lại đúng `limit` của mình.
const subs = new Map() // cb -> limit
let state = { jobs: [], loading: true, error: null, updatedAt: null, limit: 0 }
let timer = null
let inflight = null
let wantAgain = false

const maxLimit = () => Math.max(...subs.values())
const emit = () => subs.forEach((_, cb) => cb(state))

async function load() {
  clearTimeout(timer)
  if (!subs.size) return
  if (inflight) { wantAgain = true; return inflight } // đang hỏi: xong sẽ hỏi lại 1 lần (vd. limit vừa tăng)
  const limit = maxLimit()
  let next = 30000
  inflight = (async () => {
    try {
      const jobs = await listAllJobs(limit)
      state = { jobs, loading: false, error: null, updatedAt: Date.now(), limit }
      if (jobs.some(isActiveJob)) next = 5000
    } catch (e) {
      state = { ...state, loading: false, error: e.message }
    }
    emit()
  })()
  await inflight
  inflight = null
  if (!subs.size) return
  if (wantAgain || maxLimit() > state.limit) { wantAgain = false; return load() }
  if (!document.hidden) timer = setTimeout(load, next)
}

const onVis = () => { if (!document.hidden) load(); else clearTimeout(timer) }

function subscribe(limit, cb) {
  const first = !subs.size
  subs.set(cb, limit)
  if (first) document.addEventListener('visibilitychange', onVis)
  if (!first && state.updatedAt) cb(state) // người đến sau nhận ngay dữ liệu đã có
  if (first || limit > state.limit) load()
  return () => {
    subs.delete(cb)
    if (!subs.size) {
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVis)
      state = { ...state, loading: true, updatedAt: null, limit: 0 } // lần sau mount hỏi lại từ đầu, giữ jobs cũ để khỏi nháy
    }
  }
}

/**
 * Danh sách job mới nhất (mọi loại). Cứ 5 giây hỏi lại khi có job đang chạy/chờ, nếu không thì 30 giây; tạm dừng khi tab bị ẩn
 * và hỏi lại ngay khi tab hiện lại. Nhiều component cùng dùng = một vòng poll chung (limit lớn nhất).
 */
export default function useJobList(limit = 20) {
  const [st, setSt] = useState(() => (state.updatedAt ? state : { ...state, loading: true }))
  useEffect(() => subscribe(limit, setSt), [limit])
  const jobs = useMemo(() => (st.jobs.length > limit ? st.jobs.slice(0, limit) : st.jobs), [st.jobs, limit])
  const reload = useCallback(() => load(), [])
  const running = jobs.filter((j) => j.status === 'running').length
  const queued = jobs.filter((j) => j.status === 'queued').length
  return { jobs, loading: st.loading, error: st.error, updatedAt: st.updatedAt, running, queued, reload }
}
