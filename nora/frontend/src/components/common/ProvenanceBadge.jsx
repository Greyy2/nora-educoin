import React from 'react'

// Nhãn nguồn gốc kết quả: provenance do backend gắn (backend/nautilus/engine.py provenance()). Không có provenance -> không hiện gì.
const NOT_MODELED = [
  ['slippage_modeled', 'trượt giá'],
  ['funding_modeled', 'funding'],
  ['liquidation_modeled', 'thanh lý'],
]

export const provenanceLabel = (p) => (p?.base_frame === '1m' ? 'Khớp Chuẩn (1m)' : `Khớp Nhanh (${p?.base_frame || ''})`)

export default function ProvenanceBadge({ provenance, style }) {
  if (!provenance || typeof provenance !== 'object') return null
  const off = NOT_MODELED.filter(([k]) => provenance[k] === false).map(([, v]) => v)
  const parts = [`Chế độ khớp: ${provenance.base_frame === '1m' ? 'Chuẩn (1m)' : `Nhanh (${provenance.base_frame || ''})`}`]
  if (provenance.engine) parts.push(`Engine: ${provenance.engine}${provenance.version ? ` ${provenance.version}` : ''}`)
  if (off.length) parts.push(`Chưa mô phỏng: ${off.join(', ')}`)
  return <span className="n-tag sm" style={{ marginLeft: 6, ...style }} title={parts.join(' · ')}>{provenanceLabel(provenance)}</span>
}
