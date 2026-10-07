import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Spinner, ErrorBox, Empty } from '../components/ui'
import JobPanel from '../components/JobPanel'
import CodeEditor from '../components/studio/CodeEditor'
import RunSettings from '../components/studio/RunSettings'
import { ICON, JobLine, StoredLine, CompileOutput } from '../components/studio/RunParts'
import CustomResult from '../components/studio/CustomResult'
import SaveStrategyModal from '../components/studio/SaveStrategyModal'
import SavedAlphaList from '../components/studio/SavedAlphaList'
import LeaveGuardDialog from '../components/studio/LeaveGuardDialog'
import Reference from '../components/studio/Reference'
import { SAMPLES, BLANK_CODE } from '../components/studio/samples'
import useJob from '../hooks/useJob'
import useAsync from '../hooks/useAsync'
import useMemState from '../hooks/useMemState'
import useUnsavedGuard from '../hooks/useUnsavedGuard'
import { useRunDefaults, resolveForm } from '../lib/runDefaults'
import { POSITION_KEYS, validateRun, buildRunBody } from '../lib/runForm'
import { newDraft, isDraftDirty, configToForm } from '../lib/studioDraft'
import { postCompileStrategy, postCustomBacktest, postSaveUserAlpha, getUserAlphas, getUserAlphaDetail } from '../api'
import { parseCompileError } from '../lib/customResult'
import '../styles/strategyEditor.css'

// Trạng thái trang CHỈ trong bộ nhớ (mất khi đóng / tải lại trang): bản nháp, form chạy, lần chạy. Chỉ "Lưu chiến lược" mới ghi vào kho alpha người dùng.
const DEFAULT_FORM = { pos: {} } // rổ / ngày / train / vốn lấy từ backend (lib/runDefaults.js)
const makeInitial = () => ({ drafts: [newDraft('Chiến lược 1', SAMPLES[0].code)], active: '', form: {} })

