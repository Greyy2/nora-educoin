import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Shell from './layout/Shell'
import { CatalogProvider } from './context/Catalog'
import Portfolio from './pages/Portfolio'
import Backtest from './pages/Backtest'
import AlphaV2 from './pages/Alpha'
import History from './pages/History'
import Funnel from './pages/Funnel'

function AppRoutes() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Navigate to="/portfolio" replace />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/funnel" element={<Funnel />} />
        <Route path="/funnel/:runId" element={<Funnel />} />
        <Route path="/alpha" element={<AlphaV2 />} />
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
