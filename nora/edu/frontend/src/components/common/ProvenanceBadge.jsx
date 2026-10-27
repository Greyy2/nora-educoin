import React from 'react'

// Nhãn nguồn gốc kết quả: provenance do backend gắn (backend/nautilus/engine.py provenance()). Không có provenance -> không hiện gì.
const NOT_MODELED = [
  ['funding_modeled', 'funding'],
  ['liquidation_modeled', 'thanh lý'],
  ['quote_depth_modeled', 'depth/partial fills'],
]

export const provenanceLabel = (p) => (p?.base_frame === '1m' ? 'Khớp Chuẩn (1m)' : `Khớp Nhanh (${p?.base_frame || ''})`)

export default function ProvenanceBadge({ provenance, style }) {
  if (!provenance || typeof provenance !== 'object') return null
  const off = NOT_MODELED.filter(([k]) => provenance[k] === false).map(([, v]) => v)
  if (provenance.slippage_modeled === false) off.unshift('trượt giá')
  const parts = [`Chế độ khớp: ${provenance.base_frame === '1m' ? 'Chuẩn (1m)' : `Nhanh (${provenance.base_frame || ''})`}`]
  if (provenance.engine) parts.push(`Engine: ${provenance.engine}${provenance.version ? ` ${provenance.version}` : ''}`)
  if (off.length) parts.push(`Chưa mô phỏng: ${off.join(', ')}`)
  if (provenance.research_cost_proxy) parts.push('Spread/stop dùng proxy OHLC-open nghiên cứu, chưa đo từ fills venue')
  if (provenance.stop_slippage_proxy_multiplier) parts.push(`Proxy trượt giá stop x${provenance.stop_slippage_proxy_multiplier}`)
  return <span className="n-tag sm" style={{ marginLeft: 6, ...style }} title={parts.join(' · ')}>{provenanceLabel(provenance)}</span>
}
