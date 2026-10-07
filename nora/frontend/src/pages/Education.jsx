import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Status, Spinner, ErrorBox, Empty } from '../components/ui'
import JobPanel from '../components/JobPanel'
import CodeEditor from '../components/studio/CodeEditor'
import RunSettings, { POSITION_FIELDS } from '../components/studio/RunSettings'
import EduResult from '../components/education/EduResult'
import EduExplain from '../components/education/EduExplain'
import PrecomputedNote from '../components/education/PrecomputedNote'
import usePrecomputed from '../components/education/usePrecomputed'
import SaveStrategyModal from '../components/studio/SaveStrategyModal'
import SavedAlphaList from '../components/studio/SavedAlphaList'
import LeaveGuardDialog from '../components/studio/LeaveGuardDialog'
import { EDU_SAMPLES } from '../components/education/educationSamples'
import useJob from '../hooks/useJob'
import useAsync from '../hooks/useAsync'
import useMemState from '../hooks/useMemState'
import useUnsavedGuard from '../hooks/useUnsavedGuard'
import { useRunDefaults, resolveForm } from '../lib/eduDefaults'
import { newDraft, isDraftDirty, configToForm } from '../lib/studioDraft'
import { useCatalog } from '../context/Catalog'
import { postCompileStrategy, postCustomBacktest, postSaveUserAlpha, getUserAlphas, getUserAlphaDetail } from '../api'
import { parseCompileError, normWarnings } from '../lib/customResult'
import { isNum, toMs, fmtDuration } from '../lib/format'
import '../styles/strategyEditor.css'
import '../styles/education.css'
import '../styles/diagnostics.css'

// Trạng thái trang CHỈ trong bộ nhớ (mất khi đóng / tải lại trang). Lượt chạy của người học là TẠM THỜI; chỉ "Lưu chiến lược" mới ghi vào kho alpha người dùng.
const DEFAULT_FORM = { profile: 'xno', symbols: ['BTC@perp'], pos: {} } // start/end/train/vốn lấy từ useRunDefaults (cấu hình kết quả tính trước)
const makeInitial = () => ({ drafts: [newDraft(EDU_SAMPLES[0].name, EDU_SAMPLES[0].code, { sampleKey: EDU_SAMPLES[0].key })], active: '', form: {} })
const POSITION_KEYS = POSITION_FIELDS.map((f) => f.key)

const num = (v) => (v === '' || v == null ? NaN : Number(v))
const label = (x) => (typeof x === 'string' ? x : x?.side || x?.name || x?.id || JSON.stringify(x))

function validate(form, code) {
  const out = []
  if (!code.trim()) out.push('Chưa có code chiến lược.')
  if (!form.start || !form.end) out.push('Ngày bắt đầu / kết thúc chưa hợp lệ (dd/mm/yyyy).')
  else if (form.start >= form.end) out.push('Ngày kết thúc phải sau ngày bắt đầu.')
  const r = num(form.train_ratio)
  if (!(r > 0 && r < 1)) out.push('Tỉ lệ train phải nằm trong khoảng (0, 1), ví dụ 0.7.')
  if (!(num(form.capital) > 0)) out.push('Vốn ban đầu phải lớn hơn 0.')
  if (form.profile === 'nora') {
    if (!form.symbols.length) out.push('Chọn ít nhất một tài sản.')
    POSITION_FIELDS.forEach((f) => {
      const v = form.pos?.[f.key]
      if (v !== '' && v != null && !(num(v) >= 0)) out.push(`Tham số quản lý vị thế "${f.key}" phải là số không âm.`)
    })
  }
  return out
}

function buildBody(form, code) {
  const body = { code, profile: form.profile, start: form.start, end: form.end, train_ratio: num(form.train_ratio), initial_capital: num(form.capital) }
  if (form.profile === 'xno') body.universe = 'TOP10'
  else {
    body.symbols = form.symbols
    const position = {}
    // Mẫu nora có thể kèm khoá ngoài ô nhập (vd atr_frame: '24h'): gửi nguyên, số thì ép số.
    Object.entries(form.pos || {}).forEach(([k, v]) => { if (v !== '' && v != null) position[k] = Number.isNaN(Number(v)) ? v : Number(v) })
    if (Object.keys(position).length) body.position = position
  }
  return body
}

