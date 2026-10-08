import React, { Suspense, lazy } from 'react'
import { createBrowserRouter, RouterProvider, Routes, Route, Navigate } from 'react-router-dom'
import Shell from './layout/Shell'
import { CatalogProvider } from './context/Catalog'
import { Loading } from './components/ui'
import AlphaTabs from './components/alpha/AlphaTabs'

// Mỗi trang một chunk: lần đầu chỉ tải trang đang mở (biểu đồ nến chỉ tải khi vào trang có biểu đồ)
const Portfolio   = lazy(() => import('./pages/Portfolio'))
const Backtest    = lazy(() => import('./pages/Backtest'))
const AlphaCatalog = lazy(() => import('./pages/AlphaCatalog'))
const Studio       = lazy(() => import('./pages/Studio'))
const Tune        = lazy(() => import('./pages/Tune'))         // tối ưu sổ chiến lược (/alpha/tune)
const History     = lazy(() => import('./pages/History'))
const Live        = lazy(() => import('./pages/Live'))
const Funnel      = lazy(() => import('./pages/Funnel'))

function AppRoutes() {
  return (
    <Shell>
      <Suspense fallback={<Loading what="trang" />}>
      <Routes>
        <Route path="/"                    element={<Navigate to="/portfolio" replace />} />
        <Route path="/portfolio"           element={<Portfolio />} />
        <Route path="/backtest"            element={<Backtest />} />
        <Route path="/alpha/funnel"        element={<><AlphaTabs /><Funnel /></>} />
        <Route path="/alpha/funnel/:runId" element={<><AlphaTabs /><Funnel /></>} />
        <Route path="/alpha"               element={<><AlphaTabs /><AlphaCatalog /></>} />
        <Route path="/alpha/create"        element={<><AlphaTabs /><Studio mode="create" /></>} />
        <Route path="/alpha/tune"          element={<><AlphaTabs /><Tune /></>} />
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
