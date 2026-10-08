import { fmtNum } from './format'

// Nguồn duy nhất cho nhãn / đơn vị / cách hiển thị tham số chiến lược. Khoá thô vẫn được giữ làm tooltip cho người dùng chuyên sâu.
const num = (v) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v ?? '—')
  return fmtNum(n, 2)
}

// timeout tính bằng phút: 0 = không giới hạn; < 2 ngày hiện theo giờ, còn lại theo ngày
export function fmtTimeout(v) {
  const m = Number(v)
  if (!Number.isFinite(m)) return String(v ?? '—')
  if (m === 0) return 'Không giới hạn'
  if (m % 1440 === 0 && m >= 2880) return `${m / 1440} ngày`
  if (m % 60 === 0) return `${m / 60} giờ`
  return `${num(m)} phút`
}

export const PARAMS = {
  stop_loss_rate: { label: 'Cắt lỗ', unit: '× ATR', hint: 'Khoảng cách cắt lỗ, tính bằng bội số ATR' },
  take_profit_rate: { label: 'Chốt lời', unit: '× ATR', zero: 'Tắt', hint: 'Khoảng cách chốt lời, tính bằng bội số ATR' },
  trailing_stop: { label: 'Trailing', unit: '× ATR', zero: 'Tắt', hint: 'Khoảng bám đuôi của lệnh cắt lỗ động' },
  trailing_activation_pct: { label: 'Kích hoạt trailing', unit: '× ATR', zero: 'Ngay', hint: 'Lãi tối thiểu (bội số ATR) trước khi trailing bắt đầu bám; 0 = ngay' },
  timeout: { label: 'Giữ tối đa', unit: '', fmt: fmtTimeout, hint: 'Thời gian giữ lệnh tối đa; 0 = không giới hạn' },
  'sig.adx_min': { label: 'ADX tối thiểu', unit: '', hint: 'Chỉ vào lệnh khi ADX lớn hơn mức này (xu hướng đủ rõ)' },
  'sig.roc_min': { label: 'ROC tối thiểu (%)', unit: '%', hint: 'Tốc độ tăng giá tối thiểu trong chu kỳ ROC để vào lệnh' },
  'sig.rsi_lo': { label: 'RSI dưới', unit: '', hint: 'Mua khi RSI thấp hơn mức này (quá bán)' },
  'sig.rsi_hi': { label: 'RSI trên', unit: '', hint: 'Bán khi RSI cao hơn mức này (quá mua)' },
  'sig.er_max': { label: 'ER tối đa (đi ngang)', unit: '', hint: 'Efficiency Ratio tối đa: thấp nghĩa là thị trường đi ngang, hợp với hồi quy về trung bình' },
  cooldown: { label: 'Chờ sau khi thoát (phút)', unit: 'phút', hint: 'Chờ bấy nhiêu phút sau khi đóng lệnh mới vào lệnh mới' },
  // tín hiệu: khung thời gian
  'sig.trend_tf': { label: 'Khung xu hướng', unit: '', hint: 'Khung nến tính EMA và ADX xác nhận xu hướng' },
  'sig.entry_tf': { label: 'Khung điểm vào', unit: '', hint: 'Khung nến tìm điểm vào lệnh' },
  'sig.signal_tf': { label: 'Khung tín hiệu', unit: '', hint: 'Khung nến phát tín hiệu phá vỡ' },
  'sig.roc_tf': { label: 'Khung ROC', unit: '', hint: 'Khung nến tính tốc độ tăng giá (ROC)' },
  'sig.regime_tf': { label: 'Khung chế độ thị trường', unit: '', hint: 'Khung nến đo ER để nhận biết thị trường đi ngang' },
  atr_frame: { label: 'Khung ATR', unit: '', hint: 'Khung nến tính ATR cho cắt lỗ / chốt lời / trailing' },
  // tín hiệu: chu kỳ, hệ số
  'sig.ema_fast': { label: 'EMA nhanh', unit: 'nến', hint: 'Chu kỳ EMA nhanh (phải nhỏ hơn EMA chậm)' },
  'sig.ema_slow': { label: 'EMA chậm', unit: 'nến', hint: 'Chu kỳ EMA chậm; EMA nhanh nằm trên / dưới nó quyết định chiều xu hướng' },
  'sig.ema_n': { label: 'Chu kỳ EMA', unit: 'nến', hint: 'Chu kỳ EMA lọc chiều xu hướng' },
  'sig.adx_n': { label: 'Chu kỳ ADX', unit: 'nến', hint: 'Chu kỳ ADX đo độ mạnh xu hướng' },
  'sig.dch_n': { label: 'Chu kỳ kênh Donchian', unit: 'nến', hint: 'Vào lệnh khi giá vượt đỉnh / đáy của bấy nhiêu nến trước' },
  'sig.rsi_n': { label: 'Chu kỳ RSI', unit: 'nến', hint: 'Chu kỳ tính RSI' },
  'sig.bb_n': { label: 'Chu kỳ Bollinger', unit: 'nến', hint: 'Số nến tính đường trung bình của dải Bollinger' },
  'sig.bb_k': { label: 'Độ rộng Bollinger', unit: 'σ', hint: 'Số độ lệch chuẩn của dải Bollinger' },
  'sig.er_n': { label: 'Chu kỳ ER', unit: 'nến', hint: 'Chu kỳ tính Efficiency Ratio' },
  'sig.roc_n': { label: 'Chu kỳ ROC', unit: 'nến', hint: 'Chu kỳ tính tốc độ tăng giá (ROC)' },
  // Keltner (KEMA) và DCA
  'sig.atr_n': { label: 'Chu kỳ ATR của kênh', unit: 'nến', hint: 'ATR (Wilder) đo độ rộng kênh Keltner' },
  'sig.k_up': { label: 'Hệ số dải trên', unit: '× ATR', hint: 'Dải trên = EMA + hệ số × ATR' },
  'sig.k_dn': { label: 'Hệ số dải dưới', unit: '× ATR', hint: 'Dải dưới = EMA − hệ số × ATR' },
  'sig.gate_er_max': { label: 'Chỉ dồn khi ER dưới', unit: '', hint: 'Tầng DCA chỉ khớp khi Efficiency Ratio còn thấp (thị trường vẫn đi ngang)' },
  'sig.gate_adx_max': { label: 'Chỉ dồn khi ADX dưới', unit: '', hint: 'Tầng DCA chỉ khớp khi chưa có xu hướng mạnh (ADX thấp hơn mức này)' },
  dca_step_pct: { label: 'Bước dồn lệnh', unit: '× ATR', hint: 'Giá đi ngược bấy nhiêu × ATR so với lần khớp trước thì dồn thêm một tầng' },
  dca_max_layers: { label: 'Số tầng dồn tối đa', unit: 'tầng', hint: 'Số lần dồn thêm sau lệnh đầu' },
  dca_size_multiplier: { label: 'Hệ số khối lượng tầng sau', unit: '×', hint: 'Mỗi tầng sau lớn gấp bấy nhiêu lần tầng trước' },
  // walk-forward / Monte Carlo
  step_days: { label: 'Bước trượt fold', unit: 'ngày', hint: 'Mỗi fold trượt bấy nhiêu ngày (mặc định bằng số ngày test)' },
  sims: { label: 'Số kịch bản MC của WFA', unit: 'kịch bản', hint: 'Số mô phỏng Monte Carlo của cổng WFA; dưới 10.000 thì không xuất bản được' },
  mc_seed: { label: 'Seed MC của WFA', unit: '', hint: 'Hạt giống ngẫu nhiên của Monte Carlo trong WFA' },
  simulations: { label: 'Số mô phỏng', unit: 'kịch bản', hint: '100 đến 50.000; dưới 10.000 thì kết quả không dùng làm cổng và không xuất bản được' },
  block_days: { label: 'Độ dài khối (ngày)', unit: 'ngày', hint: 'Bootstrap theo khối: số ngày liên tiếp mỗi lần lấy mẫu' },
  horizon_days: { label: 'Chân trời (ngày)', unit: 'ngày', hint: 'Số ngày mỗi kịch bản mô phỏng (tối đa 730)' },
  seed: { label: 'Seed', unit: '', hint: 'Hạt giống ngẫu nhiên: cùng seed cho cùng kết quả' },
  scale: { label: 'Hệ số quy mô', unit: '×', hint: 'Nhân lợi suất ngày với hệ số này (0 đến 10)' },
  ruin_threshold_pct: { label: 'Ngưỡng phá sản MDD (%)', unit: '%', hint: 'Cổng chuẩn là 30%; đổi thì kết quả không xuất bản được' },
  stress_max_mdd_pct: { label: 'MDD tối đa của kịch bản cực xấu (%)', unit: '%', hint: 'Cổng chuẩn là 50%; đổi thì kết quả không xuất bản được' },
  extra_cost_daily_pct: { label: 'Phí bổ sung kịch bản phí gấp đôi (%/ngày)', unit: '%/ngày', hint: 'Bỏ trống = hằng số bảo thủ 0,07%/ngày' },
  // thoát lệnh / rủi ro (bổ sung)
  atr_period: { label: 'Chu kỳ ATR', unit: 'nến', hint: 'Số nến tính ATR' },
  risk_per_trade_pct: { label: 'Rủi ro mỗi lệnh', unit: '% vốn', hint: 'Phần vốn có thể mất nếu lệnh chạm cắt lỗ; dùng chung cho cả danh mục' },
  max_notional_pct: { label: 'Giá trị lệnh tối đa', unit: '% vốn', hint: 'Trần giá trị danh nghĩa một lệnh, tính theo % vốn' },
  // thông số vị thế hay gặp ở kho alpha
  order_size_pct: { label: 'Cỡ lệnh (% vốn)', unit: '%' },
  leverage: { label: 'Đòn bẩy', unit: '×', hint: 'Đòn bẩy tối đa của một vị thế' },
  market: { label: 'Thị trường', unit: '', fmt: (v) => String(v) },
}

