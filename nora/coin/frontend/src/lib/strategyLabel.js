// Tên hiển thị của chiến lược / chân lệnh (leg). Chiến lược = KEMA | Sideway | DCA; alpha = chiến lược + chiều + bộ tham số.
// Engine vẫn nhận id chân lệnh (kema_long, kema_short, ...): đây là nơi duy nhất dịch id -> nhãn.

export const SIDE_TEXT = { LONG: 'Long', SHORT: 'Short', BOTH: 'Cả hai' }
export const SIDE_OPTIONS = [{ value: 'LONG', label: 'Long' }, { value: 'SHORT', label: 'Short' }, { value: 'BOTH', label: 'Cả hai' }]

const NAMES = { kema: 'KEMA', sideway: 'Sideway', dca: 'DCA' }

// id cũ (còn đọc được ở sổ / lượt phễu cũ nhưng không dùng để chọn mới) -> [tên cũ, chiều]
const LEGACY = {
  trend_long: ['Trend EMA/ADX', 'LONG'], trend_short: ['Trend EMA/ADX', 'SHORT'],
  breakout_4h_long: ['Breakout 4h', 'LONG'], breakout_4h_short: ['Breakout 4h', 'SHORT'],
  keltner_trend_long: ['KEMA', 'LONG'], keltner_trend_short: ['KEMA', 'SHORT'],
  momentum_long: ['Momentum', 'LONG'], momentum_short: ['Momentum', 'SHORT'],
  reversion_long: ['Sideway', 'LONG'], reversion_short: ['Sideway', 'SHORT'],
}

const sideKey = (v) => String(v || '').toUpperCase()

/** "kema_long" -> "KEMA · Long"; id cũ -> "Trend EMA/ADX · Long (cũ)"; id lạ giữ nguyên. */
export function legLabel(id) {
  if (!id) return '—'
  const leg = String(id)
  const old = LEGACY[leg]
  if (old) return `${old[0]} · ${SIDE_TEXT[old[1]]} (cũ)`
  const m = leg.match(/^([a-z0-9]+)_(long|short)$/)
  if (m && NAMES[m[1]]) return `${NAMES[m[1]]} · ${SIDE_TEXT[sideKey(m[2])]}`
  return leg
}

/** Chiều của một id chân lệnh ("LONG" | "SHORT" | null). */
export function legSide(id) {
  const m = String(id || '').match(/_(long|short)$/)
  return m ? sideKey(m[1]) : null
}

/** Id chân lệnh theo chiều chọn: LONG -> [legs.LONG], SHORT -> [legs.SHORT], BOTH -> cả hai. */
export function legsFor(entry, side) {
  const l = entry?.legs || {}
  const out = side === 'BOTH' ? [l.LONG, l.SHORT] : [l[side]]
  return out.filter(Boolean)
}

/** Từ danh sách id chân lệnh -> { [mã chiến lược]: 'LONG' | 'SHORT' | 'BOTH' } theo danh mục chiến lược. Id không thuộc danh mục bị bỏ qua. */
export function picksFromLegs(legIds, catalog) {
  const out = {}
  ;(catalog || []).forEach((c) => {
    const hasL = legIds.includes(c.legs?.LONG)
    const hasS = legIds.includes(c.legs?.SHORT)
    if (hasL || hasS) out[c.id] = hasL && hasS ? 'BOTH' : hasL ? 'LONG' : 'SHORT'
  })
  return out
}

/** Tên chiến lược theo mã ("kema" -> "KEMA"). */
export const strategyName = (key) => NAMES[key] || String(key || '—')