export default function CreateAlpha() {
  const [st, set] = useMemState(makeInitial)
  const { defaults, universe, error: defaultsError } = useRunDefaults()
  const form = resolveForm(DEFAULT_FORM, st.form, defaults)
  const drafts = st.drafts
  const draft = drafts.find((d) => d.id === st.active) || drafts[0]
  const setForm = (patch) => set((p) => ({ form: { ...p.form, ...patch } }))
  const setDrafts = (next, active) => set({ drafts: next, ...(active ? { active } : {}) })
  const patchById = (id, patch) => set((p) => ({ drafts: p.drafts.map((d) => (d.id === id ? { ...d, ...patch } : d)) }))
  const patchDraft = (patch) => patchById(draft.id, patch)

  const saved = useAsync(getUserAlphas, [])

  const [compiled, setCompiled] = useState(null) // { code, ok, hash, meta, warnings, error, nonce }
  const [busy, setBusy] = useState('')            // '' | 'compile' | 'run' | 'open'
  const [runErr, setRunErr] = useState(null)
  const [openingId, setOpeningId] = useState('')
  const [note, setNote] = useState(null)          // { tone, text }
  const nonce = useRef(0)
  const [tab, setTab] = useState('results')   // samples | results | data | features | operators
  const [saveOpen, setSaveOpen] = useState(false)
  const [setOpen, setSetOpen] = useState(false)
  const [strip, setStrip] = useState(false)
  const setRef = useRef(null)
  useEffect(() => {
    if (!setOpen) return undefined
    const click = (e) => { if (setRef.current && !setRef.current.contains(e.target)) setSetOpen(false) }
    const key = (e) => { if (e.key === 'Escape') setSetOpen(false) }
    document.addEventListener('mousedown', click); document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', click); document.removeEventListener('keydown', key) }
  }, [setOpen])

  // mở lại một job từ Lịch sử chạy: /alpha/create?job=... (kết quả tạm, không gắn với code đang soạn nên chưa lưu được cho tới khi chạy lại)
  const [sp] = useSearchParams()
  const qJob = sp.get('job')
  useEffect(() => { if (qJob && qJob !== draft.jobId) patchById(draft.id, { jobId: qJob, runCode: '', runAlpha: '', stored: null }) }, [qJob]) // eslint-disable-line react-hooks/exhaustive-deps
  const { job, status, error: jobErr } = useJob(draft.jobId || null)
  const running = status === 'queued' || status === 'running' || status === 'loading'
  const jobResult = status === 'done' ? job?.result : null
  // alpha_id (backend tính) của lần chạy đã xong: so với bản đã lưu để biết còn thay đổi chưa lưu hay không
  useEffect(() => { if (jobResult?.alpha_id && draft.runAlpha !== jobResult.alpha_id) patchById(draft.id, { runAlpha: jobResult.alpha_id }) }, [jobResult?.alpha_id, draft.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const problems = useMemo(() => validateRun(form, draft.code), [form, draft.code])
  const stale = compiled && compiled.code !== draft.code
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
      const r = await postCustomBacktest(buildRunBody(form, code0))
      const id = r?.job_id || r?.id
      if (!id) throw new Error('Máy chủ không trả mã job.')
      patchById(id0, { jobId: id, runCode: code0, runAlpha: '', stored: null }); setTab('results')
    } catch (e) {
      const err = parseCompileError(e.message)
      if (err?.line) showCompiled(code0, { ok: false, error: err })
      setRunErr(err?.line ? null : e.message)
    } finally { setBusy('') }
  }

  // Lưu được khi có lần chạy XONG của CHÍNH code đang soạn (cùng văn bản lúc chạy, hoặc cùng program_hash với bản biên dịch gần nhất); máy chủ vẫn kiểm lại program_hash.
  const sameProgram = !!jobResult && (draft.runCode === draft.code || (!!compiled?.ok && compiled.code === draft.code && compiled.hash === jobResult.program_hash))
  const canSave = sameProgram && !busy
  const saveWhy = !draft.jobId ? 'Chạy backtest cho code hiện tại trước khi lưu' : !jobResult ? 'Chờ lần chạy hoàn tất' : !sameProgram ? 'Kết quả không thuộc code đang soạn: chạy lại trước khi lưu' : 'Lưu chiến lược (code + cấu hình + kết quả đầy đủ)'

  function markSaved(res, name) {
    patchById(draft.id, { saved: { alpha_id: res.alpha_id, code: draft.code, name: name || draft.name }, runAlpha: res.alpha_id, name: name || draft.name, stored: null })
    saved.reload()
  }

  async function saveForLeave() {
    const name = draft.name.trim() || 'Chiến lược của tôi'
    markSaved(await postSaveUserAlpha({ job_id: draft.jobId, code: draft.code, name, note: '', source: 'alpha-create' }), name)
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

  const addDraft = (name, code) => { const d = newDraft(name, code); setDrafts([...drafts, d], d.id) }
  function closeDraft(id) {
    const d0 = drafts.find((d) => d.id === id)
    if (isDraftDirty(d0) && !window.confirm(`“${d0.name || 'Không tên'}” có thay đổi chưa lưu và sẽ mất khi đóng. Đóng không lưu?`)) return
    const rest = drafts.filter((d) => d.id !== id)
    if (!rest.length) { const d = newDraft('Chiến lược 1', BLANK_CODE); setDrafts([d], d.id); return }
    setDrafts(rest, id === draft.id ? rest[Math.max(0, drafts.findIndex((d) => d.id === id) - 1)].id : undefined)
  }

  const dirtyDrafts = drafts.filter(isDraftDirty)
  const dirty = isDraftDirty(draft)
  const blocker = useUnsavedGuard(dirtyDrafts.length > 0)
  const result = draft.jobId ? jobResult : draft.stored?.result || null

  const tm = compiled?.meta?.timeframe
  const uniText = `${form.symbols.length} tài sản`
  const issue = compiled && !stale && !compiled.ok
  const TABS = [['samples', 'Mẫu'], ['results', 'Kết quả'], ['data', 'Dữ liệu'], ['features', 'Features'], ['operators', 'Operators']]
  const useSample = (name, code) => { addDraft(name, code); setCompiled(null) }
  const chip = draft.saved ? (dirty ? 'Đã sửa, chưa lưu' : 'Đã lưu') : dirty ? 'Chưa lưu' : 'Nháp'

  return (
    <div className="se-ws">
      <div className="se-left">
        <div className="se-tabs" role="tablist" aria-label="Bản nháp">
          {drafts.map((d) => (
            <div key={d.id} className={`se-tab ${d.id === draft.id ? 'on' : ''}`}>
              <button type="button" role="tab" aria-selected={d.id === draft.id} title={d.name} onClick={() => set({ active: d.id })}>{isDraftDirty(d) ? '● ' : ''}{d.name || 'Không tên'}</button>
              <button type="button" className="x" aria-label={`Đóng ${d.name}`} onClick={() => closeDraft(d.id)}>×</button>
            </div>
          ))}
          <button type="button" className="se-add" title="Tab mới" aria-label="Thêm bản nháp" onClick={() => addDraft(`Chiến lược ${drafts.length + 1}`, BLANK_CODE)}>+</button>
        </div>

        <div className="se-hd">
          <input className="se-name" aria-label="Tên chiến lược" placeholder="Tên chiến lược" value={draft.name} onChange={(e) => patchDraft({ name: e.target.value })} />
          <div className="se-chips">
            <button type="button" className="se-chip" onClick={() => setSetOpen(true)} title={draft.saved ? `Alpha ${draft.saved.alpha_id}` : 'Chưa lưu: bản nháp và kết quả chạy chỉ tồn tại trong phiên này'}><i className={`d ${draft.saved && !dirty ? 'ok' : ''}`} />{chip}</button>
            <button type="button" className="se-chip" onClick={() => setSetOpen(true)} title="Rổ tài sản"><i className="d" />{uniText}</button>
            {tm && <span className="se-chip"><i className="d" />{tm}</span>}
          </div>
          <span className="se-sp" />
          <div className="se-btns" ref={setRef}>
            <button type="button" className={`n-icon-btn ${problems.length ? 'warn' : ''}`} aria-label="Cài đặt chạy" aria-expanded={setOpen} title="Cài đặt chạy" onClick={() => setSetOpen(!setOpen)}>{ICON.gear}</button>
            <button type="button" className="n-icon-btn" aria-label="Kiểm tra code" title="Kiểm tra (biên dịch, không chạy)" disabled={!!busy || !draft.code.trim()} onClick={() => { compile(); setStrip(true) }}>{busy === 'compile' ? <Spinner /> : ICON.check}</button>
            <button type="button" className="n-icon-btn" aria-label="Nhân bản" title="Nhân bản sang tab mới" onClick={() => addDraft(`${draft.name} (bản sao)`, draft.code)}>{ICON.copy}</button>
            {setOpen && (
              <div className="n-pop se-setp" role="dialog" aria-label="Cài đặt chạy">
                <div className="n-pop-h"><b>Cài đặt chạy</b><button type="button" className="n-btn sm" onClick={() => setSetOpen(false)}>Đóng</button></div>
                <div className="se-setb">
                  <RunSettings form={form} setForm={setForm} universe={universe} defaultsError={defaultsError} problems={problems} />
                </div>
              </div>
            )}
          </div>
          <button type="button" className="se-save" onClick={() => setSaveOpen(true)} disabled={!canSave} title={saveWhy}>{ICON.save} Lưu chiến lược</button>
          <button type="button" className="se-run" onClick={run} disabled={!!busy || running || problems.length > 0} title={problems[0] || 'Ctrl/⌘ + Enter'}>
            {busy === 'run' || running ? <><Spinner /> {status === 'queued' ? 'Đang xếp hàng…' : 'Đang chạy…'}</> : <>{ICON.play} Chạy backtest</>}
          </button>
        </div>

        <div className="se-code">
          <CodeEditor value={draft.code} onChange={(code) => patchDraft({ code })} onRun={run} errorLine={errLine} errorKey={compiled?.nonce} />
          <div className={`se-strip ${strip || issue ? 'open' : ''} ${issue ? 'bad' : ''}`}>
            <button type="button" className="se-strip-h" aria-expanded={strip || issue} onClick={() => setStrip(!(strip || issue))}>
              <span className={`se-dot ${!compiled ? '' : compiled.ok && !stale ? 'ok' : issue ? 'bad' : 'warn'}`} />
              <b>Biên dịch</b>
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
              <h3 className="se-h3">Chiến lược mẫu</h3>
              <div className="se-cards">
                {SAMPLES.map((s) => (
                  <button key={s.key} type="button" className="n-card-sel" onClick={() => useSample(s.name, s.code)}><b>{s.name}</b><span className="n-note">{s.note}</span></button>
                ))}
              </div>
              <SavedAlphaList list={saved} onOpen={openSaved} openingId={openingId} activeId={draft.saved?.alpha_id || ''} />
            </div>
          )}
          {tab === 'results' && (
            <div className="se-resw">
              <ErrorBox>{runErr}</ErrorBox>
              {note && note.tone === 'bad' && <p className="n-note neg" role="alert">{note.text}</p>}
              {draft.jobId && status !== 'done' && (
                <div className="se-job">
                  <JobPanel job={job} status={status} error={jobErr} title="Backtest Python" />
                  <button type="button" className="n-btn sm" onClick={() => patchDraft({ jobId: '', runCode: '', runAlpha: '' })} disabled={running}>Bỏ kết quả</button>
                </div>
              )}
              {draft.jobId && status === 'done' && (
                <CustomResult
                  key={draft.jobId}
                  result={jobResult}
                  jobLine={<JobLine job={job} savedId={draft.saved && draft.saved.alpha_id === draft.runAlpha ? draft.saved.alpha_id : ''} onClear={() => patchDraft({ jobId: '', runCode: '', runAlpha: draft.saved ? draft.saved.alpha_id : '' })} />}
                />
              )}
              {!draft.jobId && draft.stored?.result && <CustomResult key={`s-${draft.stored.id}`} result={draft.stored.result} jobLine={<StoredLine rec={draft.stored} />} />}
              {!draft.jobId && !draft.stored?.result && <Empty title="Chưa có kết quả">Chọn rổ tài sản và khoảng ngày ở biểu tượng cài đặt, rồi bấm “Chạy backtest”. Kết quả (Train / Test / Toàn kỳ, đường lãi lỗ, drawdown, lệnh) hiện ở đây và chỉ là tạm thời cho tới khi bấm “Lưu chiến lược”.</Empty>}
            </div>
          )}
          {tab === 'data' && <Reference kind="data" />}
          {tab === 'features' && <Reference kind="features" />}
          {tab === 'operators' && <Reference kind="operators" />}
        </div>
      </div>

      <SaveStrategyModal
        isOpen={saveOpen}
        onClose={() => setSaveOpen(false)}
        jobId={draft.jobId}
        code={draft.code}
        defaultName={draft.name}
        result={jobResult}
        source="alpha-create"
        onSaved={markSaved}
      />
      <LeaveGuardDialog blocker={blocker} dirtyNames={dirtyDrafts.map((d) => d.name || 'Không tên')} canSave={canSave && dirtyDrafts.length === 1 && dirtyDrafts[0].id === draft.id} onSave={saveForLeave} />
    </div>
  )
}
