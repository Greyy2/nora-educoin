import { useCallback, useState } from 'react'

// useState có nhớ giá trị trong localStorage (mọi thao tác bọc try/catch: trình duyệt có thể chặn).
export default function useStored(key, initial) {
  const [v, setV] = useState(() => {
    try {
      const s = localStorage.getItem(key)
      return s != null ? { ...initial, ...JSON.parse(s) } : initial
    } catch (e) { return initial }
  })
  const set = useCallback((patch) => {
    setV((prev) => {
      const next = { ...prev, ...patch }
      try { localStorage.setItem(key, JSON.stringify(next)) } catch (e) { /* bỏ qua */ }
      return next
    })
  }, [key])
  return [v, set]
}
