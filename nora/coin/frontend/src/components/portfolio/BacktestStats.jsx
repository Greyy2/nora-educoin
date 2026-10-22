import React, { useEffect, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Segmented, Field } from '../ui'
import DashboardLoader, { PERIODS } from './Dashboard'
import BacktestAlphaResults from '../backtest/BacktestAlphaResults'
import '../../styles/portfolio.css'
import useStored from '../../hooks/useStored'
import { useResource } from '../../hooks/useAsync'
import { listJobs } from '../../api'
import { fmtDateTime, toMs } from '../../lib/format'

/** Thống kê chi tiết của một lần backtest đã chạy xong. */
export default function BacktestStats({ activeJobId = '' }) {
  const [pref, setPref] = useStored('nora-v2-portfolio', { jobId: '', period: 'ALL' })
  const { data: jobList, loading, error } = useResource('jobs:book_backtest', () => listJobs('book_backtest', 50))
  const jobs = useMemo(() => ({ loading, error, rows: (jobList || []).filter((j) => j.status === 'done') }), [jobList, loading, error])

  useEffect(() => {
    if (activeJobId && jobs.rows.some((j) => j.job_id === activeJobId)) {
      if (pref.jobId !== activeJobId) setPref({ jobId: activeJobId })
      return
    }
    if (jobs.loading || !jobs.rows.length) return
    if (!jobs.rows.some((j) => j.job_id === pref.jobId)) setPref({ jobId: jobs.rows[0].job_id })
  }, [jobs, pref.jobId, setPref, activeJobId])

  const btJob = jobs.rows.some((j) => j.job_id === pref.jobId) ? pref.jobId : (jobs.rows[0]?.job_id || '')
  return (
    <>
      <div className="n-panel" style={{ padding: '10px 14px', marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 14 }}>
        <span style={{ fontSize: 13, color: 'var(--n-ink-2)' }}>Thống kê tổng hợp danh mục và phân bổ hiệu suất</span>
        <Segmented label="Kỳ xem" value={pref.period} onChange={(v) => setPref({ period: v })} options={PERIODS} />
      </div>
      <p className="n-note" style={{ marginBottom: 10 }}>Kết quả mô phỏng trên dữ liệu lịch sử, không phải giao dịch thật.</p>
      <DashboardLoader compact hideRegime jobId={btJob} period={pref.period} />
      <BacktestAlphaResults activeJobId={btJob} />
    </>
  )
}
