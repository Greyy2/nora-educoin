import React from 'react'
import { isNum, fmtSigned, signClass } from '../../lib/format'

/** Bảng nhiệt lợi nhuận theo tháng: hàng là năm, cột T1–T12 và cả năm. Màu + dấu +/− (không chỉ màu). */
export default function HeatmapTable({ years = [] }) {
  const all = years.flatMap((y) => (y.months || []).filter(isNum))
  const max = Math.max(1, ...all.map((v) => Math.abs(v)))
  const bg = (v) => {
    const pct = Math.round(14 + (Math.min(1, Math.abs(v) / max) * 52))
    return `color-mix(in srgb, ${v >= 0 ? 'var(--n-pos)' : 'var(--n-neg)'} ${pct}%, transparent)`
  }
  return (
    <table className="n-hm">
      <thead>
        <tr>
          <th scope="col">Năm</th>
          {Array.from({ length: 12 }, (_, i) => <th key={i} scope="col">T{i + 1}</th>)}
          <th scope="col">Cả năm</th>
        </tr>
      </thead>
      <tbody>
        {years.map((y) => (
          <tr key={y.year}>
            <td className="yr">{y.year}</td>
            {Array.from({ length: 12 }, (_, i) => {
              const v = (y.months || [])[i]
              return isNum(v)
                ? <td key={i} style={{ background: bg(v) }} title={`T${i + 1}/${y.year}: ${fmtSigned(v, 1)}%`}>{fmtSigned(v, 1)}</td>
                : <td key={i} aria-label="không có dữ liệu" />
            })}
            <td className={`tot ${signClass(y.total)}`}>{fmtSigned(y.total, 1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
