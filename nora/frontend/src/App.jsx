import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Analysis from './pages/Analysis'
import DiscoveryDetail from './pages/DiscoveryDetail'
import MethodComparison from './pages/MethodComparison'
import AssetResearchDetail from './pages/AssetResearchDetail'
import Alpha from './pages/Alpha'
import StrategyDetail from './pages/StrategyDetail'
import Base from './pages/Base'
import Wfa from './pages/Wfa'
import MonteCarlo from './pages/MonteCarlo'
import Results from './pages/Results'
import RunDetail from './pages/RunDetail'
import Trades from './pages/Trades'
import Chart from './pages/Chart'
import Shell from './v2/layout/Shell'
import { CatalogProvider } from './v2/context/Catalog'
import Portfolio from './v2/pages/Portfolio'
import Backtest from './v2/pages/Backtest'
import AlphaV2 from './v2/pages/Alpha'
import History from './v2/pages/History'

function AppRoutes() {
  return (
    <Shell>
      <Routes>
        <Route path="/" element={<Navigate to="/portfolio" replace />} />
        {/* giao diện v2 */}
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/alpha" element={<AlphaV2 />} />
        <Route path="/history" element={<History />} />

        {/* giao diện cũ (nhóm Legacy ở thanh bên) */}
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/research/analysis" element={<Analysis />} />
        <Route path="/research/analysis/discovery/:discoveryId" element={<DiscoveryDetail />} />
        <Route path="/research/analysis/methods" element={<MethodComparison />} />
        <Route path="/research/analysis/asset/:symbol" element={<AssetResearchDetail />} />
        <Route path="/library/alpha" element={<Alpha />} />
        <Route path="/library/alpha/:id" element={<StrategyDetail />} />
        <Route path="/library/base" element={<Base />} />
        <Route path="/library/wfa" element={<Wfa />} />
        <Route path="/library/monte-carlo" element={<MonteCarlo />} />
        <Route path="/library/result" element={<Results />} />
        <Route path="/library/result/:id" element={<RunDetail />} />
        <Route path="/library/result/:id/trades" element={<Trades />} />
        <Route path="/library/result/:id/chart" element={<Chart />} />

        {/* đường dẫn chuyển hướng tương thích */}
        <Route path="/scan" element={<Navigate to="/dashboard" replace />} />
        <Route path="/analysis" element={<Navigate to="/research/analysis" replace />} />
        <Route path="/studio" element={<Navigate to="/library/alpha?tab=builder" replace />} />
        <Route path="/wfa" element={<Navigate to="/library/wfa" replace />} />
        <Route path="/monte-carlo" element={<Navigate to="/library/monte-carlo" replace />} />
        <Route path="/runs" element={<Navigate to="/library/result" replace />} />
        <Route path="/strategies" element={<Navigate to="/library/alpha" replace />} />
        <Route path="/miner" element={<Navigate to="/library/alpha?tab=dao" replace />} />
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
