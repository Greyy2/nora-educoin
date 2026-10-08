import React, { useState } from 'react'

/** Khối gập kiểu panel: đóng sẵn, nội dung chỉ được dựng (và dữ liệu nặng chỉ được tải) khi người dùng mở. */
export default function Collapsible({ title, sub, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <details className="n-panel n-fs-coll" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>{title}{sub && <span className="sub">{sub}</span>}</summary>
      {open && <div className="body">{typeof children === 'function' ? children() : children}</div>}
    </details>
  )
}