const ICON = {
  gear: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" /></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>,
  save: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 4h11l3 3v13H5z" /><path d="M8 4v5h7V4M8 20v-6h8v6" /></svg>,
  copy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>,
  play: <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"><path d="M7 5l12 7-12 7z" /></svg>,
}

function JobLine({ job, onClear, savedId }) {
  const t0 = toMs(job?.started) || toMs(job?.created)
  const t1 = toMs(job?.finished)
  const lines = job?.log_tail || []
  return (
    <span className="se-jobline">
      <Status tone="ok">Hoàn tất</Status>
      <span className="mono muted" title="Mã job (chạy tạm, tự xoá sau 24 giờ nếu không lưu)">{job?.job_id || job?.id}</span>
      {t0 && t1 && <span className="muted">{fmtDuration((t1 - t0) / 1000)}</span>}
      {lines.length > 0 && <details className="se-logd"><summary>Log</summary><pre className="mono">{lines.join('\n')}</pre></details>}
      {savedId && <Status tone="ok">Đã lưu {savedId}</Status>}
      <button type="button" className="se-link" onClick={onClear}>Bỏ kết quả</button>
    </span>
  )
}

function StoredLine({ rec }) {
  return (
    <span className="se-jobline">
      <Status tone="ok">Đã lưu</Status>
      <span className="mono muted" title="Mã alpha">{rec.id}</span>
      <span className="muted" title="Kết quả đã lưu cùng bản ghi, không chạy lại">{rec.updated_at ? String(rec.updated_at).slice(0, 10) : ''}</span>
    </span>
  )
}

function CompileOutput({ c, stale }) {
  if (!c) return <p className="n-note se-out">Bấm “Kiểm tra” để biên dịch code và xem tóm tắt mà không chạy backtest.</p>
  const warns = normWarnings(c.warnings)
  const m = c.meta || {}
  const list = (v) => (Array.isArray(v) ? v : []).map(label)
  return (
    <div className="se-out" aria-live="polite">
      {stale && <p className="n-note">Code đã sửa sau lần kiểm tra này.</p>}
      {c.ok ? (
        <>
          <div className="se-meta">
            <Status tone="ok">Hợp lệ</Status>
            {m.timeframe && <span>Khung <b className="mono">{m.timeframe}</b></span>}
            {isNum(m.warmup_bars) && <span>Khởi động <b className="mono">{m.warmup_bars}</b> nến</span>}
            {isNum(m.position_levels) && <span>Mức vị thế <b className="mono">{m.position_levels}</b></span>}
            {c.hash && <span className="mono muted" title="Mã băm chương trình">{String(c.hash).slice(0, 12)}</span>}
          </div>
          {list(m.legs).length > 0 && <div className="se-meta"><span className="n-lbl">Chân lệnh</span>{list(m.legs).map((l) => <span key={l} className={`n-badge ${l.toLowerCase()}`}>{l}</span>)}</div>}
          {list(m.features).length > 0 && <div className="se-meta"><span className="n-lbl">Chỉ báo</span>{list(m.features).map((f) => <span key={f} className="n-badge">{f}</span>)}</div>}
          {warns.length > 0 && <ul className="n-events se-warns">{warns.map((w, i) => <li key={i}><span className="ic warn">▲</span><span className="tx">{w}</span></li>)}</ul>}
        </>
      ) : (
        <div className="se-errbox">
          <Status tone="bad">Lỗi cú pháp</Status>
          <p className="se-errmsg">{c.error?.message || 'Code không hợp lệ.'}</p>
        </div>
      )}
    </div>
  )
}

