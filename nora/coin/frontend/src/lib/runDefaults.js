import { useMemo } from 'react'
import useAsync from '../hooks/useAsync'
import { getRunDefaults } from '../api'

// Mặc định của form chạy do BACKEND tính từ kho dữ liệu OKX (GET /api/studio/custom/defaults): rổ perp, cửa sổ ngày chung của cả rổ, tỉ lệ train, vốn.
// Không có hằng số ngày/rổ ở trình duyệt; chưa tải xong hoặc lỗi -> form để trống và hiện lý do.
const str = (v) => (v == null || v === '' ? '' : String(v))

export function useRunDefaults() {
  const d = useAsync(getRunDefaults, [])
  const defaults = useMemo(() => (d.data
    ? { start: d.data.start, end: d.data.end, train_ratio: str(d.data.train_ratio), capital: str(d.data.initial_capital), symbols: d.data.symbols || [] }
    : {}), [d.data])
  return { defaults, universe: d.data?.available_symbols || d.data?.symbols || [], loading: d.loading, error: d.error }
}

// Form hiệu lực = mặc định ← trường người dùng đã chỉnh trong phiên (bộ nhớ, không còn localStorage).
export function resolveForm(base, edited, defaults) {
  return { symbols: [], ...base, ...defaults, ...(edited || {}) }
}
