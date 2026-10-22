import { useEffect, useState } from 'react'
import { isNum } from '../../lib/format'

export const PAD = { l: 58, r: 14, t: 12, b: 26 }

// Đo bề rộng phần tử (ResizeObserver) để SVG vẽ đúng pixel, không co giãn chữ.
export function useWidth(ref) {
  const [w, setW] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    setW(Math.floor(el.getBoundingClientRect().width))
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver((es) => {
      for (const e of es) setW(Math.floor(e.contentRect.width))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return w
}

// Thang "đẹp": trả về min/max/step và danh sách tick.
export function niceScale(lo, hi, target = 5) {
  if (!isNum(lo) || !isNum(hi)) return { min: 0, max: 1, step: 0.25, ticks: [0, 0.25, 0.5, 0.75, 1] }
  if (hi === lo) { const d = Math.abs(hi) * 0.05 || 1; lo -= d; hi += d }
  const raw = (hi - lo) / Math.max(1, target)
  const mag = 10 ** Math.floor(Math.log10(raw))
  const norm = raw / mag
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag
  const min = Math.floor(lo / step) * step
  const max = Math.ceil(hi / step) * step
  const ticks = []
  for (let v = min; v <= max + step * 1e-6; v += step) ticks.push(Math.abs(v) < step * 1e-9 ? 0 : +v.toPrecision(12))
  return { min, max, step, ticks }
}

// Chọn các chỉ số nhãn trục x cách đều, không chồng nhau.
export function xTicks(n, plotW, minGap = 70) {
  if (n <= 1) return [0]
  const maxLabels = Math.max(2, Math.floor(plotW / minGap))
  const every = Math.max(1, Math.ceil((n - 1) / (maxLabels - 1)))
  const out = []
  for (let i = 0; i < n; i += every) out.push(i)
  return out
}

// Đường gấp khúc, ngắt tại giá trị null.
export function linePath(xs, ys) {
  let d = ''
  let pen = false
  for (let i = 0; i < xs.length; i++) {
    if (!isNum(ys[i])) { pen = false; continue }
    d += `${pen ? 'L' : 'M'}${xs[i].toFixed(1)},${ys[i].toFixed(1)}`
    pen = true
  }
  return d
}

export function areaPath(xs, ys, baseY) {
  const idx = ys.map((y, i) => (isNum(y) ? i : -1)).filter((i) => i >= 0)
  if (!idx.length) return ''
  let d = `M${xs[idx[0]].toFixed(1)},${baseY.toFixed(1)}`
  idx.forEach((i) => { d += `L${xs[i].toFixed(1)},${ys[i].toFixed(1)}` })
  d += `L${xs[idx[idx.length - 1]].toFixed(1)},${baseY.toFixed(1)}Z`
  return d
}

// Cột có đầu tròn 4px ở phía dữ liệu, phẳng ở đường gốc.
export function barPath(x, w, yBase, yVal, r = 4) {
  const top = Math.min(yBase, yVal)
  const h = Math.abs(yVal - yBase)
  if (h < 0.5) return `M${x},${yBase - 0.5}h${w}v1h${-w}Z`
  const rr = Math.min(r, w / 2, h)
  if (w < 5) return `M${x},${top}h${w}v${h}h${-w}Z`
  if (yVal <= yBase) { // cột dương: tròn phía trên
    return `M${x},${yBase}V${top + rr}Q${x},${top} ${x + rr},${top}H${x + w - rr}Q${x + w},${top} ${x + w},${top + rr}V${yBase}Z`
  }
  return `M${x},${yBase}V${top + h - rr}Q${x},${top + h} ${x + rr},${top + h}H${x + w - rr}Q${x + w},${top + h} ${x + w},${top + h - rr}V${yBase}Z`
}

export function tipPos(x, w, tipW = 190) {
  return x > w - tipW - 12 ? { right: w - x + 12 } : { left: x + 12 }
}
