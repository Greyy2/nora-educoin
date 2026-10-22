// Form chạy backtest chiến lược Python dùng chung cho /alpha/create và /education: kiểm tra đầu vào và dựng thân POST /api/studio/custom/backtest.
// Một cấu hình thực thi duy nhất (mặc định của engine Nora); form chỉ chọn rổ, ngày, vốn và ghi đè tham số vị thế.
import { execRunFrame } from './metaDefaults'
import { POSITION_FIELDS } from '../components/alpha/studio/RunSettings'

export const POSITION_KEYS = POSITION_FIELDS.map((f) => f.key)
const num = (v) => (v === '' || v == null ? NaN : Number(v))

export function validateRun(form, code) {
  const out = []
  if (!code.trim()) out.push('Chưa có code chiến lược.')
  if (!form.start || !form.end) out.push('Ngày bắt đầu / kết thúc chưa hợp lệ (dd/mm/yyyy).')
  else if (form.start >= form.end) out.push('Ngày kết thúc phải sau ngày bắt đầu.')
  const r = num(form.train_ratio)
  if (!(r > 0 && r < 1)) out.push('Tỉ lệ train phải nằm trong khoảng (0, 1), ví dụ 0.7.')
  if (!(num(form.capital) > 0)) out.push('Vốn ban đầu phải lớn hơn 0.')
  if (!form.symbols.length) out.push('Chọn ít nhất một tài sản.')
  POSITION_FIELDS.forEach((f) => {
    const v = form.pos?.[f.key]
    if (v !== '' && v != null && !(num(v) >= 0)) out.push(`Tham số quản lý vị thế "${f.key}" phải là số không âm.`)
  })
  return out
}

/** Dựng thân POST /api/studio/custom/backtest. Chế độ Nhanh không gửi run_frame (backend quyết theo chương trình). */
export function buildRunBody(form, code, _timeframe = null, defaultMode = 'fast') {
  const body = { code, start: form.start, end: form.end, train_ratio: num(form.train_ratio), initial_capital: num(form.capital), symbols: form.symbols }
  const rf = execRunFrame(form.exec_mode || defaultMode)
  if (rf) body.run_frame = rf
  const position = {}
  // Mẫu có thể kèm khoá ngoài ô nhập (vd atr_frame: '24h'): gửi nguyên, số thì ép số.
  Object.entries(form.pos || {}).forEach(([k, v]) => { if (v !== '' && v != null) position[k] = Number.isNaN(Number(v)) ? v : Number(v) })
  if (Object.keys(position).length) body.position = position
  return body
}
