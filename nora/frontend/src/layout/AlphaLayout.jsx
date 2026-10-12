import React from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import AlphaTabs from '../components/alpha/AlphaTabs'

/**
 * Layout đồng bộ cho toàn bộ phân vùng Alpha:
 * Giữ thanh tab cố định ở cùng 1 vị trí trên góc, không reload lại tab khi chuyển trang con,
 * chỉ chuyển đổi nội dung bên dưới (Outlet).
 */
export default function AlphaLayout() {
  const loc = useLocation()
  const isCreate = loc.pathname.startsWith('/alpha/create')

  return (
    <div className="n-alpha-layout">
      <div className="n-alpha-header-tabs">
        <AlphaTabs />
      </div>
      <div className={`n-alpha-body ${isCreate ? 'flush' : 'standard'}`}>
        <Outlet />
      </div>
    </div>
  )
}
