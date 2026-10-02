import React, { useCallback, useEffect, useId, useRef, useState } from 'react'
import { GLOSSARY } from '../lib/glossary'

/**
 * Thuật ngữ có giải thích: `<Term k="sharpe">Sharpe</Term>` (bỏ children thì dùng nhãn trong glossary).
 * Biểu tượng ⓘ là một nút focus được bằng bàn phím; hover/focus hiện giải thích một dòng, Esc để đóng.
 * Tooltip dùng position: fixed nên không bị cắt bởi bảng cuộn (overflow) hay khung panel.
 */
export default function Term({ k, children, className = '' }) {
  const g = GLOSSARY[k]
  const id = useId()
  const btn = useRef(null)
  const [pos, setPos] = useState(null)

  const show = useCallback(() => {
    const el = btn.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const w = Math.min(280, window.innerWidth - 16)
    const left = Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2))
    const below = r.bottom + 8 + 90 < window.innerHeight
    setPos({ left, width: w, ...(below ? { top: r.bottom + 6 } : { bottom: window.innerHeight - r.top + 6 }) })
  }, [])
  const hide = useCallback(() => setPos(null), [])

  useEffect(() => {
    if (!pos) return undefined
    const onKey = (e) => { if (e.key === 'Escape') setPos(null) }
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', hide, true)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('scroll', hide, true) }
  }, [pos, hide])

  if (!g) return <>{children}</>
  const text = children ?? g.label
  return (
    <span className={`n-term ${className}`} onMouseEnter={show} onMouseLeave={hide}>
      {text}
      <button ref={btn} type="button" className="n-term-i" aria-label={`Giải thích: ${g.label}`} aria-describedby={pos ? id : undefined}
        onFocus={show} onBlur={hide} onClick={(e) => { e.preventDefault(); e.stopPropagation(); pos ? hide() : show() }}>
        <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
          <circle cx="8" cy="8" r="6.4" /><path d="M8 7.2v3.6" /><circle cx="8" cy="4.9" r=".5" fill="currentColor" />
        </svg>
      </button>
      {pos && <span id={id} role="tooltip" className="n-term-tip" style={pos}><b>{g.label}</b>{g.def}</span>}
    </span>
  )
}
