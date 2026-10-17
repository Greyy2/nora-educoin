import { useState } from 'react'

/** Hook hỗ trợ co giãn drawer sang trái và lưu kích thước vào localStorage. */
export default function useResizableDrawer(defaultWidth = 980) {
  const [width, setWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem('nora_alpha_drawer_w'))
      if (saved && saved >= 420 && saved <= window.innerWidth) return saved
    } catch (e) { /* bỏ qua */ }
    return Math.min(defaultWidth, window.innerWidth - 20)
  })

  const onMouseDown = (e) => {
    e.preventDefault()
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMouseMove = (moveEvt) => {
      const newW = window.innerWidth - moveEvt.clientX
      const clamped = Math.max(450, Math.min(window.innerWidth - 10, newW))
      setWidth(clamped)
      try {
        localStorage.setItem('nora_alpha_drawer_w', String(clamped))
      } catch (err) { /* bỏ qua */ }
    }

    const onMouseUp = () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }

    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
  }

  return { width, onMouseDown }
}
