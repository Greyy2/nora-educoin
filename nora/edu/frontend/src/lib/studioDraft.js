// Trạng thái bản nháp của /alpha/create và /education: CHỈ trong bộ nhớ (mất khi đóng/tải lại trang). Chỉ lệnh "Lưu chiến lược" mới ghi vào kho alpha người dùng.
//
// Bản nháp: { id, name, code, baseCode, jobId, sampleKey, runAlpha, saved, stored }
//   baseCode : code lúc mở bản nháp (mẫu / trống) — khác baseCode = đã sửa
//   jobId    : lần chạy tạm hiện tại (job custom_backtest; máy chủ tự xoá sau 24 h nếu không lưu)
//   runAlpha : alpha_id (do BACKEND tính) của kết quả lần chạy đã xong gần nhất
//   saved    : { alpha_id, code, name } của bản đã lưu gần nhất (null = chưa lưu)
//   stored   : bản ghi alpha đã lưu mở từ danh sách "Đã lưu" (chứa result đã lưu, hiển thị mà không chạy lại)

export const uid = (p = 'd') => `${p}${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`

export const newDraft = (name, code, extra = {}) => ({
  id: uid(), name, code, baseCode: code, jobId: '', sampleKey: '', runAlpha: '', saved: null, stored: null, ...extra,
})

/** Chưa lưu: chỉ cảnh báo khi người dùng thực sự sửa code so với bản gốc.
 * Chiến lược mẫu hoặc chiến lược đã có trong hệ thống bản chất đã được lưu sẵn,
 * việc chưa chạy hoặc chạy lại không làm mất mát gì nên không coi là dirty khi thoát. */
export function isDraftDirty(d) {
  if (!d) return false
  const isSampleOrSaved = Boolean(d.sampleKey || d.saved || d.stored || d.alphaId)
  if (isSampleOrSaved) {
    // Chỉ dirty khi người dùng đã chỉnh sửa code so với bản gốc của mẫu / bản đã lưu
    return d.code !== d.baseCode
  }
  // Chiến lược mới hẳn: chỉ dirty khi đã nhập code thực tế
  return Boolean(d.code && d.code.trim().length > 0 && d.code !== d.baseCode)
}

/** Cấu hình đã lưu (config của kết quả) -> các trường form chạy. Tham số vị thế chỉ lấy các khoá có ô nhập. */
export function configToForm(config, positionKeys = []) {
  const c = config || {}
  const f = {}
  if (c.start) f.start = c.start
  if (c.end) f.end = c.end
  if (c.train_ratio != null) f.train_ratio = String(c.train_ratio)
  if (c.initial_capital != null) f.capital = String(c.initial_capital)
  const syms = Array.isArray(c.data_symbols) && c.data_symbols.length ? c.data_symbols : c.symbols
  if (Array.isArray(syms) && syms.length) f.symbols = syms
  f.exec_mode = c.exec_mode || 'fast'
  const pos = {}
  // Chỉ lấy các tham số người dùng thực sự ghi đè ở giao diện (position_overrides).
  // Không fallback về c.position (vì c.position chứa toàn bộ mặc định của engine, sẽ tự điền vào form và ghi đè code).
  const position = c.position_overrides || {}
  positionKeys.forEach((k) => { if (position && position[k] != null) pos[k] = String(position[k]) })
  f.pos = pos
  return f
}
