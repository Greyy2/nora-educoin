import React, { useId, useState } from 'react'

/**
 * Mục "Chi tiết" thu gọn, mặc định ĐÓNG. Nội dung chỉ được dựng (và tải dữ liệu nếu có) khi mở lần đầu,
 * nên các bảng/biểu đồ phụ không làm chậm trang tổng quan.
 */
export default function DetailSection({ title, hint, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  return (
    <section className={`n-panel pf-sec ${open ? 'open' : ''}`}>
      <button type="button" className="pf-sec-h" aria-expanded={open} aria-controls={id} onClick={() => setOpen((o) => !o)}>
        <span className="pf-chev" aria-hidden="true">▸</span>
        <span className="pf-sec-t">{title}</span>
        {hint && <span className="pf-sec-hint">{hint}</span>}
      </button>
      {open && <div id={id} className="pf-sec-b">{children}</div>}
    </section>
  )
}
