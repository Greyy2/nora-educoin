import React from 'react'
import { NavLink } from 'react-router-dom'

/** Trang Alpha gồm: tạo chiến lược Python và danh mục alpha (ý tưởng + công thức). */
export default function AlphaTabs() {
  return (
    <nav className="n-tabs" aria-label="Alpha">
      <NavLink to="/coin/alpha/create" className={({ isActive }) => (isActive ? 'on' : '')}>Tạo chiến lược</NavLink>
      <NavLink to="/coin/alpha/catalog" className={({ isActive }) => (isActive ? 'on' : '')}>Alpha</NavLink>
    </nav>
  )
}

