import React, { useMemo, useState } from 'react'
import SavedAlphaList from './SavedAlphaList'

/** Tab "Mẫu" dùng chung /alpha/create và /education: danh sách mẫu (GET /api/studio/education/samples), lọc nhóm / độ khó / từ khoá, bấm để mở vào tab file mới; kèm mục "Đã lưu". */
export default function SamplesPane({ samples, onUse, saved, onOpenSaved, openingId, activeId }) {
  const [cat, setCat] = useState('')
  const [diff, setDiff] = useState('')
  const [q, setQ] = useState('')
  const cats = useMemo(() => Array.from(new Set(samples.map((s) => s.category).filter(Boolean))), [samples])
  const diffs = useMemo(() => Array.from(new Set(samples.map((s) => s.difficulty).filter(Boolean))), [samples])
  const list = useMemo(() => {
    const k = q.trim().toLowerCase()
    return samples.filter((s) => (!cat || s.category === cat) && (!diff || s.difficulty === diff)
      && (!k || `${s.name} ${s.summary || s.note || ''} ${s.category || ''}`.toLowerCase().includes(k)))
  }, [samples, cat, diff, q])
  const chips = (items, cur, setCur, all) => (
    <div className="se-filter">
      <button type="button" className={`n-btn xs ${!cur ? 'primary' : ''}`} onClick={() => setCur('')}>{all}</button>
      {items.map((c) => <button key={c} type="button" className={`n-btn xs ${cur === c ? 'primary' : ''}`} onClick={() => setCur(c)}>{c}</button>)}
    </div>
  )
  return (
    <div className="se-samples">
      <h3 className="se-h3">Mẫu chiến lược ({list.length}/{samples.length})</h3>
      <input type="text" className="n-input se-sq" aria-label="Tìm mẫu" placeholder="Tìm mẫu (Keltner, RSI, Z-Score, ATR…)" value={q} onChange={(e) => setQ(e.target.value)} />
      {cats.length > 0 && chips(cats, cat, setCat, 'Tất cả nhóm')}
      {diffs.length > 0 && chips(diffs, diff, setDiff, 'Mọi độ khó')}
      <div className="se-cards">
        {list.map((s) => (
          <button key={s.key || s.name} type="button" className="n-card-sel" onClick={() => onUse(s.name, s.code)}>
            <div className="se-card-h"><b>{s.name}</b>{s.difficulty && <span className="n-chip">{s.difficulty}</span>}</div>
            {s.category && <div className="se-card-c">{s.category}</div>}
            <span className="n-note">{s.summary || s.note}</span>
          </button>
        ))}
      </div>
      {!list.length && <p className="n-note">Không có mẫu phù hợp bộ lọc.</p>}
      <SavedAlphaList list={saved} onOpen={onOpenSaved} openingId={openingId} activeId={activeId} />
    </div>
  )
}
