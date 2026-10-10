import React, { useEffect, useState, useRef } from 'react'
import { Status, Spinner, ErrorBox } from '../ui'
import { JOB_STATUS, jobProgress, fmtRate } from '../../lib/jobs'
import { toMs, fmtDuration, fmtPct } from '../../lib/format'
import { postCancel } from '../../api'
import { ModeStamp, ResolvedParams } from '../optimize/RunModes'

// 5 bước tiêu chuẩn trong tiến trình Backtest Nautilus của Nora
const BACKTEST_STEPS = [
  { id: 1, label: 'Biên dịch', key: 'Biên dịch' },
  { id: 2, label: 'Nạp dữ liệu', key: 'Nạp' },
  { id: 3, label: 'Tín hiệu', key: 'Tín hiệu' },
  { id: 4, label: 'Khớp Nautilus', key: 'Nautilus' },
  { id: 5, label: 'Chỉ số', key: 'chỉ số' },
]

function parseLogLine(ln) {
  // Chuẩn hóa dòng log: [HH:MM:SS] [1/5] Tên bước · chi tiết
  const m = String(ln || '').match(/^\[(\d{2}:\d{2}:\d{2})\](?:\s+\[(\d\/\d)\])?\s+(.*)$/)
  if (m) {
    return { time: m[1], step: m[2] || null, msg: m[3] }
  }
  return { time: null, step: null, msg: ln }
}

