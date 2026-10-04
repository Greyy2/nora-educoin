import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHead, Segmented, Field } from '../components/ui'
import DashboardLoader, { PERIODS } from '../components/Dashboard'
import { LiveBotCard } from '../components/OverviewExtras'
import '../styles/portfolio.css'
import useStored from '../hooks/useStored'
import { listJobs } from '../api'
import { fmtDateTime, toMs } from '../lib/format'

export default function Portfolio() {
  const [pref, setPref] = useStored('nora-v2-portfolio', { jobId: '', period: 'ALL' }) // bản cũ còn `source`: bỏ qua
  const [jobs, setJobs] = useState({ loading: true, rows: [], error: null })

  useEffect(() => {
    let dead = false
    listJobs('book_backtest', 50).then(
      (rows) => { if (!dead) setJobs({ loading: false, rows: rows.filter((j) => j.status === 'done'), error: null }) },
      (e) => { if (!dead) setJobs({ loading: false, rows: [], error: e.message }) },
    )
    return () => { dead = true }
  }, [])

  // chọn job đầu tiên khi chưa có lựa chọn hợp lệ
  useEffect(() => {
    if (jobs.loading || !jobs.rows.length) return
    if (!jobs.rows.some((j) => j.job_id === pref.jobId)) setPref({ jobId: jobs.rows[0].job_id })
  }, [jobs, pref.jobId, setPref])

  // chỉ tải dashboard khi job đã lưu còn hợp lệ trong danh sách (tránh tải thừa với job cũ rồi tải lại)
  const btJob = jobs.rows.some((j) => j.job_id === pref.jobId) ? pref.jobId : ''
  return (
    <>
      <PageHead kicker="Tổng quan" title="Kết quả backtest"
        subtitle="Kết quả mô phỏng trên dữ liệu lịch sử, không phải giao dịch thật. Bot đang chạy xem ở trang Live. Số liệu chi tiết nằm trong các mục “Chi tiết” bên dưới (bấm để mở).">
        <Segmented label="Kỳ xem" value={pref.period} onChange={(v) => setPref({ period: v })} options={PERIODS} />
      </PageHead>

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

      <DashboardLoader compact jobId={btJob} period={pref.period} />
      <div className="pf-gap"><LiveBotCard /></div>
    </>
  )
}
