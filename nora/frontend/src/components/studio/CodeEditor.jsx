import React, { useEffect, useMemo, useRef } from 'react'

// Ô soạn code Python nhẹ: textarea trong suốt đặt lên lớp tô màu cú pháp; số dòng bên trái; dòng lỗi được tô đỏ.
// Phím: Tab = thụt 4 dấu cách (Shift+Tab = bớt thụt; Esc rồi Tab để rời ô), Enter giữ thụt lề, Ctrl/⌘+Enter = chạy.

const LINE_H = 19
const KEYWORDS = new Set(['class', 'def', 'return', 'import', 'from', 'as', 'if', 'elif', 'else', 'for', 'while', 'in', 'not', 'and', 'or', 'is',
  'None', 'True', 'False', 'pass', 'lambda', 'with', 'try', 'except', 'finally', 'raise', 'yield', 'del', 'global'])

/** Tách một dòng thành các đoạn [lớp, chữ]; `open` là dấu mở chuỗi ba nháy còn dang dở từ dòng trước. Trả { parts, open }. */
function tokenizeLine(line, open) {
  const parts = []
  let i = 0
  let prevWord = ''
  const push = (cls, text) => { if (text) parts.push([cls, text]) }
  if (open) {
    const end = line.indexOf(open)
    if (end < 0) return { parts: [['str', line]], open }
    push('str', line.slice(0, end + 3))
    i = end + 3
    open = null
  }
  while (i < line.length) {
    const rest = line.slice(i)
    let m
    if (rest[0] === '#') { push('com', rest); break }
    if ((m = /^("""|''')/.exec(rest))) {
      const end = rest.indexOf(m[1], 3)
      if (end < 0) { push('str', rest); open = m[1]; break }
      push('str', rest.slice(0, end + 3)); i += end + 3; continue
    }
    if ((m = /^("(?:[^"\\]|\\.)*"?|'(?:[^'\\]|\\.)*'?)/.exec(rest))) { push('str', m[0]); i += m[0].length; continue }
    if ((m = /^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(rest))) { push('num', m[0]); i += m[0].length; continue }
    if ((m = /^[A-Za-z_]\w*/.exec(rest))) {
      const w = m[0]
      const after = rest[w.length]
      const dotBefore = line[i - 1] === '.'
      let cls = ''
      if (KEYWORDS.has(w)) cls = 'kw'
      else if (prevWord === 'class' || prevWord === 'def') cls = 'def'
      else if (w === 'self') cls = 'self'
      else if (after === '(' && (dotBefore || /^[a-z_]/.test(w))) cls = 'fn'
      push(cls, w); i += w.length; prevWord = w; continue
    }
    push('', rest[0]); i += 1
    if (!/\s/.test(rest[0])) prevWord = ''
  }
  return { parts, open }
}

const indentOf = (line) => /^ */.exec(line)[0]

/** Chèn chữ tại vị trí con trỏ nhưng giữ được lịch sử hoàn tác (Ctrl+Z) của trình duyệt. */
function insertText(ta, text) {
  if (document.execCommand && document.execCommand('insertText', false, text)) return
  ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, 'end')
  ta.dispatchEvent(new Event('input', { bubbles: true }))
}

export default function CodeEditor({ value, onChange, onRun, errorLine, errorKey, height = '100%', label = 'Code chiến lược Python' }) {
  const taRef = useRef(null)
  const hlRef = useRef(null)
  const gutRef = useRef(null)
  const escaped = useRef(false)

  const lines = useMemo(() => String(value).split('\n'), [value])
  const rendered = useMemo(() => {
    let open = null
    return lines.map((ln) => {
      const r = tokenizeLine(ln, open)
      open = r.open
      const lead = indentOf(ln).length
      const parts = r.parts
      if (lead >= 4 && parts.length >= lead && parts.slice(0, lead).every((p) => p[0] === '' && p[1] === ' ')) return [['ig', ' '.repeat(lead)], ...parts.slice(lead)]
      return parts
    })
  }, [lines])

  const sync = () => {
    const ta = taRef.current
    if (!ta) return
    if (hlRef.current) { hlRef.current.scrollTop = ta.scrollTop; hlRef.current.scrollLeft = ta.scrollLeft }
    if (gutRef.current) gutRef.current.scrollTop = ta.scrollTop
  }
  useEffect(sync, [value])

  // có lỗi mới -> cuộn tới dòng lỗi
  useEffect(() => {
    const ta = taRef.current
    if (!ta || !(errorLine >= 1)) return
    ta.scrollTop = Math.max(0, (errorLine - 3) * LINE_H)
    sync()
  }, [errorKey]) // eslint-disable-line react-hooks/exhaustive-deps

  function onKeyDown(e) {
    const ta = e.currentTarget
    const mod = e.ctrlKey || e.metaKey
    if (mod && e.key === 'Enter') { e.preventDefault(); if (onRun) onRun(); return }
    if (e.key === 'Escape') { escaped.current = true; return }
    if (e.key === 'Tab') {
      if (escaped.current) { escaped.current = false; return }
      e.preventDefault()
      const { selectionStart: a, selectionEnd: b } = ta
      const text = ta.value
      const multi = text.slice(a, b).includes('\n')
      if (!multi && !e.shiftKey) { insertText(ta, '    '); return }
      // nhiều dòng (hoặc Shift+Tab): thụt / bớt thụt từng dòng
      const from = text.lastIndexOf('\n', a - 1) + 1
      const toRaw = text.indexOf('\n', b)
      const to = toRaw < 0 ? text.length : toRaw
      const block = text.slice(from, to).split('\n')
      const next = block.map((l) => (e.shiftKey ? l.replace(/^ {1,4}/, '') : `    ${l}`)).join('\n')
      ta.setSelectionRange(from, to)
      insertText(ta, next)
      ta.setSelectionRange(from, from + next.length)
      return
    }
    if (e.key === 'Enter' && !mod && !e.shiftKey && !e.altKey) {
      const a = ta.selectionStart
      const cur = ta.value.slice(ta.value.lastIndexOf('\n', a - 1) + 1, a)
      const ind = indentOf(cur) + (/:\s*$/.test(cur) ? '    ' : '')
      e.preventDefault()
      insertText(ta, `\n${ind}`)
    }
  }

  return (
    <div className="se-ed" style={{ height }}>
      <div className="se-gut" ref={gutRef} aria-hidden="true">
        {lines.map((_, i) => <div key={i} className={`se-gn ${errorLine === i + 1 ? 'err' : ''}`}>{i + 1}</div>)}
      </div>
      <div className="se-stack">
        <div className="se-hl" ref={hlRef} aria-hidden="true">
          <div className="se-hl-in">
            {rendered.map((parts, i) => (
              <div key={i} className={`se-ln ${errorLine === i + 1 ? 'err' : ''}`}>
                {parts.length ? parts.map(([cls, t], j) => (cls === 'ig' ? <span key={j} className="se-ig">{t}</span> : cls ? <span key={j} className={`tk-${cls}`}>{t}</span> : t)) : '​'}
              </div>
            ))}
          </div>
        </div>
        <textarea ref={taRef} className="se-ta" value={value} spellCheck={false} wrap="off" autoCapitalize="off" autoCorrect="off"
          aria-label={label} onChange={(e) => onChange(e.target.value)} onScroll={sync} onKeyDown={onKeyDown}
          onBlur={() => { escaped.current = false }} />
      </div>
    </div>
  )
}
