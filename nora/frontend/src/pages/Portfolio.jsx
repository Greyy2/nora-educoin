import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHead, Segmented, Field } from '../components/ui'
import DashboardLoader, { PERIODS } from '../components/Dashboard'
import '../styles/portfolio.css'
import useStored from '../hooks/useStored'
import { listJobs } from '../api'
import { fmtDateTime, toMs } from '../lib/format'

const SOURCES = [
  { value: 'live', label: 'Live' }, { value: 'testnet', label: 'Testnet' }, { value: 'backtest', label: 'Backtest' },
]

export default function Portfolio() {
  const [pref, setPref] = useStored('nora-v2-portfolio', { source: 'live', jobId: '', period: 'ALL' })
  const [jobs, setJobs] = useState({ loading: false, rows: [], error: null })
  const source = SOURCES.some((o) => o.value === pref.source) ? pref.source : 'live' // giá trị cũ đã lưu (vd. nguồn đã bỏ) -> Live

  useEffect(() => {
    if (source !== 'backtest') return undefined
    let dead = false
    setJobs((j) => ({ ...j, loading: true }))
    listJobs('book_backtest', 50).then(
      (rows) => { if (!dead) setJobs({ loading: false, rows: rows.filter((j) => j.status === 'done'), error: null }) },
      (e) => { if (!dead) setJobs({ loading: false, rows: [], error: e.message }) },
    )
    return () => { dead = true }
  }, [source])

  // chọn job đầu tiên khi chưa có lựa chọn hợp lệ
  useEffect(() => {
    if (source !== 'backtest' || jobs.loading || !jobs.rows.length) return
    if (!jobs.rows.some((j) => j.job_id === pref.jobId)) setPref({ jobId: jobs.rows[0].job_id })
  }, [jobs, source, pref.jobId, setPref])

  const isBt = source === 'backtest'
  // chỉ tải dashboard khi job đã lưu còn hợp lệ trong danh sách (tránh tải thừa với job cũ rồi tải lại)
  const btJob = jobs.rows.some((j) => j.job_id === pref.jobId) ? pref.jobId : ''
  return (
    <>
      <PageHead kicker="Tổng quan" title="Danh mục"
        subtitle="Tổng quan nhanh: các chỉ số chính và đường NAV. Số liệu chi tiết nằm trong các mục “Chi tiết” bên dưới (bấm để mở).">
        <Segmented label="Nguồn dữ liệu" value={source} onChange={(v) => setPref({ source: v })} options={SOURCES} />
        <Segmented label="Kỳ xem" value={pref.period} onChange={(v) => setPref({ period: v })} options={PERIODS} />
      </PageHead>

      {isBt && (
        <div className="n-panel" style={{ padding: '10px 14px', marginBottom: 12, display: 'flex', gap: 14, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 320, flex: '1 1 320px' }}>
            <Field id="pf-job" label="Lần backtest đã chạy xong">
              <select id="pf-job" className="n-sel" value={pref.jobId} disabled={!jobs.rows.length}
                onChange={(e) => setPref({ jobId: e.target.value })}>
                {!jobs.rows.length && <option value="">{jobs.loading ? 'Đang tải…' : 'Chưa có backtest nào'}</option>}
                {jobs.rows.map((j) => <option key={j.job_id} value={j.job_id}>{fmtDateTime(toMs(j.created))} · {j.label}</option>)}
              </select>
            </Field>
          </div>
          <span className="n-note">{jobs.error ? `Lỗi tải danh sách: ${jobs.error}` : 'Chạy thêm tại'} <Link to="/backtest" style={{ color: 'var(--n-accent)' }}>Backtest</Link></span>
        </div>
      )}

      <DashboardLoader compact source={source} jobId={isBt ? btJob : undefined} period={pref.period} refreshMs={isBt ? 0 : 60000} />
    </>
  )
}
