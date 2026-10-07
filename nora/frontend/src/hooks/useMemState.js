import { useCallback, useState } from 'react'

// useState gộp theo patch, CHỈ trong bộ nhớ (không localStorage): bản nháp / form / lần chạy tạm mất khi đóng hoặc tải lại trang.
export default function useMemState(initial) {
  const [v, setV] = useState(initial)
  const set = useCallback((patch) => setV((prev) => ({ ...prev, ...(typeof patch === 'function' ? patch(prev) : patch) })), [])
  return [v, set]
}
