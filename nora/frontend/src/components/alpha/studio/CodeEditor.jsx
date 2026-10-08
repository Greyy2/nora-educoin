import React, { forwardRef, useEffect, useImperativeHandle, useRef } from 'react'
import { Annotation, Compartment, EditorState, StateEffect, StateField } from '@codemirror/state'
import { Decoration, EditorView, drawSelection, highlightActiveLine, highlightActiveLineGutter, hoverTooltip, keymap, lineNumbers, showTooltip } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { bracketMatching, HighlightStyle, indentOnInput, indentUnit, syntaxHighlighting } from '@codemirror/language'
import { python } from '@codemirror/lang-python'
import { autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap, snippet } from '@codemirror/autocomplete'
import { linter, lintGutter, lintKeymap } from '@codemirror/lint'
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search'
import { tags as t } from '@lezer/highlight'
import { postAssistCheck, postAssistComplete, postAssistHover } from '../../../api'
import { completionType, localComplete, loadAssistCatalog, mdToDom, openCall, peekAssistCatalog, posAt } from '../../../lib/assist'

// Trình soạn code Python dựa trên CodeMirror 6: gõ nhiều dòng là chức năng gốc của CM (không còn lớp tô màu tách rời khỏi textarea nên không thể lệch dòng).
// Trợ lý fintech (tất định, không AI) lấy từ API /api/studio/strategies/assist/*: gợi ý theo ngữ cảnh, hover, chữ ký, kiểm lỗi (trễ 400 ms) kèm sửa nhanh.
// Máy chủ chưa có API trợ lý -> vẫn soạn bình thường (tô màu, thụt lề, tìm kiếm), chỉ không có gợi ý / kiểm lỗi.
// API giữ nguyên: value / onChange / onRun / errorLine / errorKey / height / label; thêm: readOnly, assist (mặc định bật), onAssist(state), ref.goTo(line, col).
// Phím: Tab = thụt, Shift+Tab = bớt thụt (Esc rồi Tab để rời ô), Ctrl/⌘+Enter = chạy, Ctrl+Space = gợi ý, Ctrl+F = tìm.

const HL = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.definitionKeyword, t.moduleKeyword, t.operatorKeyword], color: 'var(--n-accent)' },
  { tag: [t.string, t.special(t.string)], color: 'var(--n-pos)' },
  { tag: [t.number, t.bool, t.null, t.atom], color: 'var(--n-info)' },
  // chú thích kiểu VS Code (kể cả dòng `# ▸` tự sinh ở /education): xanh lục dịu, không nghiêng, đủ tương phản ở cả nền sáng và tối
  { tag: [t.comment, t.lineComment], color: 'color-mix(in srgb, var(--n-pos) 78%, var(--n-ink-2))' },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: 'var(--n-teal)' },
  { tag: [t.definition(t.variableName), t.className, t.definition(t.propertyName)], color: 'var(--n-warn)' },
  { tag: t.self, color: 'var(--n-ink-2)', fontStyle: 'italic' },
])

