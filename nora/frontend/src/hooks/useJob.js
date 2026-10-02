import { useEffect, useState } from 'react'
import { getJob } from '../api'

/**
 * Poll GET /api/studio/book/jobs/{id} mỗi `interval` ms cho tới khi done/failed/cancelled; dừng khi unmount hoặc đổi id.
 * Trả { job, status, error }. status: 'loading' (chưa có phản hồi đầu) | queued | running | done | failed | cancelled | null (không có id).
 */
export default function useJob(jobId, { interval = 2000 } = {}) {
  const [state, setState] = useState({ job: null, error: null })
  useEffect(() => {
    setState({ job: null, error: null })
    if (!jobId) return undefined
    let dead = false
    let timer = null
    let fails = 0
    const tick = async () => {
      try {
        const j = await getJob(jobId)
        if (dead) return
        fails = 0
        setState({ job: j, error: null })
        if (j.status === 'done' || j.status === 'failed' || j.status === 'cancelled') return
      } catch (e) {
        if (dead) return
        fails += 1
        if (fails >= 5 || e.status === 404 || e.status === 422) { setState((s) => ({ ...s, error: e.message })); return }
      }
      timer = setTimeout(tick, interval)
    }
    tick()
    return () => { dead = true; clearTimeout(timer) }
  }, [jobId, interval])
  const status = state.job?.status || (jobId && !state.error ? 'loading' : null)
  return { ...state, status }
}
