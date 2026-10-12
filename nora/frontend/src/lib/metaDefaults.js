// Khung chạy + chế độ khớp lệnh mặc định: MỘT nơi duy nhất. Ưu tiên giá trị backend công bố trong GET /api/studio/meta; chỉ khi meta chưa có mới dùng dự phòng dưới đây.
// Meta hiện có meta.frames.{all,custom_backtest,funnel} (danh sách); mặc định có thể là meta.frames.defaults[kind] và meta.engine.default_exec_mode (nếu backend bổ sung).
export const FALLBACK_FRAMES = ['15m', '1h', '4h']
const PREFERRED_FRAME = '1h'

/** Danh sách khung theo loại ('funnel' | 'custom_backtest' | 'all'); meta chưa tải -> dự phòng. */
export function framesOf(meta, kind = 'funnel') {
  const f = meta?.frames?.[kind]
  return Array.isArray(f) && f.length ? f : FALLBACK_FRAMES
}

/** Khung mặc định: meta.frames.defaults[kind] nếu có, không thì 1h khi nằm trong danh sách, không thì khung đầu tiên. */
export function defaultFrame(meta, kind = 'funnel') {
  const list = framesOf(meta, kind)
  const d = meta?.frames?.defaults?.[kind]
  if (d && list.includes(d)) return d
  return list.includes(PREFERRED_FRAME) ? PREFERRED_FRAME : list[0]
}

/** Chế độ khớp lệnh: 'fast' (khung tín hiệu) | 'standard' (nến 1m). */
export const EXEC_MODES = [
  { value: 'fast', label: 'Nhanh (khung tín hiệu)' },
  { value: 'standard', label: 'Chuẩn (nến 1m)' },
]
export const defaultExecMode = (meta) => {
  const d = meta?.engine?.default_exec_mode
  return d === 'standard' ? 'standard' : 'fast'
}
/** Chuẩn -> run_frame '1m'; Nhanh -> khung `fallback` (khung tín hiệu / chọn tay) hoặc null (backend quyết định). */
export const execRunFrame = (mode, fallback = null) => (mode === 'standard' ? '1m' : fallback || null)
