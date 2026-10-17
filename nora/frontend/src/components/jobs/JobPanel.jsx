import React, { useEffect, useState, useRef } from 'react'
import { Status, Spinner, ErrorBox } from '../ui'
import { JOB_STATUS, jobProgress, fmtRate } from '../../lib/jobs'
import { toMs, fmtDuration, fmtPct } from '../../lib/format'
import { postCancel } from '../../api'
import { ModeStamp, ResolvedParams } from '../optimize/RunModes'

// 5 bước tiêu chuẩn trong tiến trình Backtest
const BACKTEST_STEPS = [
  { id: 1, label: 'Biên dịch', key: 'Biên dịch' },
  { id: 2, label: 'Nạp dữ liệu', key: 'Nạp' },
  { id: 3, label: 'Tín hiệu', key: 'Tín hiệu' },
  { id: 4, label: 'Khớp lệnh', key: 'Khớp' },
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
export default function JobPanel({ job, status, error, title, onCancelled, isBacktest }) {
  const [now, setNow] = useState(Date.now())
  const [cancelling, setCancelling] = useState(false)
  const [cancelError, setCancelError] = useState(null)
  const [copied, setCopied] = useState(false)
  const consoleBodyRef = useRef(null)

  const copyLogs = () => {
    if (!lines.length) return
    navigator.clipboard.writeText(lines.join('\n')).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const live = status === 'queued' || status === 'running' || status === 'loading'
  useEffect(() => {
    if (!live) return undefined
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [live])
  useEffect(() => { if (!live) setCancelling(false) }, [live])

  const meta = JOB_STATUS[status] || { text: 'Đang chuẩn bị', cls: '' }
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

  // Xác định bước pipeline hiện tại từ backend (hỗ trợ hiển thị ngay lập tức khi vừa nhấn Chạy)
  const isBacktestPipeline = Boolean(isBacktest || prog?.total === 5 || String(title || '').toLowerCase().includes('backtest') || String(job?.kind || '').includes('backtest'))
  let targetStepIdx = 0
  if (status === 'done') {
    targetStepIdx = BACKTEST_STEPS.length
  } else if (prog) {
    if (prog.stage) {
      const idx = BACKTEST_STEPS.findIndex((s) => prog.stage.toLowerCase().includes(s.key.toLowerCase()))
      if (idx >= 0) targetStepIdx = idx
      else targetStepIdx = Math.max(0, Math.min(BACKTEST_STEPS.length - 1, (prog.done || 1) - 1))
    } else if (prog.done != null) {
      targetStepIdx = Math.max(0, Math.min(BACKTEST_STEPS.length - 1, prog.done - 1))
    }
  }

  // Paced Step Animator: Tạo chuyển động lướt nhanh, dứt khoát và mượt mà giữa các bước
  // Khi backend tính toán siêu tốc, UI vẫn lướt tuần tự qua từng bước một cách dứt khoát (110ms - 160ms), không bị cảm giác delay/lag
  const [displayedStepIdx, setDisplayedStepIdx] = useState(() => (status === 'done' ? BACKTEST_STEPS.length : 0))

  useEffect(() => {
    if (status === 'done') {
      setDisplayedStepIdx(BACKTEST_STEPS.length)
      return undefined
    }
    if (!isBacktestPipeline) {
      setDisplayedStepIdx(targetStepIdx)
      return undefined
    }

    if (displayedStepIdx < targetStepIdx) {
      const delay = (targetStepIdx - displayedStepIdx > 1) ? 80 : 120
      const timer = setTimeout(() => {
        setDisplayedStepIdx((prev) => Math.min(targetStepIdx, prev + 1))
      }, delay)
      return () => clearTimeout(timer)
    }
  }, [displayedStepIdx, targetStepIdx, isBacktestPipeline, status])

  // Nội suy phần trăm mượt mà đồng bộ với displayedStepIdx (chu kỳ 50ms, siêu nhạy)
  const [animatedPct, setAnimatedPct] = useState(0)

  useEffect(() => {
    if (status === 'done') {
      setAnimatedPct(100)
      return undefined
    }
    if (status !== 'running') {
      setAnimatedPct(status === 'queued' ? 4 : 0)
      return undefined
    }

    const currentStep = isBacktestPipeline ? displayedStepIdx : targetStepIdx
    const basePct = isBacktestPipeline
      ? Math.max(8, currentStep * 20 + 4)
      : Math.max(8, prog?.pct || 8)

    setAnimatedPct((prev) => Math.max(prev, basePct))

    const maxStepPct = isBacktestPipeline
      ? Math.min(status === 'done' ? 100 : 96, (currentStep + 1) * 20 - 2)
      : Math.min(96, (prog?.pct || 0) + 15)

    const timer = setInterval(() => {
      setAnimatedPct((prev) => {
        if (prev < maxStepPct) {
          const delta = (maxStepPct - prev) * 0.22 + 0.4
          return Math.min(maxStepPct, prev + delta)
        }
        return prev
      })
    }, 50)

    return () => clearInterval(timer)
  }, [status, displayedStepIdx, targetStepIdx, isBacktestPipeline, prog?.pct])

  const effectiveStepIdx = isBacktestPipeline ? displayedStepIdx : targetStepIdx
  const isAllStepsFinished = effectiveStepIdx >= BACKTEST_STEPS.length || (status === 'done' && displayedStepIdx >= BACKTEST_STEPS.length)

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

      {/* THANH TIẾN ĐỘ HỢP NHẤT: Kích thước rộng hơn, chứa trực tiếp các bước pipeline bên trong */}
      {isBacktestPipeline ? (
        <div className="n-unified-pipeline-wrap" role="group" aria-label="Tiến trình Backtest">
          <div
            className="n-unified-pipeline-bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(isAllStepsFinished ? 100 : animatedPct)}
          >
            {/* Lớp fill nền gradient chuyển động theo tiến độ */}
            <div
              className={`n-unified-fill ${status === 'running' ? 'is-running' : ''}`}
              style={{ width: `${Math.min(100, Math.max(isAllStepsFinished ? 100 : 6, animatedPct))}%` }}
            />

            {/* Các bước pipeline hiển thị trực tiếp bên trong thanh */}
            <div className="n-unified-steps">
              {BACKTEST_STEPS.map((step, idx) => {
                const isDone = isAllStepsFinished || idx < effectiveStepIdx
                const isActive = !isAllStepsFinished && idx === effectiveStepIdx
                const stepClass = isDone ? 'done' : isActive ? 'active' : 'pending'
                const arrowDone = isDone || (idx < effectiveStepIdx)

                return (
                  <React.Fragment key={step.id}>
                    <div className={`n-unified-step-item ${stepClass}`}>
                      <span className="n-unified-badge">
                        {isDone ? '✓' : step.id}
                      </span>
                      <span className="n-unified-label">{step.label}</span>
                    </div>
                    {idx < BACKTEST_STEPS.length - 1 && (
                      <span className={`n-unified-arrow ${arrowDone ? 'done' : ''}`} aria-hidden="true">→</span>
                    )}
                  </React.Fragment>
                )
              })}
            </div>
          </div>

          {/* Dòng metadata thông số tiến độ bên dưới */}
          <div className="n-prog-meta mono">
            <b>{fmtPct(isAllStepsFinished ? 100 : Math.round(animatedPct), 0)}</b>
            <span>
              {isAllStepsFinished
                ? '5/5 · Hoàn tất tất cả các bước'
                : `Bước ${Math.min(5, effectiveStepIdx + 1)}/5: ${BACKTEST_STEPS[effectiveStepIdx]?.label || prog?.stage || ''}`}
            </span>
            {elapsed != null && (status === 'running' || !isAllStepsFinished) && (
              <span>Thời gian {fmtDuration(elapsed)}</span>
            )}
            {prog?.peakMb != null && <span className="muted">RAM đỉnh {Math.round(prog.peakMb)} MB</span>}
          </div>
        </div>
      ) : (
        /* Fallback cho các loại job khác không phải Backtest 5 bước */
        prog && (status === 'running' || status === 'done' || status === 'cancelled') && (
          <div className="n-prog" role="group" aria-label="Tiến độ thực thi">
            <div
              className={`n-prog-bar download-style ${status === 'running' ? 'is-running' : ''}`}
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(status === 'done' ? 100 : animatedPct)}
            >
              <span style={{ width: `${Math.min(100, Math.max(status === 'done' ? 100 : 5, animatedPct))}%` }} />
            </div>
            <div className="n-prog-meta mono">
              <b>{fmtPct(status === 'done' ? 100 : Math.round(animatedPct), 0)}</b>
              <span>
                {`${prog.done.toLocaleString('vi-VN')}/${prog.total.toLocaleString('vi-VN')}${prog.stage ? ` · ${prog.stage}` : ''}`}
              </span>
              {elapsed != null && status === 'running' && (
                <span>Thời gian {fmtDuration(elapsed)}</span>
              )}
              {prog.rate > 0 && status === 'running' && (
                <span>Tốc độ {fmtRate(prog.rate)}</span>
              )}
              {prog.eta != null && status === 'running' && (
                <span>Còn khoảng {fmtDuration(prog.eta)}</span>
              )}
              {prog.peakMb != null && <span className="muted">RAM đỉnh {Math.round(prog.peakMb)} MB</span>}
            </div>
          </div>
        )
      )}

      {job?.mode && <ModeStamp mode={job.mode} customGates={job.custom_gates} promotable={job.promotable} ignored={job.ignored_client_params} />}
      {job?.resolved && <ResolvedParams job={job} />}
      <ErrorBox>{error}</ErrorBox>
      <ErrorBox>{cancelError}</ErrorBox>
      {status === 'failed' && <ErrorBox>Job thất bại (mã thoát {String(job?.exit_code ?? '?')}). Xem nhật ký bên dưới.</ErrorBox>}
      {status === 'cancelled' && <div className="muted">Job đã bị huỷ. Kết quả đã chạy được giữ lại trong kho; chạy tiếp bằng <span className="mono">--resume</span> với cùng thư mục lần chạy.</div>}

      {/* Nhật ký thực thi trực tiếp dạng Terminal Console chuẩn */}
      {lines.length > 0 && (
        <div className="n-live-console" role="region" aria-label="Terminal Output">
          <div className="n-console-hdr">
            <div className="n-console-dots" aria-hidden="true">
              <span className="n-console-dot r" />
              <span className="n-console-dot y" />
              <span className="n-console-dot g" />
            </div>
            <span className="n-console-title" style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace' }}>
              Terminal Console (out.log)
            </span>
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                type="button"
                onClick={copyLogs}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--n-line, #334155)',
                  color: copied ? 'var(--n-pos, #10b981)' : 'var(--n-ink-2, #94a3b8)',
                  borderRadius: 4,
                  padding: '2px 8px',
                  fontSize: 10.5,
                  cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
                title="Sao chép toàn bộ nhật ký"
              >
                {copied ? '✓ Đã chép' : 'Sao chép'}
              </button>
              {status === 'running' ? (
                <span className="n-console-live-badge">
                  <span className="n-console-live-pulse" />
                  LIVE
                </span>
              ) : status === 'done' ? (
                <span className="n-badge ok" style={{ fontSize: 10 }}>DONE ✓</span>
              ) : null}
            </div>
          </div>
          <div className="n-console-body" ref={consoleBodyRef} style={{ maxHeight: 220, background: '#0b0f19', color: '#e2e8f0', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Fira Code", monospace' }}>
            {lines.map((ln, i) => {
              const parsed = parseLogLine(ln)
              const isFinished = parsed.msg.includes('Hoàn tất!')
              return (
                <div key={i} className="n-console-row" style={{ display: 'flex', gap: 6 }}>
                  <span style={{ color: '#475569', userSelect: 'none' }}>$</span>
                  {parsed.time && <span className="n-console-time" style={{ color: '#64748b' }}>[{parsed.time}]</span>}
                  {parsed.step && <span className="n-console-step-badge">{parsed.step}</span>}
                  <span className={`n-console-msg ${isFinished ? 'done-msg' : ''}`} style={{ color: isFinished ? '#34d399' : '#e2e8f0' }}>{parsed.msg}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

