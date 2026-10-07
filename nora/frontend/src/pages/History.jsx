import React, { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageHead, Panel, Segmented, Status, Spinner, Empty, Loading, ErrorState } from '../components/ui'
import useJobList from '../hooks/useJobList'
import { ResolvedParams } from '../components/RunModes'
import { CUSTOM_BADGE, CUSTOM_REASON } from '../lib/modes'
import Term from '../components/Term'
import { JOB_STATUS, jobKindText, jobLink, jobElapsed, isActiveJob, jobDetail } from '../lib/jobs'
import { fmtDuration, fmtDateTime, toMs } from '../lib/format'

const KINDS = [
  { value: 'all', label: 'Tất cả' }, { value: 'book_backtest', label: 'Backtest' }, { value: 'book_wfa', label: 'WFA' }, { value: 'book_build', label: 'Alpha' }, { value: 'custom_backtest', label: 'Python' },
]
const STATES = [
  { value: 'all', label: 'Tất cả' }, { value: 'running', label: 'Đang chạy' }, { value: 'queued', label: 'Đang chờ' }, { value: 'done', label: 'Hoàn tất' }, { value: 'failed', label: 'Thất bại' },
]

export default function History() {
  const { jobs, loading, error, reload, running, queued, updatedAt } = useJobList(100)
  const [kind, setKind] = useState('all')
  const [state, setState] = useState('all')
  const nav = useNavigate()
  const rows = useMemo(() => jobs.filter((j) => (kind === 'all' || j.kind === kind) && (state === 'all' || j.status === state)), [jobs, kind, state])
  const now = Date.now()

  const openOnPortfolio = (j) => {
    try { localStorage.setItem('nora-v2-portfolio', JSON.stringify({ jobId: j.job_id, period: 'ALL' })) } catch (e) { /* bỏ qua */ }
    nav('/portfolio')
  }

  return (
    <>
      <PageHead kicker="Công việc nền" title="Lịch sử chạy"
        subtitle="Mọi lần chạy backtest, walk-forward và tối ưu alpha (tối đa 100 lần gần nhất). Mở một dòng để quay lại đúng trang và bước đã chạy.">
        <Segmented label="Lọc theo loại" value={kind} onChange={setKind} options={KINDS} />
        <Segmented label="Lọc theo trạng thái" value={state} onChange={setState} options={STATES} />
      </PageHead>

      {error && <ErrorState title="Không tải được lịch sử chạy" error={error} onRetry={reload} />}
      {loading && !jobs.length && <Loading what="lịch sử chạy" />}
      {!loading && !error && !jobs.length && <Empty title="Chưa có lần chạy nào">Chạy thử tại <Link to="/alpha/tune" style={{ color: 'var(--n-accent)' }}>Alpha</Link> hoặc <Link to="/backtest" style={{ color: 'var(--n-accent)' }}>Backtest</Link>.</Empty>}

      {jobs.length > 0 && (
        <Panel title="Các lần chạy" meta={
          <>
            <span>{rows.length}/{jobs.length} lần</span>
            {(running + queued) > 0 && <span><Spinner /> {running} đang chạy{queued ? ` · ${queued} đang chờ` : ''}</span>}
            {updatedAt && <span className="muted">tự làm mới</span>}
            <button type="button" className="n-btn sm" onClick={reload}>Làm mới</button>
          </>
        }>
          <div className="n-tblwrap long">
            <table className="n-tbl">
              <thead>
                <tr><th>Bắt đầu (UTC)</th><th>Loại</th><th>Chế độ</th><th>Nội dung</th><th>Trạng thái</th><th className="r">Thời lượng</th><th>Mã job</th><th /></tr>
              </thead>
              <tbody>
                {rows.map((j) => {
                  const meta = JOB_STATUS[j.status] || { text: j.status, cls: '' }
                  const el = jobElapsed(j, now)
                  return (
                    <tr key={j.job_id}>
                      <td className="mono">{fmtDateTime(toMs(j.created))}</td>
                      <td>{jobKindText(j.kind)}</td>
                      <td>{j.mode ? (
                        <span className="n-modecell">
                          <span className={`n-mode-badge ${j.mode}`}>{j.mode === 'advanced' ? <Term k="mode_advanced">Nâng cao</Term> : <Term k="mode_basic">Cơ bản</Term>}</span>
                          {(j.custom_gates || j.promotable === false) && <span className="n-custom-badge" title={CUSTOM_REASON}>⚠ {CUSTOM_BADGE}</span>}
                        </span>
                      ) : <span className="muted">—</span>}</td>
                      <td className="wrap" title={j.label}>{jobDetail(j)}<ResolvedParams job={j} /></td>
                      <td><Status tone={meta.cls}>{isActiveJob(j) && <Spinner />}{meta.text}</Status></td>
                      <td className="r">{el != null ? fmtDuration(el) : '—'}</td>
                      <td className="mono muted">{j.job_id}</td>
                      <td><div className="acts">
                        {jobLink(j) && <Link className="n-btn sm" to={jobLink(j)}>Mở</Link>}
                        {j.kind === 'book_backtest' && j.status === 'done' && <button type="button" className="n-btn sm" onClick={() => openOnPortfolio(j)}>Danh mục ↗</button>}
                      </div></td>
                    </tr>
                  )
                })}
                {!rows.length && <tr><td colSpan={8} className="muted">Không có lần chạy nào khớp bộ lọc.</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </>
  )
}
