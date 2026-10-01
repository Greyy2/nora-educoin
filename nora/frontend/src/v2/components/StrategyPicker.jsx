import React, { useMemo } from 'react'
import { paramHeader, fmtParam } from '../lib/params'

const same = (a, b) => Number(a) === Number(b)

export function ParamEditor({ item, value, onChange }) {
  const space = item.space || {}
  const keys = Object.keys(space)
  return (
    <div className="n-params">
      {keys.map((k) => {
        const opts = [...space[k]]
        const cur = value?.[k]
        if (cur != null && !opts.some((o) => same(o, cur))) opts.push(cur)
        opts.sort((a, b) => a - b)
        const id = `p-${item.id}-${k}`
        return (
          <div className="n-field" key={k}>
            <label htmlFor={id} title={k}>{paramHeader(k)}</label>
            <select id={id} className="n-sel" title={k} value={cur ?? ''} onChange={(e) => onChange({ ...value, [k]: Number(e.target.value) })}>
              {opts.map((o) => <option key={o} value={o}>{fmtParam(k, o)}</option>)}
            </select>
          </div>
        )
      })}
    </div>
  )
}

/** Danh sách chiến lược theo họ, tick để chọn, mở trình sửa tham số khi được chọn. sel = { [id]: params } */
export default function StrategyPicker({ catalog = [], sel, setSel }) {
  const families = useMemo(() => {
    const m = new Map()
    catalog.forEach((c) => { const f = c.family || 'Khác'; if (!m.has(f)) m.set(f, []); m.get(f).push(c) })
    return [...m.entries()]
  }, [catalog])
  const toggle = (c) => {
    const next = { ...sel }
    if (next[c.id]) delete next[c.id]
    else next[c.id] = { ...(c.default_params || {}) }
    setSel(next)
  }
  return (
    <div>
      {families.map(([fam, items]) => (
        <div className="n-fam" key={fam}>
          <h4>{fam}</h4>
          {items.map((c) => {
            const on = !!sel[c.id]
            return (
              <div className={`n-strat ${on ? 'on' : ''}`} key={c.id}>
                <div className="n-strat-h">
                  <input type="checkbox" id={`s-${c.id}`} checked={on} onChange={() => toggle(c)} />
                  <label htmlFor={`s-${c.id}`} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', cursor: 'pointer' }}>
                    <span className="id">{c.id}</span>
                    <span className={`n-badge ${String(c.side).toLowerCase()}`}>{c.side}</span>
                    <span className="ds">{c.description}</span>
                  </label>
                </div>
                {on && <ParamEditor item={c} value={sel[c.id]} onChange={(p) => setSel({ ...sel, [c.id]: p })} />}
              </div>
            )
          })}
        </div>
      ))}
      {!catalog.length && <p className="n-note">Chưa có danh mục chiến lược.</p>}
    </div>
  )
}
