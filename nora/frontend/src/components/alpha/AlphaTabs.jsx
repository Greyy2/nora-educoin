import React from 'react'
import { NavLink } from 'react-router-dom'

/** Trang Alpha gồm 2 phần: tạo chiến lược Python và danh mục alpha (ý tưởng + công thức). */
export default function AlphaTabs() {
  return (
    <nav className="n-tabs" aria-label="Alpha">
      <NavLink to="/alpha/create" className={({ isActive }) => (isActive ? 'on' : '')}>Tạo chiến lược</NavLink>
      <NavLink end to="/alpha" className={({ isActive }) => (isActive ? 'on' : '')}>Alpha</NavLink>
    </nav>
  )
}
