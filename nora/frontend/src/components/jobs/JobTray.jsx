import React, { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Status, Spinner } from '../ui'
import useJobList from '../../hooks/useJobList'
import { useMeta } from '../../meta/MetaProvider'
import { JOB_STATUS, jobKindText, jobLink, jobElapsed, isActiveJob, jobDetail } from '../../lib/jobs'
import { fmtDuration, fmtDateTime, toMs } from '../../lib/format'

const ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="4" y="3.5" width="16" height="17" rx="2.5" /><path d="M8 8.5h8M8 12.5h8M8 16.5h5" />
  </svg>
)

/** Chỉ báo công việc nền ở thanh trên: số job đang chạy / đang chờ + danh sách job gần đây, mỗi dòng dẫn tới đúng trang/bước. */
export default function JobTray() {
  const { jobs, loading, error, running, queued, reload } = useJobList(20)
  const { meta: appMeta } = useMeta()
  const [open, setOpen] = useState(false)
  const [now, setNow] = useState(Date.now())
  const box = useRef(null)
  const loc = useLocation()
  const active = running + queued

  useEffect(() => { setOpen(false) }, [loc.pathname, loc.search])
  useEffect(() => {
    if (!open) return undefined
    reload()
    const t = setInterval(() => setNow(Date.now()), 1000)
    const click = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const key = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', click)
    document.addEventListener('keydown', key)
    return () => { clearInterval(t); document.removeEventListener('mousedown', click); document.removeEventListener('keydown', key) }
  }, [open, reload])

  const summary = active ? `${running} đang chạy${queued ? ` · ${queued} đang chờ` : ''}` : 'Không có job đang chạy'
  return (
    <div className="n-tray" ref={box}>
      <button type="button" className={`n-pill n-tray-btn ${active ? 'live' : ''}`} aria-expanded={open} aria-haspopup="true" aria-controls="n-tray-pop"
        title="Công việc nền (backtest, WFA, tối ưu alpha)" onClick={() => setOpen((o) => !o)}>
        {active ? <Spinner /> : ICON}
        <span>{active ? `${running}${queued ? ` + ${queued} chờ` : ''}` : 'Công việc'}</span>
        <span className="sr-only">{summary}</span>
      </button>
      {open && (
        <div className="n-pop n-tray-pop" id="n-tray-pop">
          <div className="n-pop-h"><b>Công việc nền</b><span className="muted">{summary}</span></div>
          {loading && !jobs.length && <p className="n-note" style={{ padding: '10px 12px' }}>Đang tải…</p>}
          {error && <p className="n-note neg" style={{ padding: '4px 12px' }}>Không tải được danh sách: {error}</p>}
          {!loading && !error && !jobs.length && <p className="n-note" style={{ padding: '10px 12px' }}>Chưa có job nào. Chạy backtest, WFA hoặc tối ưu alpha để thấy ở đây.</p>}
          <ul className="n-tray-list">
            {jobs.slice(0, 8).map((j) => {
              const meta = JOB_STATUS[j.status] || { text: j.status, cls: '' }
              const el = jobElapsed(j, now)
              return (
                <li key={j.job_id}>
                  <Link to={jobLink(j) || '/history'} title={`Mở ${j.job_id}`}>
                    <span className="k">{jobKindText(j.kind, appMeta)}</span>
                    <span className="lb">{jobDetail(j)}</span>
                    <Status tone={meta.cls}>{isActiveJob(j) && <Spinner />}{meta.text}</Status>
                    <span className="mono t">{el != null ? fmtDuration(el) : '—'}</span>
                    <span className="mono muted w">{fmtDateTime(toMs(j.created))}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
          <div className="n-pop-f"><Link to="/history">Xem toàn bộ lịch sử chạy →</Link></div>
        </div>
      )}
    </div>
  )
}
