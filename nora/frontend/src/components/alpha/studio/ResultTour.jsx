import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

/**
 * Hướng dẫn từng bước kết quả (chỉ /education): bôi sáng lần lượt từng mục chính của CustomResult, popover hiện lời giải thích
 * do backend sinh (result.explain.notes). Component chỉ vẽ; danh sách bước và việc chuyển tab do CustomResult quyết định.
 * step = { id, sel (CSS selector của mục), title, body: [{ label?, text }] }.
 */
const PAD = 8
const POP_W = 380

function useRect(sel, nonce) {
  const [rect, setRect] = useState(null)
  const last = useRef('')
  useEffect(() => {
    let raf = 0
    let tries = 0
    let scrolled = false
    setRect(null); last.current = ''
    const tick = () => {
      const el = sel ? document.querySelector(sel) : null
      if (el) {
        if (!scrolled) { scrolled = true; el.scrollIntoView({ block: 'center', behavior: 'instant' in document.documentElement.style ? 'instant' : 'auto' }) }
        const r = el.getBoundingClientRect()
        const key = [r.left, r.top, r.width, r.height].map(Math.round).join()
        if (key !== last.current) { last.current = key; setRect({ left: r.left, top: r.top, width: r.width, height: r.height }) }
      } else if (++tries > 40 && last.current !== 'none') { last.current = 'none'; setRect(null) }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [sel, nonce])
  return rect
}

export default function ResultTour({ steps, index, onIndex, onClose }) {
  const step = steps[index]
  const rect = useRect(step?.sel, step?.id)
  const popRef = useRef(null)
  const [pos, setPos] = useState({ left: 0, top: 0 })
  const last = index === steps.length - 1

  const next = useCallback(() => { if (index < steps.length - 1) onIndex(index + 1); else onClose(true) }, [index, steps.length, onIndex, onClose])
  const prev = useCallback(() => { if (index > 0) onIndex(index - 1) }, [index, onIndex])

  useEffect(() => {
    const key = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onClose(false); return }
      const t = e.target
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.closest?.('.cm-editor'))) return
      if (e.key === 'ArrowRight') { e.preventDefault(); next() } else if (e.key === 'ArrowLeft') { e.preventDefault(); prev() }
    }
    window.addEventListener('keydown', key, true)
    return () => window.removeEventListener('keydown', key, true)
  }, [next, prev, onClose])

  useLayoutEffect(() => {
    const pop = popRef.current
    if (!pop) return
    const vw = window.innerWidth
    const vh = window.innerHeight
    const h = pop.offsetHeight
    const w = Math.min(POP_W, vw - 24)
    if (!rect) { setPos({ left: (vw - w) / 2, top: Math.max(12, (vh - h) / 2) }); return }
    const below = vh - (rect.top + rect.height) - PAD
    const above = rect.top - PAD
    let top
    if (below >= h + 12) top = rect.top + rect.height + PAD + 8
    else if (above >= h + 12) top = rect.top - PAD - 8 - h
    else top = Math.min(vh - h - 12, Math.max(12, vh - h - 24)) // mục quá cao: popover nằm đáy màn hình, đè lên mép mục
    const left = Math.min(vw - w - 12, Math.max(12, rect.left + Math.min(rect.width, 600) / 2 - w / 2))
    setPos({ left, top })
  }, [rect, index, step])

  if (!step) return null
  const sp = rect ? { left: rect.left - PAD, top: rect.top - PAD, width: rect.width + 2 * PAD, height: rect.height + 2 * PAD } : null
  return createPortal(
    <div className="rt-root" role="dialog" aria-modal="false" aria-label="Hướng dẫn đọc kết quả">
      {sp ? <div className="rt-spot" style={sp} /> : <div className="rt-dim" />}
      <div ref={popRef} className="rt-pop" style={{ left: pos.left, top: pos.top, width: Math.min(POP_W, window.innerWidth - 24) }}>
        <div className="rt-hd"><span className="rt-step">Bước {index + 1}/{steps.length}</span><span className="rt-title">{step.title}</span></div>
        <div className="rt-body">
          {step.body.map((b, i) => <p key={i}>{b.label && <b>{b.label}: </b>}{b.text}</p>)}
        </div>
        <div className="rt-dots" aria-hidden="true">{steps.map((s, i) => <i key={s.id} className={i === index ? 'on' : i < index ? 'done' : ''} />)}</div>
        <div className="rt-ft">
          <button type="button" className="n-btn sm ghost" onClick={() => onClose(false)} title="Esc">Bỏ qua</button>
          <span className="rt-sp" />
          <button type="button" className="n-btn sm" onClick={prev} disabled={index === 0} title="←">Trước</button>
          <button type="button" className="n-btn sm primary" onClick={next} title="→" autoFocus>{last ? 'Xong' : 'Tiếp'}</button>
        </div>
      </div>
    </div>,
    document.querySelector('.v2') || document.body, // biến --n-* chỉ có trong .v2
  )
}
