import { useCallback, useEffect, useRef, useState } from 'react'
import { listAllJobs } from '../api'
import { isActiveJob } from '../lib/jobs'

/**
 * Danh sách job mới nhất (mọi loại). Cứ 5 giây hỏi lại khi có job đang chạy/chờ, nếu không thì 30 giây; tạm dừng khi tab bị ẩn
 * và hỏi lại ngay khi tab hiện lại.
 */
export default function useJobList(limit = 20) {
  const [st, setSt] = useState({ jobs: [], loading: true, error: null, updatedAt: null })
  const timer = useRef(null)
  const dead = useRef(false)

  const load = useCallback(async () => {
    clearTimeout(timer.current)
    let next = 30000
    try {
      const jobs = await listAllJobs(limit)
      if (dead.current) return
      setSt({ jobs, loading: false, error: null, updatedAt: Date.now() })
      if (jobs.some(isActiveJob)) next = 5000
    } catch (e) {
      if (dead.current) return
      setSt((s) => ({ ...s, loading: false, error: e.message }))
    }
    if (!dead.current && !document.hidden) timer.current = setTimeout(load, next)
  }, [limit])

  useEffect(() => {
    dead.current = false
    load()
    const vis = () => { if (!document.hidden) load(); else clearTimeout(timer.current) }
    document.addEventListener('visibilitychange', vis)
    return () => { dead.current = true; clearTimeout(timer.current); document.removeEventListener('visibilitychange', vis) }
  }, [load])

  const running = st.jobs.filter((j) => j.status === 'running').length
  const queued = st.jobs.filter((j) => j.status === 'queued').length
  return { ...st, running, queued, reload: load }
}
