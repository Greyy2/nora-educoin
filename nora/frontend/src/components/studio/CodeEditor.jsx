import React, { useEffect, useMemo, useRef } from 'react'

// Ô soạn code Python nhẹ: textarea trong suốt đặt lên lớp tô màu cú pháp; số dòng bên trái; dòng lỗi được tô đỏ.
// MỘT khung cuộn duy nhất (.se-ed) chứa số dòng (dính trái), lớp tô màu (nằm trong dòng chảy, quyết định kích thước) và textarea phủ đúng lên lớp đó (overflow: hidden,
// không tự cuộn). Trước đây textarea và lớp tô màu cuộn RIÊNG, đồng bộ bằng JS: thanh cuộn ngang/dọc của textarea (15px) làm vùng cuộn tối đa của nó lớn hơn lớp tô màu,
// nên ở cuối file chữ hiển thị lệch ~1 dòng so với con trỏ ("gõ dòng dưới nhảy lên dòng trên"). Một khung cuộn thì không thể lệch.
// Phím: Tab = thụt 4 dấu cách (Shift+Tab = bớt thụt; Esc rồi Tab để rời ô), Enter giữ thụt lề, Ctrl/⌘+Enter = chạy.

const LINE_H = 19          // phải khớp .se-gut/.se-hl/.se-ta trong strategyEditor.css
const PAD_T = 10           // padding-top của lớp tô màu và textarea
const PAD_X = 14           // padding ngang của dòng code
const GUTTER_W = 52        // bề rộng cột số dòng
const BOTTOM_COVER = 44    // chiều cao đáy bị thanh trạng thái biên dịch phủ

let CHAR_W = 0
/** Bề rộng một ký tự của font code (đo một lần bằng canvas theo đúng font của textarea). */
function charW(ta) {
  if (CHAR_W) return CHAR_W
  const ctx = document.createElement('canvas').getContext('2d')
  ctx.font = getComputedStyle(ta).font
  CHAR_W = ctx.measureText('0').width || 7.8
  return CHAR_W
}
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
  const scrollRef = useRef(null)
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

  // có lỗi mới -> cuộn tới dòng lỗi
  useEffect(() => {
    const sc = scrollRef.current
    if (sc && errorLine >= 1) sc.scrollTop = Math.max(0, (errorLine - 3) * LINE_H)
  }, [errorKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // Giữ con trỏ trong vùng nhìn thấy: textarea không tự cuộn nên khung cuộn phải làm việc đó; chừa chỗ cho thanh trạng thái biên dịch phủ ở đáy.
  const reveal = () => {
    const ta = taRef.current
    const sc = scrollRef.current
    if (!ta || !sc) return
    const before = ta.value.slice(0, ta.selectionStart)
    const row = before.split('\n').length - 1
    const col = before.length - before.lastIndexOf('\n') - 1
    const top = PAD_T + row * LINE_H
    const bottom = top + LINE_H
    const viewH = sc.clientHeight - BOTTOM_COVER
    if (top < sc.scrollTop) sc.scrollTop = top - PAD_T
    else if (bottom > sc.scrollTop + viewH) sc.scrollTop = bottom - viewH
    const x = GUTTER_W + PAD_X + col * charW(ta)
    const viewW = sc.clientWidth
    if (x < sc.scrollLeft + GUTTER_W + 8) sc.scrollLeft = Math.max(0, x - GUTTER_W - 8)
    else if (x + 8 > sc.scrollLeft + viewW) sc.scrollLeft = x + 8 - viewW
  }
  useEffect(reveal, [value]) // eslint-disable-line react-hooks/exhaustive-deps

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
    <div className="se-ed" ref={scrollRef} style={{ height }}>
      <div className="se-sheet">
        <div className="se-gut" aria-hidden="true">
          {lines.map((_, i) => <div key={i} className={`se-gn ${errorLine === i + 1 ? 'err' : ''}`}>{i + 1}</div>)}
        </div>
        <div className="se-stack">
          <div className="se-hl" aria-hidden="true">
            {rendered.map((parts, i) => (
              <div key={i} className={`se-ln ${errorLine === i + 1 ? 'err' : ''}`}>
                {parts.length ? parts.map(([cls, t], j) => (cls === 'ig' ? <span key={j} className="se-ig">{t}</span> : cls ? <span key={j} className={`tk-${cls}`}>{t}</span> : t)) : '\u200b'}
              </div>
            ))}
          </div>
          <textarea ref={taRef} className="se-ta" value={value} spellCheck={false} wrap="off" autoCapitalize="off" autoCorrect="off"
            aria-label={label} onChange={(e) => onChange(e.target.value)} onKeyDown={onKeyDown} onKeyUp={reveal} onClick={reveal}
            onScroll={(e) => { e.currentTarget.scrollTop = 0; e.currentTarget.scrollLeft = 0 }}
            onBlur={() => { escaped.current = false }} />
        </div>
      </div>
    </div>
  )
}