// `adx_min` (kho alpha) và `sig.adx_min` (danh mục) là cùng một tham số
function meta(key) {
  return PARAMS[key] || PARAMS[`sig.${key}`] || null
}

export const paramLabel = (key) => meta(key)?.label || String(key)

export function paramUnit(key) {
  const u = meta(key)?.unit
  return u || ''
}

/** Tiêu đề cột / nhãn có đơn vị: "Cắt lỗ (× ATR)". Đơn vị đã nằm trong nhãn thì không thêm lần nữa. */
export function paramHeader(key) {
  const m = meta(key)
  if (!m) return String(key)
  const u = m.unit
  return u && !m.label.includes('(') && !['phút', '%'].includes(u) ? `${m.label} (${u})` : m.label
}

/** Giá trị đã định dạng, KHÔNG kèm đơn vị (dùng dưới tiêu đề cột đã có đơn vị). */
export function fmtParam(key, v) {
  const m = meta(key)
  if (v == null) return '—'
  if (m?.fmt) return m.fmt(v)
  if (m?.zero && Number(v) === 0) return m.zero
  return num(v)
}

/** Giá trị kèm đơn vị: "2.5× ATR", "7 ngày", "Ngay". */
export function fmtParamFull(key, v) {
  const m = meta(key)
  const base = fmtParam(key, v)
  if (!m || m.fmt || (m.zero && Number(v) === 0) || !m.unit || m.label.includes('(')) return base
  return m.unit.startsWith('×') ? `${base}${m.unit}` : `${base} ${m.unit}`
}

/** "Cắt lỗ 2.5× ATR" */
export const paramText = (key, v) => `${paramLabel(key)} ${fmtParamFull(key, v)}`

/** Hai bộ tham số có giống nhau không (so theo giá trị số). */
export function sameParams(a, b) {
  const ka = Object.keys(a || {})
  const kb = Object.keys(b || {})
  if (ka.length !== kb.length) return false
  return ka.every((k) => b && k in b && Number(a[k]) === Number(b[k]))
}

/** Nhóm tham số của lược đồ chiến lược (`params_schema[k].group`). */
export const PARAM_GROUPS = [
  { key: 'signal', label: 'Tín hiệu vào lệnh' },
  { key: 'dca', label: 'Dồn lệnh (DCA)' },
  { key: 'exit', label: 'Thoát lệnh' },
  { key: 'risk', label: 'Rủi ro và vốn' },
]

export const paramHint = (key) => meta(key)?.hint || ''
