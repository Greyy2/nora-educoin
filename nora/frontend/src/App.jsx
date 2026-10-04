import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import Shell from './layout/Shell'
import { CatalogProvider } from './context/Catalog'
import Portfolio from './pages/Portfolio'
import Backtest from './pages/Backtest'
import AlphaV2 from './pages/Alpha'
import History from './pages/History'
import Live from './pages/Live'
import Funnel from './pages/Funnel'
import AlphaTabs from './components/AlphaTabs'

function FunnelRedirect() {
  const { runId } = useParams()
  return <Navigate to={`/alpha/funnel/${encodeURIComponent(runId || '')}`} replace />
}

function AppRoutes() {
  return (
    <Shell>
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