/** Bảng theo dõi một job nền: trạng thái, thanh tiến độ download-style, các bước pipeline, và nhật ký mốc trực tiếp. */
export default function JobPanel({ job, status, error, title, onCancelled }) {
  const [now, setNow] = useState(Date.now())
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState(null)
  const consoleBodyRef = useRef(null)

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

  // Tự động cuộn xuống dòng mới nhất trong log terminal
  useEffect(() => {
    if (consoleBodyRef.current) {
      consoleBodyRef.current.scrollTop = consoleBodyRef.current.scrollHeight
    }
  }, [lines.length, status])

  const cancel = async () => {
    if (!window.confirm('Huỷ job này? Kết quả đã chạy được giữ lại, có thể chạy tiếp bằng --resume.')) return
    setCancelling(true)
    setCancelError(null)
    try { const j = await postCancel(job.job_id); if (onCancelled) onCancelled(j) } catch (e) { setCancelError(e.message); setCancelling(false) }
  }

  // Xác định bước pipeline hiện tại
  const isBacktestPipeline = prog?.total === 5 || String(title || '').toLowerCase().includes('backtest') || String(job?.kind || '').includes('backtest')
  let currentStepIdx = 0
  if (status === 'done') {
    currentStepIdx = BACKTEST_STEPS.length
  } else if (prog) {
    if (prog.stage) {
      const idx = BACKTEST_STEPS.findIndex((s) => prog.stage.toLowerCase().includes(s.key.toLowerCase()))
      if (idx >= 0) currentStepIdx = idx
      else currentStepIdx = Math.max(0, Math.min(BACKTEST_STEPS.length - 1, (prog.done || 1) - 1))
    } else if (prog.done != null) {
      currentStepIdx = Math.max(0, Math.min(BACKTEST_STEPS.length - 1, prog.done - 1))
    }
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

      {/* Hiển thị pipeline các bước trong tiến trình Backtest */}
      {isBacktestPipeline && (status === 'running' || status === 'queued' || status === 'done') && (
        <div className="n-pipeline-track" role="list" aria-label="Các bước thực thi">
          {BACKTEST_STEPS.map((step, idx) => {
            const isDone = status === 'done' || idx < currentStepIdx
            const isActive = status === 'running' && idx === currentStepIdx
            const stepClass = isDone ? 'done' : isActive ? 'active' : 'pending'
            return (
              <React.Fragment key={step.id}>
                <div className={`n-step-item ${stepClass}`} role="listitem">
                  <span className="n-step-badge">
                    {isDone ? '✓' : step.id}
                  </span>
                  <span className="n-step-name">{step.label}</span>
                </div>
                {idx < BACKTEST_STEPS.length - 1 && (
                  <span className="n-step-arrow" aria-hidden="true">→</span>
                )}
              </React.Fragment>
            )
          })}
        </div>
      )}

      {/* Thanh tiến độ phong cách download: mượt mà, shimmer khi chạy */}
      {prog && (status === 'running' || status === 'done' || status === 'cancelled') && (
        <div className="n-prog" role="group" aria-label="Tiến độ thực thi">
          <div
            className={`n-prog-bar download-style ${status === 'running' ? 'is-running' : ''}`}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(prog.pct)}
          >
            <span style={{ width: `${Math.min(100, Math.max(status === 'done' ? 100 : (prog.pct > 0 ? prog.pct : 5), prog.pct))}%` }} />
          </div>
          <div className="n-prog-meta mono">
            <b>{fmtPct(status === 'done' ? 100 : prog.pct, prog.pct < 10 ? 1 : 0)}</b>
            <span>
              {prog.done.toLocaleString('vi-VN')}/{prog.total.toLocaleString('vi-VN')}
              {prog.stage ? ` · ${prog.stage}` : ''}
            </span>
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
      {status === 'failed' && <ErrorBox>Job thất bại (mã thoát {String(job?.exit_code ?? '?')}). Xem nhật ký bên dưới.</ErrorBox>}
      {status === 'cancelled' && <div className="muted">Job đã bị huỷ. Kết quả đã chạy được giữ lại trong kho; chạy tiếp bằng <span className="mono">--resume</span> với cùng thư mục lần chạy.</div>}

      {/* Nhật ký thực thi trực tiếp theo mốc: mở sẵn khi đang chạy hoặc lỗi, thu gọn khi đã xong */}
      {lines.length > 0 && (
        status === 'running' || status === 'queued' || status === 'failed' ? (
          <div className="n-live-console" role="region" aria-label="Nhật ký thực thi trực tiếp">
            <div className="n-console-hdr">
              <div className="n-console-dots" aria-hidden="true">
                <span className="n-console-dot r" />
                <span className="n-console-dot y" />
                <span className="n-console-dot g" />
              </div>
              <span className="n-console-title">Nhật ký thực thi · Nautilus Trader</span>
              {status === 'running' && (
                <span className="n-console-live-badge">
                  <span className="n-console-live-pulse" />
                  TRỰC TIẾP
                </span>
              )}
            </div>
            <div className="n-console-body" ref={consoleBodyRef}>
              {lines.map((ln, i) => {
                const parsed = parseLogLine(ln)
                const isFinished = parsed.msg.includes('Hoàn tất!')
                return (
                  <div key={i} className="n-console-row">
                    {parsed.time && <span className="n-console-time">[{parsed.time}]</span>}
                    {parsed.step && <span className="n-console-step-badge">{parsed.step}</span>}
                    <span className={`n-console-msg ${isFinished ? 'done-msg' : ''}`}>{parsed.msg}</span>
                  </div>
                )
              })}
            </div>
          </div>
        ) : (
          <details className="n-details">
            <summary>Nhật ký thực thi đã hoàn tất ({lines.length} dòng)</summary>
            <div className="n-live-console" style={{ marginTop: 6 }}>
              <div className="n-console-body" style={{ maxHeight: 160 }}>
                {lines.map((ln, i) => {
                  const parsed = parseLogLine(ln)
                  return (
                    <div key={i} className="n-console-row">
                      {parsed.time && <span className="n-console-time">[{parsed.time}]</span>}
                      {parsed.step && <span className="n-console-step-badge">{parsed.step}</span>}
                      <span className="n-console-msg">{parsed.msg}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </details>
        )
      )}
    </div>
  )
}

