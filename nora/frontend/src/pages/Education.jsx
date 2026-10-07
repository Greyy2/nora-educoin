import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Spinner, ErrorBox, Empty } from '../components/ui'
import JobPanel from '../components/JobPanel'
import CodeEditor from '../components/studio/CodeEditor'
import RunSettings from '../components/studio/RunSettings'
import { ICON, JobLine, StoredLine, CompileOutput } from '../components/studio/RunParts'
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
import { useRunDefaults, resolveForm } from '../lib/runDefaults'
import { POSITION_KEYS, validateRun, buildRunBody } from '../lib/runForm'
import { newDraft, isDraftDirty, configToForm } from '../lib/studioDraft'
import { postCompileStrategy, postCustomBacktest, postSaveUserAlpha, getUserAlphas, getUserAlphaDetail } from '../api'
import { parseCompileError } from '../lib/customResult'
import '../styles/strategyEditor.css'
import '../styles/education.css'
import '../styles/diagnostics.css'

// Trạng thái trang CHỈ trong bộ nhớ (mất khi đóng / tải lại trang). Lượt chạy của người học là TẠM THỜI; chỉ "Lưu chiến lược" mới ghi vào kho alpha người dùng.
const DEFAULT_FORM = { pos: {} } // rổ / ngày / train / vốn lấy từ backend (lib/runDefaults.js)
const makeInitial = () => ({ drafts: [newDraft(EDU_SAMPLES[0].name, EDU_SAMPLES[0].code, { sampleKey: EDU_SAMPLES[0].key })], active: '', form: {} })

export default function Education() {
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

  const problems = useMemo(() => validateRun(form, draft.code), [form, draft.code])
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
      const r = await postCustomBacktest(buildRunBody(form, code0))
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
  const pre = usePrecomputed({ code: draft.code, sampleKey })
  const preRec = stored ? null : pre.record
  const result = jobResult || stored?.result || preRec || null
  const usingPre = !jobResult && !!preRec
  const preNote = preRec ? <PrecomputedNote record={preRec} superseded={!!jobResult} /> : null
  const preStale = !jobResult && !stored && pre.state === 'stale'

  const tm = compiled?.meta?.timeframe
  const uniText = `${form.symbols.length} tài sản`
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
    // Mẫu chạy với tham số vị thế đã khai báo (nếu có)
    setForm({ pos: { ...(s.position || {}) } })
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
                  <RunSettings form={form} setForm={setForm} universe={universe} defaultsError={defaultsError} problems={problems} />
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
              <EduExplain draft={draft} result={result} position={form.pos} note={preNote} staleNote={preStale} precomputedExplain={stored ? stored.explain || null : usingPre ? preRec.explain : null} />
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
