import React, { Suspense, lazy } from 'react'
import { createBrowserRouter, RouterProvider, Routes, Route, Navigate } from 'react-router-dom'
import Shell from './layout/Shell'
import { CatalogProvider } from './meta/MetaProvider'
import { Loading } from './components/ui'
import AlphaLayout from './layout/AlphaLayout'

// Tự động tải lại trang khi gặp chunk cũ bị xoá sau khi deploy (Failed to fetch dynamically imported module)
function lazyRetry(fn) {
  return lazy(() =>
    fn().catch((err) => {
      const msg = String(err?.message || '')
      if (msg.includes('dynamically imported module') || msg.includes('Importing a module script failed')) {
        const key = 'nora_chunk_reload'
        const last = sessionStorage.getItem(key)
        if (!last || Date.now() - Number(last) > 8000) {
          sessionStorage.setItem(key, String(Date.now()))
          window.location.reload()
          return new Promise(() => {})
        }
      }
      throw err
    })
  )
}

// Mỗi trang một chunk: lần đầu chỉ tải trang đang mở (biểu đồ nến chỉ tải khi vào trang có biểu đồ)
const Portfolio    = lazyRetry(() => import('./pages/Portfolio'))
const Backtest     = lazyRetry(() => import('./pages/Backtest'))
const AlphaCatalog = lazyRetry(() => import('./pages/AlphaCatalog'))
const Studio       = lazyRetry(() => import('./pages/Studio'))
const History      = lazyRetry(() => import('./pages/History'))
const Live         = lazyRetry(() => import('./pages/Live'))

function AppRoutes() {
  return (
    <Shell>
      <Suspense fallback={<Loading what="trang" />}>
      <Routes>
        <Route path="/"                    element={<Navigate to="/portfolio" replace />} />
        <Route path="/portfolio"           element={<Portfolio />} />
        <Route path="/backtest"            element={<Backtest />} />
        <Route path="/alpha"               element={<AlphaLayout />}>
          <Route index                     element={<AlphaCatalog />} />
          <Route path="create"             element={<Studio mode="create" />} />
          <Route path="tune"               element={<Navigate to="/alpha" replace />} />
          <Route path="funnel"             element={<Navigate to="/alpha" replace />} />
          <Route path="funnel/:runId"      element={<Navigate to="/alpha" replace />} />
        </Route>

        <Route path="/live"                element={<Live />} />
        <Route path="/history"             element={<History />} />
        <Route path="/education"           element={<Studio mode="education" />} />
        <Route path="*"                    element={<Navigate to="/portfolio" replace />} />
      </Routes>
      </Suspense>
    </Shell>
  )
}

// Data router (createBrowserRouter) là điều kiện để dùng useBlocker: cảnh báo rời trang khi còn bản nháp / kết quả chưa lưu (hooks/useUnsavedGuard.js).
function Root() {
  return (
    <CatalogProvider>
      <AppRoutes />
    </CatalogProvider>
  )
}

const router = createBrowserRouter([{ path: '*', element: <Root /> }])

export default function App() {
  return <RouterProvider router={router} />
}
