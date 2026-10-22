// Cách khớp lệnh cắt lỗ trong backtest: `level` = đúng mức đặt (lạc quan), `extreme` = giá xấu nhất của nến (bi quan).
export const STOP_FILL = {
  level: { name: 'Đúng mức', tone: 'lạc quan', text: 'Đúng mức (lạc quan)' },
  extreme: { name: 'Giá xấu nhất của nến', tone: 'bi quan', text: 'Giá xấu nhất của nến (bi quan)' },
}
export const stopFillText = (k) => STOP_FILL[k]?.text || String(k)
export const stopFillOptions = [{ value: 'level', label: STOP_FILL.level.text }, { value: 'extreme', label: STOP_FILL.extreme.text }]

/** Đổi "(extreme)" / "(level)" trong nhãn do backend trả về sang cách gọi dễ hiểu. */
export function fillWording(s) {
  if (typeof s !== 'string') return s
  return s.replace(/\(extreme\)/gi, `· ${STOP_FILL.extreme.text}`).replace(/\(level\)/gi, `· ${STOP_FILL.level.text}`)
}