export default function Education() {
  const [st, set] = useMemState(makeInitial)
  const runDefaults = useRunDefaults()
  const form = resolveForm(DEFAULT_FORM, st.form, runDefaults)
  const drafts = st.drafts
  const draft = drafts.find((d) => d.id === st.active) || drafts[0]
  const setForm = (patch) => set((p) => ({ form: { ...p.form, ...patch } }))
  const setDrafts = (next, active) => set({ drafts: next, ...(active ? { active } : {}) })
  const patchById = (id, patch) => set((p) => ({ drafts: p.drafts.map((d) => (d.id === id ? { ...d, ...patch } : d)) }))
  const patchDraft = (patch) => patchById(draft.id, patch)

  const { data: cat, loading: catLoading, error: catError } = useCatalog()
  const universe = cat?.universe || []
  const windows = cat?.windows?.start && cat?.windows?.end ? { start: cat.windows.start, end: cat.windows.end } : null
  const saved = useAsync(getUserAlphas, [])

  const [compiled, setCompiled] = useState(null)
  const [busy, setBusy] = useState('')            // '' | 'compile' | 'run'
  const [openingId, setOpeningId] = useState('')
  const [runErr, setRunErr] = useState(null)
  const [note, setNote] = useState(null)
  const nonce = useRef(0)

  // 2 Tab rõ ràng: Mẫu chiến lược và Kết quả & Phân tích
  const [tab, setTab] = useState('samples')
  const [setOpen, setSetOpen] = useState(false)
  const [strip, setStrip] = useState(false)
  const [sampleCategory, setSampleCategory] = useState('All')
  const [sampleQuery, setSampleQuery] = useState('')
  const setRef = useRef(null)

  useEffect(() => {
    if (!setOpen) return undefined
    const click = (e) => { if (setRef.current && !setRef.current.contains(e.target)) setSetOpen(false) }
    const key = (e) => { if (e.key === 'Escape') setSetOpen(false) }
    document.addEventListener('mousedown', click); document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', click); document.removeEventListener('keydown', key) }
  }, [setOpen])

  // Lắng nghe jobId của TỪNG draft riêng biệt
  const currentJobId = draft.jobId || null
  const { job, status, error: jobErr } = useJob(currentJobId)
  const running = status === 'queued' || status === 'running' || status === 'loading'
  const jobResult = status === 'done' ? job?.result : null
  // alpha_id (backend tính) của lần chạy đã xong: so với bản đã lưu để biết còn thay đổi chưa lưu hay không
  useEffect(() => { if (jobResult?.alpha_id && draft.runAlpha !== jobResult.alpha_id) patchById(draft.id, { runAlpha: jobResult.alpha_id }) }, [jobResult?.alpha_id, draft.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const problems = useMemo(() => validate(form, draft.code), [form, draft.code]) // eslint-disable-line react-hooks/exhaustive-deps
  const stale = compiled && compiled.code !== draft.code
  const issue = !!(compiled && !stale && !compiled.ok)
  const errLine = compiled && !stale && !compiled.ok ? compiled.error?.line : null

  const showCompiled = (code, r) => {
    nonce.current += 1
    setCompiled({ code, ok: !!r.ok, hash: r.program_hash, meta: r.meta, warnings: r.warnings, error: r.ok ? null : parseCompileError(r.error), nonce: nonce.current })
  }

  async function compile() {
    if (busy || !draft.code.trim()) return
    setBusy('compile'); setNote(null)
    try { showCompiled(draft.code, await postCompileStrategy(draft.code)) } catch (e) {
      const err = parseCompileError(e.message)
      showCompiled(draft.code, { ok: false, error: e.status === 0 ? { message: e.message } : err })
    } finally { setBusy('') }
  }

  async function run() {
    if (busy || running || problems.length) return
    setBusy('run'); setRunErr(null); setNote(null)
    const id0 = draft.id
    const code0 = draft.code
    try {
      const r = await postCustomBacktest(buildBody(form, code0))
      const id = r?.job_id || r?.id
      if (!id) throw new Error('Máy chủ không trả mã job.')
      patchById(id0, { jobId: id, runCode: code0, runAlpha: '', stored: null })
      setTab('results')
    } catch (e) {
      const err = parseCompileError(e.message)
      if (err?.line) showCompiled(code0, { ok: false, error: err })
      setRunErr(err?.line ? null : e.message)
    } finally { setBusy('') }
  }

  // Lưu được khi có lần chạy XONG của CHÍNH code đang soạn (cùng văn bản lúc chạy, hoặc cùng program_hash với bản biên dịch gần nhất); máy chủ vẫn kiểm lại program_hash.
  const sameProgram = !!jobResult && (draft.runCode === draft.code || (!!compiled?.ok && compiled.code === draft.code && compiled.hash === jobResult.program_hash))
  const canSave = sameProgram && !busy
  const saveWhy = !draft.jobId ? 'Bấm “Chạy thử nghiệm” cho code hiện tại trước khi lưu' : !jobResult ? 'Chờ lần chạy hoàn tất' : !sameProgram ? 'Kết quả không thuộc code đang soạn: chạy lại trước khi lưu' : 'Lưu chiến lược (code + cấu hình + kết quả đầy đủ)'

  function markSaved(res, name) {
    patchById(draft.id, { saved: { alpha_id: res.alpha_id, code: draft.code, name: name || draft.name }, runAlpha: res.alpha_id, name: name || draft.name, stored: null })
    saved.reload()
  }

  async function saveForLeave() {
    const name = draft.name.trim() || 'Chiến lược của tôi'
    markSaved(await postSaveUserAlpha({ job_id: draft.jobId, code: draft.code, name, note: '', source: 'education' }), name)
  }

  async function openSaved(id) {
    const have = drafts.find((d) => d.saved?.alpha_id === id)
    if (have) { set({ active: have.id }); setTab('results'); return }
    setOpeningId(id); setNote(null)
    try {
      const rec = await getUserAlphaDetail(id)
      const d = newDraft(rec.name || rec.id, rec.code || '', { saved: { alpha_id: rec.id, code: rec.code || '', name: rec.name || rec.id }, stored: rec, runAlpha: rec.id })
      set((p) => ({ drafts: [...p.drafts, d], active: d.id, form: { ...p.form, ...configToForm(rec.config, POSITION_KEYS) } }))
      setCompiled(null); setTab('results')
      if (!rec.result) setNote({ tone: 'bad', text: 'Bản ghi cũ không có kết quả đã lưu: đã nạp code và cấu hình, hãy chạy lại.' })
    } catch (e) { setNote({ tone: 'bad', text: `Không mở được: ${e.message}` }) } finally { setOpeningId('') }
  }

  const addDraft = (name, code, key = '') => { const d = newDraft(name, code, { sampleKey: key }); setDrafts([...drafts, d], d.id) }
  function closeDraft(id) {
    const d0 = drafts.find((d) => d.id === id)
    if (isDraftDirty(d0) && !window.confirm(`“${d0.name || 'Mẫu'}” có thay đổi chưa lưu và sẽ mất khi đóng. Đóng không lưu?`)) return
    const rest = drafts.filter((d) => d.id !== id)
    if (!rest.length) { const d = newDraft(EDU_SAMPLES[0].name, EDU_SAMPLES[0].code, { sampleKey: EDU_SAMPLES[0].key }); setDrafts([d], d.id); return }
    setDrafts(rest, id === draft.id ? rest[Math.max(0, drafts.findIndex((d) => d.id === id) - 1)].id : undefined)
  }

  // Kết quả hiển thị: lần chạy mới (job xong) > bản đã lưu mở từ "Đã lưu" > kết quả chạy sẵn của mẫu (khớp program_hash)
  const stored = !draft.jobId ? draft.stored : null
  const sampleKey = draft.sampleKey || EDU_SAMPLES.find((x) => x.code.trim() === (draft.code || '').trim())?.key || ''
  const pre = usePrecomputed({ code: draft.code, profile: form.profile, sampleKey })
  const preRec = stored ? null : pre.record
  const result = jobResult || stored?.result || preRec || null
  const usingPre = !jobResult && !!preRec
  const preNote = preRec ? <PrecomputedNote record={preRec} item={pre.item} superseded={!!jobResult} /> : null
  const preStale = !jobResult && !stored && pre.state === 'stale'

  const tm = compiled?.meta?.timeframe
  const uniText = form.profile === 'xno' ? 'TOP10' : `${form.symbols.length} tài sản`
  const dirtyDrafts = drafts.filter(isDraftDirty)
  const dirty = isDraftDirty(draft)
  const [saveOpen, setSaveOpen] = useState(false)
  const blocker = useUnsavedGuard(dirtyDrafts.length > 0)
  const chip = draft.saved ? (dirty ? 'Đã sửa, chưa lưu' : 'Đã lưu') : dirty ? 'Chưa lưu' : 'Nháp'

  // 3 Tab: Mẫu chiến lược, Giải thích thuật toán và Kết quả & Phân tích
  const TABS = [
    ['samples', 'Mẫu chiến lược'],
    ['explain', 'Giải thích thuật toán'],
    ['results', 'Kết quả & Phân tích'],
  ]
  const useSample = (s) => {
    addDraft(s.name, s.code, s.key)
    // Mẫu chạy đúng hồ sơ + tham số vị thế đã khai báo (xno mặc định: không có position)
    setForm({ profile: s.profile || 'xno', pos: { ...(s.position || {}) } })
    setCompiled(null)
    setTab('samples')
  }

  const categories = useMemo(() => {
    const list = Array.from(new Set(EDU_SAMPLES.map((s) => s.category)))
    return ['Tất cả', ...list]
  }, [])

  const filteredSamples = useMemo(() => {
    return EDU_SAMPLES.filter((s) => {
      const matchCat = sampleCategory === 'All' || sampleCategory === 'Tất cả' || s.category === sampleCategory
      const q = sampleQuery.trim().toLowerCase()
      const matchQ = !q || s.name.toLowerCase().includes(q) || s.summary.toLowerCase().includes(q) || s.category.toLowerCase().includes(q)
      return matchCat && matchQ
    })
  }, [sampleCategory, sampleQuery])

  return (
    <div className="se-ws">
      <div className="se-left">
        <div className="se-tabs" role="tablist" aria-label="Bản nháp mẫu chiến lược">
          {drafts.map((d) => (
            <div key={d.id} className={`se-tab ${d.id === draft.id ? 'on' : ''}`}>
              <button type="button" role="tab" aria-selected={d.id === draft.id} title={d.name} onClick={() => set({ active: d.id })}>{isDraftDirty(d) ? '● ' : ''}{d.name || 'Mẫu'}</button>
              <button type="button" className="x" aria-label={`Đóng ${d.name}`} onClick={() => closeDraft(d.id)}>×</button>
            </div>
          ))}
          <button type="button" className="se-add" title="Thêm mẫu mới" aria-label="Thêm mẫu mới" onClick={() => addDraft(`Mẫu ${drafts.length + 1}`, EDU_SAMPLES[0].code)}>+</button>
        </div>

        <div className="se-hd">
          <input className="se-name" aria-label="Tên mẫu chiến lược" placeholder="Tên mẫu chiến lược" value={draft.name} onChange={(e) => patchDraft({ name: e.target.value })} />
          <div className="se-chips">
            <button type="button" className="se-chip" onClick={() => setSetOpen(true)} title={draft.saved ? `Alpha ${draft.saved.alpha_id}` : 'Chưa lưu: bản nháp và kết quả chạy chỉ tồn tại trong phiên này'}><i className={`d ${draft.saved && !dirty ? 'ok' : ''}`} />{chip}</button>
            <button type="button" className="se-chip" onClick={() => setSetOpen(true)} title="Hồ sơ thực thi"><i className="d" />{form.profile}</button>
            <button type="button" className="se-chip" onClick={() => setSetOpen(true)} title="Rổ tài sản"><i className="d" />{uniText}</button>
            {tm && <span className="se-chip"><i className="d" />{tm}</span>}
          </div>
          <span className="se-sp" />
          <div className="se-btns" ref={setRef}>
            <button type="button" className={`n-icon-btn ${problems.length ? 'warn' : ''}`} aria-label="Cài đặt chạy" aria-expanded={setOpen} title="Cài đặt tham số thực thi" onClick={() => setSetOpen(!setOpen)}>{ICON.gear}</button>
            <button type="button" className="n-icon-btn" aria-label="Kiểm tra code" title="Biên dịch kiểm tra cú pháp (không chạy)" disabled={!!busy || !draft.code.trim()} onClick={() => { compile(); setStrip(true) }}>{busy === 'compile' ? <Spinner /> : ICON.check}</button>
            <button type="button" className="n-icon-btn" aria-label="Nhân bản" title="Nhân bản mẫu sang tab mới" onClick={() => addDraft(`${draft.name} (bản sao)`, draft.code)}>{ICON.copy}</button>
            {setOpen && (
              <div className="n-pop se-setp" role="dialog" aria-label="Cài đặt chạy">
                <div className="n-pop-h"><b>Cài đặt thông số thực nghiệm</b><button type="button" className="n-btn sm" onClick={() => setSetOpen(false)}>Đóng</button></div>
                <div className="se-setb">
                  <RunSettings form={form} setForm={setForm} universe={universe} catalogLoading={catLoading} catalogError={catError} windows={windows} problems={problems} />
                </div>
              </div>
            )}
          </div>
          <button type="button" className="se-save" onClick={() => setSaveOpen(true)} disabled={!canSave} title={saveWhy}>{ICON.save} Lưu chiến lược</button>
          <button type="button" className="se-run" onClick={run} disabled={!!busy || running || problems.length > 0} title={problems[0] || 'Ctrl/⌘ + Enter'}>
            {busy === 'run' || running ? <><Spinner /> {status === 'queued' ? 'Đang xếp hàng…' : 'Đang tính toán…'}</> : <>{ICON.play} Chạy thử nghiệm</>}
          </button>
        </div>

        <div className="se-code">
          <CodeEditor value={draft.code} onChange={(code) => patchDraft({ code })} onRun={run} errorLine={errLine} errorKey={compiled?.nonce} />
          <div className={`se-strip ${strip || issue ? 'open' : ''} ${issue ? 'bad' : ''}`}>
            <button type="button" className="se-strip-h" aria-expanded={strip || issue} onClick={() => setStrip(!(strip || issue))}>
              <span className={`se-dot ${!compiled ? '' : compiled.ok && !stale ? 'ok' : issue ? 'bad' : 'warn'}`} />
              <b>Kiểm tra cú pháp</b>
              <span className="se-strip-s">{note ? note.text : !compiled ? 'Chưa kiểm tra · Ctrl/⌘ + Enter = chạy · Tab = thụt 4 dấu cách' : stale ? 'Code đã sửa sau lần kiểm tra' : compiled.ok ? `Hợp lệ${tm ? ` · khung ${tm}` : ''}` : `Lỗi${compiled.error?.line ? ` · dòng ${compiled.error.line}` : ''}`}</span>
              <span className="se-sp" /><span aria-hidden="true">{strip || issue ? '▾' : '▴'}</span>
            </button>
            {(strip || issue) && <div className="se-strip-b"><CompileOutput c={compiled} stale={stale} /></div>}
          </div>
        </div>
      </div>

      <div className="se-right">
        <div className="se-rtabs" role="tablist" aria-label="Khu vực bên phải">
          {TABS.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        <div className="se-rbody">
          {tab === 'samples' && (
            <div className="se-samples">
              <h3 className="se-h3">Thư viện Mẫu Chiến Lược ({EDU_SAMPLES.length} Mẫu Định Lượng)</h3>
              <p className="n-note" style={{ marginBottom: 12 }}>
                Bộ 50 mẫu chiến lược chia thành 5 trường phái định lượng kinh điển, đầy đủ <b>chú thích tiếng Anh từng khối lệnh</b> và biên dịch chuẩn 100% trên engine Nautilus/Nora.
              </p>

              <div className="edu-filters-bar">
                <input
                  type="text"
                  className="edu-search-input"
                  placeholder="🔍 Tìm kiếm mẫu chiến lược (VD: KEMA, Breakout, RSI, Z-Score, ATR, Trend, Turtle...)..."
                  value={sampleQuery}
                  onChange={(e) => setSampleQuery(e.target.value)}
                />
                <div className="edu-pills">
                  {categories.map((cat) => {
                    const isAct = (cat === 'Tất cả' && (sampleCategory === 'All' || sampleCategory === 'Tất cả')) || sampleCategory === cat
                    const count = cat === 'Tất cả' ? EDU_SAMPLES.length : EDU_SAMPLES.filter((s) => s.category === cat).length
                    return (
                      <button
                        key={cat}
                        type="button"
                        className={`edu-pill ${isAct ? 'active' : ''}`}
                        onClick={() => setSampleCategory(cat === 'Tất cả' ? 'All' : cat)}
                      >
                        {cat} ({count})
                      </button>
                    )
                  })}
                </div>
              </div>

              <div className="se-cards">
                {filteredSamples.map((s) => (
                  <button key={s.key} type="button" className="edu-sample-card" onClick={() => useSample(s)}>
                    <div className="edu-sample-top">
                      <span className="edu-sample-lesson">{s.category}</span>
                      <span className={`edu-sample-diff ${s.difficulty.toLowerCase()}`}>{s.difficulty}</span>
                    </div>
                    <div className="edu-sample-name">{s.name}</div>
                    <div className="edu-sample-summary">{s.summary}</div>
                  </button>
                ))}
              </div>
              {filteredSamples.length === 0 && (
                <p className="n-note" style={{ textAlign: 'center', margin: '20px 0' }}>
                  Không tìm thấy mẫu nào phù hợp với bộ lọc hoặc từ khoá “{sampleQuery}”.
                </p>
              )}

              <div style={{ marginTop: 20 }}>
                <SavedAlphaList list={saved} onOpen={openSaved} openingId={openingId} activeId={draft.saved?.alpha_id || ''} />
              </div>
            </div>
          )}

          {tab === 'explain' && (
            <div className="se-resw">
              <EduExplain draft={draft} result={result} profile={form.profile} position={form.pos} note={preNote} staleNote={preStale} precomputedExplain={stored ? stored.explain || null : usingPre ? preRec.explain : null} />
            </div>
          )}

          {tab === 'results' && (
            <div className="se-resw">
              <ErrorBox>{runErr}</ErrorBox>
              {note && note.tone === 'bad' && <p className="n-note neg" role="alert">{note.text}</p>}
              {currentJobId && status !== 'done' && (
                <div className="se-job">
                  <JobPanel job={job} status={status} error={jobErr} title="Engine Backtest Thực Nghiệm" />
                  <button type="button" className="n-btn sm" onClick={() => patchDraft({ jobId: '', runCode: '', runAlpha: '' })} disabled={running}>Bỏ kết quả</button>
                </div>
              )}
              {currentJobId && status === 'done' && (
                <>
                  {preNote && <div style={{ marginBottom: 8 }}>{preNote}</div>}
                  <EduResult
                    key={currentJobId}
                    result={jobResult}
                    jobLine={<JobLine job={job} savedId={draft.saved && draft.saved.alpha_id === draft.runAlpha ? draft.saved.alpha_id : ''} onClear={() => patchDraft({ jobId: '', runCode: '', runAlpha: '' })} />}
                  />
                </>
              )}
              {!currentJobId && stored?.result && <EduResult key={`st-${stored.id}`} result={stored.result} jobLine={<StoredLine rec={stored} />} />}
              {!currentJobId && !stored?.result && usingPre && (
                <>
                  <div style={{ marginBottom: 8 }}>{preNote}</div>
                  <EduResult key={`pre-${preRec.key}-${preRec.generated_at}`} result={preRec} />
                </>
              )}
              {!currentJobId && preStale && (
                <p className="dg-pre stale" style={{ marginBottom: 8 }}>Mã đã khác bản gốc của mẫu nên kết quả chạy sẵn không còn khớp (hash chương trình thay đổi). Bấm “Chạy thử nghiệm” để có kết quả mới.</p>
              )}
              {!currentJobId && !stored?.result && !usingPre && (
                <Empty title="Chưa có kết quả thực nghiệm">
                  Mẫu chiến lược “<b>{draft.name}</b>” chưa được chạy backtest. Hãy bấm nút <b>“Chạy thử nghiệm”</b> ở góc trên bên phải để bắt đầu tính toán. Lượt chạy chỉ là tạm thời cho tới khi bạn bấm “Lưu chiến lược”.
                </Empty>
              )}
            </div>
          )}
        </div>
      </div>

      <SaveStrategyModal
        isOpen={saveOpen}
        onClose={() => setSaveOpen(false)}
        jobId={currentJobId}
        code={draft.code}
        defaultName={draft.name}
        result={jobResult}
        source="education"
        onSaved={markSaved}
      />
      <LeaveGuardDialog blocker={blocker} dirtyNames={dirtyDrafts.map((d) => d.name || 'Mẫu')} canSave={canSave && dirtyDrafts.length === 1 && dirtyDrafts[0].id === draft.id} onSave={saveForLeave} />
    </div>
  )
}
