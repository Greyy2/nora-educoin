import React, { useMemo } from 'react'
import katex from 'katex'
import 'katex/dist/katex.min.css'   // chỉ nằm trong chunk lười của trang Alpha

/** Công thức LaTeX (KaTeX, chế độ display). Cuộn ngang trong khung khi công thức dài; lỗi cú pháp hiện lại nguyên mã thay vì làm trắng trang. */
export default function MathBlock({ latex, label }) {
  const html = useMemo(() => {
    try { return katex.renderToString(String(latex || ''), { throwOnError: false, displayMode: true, output: 'html', strict: 'ignore' }) } catch (e) { return null }
  }, [latex])
  if (html == null) return <pre className="n-math-raw mono">{latex}</pre>
  return <div className="n-math" role="math" aria-label={label || 'Công thức'} dangerouslySetInnerHTML={{ __html: html }} />
}
