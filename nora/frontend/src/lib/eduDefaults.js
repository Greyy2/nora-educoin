import { useMemo } from 'react'
import useAsync from '../hooks/useAsync'
import { getEducationResults } from '../api'

// Cửa sổ chạy mặc định = cấu hình của kết quả tính trước (data/education/results/index.json: start/end/train_ratio/initial_capital), để chạy lại mẫu giữ nguyên
// ra đúng số đã tính trước. Chưa có chỉ mục -> 2019-12-31 → 2024-12-31 (cửa sổ khớp xnoquant: tín hiệu nến 12-31 khớp ở open 01-01), train 0,7, vốn 100.000.
export const FALLBACK_RUN = { start: '2019-12-31', end: '2024-12-31', train_ratio: '0.7', capital: '100000' }
const str = (v, d) => (v == null || v === '' ? d : String(v))

export function runDefaults(index) {
  const ok = index && /^\d{4}-\d{2}-\d{2}$/.test(index.start || '') && /^\d{4}-\d{2}-\d{2}$/.test(index.end || '')
  if (!ok) return FALLBACK_RUN
  return { start: index.start, end: index.end, train_ratio: str(index.train_ratio, FALLBACK_RUN.train_ratio), capital: str(index.initial_capital, FALLBACK_RUN.capital) }
}

export function useRunDefaults() {
  const idx = useAsync(getEducationResults, [])
  return useMemo(() => runDefaults(idx.data), [idx.data])
}

// Form hiệu lực = mặc định cửa sổ ← trường người dùng đã chỉnh trong phiên (bộ nhớ, không còn localStorage).
export function resolveForm(base, edited, defaults) {
  return { ...base, ...defaults, ...(edited || {}) }
}
