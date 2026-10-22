/**
 * App.edu.jsx — SPA router độc lập cho EDU product.
 *
 * Routes EDU: /, /login, /edu/* (EduMarket, MyProfile, EduUser, EduStrategy, Studio education mode).
 * KHÔNG có route /coin/* — nếu user cố vào /coin sẽ redirect về /edu.
 *
 * API base: edu.nora.expsolution.io/api (hoặc localhost:18020/api khi dev).
 */
import React, { Suspense, lazy } from 'react'
import { createBrowserRouter, RouterProvider, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import EduLayout from './layout/EduLayout'
import { CatalogProvider } from './meta/MetaProvider'
import { UserProvider, useUser } from './meta/UserProvider'
import { Loading } from './components/ui'

function lazyRetry(fn) {
  return lazy(() =>
    fn().catch((err) => {
      const msg = String(err?.message || '')
      if (msg.includes('dynamically imported module') || msg.includes('Importing a module script failed')) {
        const key = 'nora_edu_chunk_reload'
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

// EDU pages only
const Home        = lazyRetry(() => import('./pages/Home'))
const Login       = lazyRetry(() => import('./pages/Login'))
const EduMarket   = lazyRetry(() => import('./pages/edu/EduMarket'))
const MyProfile   = lazyRetry(() => import('./pages/edu/MyProfile'))
const EduUser     = lazyRetry(() => import('./pages/edu/EduUser'))
const EduStrategy = lazyRetry(() => import('./pages/edu/EduStrategy'))
const Studio      = lazyRetry(() => import('./pages/Studio'))

function ProtectedRoute({ children }) {
  const { me, loading } = useUser()
  const location = useLocation()
  if (loading) return <Loading what="phiên đăng nhập" />
  if (!me) return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />
  return children
}

function AppEduRoutes() {
  return (
    <Suspense fallback={<Loading what="trang" />}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<Login />} />

        {/* EDU system */}
        <Route path="/edu" element={<ProtectedRoute><EduLayout /></ProtectedRoute>}>
          <Route index element={<EduMarket />} />
          <Route path="studio" element={<Studio mode="education" />} />
          <Route path="me" element={<MyProfile />} />
          <Route path="u/:handle" element={<EduUser />} />
          <Route path="s/:id" element={<EduStrategy />} />
        </Route>

        {/* Redirect legacy /education và /coin/* -> /edu */}
        <Route path="/education" element={<Navigate to="/edu/studio" replace />} />
        <Route path="/coin/*" element={<Navigate to="/edu" replace />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

function EduRoot() {
  return (
    <UserProvider>
      <CatalogProvider>
        <AppEduRoutes />
      </CatalogProvider>
    </UserProvider>
  )
}

const router = createBrowserRouter([{ path: '*', element: <EduRoot /> }])

export default function AppEdu() {
  return <RouterProvider router={router} />
}
