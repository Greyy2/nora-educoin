import React, { Suspense, lazy } from 'react'
import { createBrowserRouter, RouterProvider, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import CoinLayout from './layout/CoinLayout'
import AlphaLayout from './layout/AlphaLayout'
import { CatalogProvider } from './meta/MetaProvider'
import { UserProvider, useUser } from './meta/UserProvider'
import { Loading } from './components/ui'

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
        }
      }
      throw err
    })
  )
}

// Lazy load các trang COIN
const Home         = lazyRetry(() => import('./pages/Home'))
const Login        = lazyRetry(() => import('./pages/Login'))
const Portfolio    = lazyRetry(() => import('./pages/Portfolio'))
const Backtest     = lazyRetry(() => import('./pages/Backtest'))
const AlphaCatalog = lazyRetry(() => import('./pages/AlphaCatalog'))
const Studio       = lazyRetry(() => import('./pages/Studio'))
const History      = lazyRetry(() => import('./pages/History'))
const Live         = lazyRetry(() => import('./pages/Live'))

function ProtectedRoute({ children }) {
  const { me, loading } = useUser()
  const location = useLocation()

  if (loading) {
    return <Loading what="phiên đăng nhập" />
  }

  if (!me) {
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />
  }

  return children
}

function LegacyRedirect({ to }) {
  const location = useLocation()
  return <Navigate to={`${to}${location.search}`} replace />
}

function AppRoutes() {
  return (
    <Suspense fallback={<Loading what="trang" />}>
      <Routes>
        {/* Trang chủ điều hướng chính & đăng nhập */}
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<Login />} />

        {/* Hệ thống Coin */}
        <Route path="/coin" element={<ProtectedRoute><CoinLayout /></ProtectedRoute>}>
          <Route index element={<Navigate to="/coin/portfolio" replace />} />
          <Route path="portfolio" element={<Portfolio />} />
          <Route path="backtest" element={<Backtest />} />
          <Route path="alpha" element={<AlphaLayout />}>
            <Route index element={<Navigate to="/coin/alpha/create" replace />} />
            <Route path="create" element={<Studio mode="create" />} />
            <Route path="catalog" element={<AlphaCatalog />} />
            <Route path="tune" element={<Navigate to="/coin/alpha/create" replace />} />
            <Route path="funnel" element={<Navigate to="/coin/alpha/create" replace />} />
            <Route path="funnel/:runId" element={<Navigate to="/coin/alpha/create" replace />} />
          </Route>
          <Route path="live" element={<Live />} />
          <Route path="history" element={<History />} />
        </Route>

        {/* Redirect tương thích ngược toàn bộ đường dẫn cũ */}
        <Route path="/portfolio" element={<LegacyRedirect to="/coin/portfolio" />} />
        <Route path="/backtest" element={<LegacyRedirect to="/coin/backtest" />} />
        <Route path="/alpha" element={<LegacyRedirect to="/coin/alpha/create" />} />
        <Route path="/alpha/create" element={<LegacyRedirect to="/coin/alpha/create" />} />
        <Route path="/alpha/*" element={<LegacyRedirect to="/coin/alpha/create" />} />
        <Route path="/live" element={<LegacyRedirect to="/coin/live" />} />
        <Route path="/history" element={<LegacyRedirect to="/coin/history" />} />
        <Route path="/education" element={<LegacyRedirect to="/coin/alpha/create" />} />
        <Route path="/edu" element={<LegacyRedirect to="/coin/portfolio" />} />
        <Route path="/edu/*" element={<LegacyRedirect to="/coin/portfolio" />} />

        {/* Đường dẫn không xác định về trang chủ */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

function Root() {
  return (
    <UserProvider>
      <CatalogProvider>
        <AppRoutes />
      </CatalogProvider>
    </UserProvider>
  )
}

const router = createBrowserRouter([{ path: '*', element: <Root /> }])

export default function App() {
  return <RouterProvider router={router} />
}
