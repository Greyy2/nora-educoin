import React from 'react'
import { createPortal } from 'react-dom'
import EnterForm from './EnterForm'

export default function UserPicker({ open, onClose, onSelect }) {
  if (!open) return null
  return createPortal(
    <div className="n-modal-backdrop" onClick={onClose}>
      <div
        className="n-modal-content user-picker-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="user-picker-title"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 440, width: '92%' }}
      >
        <header className="push-alpha-header" style={{ marginBottom: 16 }}>
          <div>
            <h2 className="push-alpha-title" id="user-picker-title">Bạn là ai?</h2>
          </div>
          <button type="button" className="push-alpha-close-btn" onClick={onClose} aria-label="Đóng">✕</button>
        </header>
        <EnterForm onDone={(u) => { if (onSelect) onSelect(u); onClose() }} />
      </div>
    </div>,
    document.querySelector('.v2') || document.body
  )
}
