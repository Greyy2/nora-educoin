import React, { useMemo } from 'react'

/**
 * Danh sách chiến lược chỉ gồm tên, huy hiệu chiều lệnh và mô tả ngắn, nhóm theo họ.
 * Mặc định chọn một (radio); multi=true cho phép chọn nhiều (danh mục). sel = { [id]: params }.
 */
export default function StrategyChoice({ strategies, sel, multi = false, onPick, label = 'Chiến lược' }) {
  const families = useMemo(() => {
    const m = new Map()
    strategies.forEach((c) => { const f = c.family || 'Khác'; if (!m.has(f)) m.set(f, []); m.get(f).push(c) })
    return [...m.entries()]
  }, [strategies])
  return (
    <div className="n-sc-list" role={multi ? 'group' : 'radiogroup'} aria-label={label}>
      {families.map(([fam, items]) => (
        <div className="n-fam" key={fam}>
          <h4>{fam}</h4>
          <div className="n-sc-grid">
            {items.map((c) => {
              const on = !!sel[c.id]
              return (
                <label key={c.id} className={`n-sc-card ${on ? 'on' : ''}`} title={c.description}>
                  <input type={multi ? 'checkbox' : 'radio'} name="bt-strategy" checked={on} onChange={() => onPick(c)} />
                  <span className="n-sc-body">
                    <span className="n-sc-top">
                      <span className="id">{c.id}</span>
                      <span className={`n-badge ${String(c.side).toLowerCase()}`}>{c.side}</span>
                    </span>
                    <span className="ds">{c.description}</span>
                  </span>
                </label>
              )
            })}
          </div>
        </div>
      ))}
      {!strategies.length && <p className="n-note">Chưa có danh sách chiến lược.</p>}
    </div>
  )
}
