import React, { useEffect, useState } from 'react'
import { Status, Spinner, ErrorBox } from './ui'
import { JOB_STATUS } from '../lib/jobs'
import { toMs, fmtDuration } from '../lib/format'

/** Bảng theo dõi một job nền: trạng thái, thời gian đã chạy, vài dòng log cuối (thu gọn được). */
export default function JobPanel({ job, status, error, title }) {
  const [now, setNow] = useState(Date.now())
  const live = status === 'queued' || status === 'running' || status === 'loading'
  useEffect(() => {
    if (!live) return undefined
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [live])
  const meta = JOB_STATUS[status] || { text: 'Đang tải', cls: '' }
  const created = toMs(job?.created)
  const started = toMs(job?.started) || created
  const finished = toMs(job?.finished)
  const elapsed = started ? ((finished || now) - started) / 1000 : null
  const lines = job?.log_tail || []
  return (
    <div className="n-job" aria-live="polite">
      <div className="n-job-top">
        {title && <b>{title}</b>}
        <Status tone={meta.cls}>{live && <Spinner />}{meta.text}</Status>
        {job && <span className="mono muted">{job.job_id}</span>}
        {elapsed != null && <span className="mono">Đã chạy {fmtDuration(elapsed)}</span>}
      </div>
      <ErrorBox>{error}</ErrorBox>
      {status === 'failed' && <ErrorBox>Job thất bại (mã thoát {String(job?.exit_code ?? '?')}). Xem log bên dưới.</ErrorBox>}
      {lines.length > 0 && (
        <details className="n-details" open={status === 'failed'}>
          <summary>Log cuối ({lines.length} dòng)</summary>
          <pre className="n-log">{lines.slice(-12).join('\n')}</pre>
        </details>
      )}
    </div>
  )
}
