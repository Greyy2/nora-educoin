import { useCallback, useEffect, useRef, useState } from 'react'
import { subscribeResource, invalidateResource } from '../lib/bus'

export { invalidateResource, invalidateResource as invalidate }

const RESOURCE_CACHE = new Map()

/**
 * useResource(key, fetcher, { poll, deps }):
 * Hook nạp tài nguyên theo khoá key, tự động lắng nghe invalidate(key) để làm mới.
 * Có cơ chế SWR (Stale-While-Revalidate): nếu có cache thì trả về ngay lập tức (0ms),
 * không làm màn hình bị chớp loading / giật lag khi chuyển đổi view.
 * Trả về { data, loading, error, reload }.
 */
export function useResource(key, fn, { poll, deps = [] } = {}) {
  const cached = key && RESOURCE_CACHE.has(key) ? RESOURCE_CACHE.get(key) : null
  const [st, setSt] = useState({
    data: cached ? cached.data : null,
    loading: cached ? false : !!fn,
    error: null,
  })
  const seq = useRef(0)
  const timer = useRef(null)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const pollRef = useRef(poll)
  pollRef.current = poll
  const polling = useRef(false) // lần xong gần nhất còn hẹn poll tiếp

  const run = useCallback((silent = false) => {
    clearTimeout(timer.current)
    const f = fnRef.current
    if (!f) {
      setSt({ data: null, loading: false, error: null })
      return
    }
    const my = ++seq.current
    const hasCache = key && RESOURCE_CACHE.has(key)
    const isSilent = silent || hasCache
    if (!isSilent) setSt((s) => ({ ...s, loading: true, error: null }))
    f().then(
      (data) => {
        if (my !== seq.current) return
        if (key) RESOURCE_CACHE.set(key, { data, ts: Date.now() })
        setSt({ data, loading: false, error: null })
        const ms = pollRef.current ? pollRef.current(data) : 0
        polling.current = !!ms
        if (ms) {
          timer.current = setTimeout(() => {
            if (document.hidden) {
              timer.current = setTimeout(() => run(true), ms)
            } else {
              run(true)
            }
          }, ms)
        }
      },
      (e) => {
        if (my !== seq.current) return
        setSt((s) => ({ data: isSilent ? s.data : null, loading: false, error: e.message || String(e) }))
      }
    )
  }, [key])

  useEffect(() => {
    run(false)
    return () => {
      seq.current++
      clearTimeout(timer.current)
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps

  // Lắng nghe sự kiện invalidate theo khoá tài nguyên
  useEffect(() => {
    if (!key) return undefined
    const handler = (pattern) => {
      if (pattern === 'all' || pattern === key || (typeof key === 'string' && key.startsWith(pattern))) {
        if (key) RESOURCE_CACHE.delete(key)
        run(true)
      }
    }
    return subscribeResource(handler)
  }, [key, run])

  useEffect(() => {
    const vis = () => {
      if (!document.hidden && polling.current && fnRef.current) run(true)
    }
    document.addEventListener('visibilitychange', vis)
    return () => document.removeEventListener('visibilitychange', vis)
  }, [run])

  return { ...st, reload: useCallback(() => run(false), [run]) }
}

/**
 * useAsync(fn, deps, { poll }):
 * Tương thích ngược với mọi nơi dùng useAsync cũ, đồng thời nhận lợi ích đồng bộ visibility.
 */
export default function useAsync(fn, deps, opts = {}) {
  return useResource(null, fn, { ...opts, deps })
}
