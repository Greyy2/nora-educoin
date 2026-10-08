import React, { useMemo } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'   // chỉ nằm trong chunk lười của trang Alpha

/** Công thức LaTeX (KaTeX). Mặc định khối (display, cuộn ngang khi dài); `inline` = ký hiệu trong dòng (ô bảng). Lỗi cú pháp hiện nguyên mã. */
export default function MathBlock({ latex, label, inline = false }) {
  const html = useMemo(() => {
    try { return katex.renderToString(String(latex || ''), { throwOnError: false, displayMode: !inline, output: 'html', strict: 'ignore' }) } catch (e) { return null }
  }, [latex, inline])
  if (inline) return html == null ? <code>{latex}</code> : <span className="n-math-i" role="math" aria-label={label || latex} dangerouslySetInnerHTML={{ __html: html }} />
  if (html == null) return <pre className="n-math-raw mono">{latex}</pre>
  return <div className="n-math" role="math" aria-label={label || 'Công thức'} dangerouslySetInnerHTML={{ __html: html }} />
}
