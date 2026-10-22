import { getAssistCatalog } from '../api'

// Trợ lý viết code (tất định, không AI): danh mục từ máy chủ (docs/bmad/p10_alpha_contract.md §3), đệm theo phiên trang.
// Máy chủ chưa có API (404/405/mạng) -> trình soạn vẫn dùng được, chỉ không có gợi ý / kiểm lỗi.

let catalog = null
let pending = null
let failedAt = 0

export function peekAssistCatalog() { return catalog }

/** Tải danh mục một lần; lỗi thì thử lại sau 20 giây. Trả null nếu không có. */
export function loadAssistCatalog() {
  if (catalog) return Promise.resolve(catalog)
  if (pending) return pending
  if (failedAt && Date.now() - failedAt < 20000) return Promise.resolve(null)
  pending = getAssistCatalog().then((c) => { catalog = c && typeof c === 'object' ? c : null; if (!catalog) failedAt = Date.now(); return catalog }, () => { failedAt = Date.now(); return null }).finally(() => { pending = null })
  return pending
}

const STYLE_LABEL = {
  simple_algorithm: 'lớp SimpleAlgorithm', lifecycle: 'lớp on_start / on_bar', strategy_module: 'module chiến lược', function: 'hàm strategy(data)',
  json_spec: 'JSON', ai_python: 'Python dạng khác', unknown: 'không nhận dạng được',
}
export function styleLabel(style, cat = catalog) {
  const s = cat?.styles?.find((x) => x.style === style)
  return s?.label_vi || STYLE_LABEL[style] || style || ''
}

/** Toạ độ 1-based {line, col} (col = trước ký tự thứ col) -> vị trí trong văn bản; kẹp trong tài liệu. */
export function posAt(doc, line, col) {
  const ln = doc.line(Math.min(Math.max(1, line || 1), doc.lines))
  return Math.min(ln.to, ln.from + Math.max(0, (col || 1) - 1))
}

const KIND_TYPE = { feature: 'function', op: 'function', attr: 'property', method: 'method', param: 'variable', keyword: 'keyword', snippet: 'text' }
export const completionType = (kind) => KIND_TYPE[kind] || 'text'

const mk = (label, kind, detail, insert, doc_md) => ({ label, kind, detail, insert, is_snippet: /\$\{/.test(insert || ''), doc_md })
const featItem = (f) => mk(f.name, f.kind || 'feature', f.signature, `${f.insert || f.name}`.replace(/^self\.(feat|op)\./, ''), f.doc_vi ? `**${f.name}** — ${f.doc_vi}` : '')

/** Gợi ý dự phòng từ danh mục khi POST complete lỗi: chỉ dựa vào văn bản trước con trỏ. Trả { items, from } hoặc null. */
export function localComplete(cat, before) {
  if (!cat) return null
  let m
  const out = (items, word) => ({ items, word })
  if ((m = /self\.feat\.(\w*)$/.exec(before))) return out((cat.features || []).map(featItem), m[1])
  if ((m = /self\.op\.(\w*)$/.exec(before))) return out((cat.ops || []).map(featItem), m[1])
  if ((m = /self\.data\.(\w*)$/.exec(before))) return out((cat.data || []).map((d) => mk(d.name, 'attr', d.signature, d.name, d.doc_vi)), m[1])
  if ((m = /self\.(\w*)$/.exec(before))) {
    return out([mk('feat', 'attr', 'self.feat', 'feat'), mk('op', 'attr', 'self.op', 'op'), mk('data', 'attr', 'self.data', 'data'),
      mk('set_positions', 'method', 'self.set_positions(mask, position=1)', 'set_positions(${1:mask}, position=${2:1})')], m[1])
  }
  if ((m = /(?:^|\s)(\w*)$/.exec(before)) && /^\s*\w*$/.test(before.slice(before.lastIndexOf('\n') + 1))) {
    const items = [...(cat.lifecycle || []).map((l) => mk(l.name, 'keyword', l.doc_vi || 'vòng đời', l.insert || l.name, l.doc_vi)),
      ...(cat.snippets || []).map((s) => mk(s.label, 'snippet', 'mẫu', s.insert, s.doc_vi))]
    return out(items, m[1])
  }
  return null
}

/** Tìm lời gọi đang mở tại con trỏ: { name, kind, argIndex, argName } hoặc null (cho gợi ý chữ ký). */
export function openCall(before) {
  const text = before.slice(-600)
  let depth = 0
  let commas = 0
  let i = text.length - 1
  for (; i >= 0; i--) {
    const c = text[i]
    if (c === ')' || c === ']' || c === '}') depth++
    else if (c === '(' || c === '[' || c === '{') {
      if (depth === 0) { if (c === '(') break; return null }
      depth--
    } else if (c === ',' && depth === 0) commas++
  }
  if (i < 0) return null
  const head = text.slice(0, i)
  const m = /(?:self\.)?(feat|op)\.(\w+)\s*$/.exec(head)
  if (!m) return null
  const tail = text.slice(i + 1)
  const lastArg = tail.split(',').pop()
  const nm = /^\s*(\w+)\s*=(?!=)/.exec(lastArg)
  return { kind: m[1] === 'feat' ? 'feature' : 'op', name: m[2], argIndex: commas, argName: nm ? nm[1] : null }
}

/** DOM an toàn cho văn bản markdown rút gọn của máy chủ: ```code```, **đậm**, `mã`. Không dùng innerHTML. */
export function mdToDom(md) {
  const root = document.createElement('div')
  root.className = 'se-md'
  const parts = String(md || '').split(/```(?:\w+)?\n?/)
  parts.forEach((part, i) => {
    if (i % 2 === 1) { const pre = document.createElement('pre'); pre.textContent = part.replace(/\n$/, ''); root.appendChild(pre); return }
    part.split(/\n{2,}/).forEach((para) => {
      if (!para.trim()) return
      const p = document.createElement('p')
      para.split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach((seg) => {
        if (!seg) return
        if (seg.startsWith('**') && seg.endsWith('**') && seg.length > 4) { const b = document.createElement('b'); b.textContent = seg.slice(2, -2); p.appendChild(b) }
        else if (seg.startsWith('`') && seg.endsWith('`') && seg.length > 2) { const c = document.createElement('code'); c.textContent = seg.slice(1, -1); p.appendChild(c) }
        else p.appendChild(document.createTextNode(seg))
      })
      root.appendChild(p)
    })
  })
  return root
}
