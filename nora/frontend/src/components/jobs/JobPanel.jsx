import React, { useEffect, useState } from 'react'
import { Status, Spinner, ErrorBox } from '../ui'
import { JOB_STATUS, jobProgress, fmtRate } from '../../lib/jobs'
import { toMs, fmtDuration, fmtPct } from '../../lib/format'
import { postCancel } from '../../api'
import { ModeStamp, ResolvedParams } from '../optimize/RunModes'

/** Bảng theo dõi một job nền: trạng thái, thời gian đã chạy, tiến độ (% · tốc độ · ETA) + nút "Huỷ", vài dòng log cuối (thu gọn được). */
export default function JobPanel({ job, status, error, title, onCancelled }) {
  const [now, setNow] = useState(Date.now())
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState(null)
  const live = status === 'queued' || status === 'running' || status === 'loading'
  useEffect(() => {
    if (!live) return undefined
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [live])
  useEffect(() => { if (!live) setCancelling(false) }, [live])
  const meta = JOB_STATUS[status] || { text: 'Đang tải', cls: '' }
  const created = toMs(job?.created)
  const started = toMs(job?.started) || created
  const finished = toMs(job?.finished)
  const elapsed = started ? ((finished || now) - started) / 1000 : null
  const lines = job?.log_tail || []
  const prog = jobProgress(job)
  const canCancel = !!job?.job_id && (status === 'queued' || status === 'running')
  const cancel = async () => {
    if (!window.confirm('Huỷ job này? Kết quả đã chạy được giữ lại, có thể chạy tiếp bằng --resume.')) return
    setCancelling(true)
    setCancelError(null)
    try { const j = await postCancel(job.job_id); if (onCancelled) onCancelled(j) } catch (e) { setCancelError(e.message); setCancelling(false) }
  }
  return (
    <div className="n-job" aria-live="polite">
      <div className="n-job-top">
        {title && <b>{title}</b>}
        <Status tone={meta.cls}>{live && <Spinner />}{meta.text}</Status>
        {job && <span className="mono muted">{job.job_id}</span>}
        {elapsed != null && <span className="mono">Đã chạy {fmtDuration(elapsed)}</span>}
        {canCancel && (
          <button type="button" className="n-btn sm n-job-cancel" onClick={cancel} disabled={cancelling}>
            {cancelling ? 'Đang huỷ…' : 'Huỷ'}
          </button>
        )}
      </div>
      {prog && (status === 'running' || status === 'done' || status === 'cancelled') && (
        <div className="n-prog" role="group" aria-label="Tiến độ">
          <div className="n-prog-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(prog.pct)}>
            <span style={{ width: `${Math.min(100, prog.pct)}%` }} />
          </div>
          <div className="n-prog-meta mono">
            <b>{fmtPct(prog.pct, prog.pct < 10 ? 1 : 0)}</b>
            <span>{prog.done.toLocaleString('vi-VN')}/{prog.total.toLocaleString('vi-VN')}{prog.stage ? ` · ${prog.stage}` : ''}</span>
            {status === 'running' && <span>Tốc độ {fmtRate(prog.rate)}</span>}
            {status === 'running' && <span>Còn khoảng {prog.eta != null ? fmtDuration(prog.eta) : '—'}</span>}
            {prog.peakMb != null && <span className="muted">RAM đỉnh {Math.round(prog.peakMb)} MB</span>}
          </div>
        </div>
      )}
      {job?.mode && <ModeStamp mode={job.mode} customGates={job.custom_gates} promotable={job.promotable} ignored={job.ignored_client_params} />}
      {job?.resolved && <ResolvedParams job={job} />}
      <ErrorBox>{error}</ErrorBox>
      <ErrorBox>{cancelError}</ErrorBox>
      {status === 'failed' && <ErrorBox>Job thất bại (mã thoát {String(job?.exit_code ?? '?')}). Xem log bên dưới.</ErrorBox>}
      {status === 'cancelled' && <div className="muted">Job đã bị huỷ. Kết quả đã chạy được giữ lại trong kho; chạy tiếp bằng <span className="mono">--resume</span> với cùng thư mục lần chạy.</div>}
      {lines.length > 0 && (
        <details className="n-details" open={status === 'failed'}>
          <summary>Log cuối ({lines.length} dòng)</summary>
          <pre className="n-log">{lines.slice(-12).join('\n')}</pre>
        </details>
      )}
    </div>
  )
}
