import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useUser } from '../../meta/UserProvider'
import UserPicker from './UserPicker'
import '../../styles/shell.css'

export default function UserBadge({ compact = false }) {
  const { me, loading, logout } = useUser()
  const [pickerOpen, setPickerOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)
  const navigate = useNavigate()

  useEffect(() => {
    function handleClickOutside(event) {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false)
      }
    }
    if (menuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [menuOpen])

  if (loading) {
    return (
      <div className="n-user-badge-loading" style={{ fontSize: 12, opacity: 0.6, padding: '4px 8px' }}>
        ...
      </div>
    )
  }

  if (!me) {
    return (
      <>
        <button
          type="button"
          className="n-btn sm n-user-badge-login"
          onClick={() => setPickerOpen(true)}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13 }}
        >
          <span>👤</span>
          <span>Vào bằng tên</span>
        </button>
        <UserPicker open={pickerOpen} onClose={() => setPickerOpen(false)} />
      </>
    )
  }

  const bg = me.avatar?.color || '#3b82f6'
  const emoji = me.avatar?.emoji || '👤'

  return (
    <div className="n-user-badge-wrap" ref={menuRef}>
      <button
        type="button"
        className={`n-user-badge-btn ${menuOpen ? 'active' : ''}`}
        onClick={() => setMenuOpen(!menuOpen)}
        title={`Người dùng: ${me.display_name} (@${me.handle})`}
        aria-expanded={menuOpen}
        aria-haspopup="true"
      >
        <span
          className="n-user-badge-avatar"
          style={{ background: bg }}
        >
          {emoji}
        </span>
        {!compact && (
          <span className="n-user-badge-name">
            {me.display_name}
          </span>
        )}
        <span className="n-user-badge-arrow">▾</span>
      </button>

      {menuOpen && (
        <div className="n-user-menu" role="menu">
          <div className="n-user-menu-header">
            <div className="n-user-menu-name">{me.display_name}</div>
            <div className="n-user-menu-handle">@{me.handle}</div>
          </div>

          <button
            type="button"
            className="n-user-menu-item"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false)
              navigate('/edu/me')
            }}
          >
            <span className="n-user-menu-ico">📜</span>
            <span>Hồ sơ của tôi</span>
          </button>

          <button
            type="button"
            className="n-user-menu-item"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false)
              setPickerOpen(true)
            }}
          >
            <span className="n-user-menu-ico">🔄</span>
            <span>Đổi người dùng</span>
          </button>

          <div className="n-user-menu-divider" />

          <button
            type="button"
            className="n-user-menu-item logout"
            role="menuitem"
            onClick={async () => {
              setMenuOpen(false)
              await logout()
            }}
          >
            <span className="n-user-menu-ico">🚪</span>
            <span>Đăng xuất</span>
          </button>
        </div>
      )}

      <UserPicker open={pickerOpen} onClose={() => setPickerOpen(false)} />
    </div>
  )
}
