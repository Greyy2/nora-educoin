import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Spinner } from '../../ui'
import CodeEditor from './CodeEditor'
import AssistChip, { AssistList } from './AssistChip'
import { getStrategySource, postAssistCheck, putStrategySource } from '../../../api'
import '../../../styles/alpha.css'

// Sửa mã nguồn một chiến lược HỆ THỐNG (data/alpha/strategies/<file>.py) tại chỗ: GET source -> sửa -> "Kiểm tra" -> "Lưu & nạp lại" (PUT kèm sha256, khoá lạc quan).
// Máy chủ sao lưu bản cũ, ghi nguyên tử, nạp lại sổ; các lượt backtest / book / funnel SAU ĐÓ dùng mã mới (docs/bmad/p10_alpha_contract.md §5).
export default function SystemStrategyEditor({ id, name, onClose, onSaved }) {
  const [src, setSrc] = useState(null)       // { id, file, code, sha256, legs } đã tải (sha256 = bản đang sửa)
  const [code, setCode] = useState('')
  const [loadErr, setLoadErr] = useState('')
  const [assist, setAssist] = useState(null)
  const [busy, setBusy] = useState('')       // '' | 'check' | 'save'
  const [msg, setMsg] = useState(null)       // { tone: ok|bad|warn, text, diagnostics?, conflict? }
  const [showList, setShowList] = useState(true)
  const ed = useRef(null)

  const load = () => {
    setLoadErr(''); setMsg(null)
    getStrategySource(id).then((r) => { setSrc(r); setCode(r.code || '') }, (e) => setLoadErr(e.status === 404 ? 'Không tìm thấy mã nguồn của chiến lược này.' : e.message))
  }
  useEffect(load, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = !!src && code !== src.code
  const tryClose = () => { if (dirty && !window.confirm('Có thay đổi chưa lưu vào chiến lược hệ thống. Đóng và bỏ thay đổi?')) return; onClose() }
  useEffect(() => {
    const key = (e) => { if (e.key === 'Escape' && !e.defaultPrevented && !document.querySelector('.cm-tooltip-autocomplete')) tryClose() }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!dirty) return undefined
    const f = (e) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', f)
    return () => window.removeEventListener('beforeunload', f)
  }, [dirty])

  async function check() {
    setBusy('check'); setMsg(null)
    try {
      const r = await postAssistCheck(code)
      setAssist({ status: 'done', ...r })
      const errs = (r.diagnostics || []).filter((d) => d.severity === 'error')
      if (r.verdict === 'REJECT') setMsg({ tone: 'bad', text: `Không hợp lệ: ${errs.length} lỗi.` })
      else if (r.kind && r.kind !== 'module') setMsg({ tone: 'bad', text: 'Đây không phải mã chiến lược hệ thống (kind=module): cần có STRATEGY = {...}.' })
      else setMsg({ tone: 'ok', text: `${r.verdict === 'ADAPT' ? 'Hợp lệ sau chuẩn hoá' : 'Hợp lệ'}${r.meta?.legs ? ` · chân: ${r.meta.legs.join(', ')}` : ''}` })
    } catch (e) { setMsg({ tone: 'bad', text: `Không kiểm tra được: ${e.message}` }) } finally { setBusy('') }
  }

  async function save() {
    setBusy('save'); setMsg(null)
    try {
      const r = await putStrategySource(id, code, src.sha256)
      const fresh = await getStrategySource(id).catch(() => null)
      setSrc(fresh || { ...src, code, sha256: r.sha256, legs: r.legs })
      if (fresh) setCode(fresh.code)
      setMsg({ tone: 'ok', text: `Đã lưu${r.reloaded ? ' và nạp lại sổ' : ' (chưa nạp lại)'}${r.normalized ? ' · đã ghi dạng chuẩn hoá' : ''}`, legs: r.legs, backup: r.backup })
      if (onSaved) onSaved(r)
    } catch (e) {
      const d = e.detail || {}
      if (e.status === 409 && d.code === 'SHA_CONFLICT') setMsg({ tone: 'bad', text: 'Mã nguồn đã bị đổi ở nơi khác kể từ lúc bạn mở. Tải lại bản mới (thay đổi của bạn trong ô này sẽ mất) rồi sửa lại.', conflict: true })
      else if (e.status === 409 && d.code === 'LIVE_BOT_RUNNING') setMsg({ tone: 'bad', text: d.message || 'Có bot live đang chạy dùng id chân này: không được đổi tên / bỏ id.' })
      else if (e.status === 422) { setAssist({ status: 'done', verdict: 'REJECT', diagnostics: d.diagnostics || [] }); setMsg({ tone: 'bad', text: d.message || 'Máy chủ từ chối: mã không đúng hợp đồng chiến lược.' }) }
      else setMsg({ tone: 'bad', text: d.message || e.message })
    } finally { setBusy('') }
  }

  const blocked = assist?.status === 'done' && assist.verdict === 'REJECT'
  return createPortal(
    <div className="n-modal-backdrop" onClick={tryClose}>
      <div className="n-modal-content sse-box" role="dialog" aria-modal="true" aria-label={`Sửa mã nguồn ${name || id}`} onClick={(e) => e.stopPropagation()}>
        <header className="sse-hd">
          <h2>Mã nguồn · {name || id}</h2>
          {src && <span className="n-note mono">{src.file} · sha {String(src.sha256).slice(0, 8)}</span>}
          {dirty && <span className="n-badge">● đã sửa</span>}
          <AssistChip a={assist} onToggle={() => setShowList(!showList)} onApply={(nc) => setCode(nc)} />
          <span className="se-sp" />
          <button type="button" className="n-btn sm" onClick={check} disabled={!src || !!busy}>{busy === 'check' ? <Spinner /> : null} Kiểm tra</button>
          <button type="button" className="n-btn brand sm" onClick={save} disabled={!src || !!busy || !dirty || blocked}
            title={!dirty ? 'Chưa có thay đổi' : blocked ? 'Sửa lỗi trước khi lưu' : 'Ghi file, sao lưu bản cũ và nạp lại sổ chiến lược'}>{busy === 'save' ? <Spinner /> : null} Lưu &amp; nạp lại</button>
          <button type="button" className="n-btn sm" onClick={tryClose}>Đóng</button>
        </header>
        <div className="sse-code">
          {!src && !loadErr && <p className="n-note se-pad"><Spinner /> Đang tải mã nguồn…</p>}
          {loadErr && <p className="n-note neg se-pad" role="alert">{loadErr} <button type="button" className="n-btn sm" onClick={load}>Thử lại</button></p>}
          {src && <CodeEditor ref={ed} value={code} onChange={setCode} onAssist={setAssist} label={`Mã nguồn ${src.file}`} />}
        </div>
        {(msg || (showList && assist?.diagnostics?.length > 0)) && (
          <footer className="sse-ft">
            {msg && (
              <div className={`n-note ${msg.tone === 'bad' ? 'neg' : ''}`} role={msg.tone === 'bad' ? 'alert' : 'status'}>
                {msg.text}{' '}
                {msg.conflict && <button type="button" className="n-btn sm" onClick={() => { setAssist(null); load() }}>Tải lại bản mới</button>}
                {msg.legs && <div className="sse-legs">Chân đã nạp lại: {msg.legs.map((l) => <span key={l} className="n-badge">{l}</span>)}{msg.backup && <span className="n-note mono">sao lưu: {msg.backup}</span>}</div>}
              </div>
            )}
            {showList && assist?.diagnostics?.length > 0 && <div style={{ maxHeight: 120, overflow: 'auto' }}><AssistList a={assist} onGo={(l, c) => ed.current?.goTo(l, c)} /></div>}
          </footer>
        )}
      </div>
    </div>,
    document.body
  )
}
