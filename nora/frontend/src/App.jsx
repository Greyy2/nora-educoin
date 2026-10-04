import React, { Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import Shell from './layout/Shell'
import { CatalogProvider } from './context/Catalog'
import { Loading } from './components/ui'
import AlphaTabs from './components/AlphaTabs'

// Mỗi trang một chunk: lần đầu chỉ tải trang đang mở (biểu đồ nến chỉ tải khi vào trang có biểu đồ)
const Portfolio = lazy(() => import('./pages/Portfolio'))
const Backtest = lazy(() => import('./pages/Backtest'))
const AlphaV2 = lazy(() => import('./pages/Alpha'))
const History = lazy(() => import('./pages/History'))
const Live = lazy(() => import('./pages/Live'))
const Funnel = lazy(() => import('./pages/Funnel'))

function FunnelRedirect() {
  const { runId } = useParams()
  return <Navigate to={`/alpha/funnel/${encodeURIComponent(runId || '')}`} replace />
}

function AppRoutes() {
  return (
    <Shell>
      <Suspense fallback={<Loading what="trang" />}>
      <Routes>
        <Route path="/" element={<Navigate to="/portfolio" replace />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/alpha/funnel" element={<><AlphaTabs /><Funnel /></>} />
        <Route path="/alpha/funnel/:runId" element={<><AlphaTabs /><Funnel /></>} />
        <Route path="/funnel" element={<Navigate to="/alpha/funnel" replace />} />
        <Route path="/funnel/:runId" element={<FunnelRedirect />} />
        <Route path="/alpha" element={<><AlphaTabs /><AlphaV2 /></>} />
        <Route path="/live" element={<Live />} />
        <Route path="/history" element={<History />} />
        <Route path="*" element={<Navigate to="/portfolio" replace />} />
      </Routes>
      </Suspense>
    </Shell>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <CatalogProvider>
        <AppRoutes />
      </CatalogProvider>
    </BrowserRouter>
  )
}
