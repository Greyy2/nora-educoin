import React from 'react'
import { NavLink } from 'react-router-dom'

/** Trang Alpha gồm 2 phần: tối ưu sổ chiến lược và phễu kiểm duyệt alpha (S0 → FINAL). */
export default function AlphaTabs() {
  return (
    <nav className="n-tabs" aria-label="Alpha">
      <NavLink end to="/alpha" className={({ isActive }) => (isActive ? 'on' : '')}>Tối ưu sổ chiến lược</NavLink>
      <NavLink to="/alpha/funnel" className={({ isActive }) => (isActive ? 'on' : '')}>Phễu kiểm duyệt alpha</NavLink>
    </nav>
  )
}
