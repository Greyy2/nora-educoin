import React, { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { postSaveUserAlpha } from '../../../api'
import { fmtNum, fmtPct, fmtSPct, signClass } from '../../../lib/format'
import { normMetrics } from '../../../lib/customResult'
import '../../../styles/alpha.css'

// Checklist: CHỈ hiển thị bản của backend (result.checklist trước khi lưu; response của POST sau khi lưu). Không tính tiêu chí nào ở trình duyệt.
const MARK = { pass: '✓', fail: '⚠', missing: '—' }
export function Checklist({ checklist }) {
  const items = Array.isArray(checklist?.items) ? checklist.items : null
  return (
    <div className="push-alpha-checklist-section">
      <div className="checklist-header">
        <b>Checklist thẩm định chất lượng</b>
        <span className="checklist-sub">Cảnh báo tham khảo — không chặn lưu</span>
      </div>
      {items ? (
        <div className="checklist-items">
          {items.map((it) => (
            <div key={it.id} className={`checklist-item ${it.state === 'pass' ? 'pass' : it.state === 'fail' ? 'warn' : 'missing'}`} title={it.required ? `Yêu cầu: ${it.required}` : undefined}>
              <span className="check-icon" aria-hidden="true">{MARK[it.state] || '—'}</span>
              <span className="check-label">{it.label}</span>
              <span className="check-val">{it.value || 'không có dữ liệu'}</span>
            </div>
          ))}
        </div>
      ) : <p className="n-note" style={{ margin: 0 }}>Máy chủ chưa trả checklist cho lần chạy này; checklist sẽ có trong bản ghi sau khi lưu.</p>}
    </div>
  )
}

export default function SaveStrategyModal({ isOpen, onClose, jobId, code, defaultName = 'Chiến lược của tôi', result, source = 'alpha-create', alphaId = '', alphaVersion = 0, onSaved }) {
  const navigate = useNavigate()
  const [name, setName] = useState(defaultName)
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)
  const [asVersion, setAsVersion] = useState(true) // có alphaId: lưu thành phiên bản mới của alpha đó (bỏ chọn = alpha mới)

  useEffect(() => { if (isOpen) { setAsVersion(true); setDone(null); setError(null); setName(defaultName || 'Chiến lược của tôi') } }, [isOpen]) // eslint-disable-line react-hooks/exhaustive-deps -- chỉ đặt lại khi mở (lưu xong đổi tên bản nháp không được xoá màn hình thành công)
  if (!isOpen) return null

  const sim = normMetrics(result?.metrics?.simulate)
  const test = normMetrics(result?.metrics?.test)

  const submit = async (e) => {
    e.preventDefault()
    if (!name.trim()) { setError('Vui lòng nhập tên chiến lược'); return }
    setSubmitting(true); setError(null)
    try {
      const res = await postSaveUserAlpha({ job_id: jobId, code, name: name.trim(), note: note.trim(), source, alpha_id: alphaId && asVersion ? alphaId : undefined })
      setDone(res)
      if (onSaved) onSaved(res, name.trim())
    } catch (err) { setError(err.message || 'Lỗi lưu chiến lược') } finally { setSubmitting(false) }
  }

  return createPortal(
    <div className="n-modal-backdrop" onClick={onClose}>
      <div className="n-modal-content push-alpha-modal" role="dialog" aria-modal="true" aria-labelledby="save-t" onClick={(e) => e.stopPropagation()}>
        <header className="push-alpha-header">
          <div>
            <div className="push-alpha-kicker">Kho alpha người dùng · xác minh từ lần chạy thật</div>
            <h2 className="push-alpha-title" id="save-t">Lưu chiến lược</h2>
          </div>
          <button type="button" className="push-alpha-close-btn" onClick={onClose} aria-label="Đóng">✕</button>
        </header>

        {done ? (
          <div className="push-alpha-success">
            <div className="success-icon">✓</div>
            <h3>{done.action === 'versioned' ? `Đã lưu phiên bản ${done.version || ''} của chiến lược` : done.action === 'updated' ? 'Đã cập nhật chiến lược' : 'Đã lưu chiến lược'}</h3>
            <p>Mã bản ghi <span className="alpha-badge-id">{done.alpha_id}</span> · code, cấu hình, kết quả đầy đủ và bằng chứng đã được lưu; không còn phụ thuộc lần chạy tạm.</p>
            <div style={{ width: '100%', textAlign: 'left' }}><Checklist checklist={done.checklist} /></div>
            <div className="success-actions">
              <button type="button" className="n-btn brand" onClick={() => { onClose(); navigate(source === 'education' ? '/edu/me' : '/coin/alpha/catalog') }}>
                {source === 'education' ? 'Xem trong Hồ sơ chiến lược ➔' : 'Xem trong Thư viện alpha ➔'}
              </button>
              <button type="button" className="n-btn" onClick={onClose}>Đóng</button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="push-alpha-body">
            {error && <div className="push-alpha-err">⚠ {error}</div>}
            <div className="push-alpha-form-group">
              <label htmlFor="alpha-name">Tên chiến lược <span className="req">*</span></label>
              <input id="alpha-name" type="text" className="push-alpha-input" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} required />
            </div>
            {alphaId && (
              <label className="n-note" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="checkbox" checked={asVersion} onChange={(e) => setAsVersion(e.target.checked)} />
                Lưu thành phiên bản {alphaVersion ? alphaVersion + 1 : 'mới'} của alpha <span className="alpha-badge-id">{alphaId}</span> (bỏ chọn = tạo alpha mới)
              </label>
            )}
            <div className="push-alpha-form-group">
              <label htmlFor="alpha-note">Ghi chú (tùy chọn)</label>
              <textarea id="alpha-note" className="push-alpha-textarea" value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={1000}
                placeholder="Ý tưởng, điều kiện thị trường áp dụng…" />
            </div>
            <div className="push-alpha-metrics-grid">
              <div className="metric-box"><span className="lbl">Sharpe Test</span><span className={`val ${signClass(test?.sharpe)}`} title="Sharpe ngoài mẫu — cùng nguồn với dòng checklist">{fmtNum(test?.sharpe, 2)}</span></div>
              <div className="metric-box" title="CAGR toàn kỳ"><span className="lbl">CAGR</span><span className={`val ${signClass(sim?.cagr)}`}>{fmtSPct(sim?.cagr, 1)}</span></div>
              <div className="metric-box"><span className="lbl">Max Drawdown</span><span className="val neg">{fmtPct(sim?.mdd == null ? null : Math.abs(sim.mdd), 1)}</span></div>
              <div className="metric-box"><span className="lbl">Thắng (lệnh)</span><span className="val">{fmtPct(sim?.winTrades, 1)}</span></div>
              <div className="metric-box"><span className="lbl">Số lệnh</span><span className="val">{fmtNum(sim?.trades, 0)}</span></div>
            </div>
            <Checklist checklist={result?.checklist} />
            <footer className="push-alpha-footer">
              <button type="button" className="n-btn" onClick={onClose} disabled={submitting}>Hủy</button>
              <button type="submit" className="n-btn brand" disabled={submitting}>{submitting ? 'Đang lưu…' : 'Lưu chiến lược'}</button>
            </footer>
          </form>
        )}
      </div>
    </div>,
    document.querySelector('.v2') || document.body
  )
}
