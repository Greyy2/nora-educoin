// Tài sản DEX trong form Backtest: ký hiệu "dex:AERO" (như engine); perp là "BTC@perp".
export const isDexSym = (s) => String(s).startsWith('dex:')
export const dexSym = (name) => `dex:${String(name).replace(/^dex:/, '')}`

const pad = (n) => String(n).padStart(2, '0')
/** ms UTC -> 'YYYY-MM-DD' */
export const msDate = (ms) => (Number.isFinite(Number(ms)) && ms != null ? new Date(Number(ms)).toISOString().slice(0, 10) : '')
/** ms UTC -> 'dd/mm hh:mm' */
export function msStamp(ms) {
  if (ms == null || !Number.isFinite(Number(ms))) return '—'
  const d = new Date(Number(ms))
  return `${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}

/** Tài sản DEX từ catalog.assets: [{ key: 'dex:AERO', name, network, fee_rate, ticks|null, candles }]. */
export function dexAssets(assets) {
  return (assets || []).filter((a) => a.venue === 'dex').map((a) => {
    const name = String(a.symbol).replace(/^dex:/, '')
    return { ...a, name, key: dexSym(name) }
  })
}

/** Nhãn ngắn về dữ liệu tick của một tài sản DEX. */
export const tickChip = (a) => (a?.ticks ? `tick ${a.ticks.window_days} ngày` : 'chỉ nến')

/** Khoảng ngày [start, end] ('YYYY-MM-DD') theo dữ liệu đang chọn của tài sản DEX. */
export function dexRange(a, tick) {
  const r = tick ? a?.ticks : a?.candles
  return r?.start_ts != null && r?.end_ts != null ? { start: msDate(r.start_ts), end: msDate(r.end_ts) } : null
}
