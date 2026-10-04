// Rút gọn `param_survival`: với mỗi chiến lược chọn vài tham số làm đổi tỉ lệ qua tầng nhiều nhất và khoảng giá trị tốt nhất.
import { fmtParam, fmtParamFull } from '../../lib/params'

const isNumeric = (v) => (typeof v === 'number' && Number.isFinite(v)) || (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v)))
const rate = (b) => (b.input > 0 ? (b.passed / b.input) * 100 : 0)

/** Giá trị số được gộp thành tối đa 4 khoảng có số alpha xấp xỉ nhau; giá trị phân loại giữ nguyên. */
function toBuckets(param, values) {
  const vs = values.map((v) => ({ value: v.value, input: v.input || 0, passed: v.passed || 0 }))
  if (!vs.length) return []
  let groups
  if (vs.every((v) => isNumeric(v.value)) && vs.length > 4) {
    vs.sort((a, b) => Number(a.value) - Number(b.value))
    const total = vs.reduce((s, v) => s + v.input, 0)
    groups = [[]]
    let acc = 0
    vs.forEach((v) => {
      const cur = groups[groups.length - 1]
      if (cur.length && groups.length < 4 && acc >= (total * groups.length) / 4) groups.push([])
      groups[groups.length - 1].push(v)
      acc += v.input
    })
  } else {
    if (vs.every((v) => isNumeric(v.value))) vs.sort((a, b) => Number(a.value) - Number(b.value))
    groups = vs.map((v) => [v])
  }
  return groups.map((g) => {
    const lo = g[0].value
    const hi = g[g.length - 1].value
    return {
      input: g.reduce((s, v) => s + v.input, 0), passed: g.reduce((s, v) => s + v.passed, 0),
      label: g.length === 1 ? fmtParamFull(param, lo) : `${fmtParam(param, lo)} – ${fmtParamFull(param, hi)}`,
    }
  })
}

/** -> [{ strategy, input, passed, rate, rows: [{ param, spread, best, worst }] }] (rows đã sắp theo độ chênh giảm dần, tối đa `top`). */
export function summarizeParams(paramSurvival, { top = 3, minSpread = 5 } = {}) {
  const by = new Map()
  paramSurvival.forEach((p) => { if (!by.has(p.strategy)) by.set(p.strategy, []); by.get(p.strategy).push(p) })
  return [...by.entries()].map(([strategy, params]) => {
    const rows = params.map((p) => {
      const total = p.values.reduce((s, v) => s + (v.input || 0), 0)
      const bs = toBuckets(p.param, p.values).filter((b) => b.input >= Math.max(10, total * 0.05)) // bỏ khoảng quá ít alpha (nhiễu)
      if (bs.length < 2) return null
      const sorted = [...bs].sort((a, b) => rate(b) - rate(a))
      const best = sorted[0]
      const worst = sorted[sorted.length - 1]
      return { param: p.param, spread: rate(best) - rate(worst), best: { ...best, rate: rate(best) }, worst: { ...worst, rate: rate(worst) } }
    }).filter(Boolean).filter((r) => r.spread >= minSpread).sort((a, b) => b.spread - a.spread).slice(0, top)
    const first = params[0]
    const input = first ? first.values.reduce((s, v) => s + (v.input || 0), 0) : 0
    const passed = first ? first.values.reduce((s, v) => s + (v.passed || 0), 0) : 0
    return { strategy, input, passed, rate: input > 0 ? (passed / input) * 100 : null, rows }
  })
}