const THEME = EditorView.theme({
  '&': { height: '100%', color: 'var(--n-ink)', backgroundColor: 'var(--n-surface-2)', fontSize: '13px' },
  '&.cm-focused': { outline: '2px solid var(--n-accent)', outlineOffset: '-2px' },
  '.cm-scroller': { fontFamily: 'var(--n-mono)', lineHeight: '19px', overflow: 'auto' },
  '.cm-content': { caretColor: 'var(--n-ink)', padding: '10px 0 56px', fontVariantLigatures: 'none' },
  '.cm-line': { padding: '0 14px' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--n-ink)' },
  '.cm-gutters': { backgroundColor: 'var(--n-surface-3)', color: 'var(--n-ink-3)', border: 0, borderRight: '1px solid var(--n-line)' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 10px 0 8px', minWidth: '32px' },
  '.cm-activeLine': { backgroundColor: 'transparent', boxShadow: 'inset 0 0 0 9999px color-mix(in srgb, var(--n-ink) 4%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--n-ink)' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': { backgroundColor: 'var(--n-accent-wash)' },
  '.cm-matchingBracket': { backgroundColor: 'var(--n-accent-wash)', outline: '1px solid var(--n-line)' },
  '.cm-se-errline': { backgroundColor: 'var(--n-neg-wash)', boxShadow: 'inset 3px 0 var(--n-neg)' },
  '.cm-tooltip': { backgroundColor: 'var(--n-surface)', color: 'var(--n-ink)', border: '1px solid var(--n-line)', borderRadius: '8px', boxShadow: '0 8px 24px rgba(0,0,0,.28)', fontFamily: 'var(--n-sans)' },
  '.cm-tooltip-autocomplete > ul': { fontFamily: 'var(--n-mono)', fontSize: '12.5px', maxHeight: '260px' },
  '.cm-tooltip-autocomplete ul li[aria-selected]': { backgroundColor: 'var(--n-accent-wash)', color: 'var(--n-ink)' },
  '.cm-completionDetail': { color: 'var(--n-ink-3)', marginLeft: '10px', fontStyle: 'normal' },
  '.cm-completionMatchedText': { color: 'var(--n-accent)', textDecoration: 'none', fontWeight: 600 },
  '.cm-completionInfo': { maxWidth: '380px', padding: '8px 10px' },
  '.cm-diagnostic': { fontFamily: 'var(--n-sans)', fontSize: '12.5px' },
  '.cm-panels': { backgroundColor: 'var(--n-surface)', color: 'var(--n-ink)', borderTop: '1px solid var(--n-line)' },
  '.cm-searchMatch': { backgroundColor: 'var(--n-accent-wash)' },
})

const External = Annotation.define()

const setErrLine = StateEffect.define()
const errLineField = StateField.define({
  create: () => Decoration.none,
  update(v, tr) {
    v = v.map(tr.changes)
    for (const e of tr.effects) {
      if (e.is(setErrLine)) {
        const n = e.value
        v = n >= 1 && n <= tr.state.doc.lines ? Decoration.set([Decoration.line({ class: 'cm-se-errline' }).range(tr.state.doc.line(n).from)]) : Decoration.none
      }
    }
    return v
  },
  provide: (f) => EditorView.decorations.from(f),
})

/** Chữ ký đang gõ: khi con trỏ ở trong self.feat.xxx( … ) hoặc self.op.xxx( … ) hiện chữ ký với đối số hiện tại in đậm + khoảng hợp lệ. */
function sigTooltips(state) {
  const cat = peekAssistCatalog()
  if (!cat) return []
  const pos = state.selection.main.head
  const ln = state.doc.lineAt(pos)
  const from = Math.max(0, pos - 600)
  const call = openCall(state.doc.sliceString(from, pos))
  if (!call) return []
  const spec = (call.kind === 'op' ? cat.ops : cat.features)?.find((f) => f.name === call.name)
  if (!spec || !spec.args) return []
  const active = call.argName ? spec.args.findIndex((a) => a.name === call.argName) : call.argIndex
  return [{
    pos: ln.from + Math.max(0, pos - ln.from),
    above: true,
    strictSide: false,
    create() {
      const dom = document.createElement('div')
      dom.className = 'se-sig'
      const head = document.createElement('div')
      head.className = 'se-sig-h'
      head.appendChild(document.createTextNode(`${call.kind === 'op' ? 'self.op' : 'self.feat'}.${spec.name}(`))
      spec.args.forEach((a, i) => {
        if (i) head.appendChild(document.createTextNode(', '))
        const s = document.createElement('span')
        s.textContent = a.required === false && a.default != null ? `${a.name}=${a.default}` : a.name
        if (i === active) s.className = 'on'
        head.appendChild(s)
      })
      head.appendChild(document.createTextNode(')'))
      dom.appendChild(head)
      const a = spec.args[active]
      if (a) {
        const d = document.createElement('div')
        d.className = 'se-sig-d'
        const range = a.lo != null || a.hi != null ? ` · khoảng [${a.lo ?? '−∞'}, ${a.hi ?? '+∞'}]` : ''
        d.textContent = `${a.name}: ${a.type}${a.required ? ' (bắt buộc)' : ''}${range}`
        dom.appendChild(d)
      }
      return { dom }
    },
  }]
}
const sigField = StateField.define({
  create: (s) => sigTooltips(s),
  update: (v, tr) => (tr.docChanged || tr.selection || tr.effects.length ? sigTooltips(tr.state) : v),
  provide: (f) => showTooltip.computeN([f], (s) => s.field(f)),
})

const CodeEditor = forwardRef(function CodeEditor({ value, onChange, onRun, errorLine, errorKey, height = '100%', label = 'Code chiến lược Python', readOnly = false, assist = true, onAssist }, ref) {
  const host = useRef(null)
  const view = useRef(null)
  const cb = useRef({})
  cb.current = { onChange, onRun, onAssist, assist }
  const lastCheck = useRef({ code: null, res: null })
  const roComp = useRef(new Compartment())

  useImperativeHandle(ref, () => ({
    goTo(line, col = 1) {
      const v = view.current
      if (!v) return
      const pos = posAt(v.state.doc, line, col)
      v.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) })
      v.focus()
    },
    focus() { view.current?.focus() },
  }), [])

  useEffect(() => {
    const emit = (s) => { if (cb.current.onAssist) cb.current.onAssist(s) }

    async function completeSource(ctx) {
      if (!cb.current.assist) return null
      const { state, pos } = ctx
      const ln = state.doc.lineAt(pos)
      const tok = ctx.matchBefore(/[\w.]*/)
      // Chỉ gợi ý khi đang gõ chữ / sau dấu chấm / gọi tay (Ctrl+Space) / sau dấu mở chuỗi hoặc ngoặc
      const prev = state.sliceDoc(Math.max(ln.from, pos - 1), pos)
      if (!ctx.explicit && !(tok && tok.text) && !/["'(,=]/.test(prev)) return null
      const code = state.doc.toString()
      let res = null
      try { res = await postAssistComplete(code, ln.number, pos - ln.from + 1) } catch (e) { res = null }
      if (ctx.aborted) return null
      let items = res && Array.isArray(res.items) ? res.items : null
      let from = pos
      let to = pos
      if (items && res.range) { from = posAt(state.doc, res.range.line, res.range.col); to = posAt(state.doc, res.range.end_line ?? res.range.line, res.range.end_col ?? res.range.col) }
      else if (items) { const w = ctx.matchBefore(/\w*/); from = w ? w.from : pos }
      if (!items) {
        await loadAssistCatalog()
        const loc = localComplete(peekAssistCatalog(), state.sliceDoc(ln.from, pos))
        if (!loc) return null
        items = loc.items
        from = pos - loc.word.length
      }
      if (!items.length) return null
      const options = items.map((it, i) => ({
        label: it.label,
        detail: it.detail ? ` ${it.detail.length > 46 ? `${it.detail.slice(0, 45)}…` : it.detail}` : undefined,
        type: completionType(it.kind),
        boost: 99 - i,
        info: it.doc_md ? () => mdToDom(it.doc_md) : undefined,
        apply: it.is_snippet || /\$\{/.test(it.insert || '') ? snippet(it.insert) : (it.insert || it.label),
      }))
      return { from, to: Math.max(to, pos), options, filter: false }
    }

    async function lintSource(v) {
      if (!cb.current.assist) return []
      const code = v.state.doc.toString()
      if (!code.trim()) { emit({ status: 'idle' }); return [] }
      let res
      if (lastCheck.current.code === code && lastCheck.current.res) res = lastCheck.current.res
      else {
        emit({ status: 'checking' })
        try { res = await postAssistCheck(code) } catch (e) { emit({ status: 'unavailable', error: e.message }); return [] }
        lastCheck.current = { code, res }
      }
      if (v.state.doc.toString() !== code) return []
      emit({ status: 'done', ...res })
      const doc = v.state.doc
      return (res.diagnostics || []).map((d) => {
        let from = posAt(doc, d.line, d.col)
        let to = d.end_line ? posAt(doc, d.end_line, d.end_col) : from
        if (to <= from) { to = Math.min(doc.length, from + 1); if (to === from) from = Math.max(0, from - 1) }
        const sug = Array.isArray(d.suggest) ? d.suggest.filter((x) => typeof x === 'string' && x) : []
        return {
          from, to, severity: d.severity === 'info' ? 'info' : d.severity === 'warning' ? 'warning' : 'error',
          source: d.code, message: d.message_vi || d.code || 'Lỗi',
          actions: sug.slice(0, 4).map((s) => ({
            name: `Sửa thành “${s}”`,
            apply(view2, f, tt) {
              const txt = view2.state.sliceDoc(f, tt)
              let a = f; let b = tt; let ins = s
              const q = /^(["'])(.*)\1$/.exec(txt)
              if (q) { a = f + 1; b = tt - 1 } else if (!/[.(\s]/.test(s)) { const m = /[A-Za-z_]\w*$/.exec(txt); if (m) a = tt - m[0].length }
              view2.dispatch({ changes: { from: a, to: b, insert: ins } })
            },
          })),
        }
      })
    }

    const hover = hoverTooltip(async (v, pos) => {
      if (!cb.current.assist) return null
      const ln = v.state.doc.lineAt(pos)
      let res
      try { res = await postAssistHover(v.state.doc.toString(), ln.number, pos - ln.from + 1) } catch (e) { return null }
      if (!res || !res.md) return null
      const from = res.range ? posAt(v.state.doc, res.range.line, res.range.col) : pos
      const to = res.range ? posAt(v.state.doc, res.range.end_line ?? res.range.line, res.range.end_col ?? res.range.col) : pos
      return { pos: from, end: Math.max(to, from), above: true, create: () => ({ dom: mdToDom(res.md) }) }
    }, { hoverTime: 350 })

    const state = EditorState.create({
      doc: String(value ?? ''),
      extensions: [
        lineNumbers(), highlightActiveLineGutter(), history(), drawSelection(), indentOnInput(), bracketMatching(), closeBrackets(), highlightActiveLine(),
        highlightSelectionMatches(), python(), syntaxHighlighting(HL), THEME, EditorState.tabSize.of(4), indentUnit.of('    '),
        EditorView.contentAttributes.of({ 'aria-label': label, spellcheck: 'false', autocapitalize: 'off', autocorrect: 'off' }),
        EditorView.scrollMargins.of(() => ({ bottom: 44 })),
        errLineField, sigField,
        autocompletion({ override: [completeSource], activateOnTyping: true, activateOnTypingDelay: 60, icons: true, maxRenderedOptions: 60 }),
        linter(lintSource, { delay: 400 }), lintGutter(), hover,
        roComp.current.of([EditorState.readOnly.of(!!readOnly), EditorView.editable.of(!readOnly)]),
        keymap.of([
          { key: 'Mod-Enter', run: () => { if (cb.current.onRun) { cb.current.onRun(); return true } return false } },
          ...closeBracketsKeymap, ...completionKeymap, ...lintKeymap, ...searchKeymap, ...historyKeymap, indentWithTab, ...defaultKeymap,
        ]),
        EditorView.updateListener.of((u) => {
          if (u.docChanged && !u.transactions.some((tr) => tr.annotation(External))) cb.current.onChange?.(u.state.doc.toString())
        }),
      ],
    })
    view.current = new EditorView({ state, parent: host.current })
    loadAssistCatalog().then(() => { const v = view.current; if (v) v.dispatch({}) })
    return () => { view.current?.destroy(); view.current = null }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps -- khởi tạo một lần; mọi prop đọc qua ref / effect riêng

  // Nội dung điều khiển từ ngoài (đổi tab bản nháp, chuẩn hoá, nạp mẫu): chỉ ghi khi khác, không phát onChange
  useEffect(() => {
    const v = view.current
    const next = String(value ?? '')
    if (!v || v.state.doc.toString() === next) return
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: next }, annotations: External.of(true), selection: { anchor: Math.min(next.length, v.state.selection.main.head) } })
  }, [value])

  useEffect(() => {
    view.current?.dispatch({ effects: roComp.current.reconfigure([EditorState.readOnly.of(!!readOnly), EditorView.editable.of(!readOnly)]) })
  }, [readOnly])


  // lỗi biên dịch mới -> tô dòng + cuộn tới
  useEffect(() => {
    const v = view.current
    if (!v) return
    const n = errorLine >= 1 ? Math.min(errorLine, v.state.doc.lines) : 0
    v.dispatch({ effects: [setErrLine.of(n)].concat(n ? [EditorView.scrollIntoView(v.state.doc.line(n).from, { y: 'center' })] : []) })
  }, [errorKey, errorLine])

  return <div className="se-ed" ref={host} style={{ height }} />
})

export default CodeEditor
