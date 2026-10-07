import React, { useMemo, useState } from 'react'
import { Spinner } from '../ui'
import useAsync from '../../hooks/useAsync'
import { getDslReference } from '../../api'

const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd')

/** Danh sách tra cứu (Dữ liệu / Features / Operators) lấy từ GET /api/studio/strategies/dsl; có ô tìm kiếm. */
export default function Reference({ kind }) {
  const { data, loading, error, reload } = useAsync(getDslReference, [])
  const [q, setQ] = useState('')
  const rows = useMemo(() => {
    const all = (data && data[kind]) || []
    const k = norm(q.trim())
    return k ? all.filter((r) => norm(`${r.name} ${r.label_vi || ''} ${r.meaning_vi || ''} ${r.doc || ''} ${r.signature} ${r.category || ''}`).includes(k)) : all
  }, [data, kind, q])
  const total = (data && data[kind] || []).length
  return (
    <div className="se-ref">
      <div className="se-ref-q">
        <input className="n-in" type="search" aria-label="Tìm kiếm" placeholder="Tìm theo tên, tiếng Việt hoặc mô tả…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="n-note">{rows.length}/{total}</span>
      </div>
      {loading && <p className="n-note"><Spinner /> Đang tải…</p>}
      {error && <p className="n-note neg">Không tải được danh sách: {String(error)} <button type="button" className="n-btn sm" onClick={reload}>Thử lại</button></p>}
      <ul className="se-ref-l">
        {rows.map((r) => (
          <li key={r.name} className="se-ref-item" style={{ padding: '10px 0', borderBottom: '1px solid var(--n-border, rgba(255,255,255,0.08))' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', marginBottom: '4px' }}>
              <code className="se-sig" style={{ fontWeight: 600 }}>{r.signature}</code>
              {r.category && <span className="n-badge" style={{ fontSize: '11px' }}>{r.category}</span>}
              {r.returns && <span className="n-badge" style={{ fontSize: '11px' }}>{r.returns === 'bool' ? 'bool' : r.outputs > 1 ? `${r.outputs} chuỗi` : 'số'}</span>}
              {r.warmup > 0 && <span className="n-note" style={{ fontSize: '11px' }}>khởi động: {r.warmup} nến</span>}
            </div>
            {r.label_vi && <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--n-text-bright, #fff)', marginBottom: '2px' }}>{r.label_vi}</div>}
            <div className="se-ref-d" style={{ fontSize: '12px', lineHeight: 1.4 }}>{r.meaning_vi || r.doc}</div>
            {r.read_vi && <div style={{ fontSize: '11px', color: 'var(--n-text-muted, #888)', marginTop: '3px' }}><b>Cách đọc:</b> {r.read_vi}</div>}
            {r.formula && <div style={{ fontSize: '11px', color: 'var(--n-text-muted, #aaa)', marginTop: '2px', fontFamily: 'monospace' }}><b>Công thức:</b> <code>{r.formula}</code></div>}
          </li>
        ))}
      </ul>
      {!loading && !error && rows.length === 0 && <p className="n-note">Không có mục phù hợp.</p>}
    </div>
  )

}
