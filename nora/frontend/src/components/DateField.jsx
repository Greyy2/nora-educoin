import React, { useEffect, useId, useState } from 'react'
import { isoToVn, vnToIso, datePresets } from '../lib/dates'

/** Ô ngày dạng dd/mm/yyyy (chữ, kiểm tra hợp lệ; không phụ thuộc locale trình duyệt). `value` / `onChange` là 'YYYY-MM-DD' ('' khi sai). */
export function DateInput({ id, value, onChange, label, min, max, invalidMsg = 'Ngày không hợp lệ (dd/mm/yyyy)' }) {
  const [text, setText] = useState(isoToVn(value))
  const [bad, setBad] = useState(false)
  const errId = useId()
  const clamp = (iso) => (min && iso < min ? min : max && iso > max ? max : iso) // min / max tuỳ chọn ('YYYY-MM-DD'): kẹp ngày vào khoảng

  // giá trị đổi từ ngoài (chọn nhanh, đồng bộ theo job) -> cập nhật chữ, trừ khi chữ đang nhập vẫn mang cùng giá trị
  useEffect(() => {
    if (value && vnToIso(text) !== value) { setText(isoToVn(value)); setBad(false) }
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps

  function type(raw) {
    // tự thêm dấu "/" khi gõ liền chữ số: 01022026 -> 01/02/2026
    let t = raw.replace(/[^\d/.\-]/g, '')
    if (/^\d{8}$/.test(t)) t = `${t.slice(0, 2)}/${t.slice(2, 4)}/${t.slice(4)}`
    setText(t)
    const iso = vnToIso(t)
    if (iso) { setBad(false); onChange(clamp(iso)) } else { onChange('') }
  }
  function commit() {
    if (!text.trim()) { setBad(true); return }
    const iso = vnToIso(text)
    setBad(!iso)
    if (iso) { setText(isoToVn(clamp(iso))); onChange(clamp(iso)) }
  }
  return (
    <>
      <input id={id} type="text" inputMode="numeric" autoComplete="off" placeholder="dd/mm/yyyy" maxLength={10} className="n-in"
        value={text} aria-label={label} aria-invalid={bad || undefined} aria-describedby={bad ? errId : undefined}
        style={bad ? { borderColor: 'var(--n-neg)' } : undefined}
        onChange={(e) => type(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit() }} />
      {bad && <span id={errId} className="n-field-err" role="alert">{invalidMsg}</span>}
    </>
  )
}

/** Hàng chọn nhanh khoảng ngày theo `windows`: dev1, dev2, Holdout, Toàn bộ, 90 ngày gần nhất. */
export function DatePresets({ windows, start, end, onPick }) {
  const presets = datePresets(windows)
  if (!presets.length) return null
  return (
    <div className="n-presets" role="group" aria-label="Chọn nhanh khoảng ngày">
      <span className="n-lbl">Chọn nhanh</span>
      {presets.map((p) => {
        const on = p.start === start && p.end === end
        return (
          <button key={p.key} type="button" className={`n-chip-btn ${on ? 'on' : ''}`} aria-pressed={on}
            title={`${isoToVn(p.start)} → ${isoToVn(p.end)}`} onClick={() => onPick(p.start, p.end)}>{p.label}</button>
        )
      })}
    </div>
  )
}
