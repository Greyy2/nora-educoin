import React from 'react'
import { PageHead, Segmented } from '../components/ui'
import DashboardLoader, { PERIODS } from '../components/portfolio/Dashboard'
import '../styles/portfolio.css'
import useStored from '../hooks/useStored'
import { useResource } from '../hooks/useAsync'
import { getOverview } from '../api'

export default function Portfolio() {
  const [pref, setPref] = useStored('nora-v2-portfolio', { period: 'ALL' })
  const { data: ov } = useResource('studio:overview', () => getOverview())

  const t = ov?.total

  return (
    <>
      <PageHead kicker="Danh mục COIN" title="Tổng quan" subtitle="Chỉ số hiệu suất và diễn biến danh mục.">
        <Segmented label="Kỳ xem" value={pref.period} onChange={(v) => setPref({ period: v })} options={PERIODS} />
      </PageHead>

      <DashboardLoader compact period={pref.period} totalWin={t} />
    </>
  )
}
