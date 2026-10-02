import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Gọi `fn()` khi `deps` đổi; bỏ qua kết quả của lần gọi cũ. Trả { data, loading, error, reload }.
 * `fn === null` thì không gọi (data = null). `poll(data)` trả số ms để hỏi lại sau mỗi lần xong (0/undefined = dừng);
 * khi tab bị ẩn thì tạm dừng. Giữ `data` cũ trong lúc tải lại để bảng không nhấp nháy.
 */
export default function useAsync(fn, deps, { poll } = {}) {
  const [st, setSt] = useState({ data: null, loading: !!fn, error: null })
  const seq = useRef(0)
  const timer = useRef(null)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const pollRef = useRef(poll)
  pollRef.current = poll

  const run = useCallback((silent = false) => {
    clearTimeout(timer.current)
    const f = fnRef.current
    if (!f) { setSt({ data: null, loading: false, error: null }); return }
    const my = ++seq.current
    if (!silent) setSt((s) => ({ ...s, loading: true, error: null }))
    f().then((data) => {
      if (my !== seq.current) return
      setSt({ data, loading: false, error: null })
      const ms = pollRef.current ? pollRef.current(data) : 0
      if (ms) timer.current = setTimeout(() => { if (document.hidden) { timer.current = setTimeout(() => run(true), ms) } else run(true) }, ms)
    }, (e) => {
      if (my !== seq.current) return
      setSt((s) => ({ data: silent ? s.data : null, loading: false, error: e.message || String(e) }))
    })
  }, [])

  useEffect(() => {
    run(false)
    return () => { seq.current++; clearTimeout(timer.current) }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps

  return { ...st, reload: useCallback(() => run(false), [run]) }
}
