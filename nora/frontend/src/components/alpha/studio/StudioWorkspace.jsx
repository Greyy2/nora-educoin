import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Spinner, ErrorBox, Empty } from '../../ui'
import JobPanel from '../../jobs/JobPanel'
import CodeEditor from './CodeEditor'
import AssistChip, { AssistList } from './AssistChip'
import RunSettings from './RunSettings'
import { ICON, JobLine, StoredLine, CompileOutput } from './RunParts'
import CustomResult from './CustomResult'
import SaveStrategyModal from './SaveStrategyModal'
import SamplesPane from './SamplesPane'
import LeaveGuardDialog from './LeaveGuardDialog'
import useJob from '../../../hooks/useJob'
import useAsync, { useResource } from '../../../hooks/useAsync'
import useMemState from '../../../hooks/useMemState'
import useUnsavedGuard from '../../../hooks/useUnsavedGuard'
import { useMeta } from '../../../meta/MetaProvider'
import { defaultExecMode } from '../../../lib/metaDefaults'
import { useRunDefaults, resolveForm } from '../../../lib/runDefaults'
import { POSITION_KEYS, validateRun, buildRunBody } from '../../../lib/runForm'
import { newDraft, isDraftDirty, configToForm } from '../../../lib/studioDraft'
import { postCompileStrategy, postCustomBacktest, postSaveUserAlpha, getUserAlphas, getUserAlphaDetail, getUserAlphaCode, getUserAlphaVersionCode, getEducationSamples, getEducationSampleResult, postAnnotate } from '../../../api'
import UserAlphaVersionHistory from './UserAlphaVersionHistory'
import { parseCompileError } from '../../../lib/customResult'
import '../../../styles/alpha.css'

// Trạng thái trang CHỈ trong bộ nhớ (mất khi đóng / tải lại trang): bản nháp, form chạy, lần chạy. Chỉ "Lưu chiến lược" mới ghi vào kho alpha người dùng.
// Tab mới luôn TRỐNG (không sao chép tab đang mở); mở mẫu = tab mới chứa code mẫu (education: kèm chú thích `# ▸`); "Nhân bản" là nút riêng.
const DEFAULT_FORM = { pos: {} } // rổ / ngày / train / vốn lấy từ backend (lib/runDefaults.js)
const makeInitial = () => ({ drafts: [newDraft('Chiến lược 1', '')], active: '', form: {}, seeded: false }) // seeded: tab 1 đã được nạp mẫu đầu tiên (chỉ một lần mỗi phiên trang)

/** View chung của /alpha/create và /education (mode = 'create' | 'education'). Khác biệt: ở 'education' CustomResult hiện ghi chú giải thích từng mục (result.explain.notes từ backend) và mẫu mở ra kèm chú thích `# ▸` từng dòng. */
// Đối chiếu mẫu <-> alpha đã lưu: ưu tiên khoá / id, dự phòng theo tên.
const findBy = (list, s, keyOf, nameOf) => list.find((x) => s.key && keyOf(x) === s.key) || list.find((x) => s.name && nameOf(x) === s.name)

export default function StudioWorkspace({ mode = 'create' }) {
  const educ = mode === 'education'
  const [st, set] = useMemState(makeInitial)
  const { meta } = useMeta()
  const { defaults, universe, error: defaultsError } = useRunDefaults()
  const form = resolveForm(DEFAULT_FORM, st.form, defaults)
  const drafts = st.drafts
  const draft = drafts.find((d) => d.id === st.active) || drafts[0]
  const setForm = (patch) => set((p) => ({ form: { ...p.form, ...patch } }))
  const setDrafts = (next, active) => set({ drafts: next, ...(active ? { active } : {}) })
  const patchById = (id, patch) => set((p) => ({ drafts: p.drafts.map((d) => (d.id === id ? { ...d, ...patch } : d)) }))
  const patchDraft = (patch) => patchById(draft.id, patch)

  const saved = useResource('alphas', getUserAlphas)

  const [compiled, setCompiled] = useState(null) // { code, ok, hash, meta, warnings, error, nonce }
  const [busy, setBusy] = useState('')            // '' | 'compile' | 'run' | 'open'
  const [runErr, setRunErr] = useState(null)
  const [openingId, setOpeningId] = useState('')
  const [note, setNote] = useState(null)          // { tone, text }
  const nonce = useRef(0)
  const edRef = useRef(null)
  const [assist, setAssist] = useState(null) // phán quyết RUN/ADAPT/REJECT của trợ lý (CodeEditor.onAssist)
  const [tab, setTab] = useState('results')   // samples | results
  const [saveOpen, setSaveOpen] = useState(false)
  const [setOpen, setSetOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [annOpen, setAnnOpen] = useState(false)
  const [strip, setStrip] = useState(false)
  const setRef = useRef(null)
  useEffect(() => {
    if (!setOpen && !historyOpen && !annOpen) return undefined
    const click = (e) => { if (setRef.current && !setRef.current.contains(e.target)) { setSetOpen(false); setHistoryOpen(false); setAnnOpen(false) } }
    const key = (e) => { if (e.key === 'Escape') { setSetOpen(false); setHistoryOpen(false); setAnnOpen(false) } }
    document.addEventListener('mousedown', click); document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', click); document.removeEventListener('keydown', key) }
  }, [setOpen, historyOpen, annOpen])

  // mở lại một job từ Lịch sử chạy: /alpha/create?job=... (kết quả tạm, không gắn với code đang soạn nên chưa lưu được cho tới khi chạy lại)
  const [sp] = useSearchParams()
  const qJob = sp.get('job')
  useEffect(() => { if (qJob && qJob !== draft.jobId) patchById(draft.id, { jobId: qJob, runCode: '', runAlpha: '', stored: null }) }, [qJob]) // eslint-disable-line react-hooks/exhaustive-deps
  // mở alpha đã lưu để SỬA: /alpha/create?alpha=<id> -> nạp code vào bản nháp tạm; chạy lại và Lưu = phiên bản mới của CHÍNH alpha đó
  const qAlpha = sp.get('alpha')
  const qVer = sp.get('version')
  const opened = useRef('')
  useEffect(() => {
    if (!qAlpha) return
    const key = `${qAlpha}:${qVer || ''}`
    if (opened.current === key) return
    opened.current = key
    const have = drafts.find((d) => d.alphaId === qAlpha && (!qVer || String(d.alphaVersion) === String(qVer)))
    if (have) { set({ active: have.id }); return }
    setOpeningId(qAlpha); setNote(null)
    const codeP = qVer ? getUserAlphaVersionCode(qAlpha, Number(qVer)) : getUserAlphaCode(qAlpha)
    Promise.all([codeP, getUserAlphaDetail(qAlpha).catch(() => null)]).then(([rc, rec]) => {
      const ver = Number(qVer) || rc.version || rec?.version || 1
      const d = newDraft(rc.name || rec?.name || qAlpha, rc.code || '', { alphaId: qAlpha, alphaVersion: ver })
      set((p) => ({ drafts: [...p.drafts, d], active: d.id, form: (rc?.config || rec?.config) ? { ...p.form, ...configToForm(rc?.config || rec.config, POSITION_KEYS) } : p.form }))
      setCompiled(null); setTab('results')
      setNote({ tone: 'ok', text: `Đã nạp “${d.name}” (phiên bản ${ver}) để sửa. Chạy backtest rồi “Lưu chiến lược” sẽ tạo phiên bản mới của alpha này.` })
    }, (e) => setNote({ tone: 'bad', text: `Không mở được alpha để sửa: ${e.message}` })).finally(() => setOpeningId(''))
  }, [qAlpha, qVer]) // eslint-disable-line react-hooks/exhaustive-deps
  const { job, status, error: jobErr, errorStatus: jobErrStatus } = useJob(draft.jobId || null)
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
      const r = await postCustomBacktest(buildRunBody(form, code0, stale ? null : compiled?.meta?.timeframe, defaultExecMode(meta)))
      const id = r?.job_id || r?.id
      if (!id) throw new Error('Máy chủ không trả mã job.')
      patchById(id0, { jobId: id, runCode: code0, runAlpha: '', stored: null }); setTab('results')
    } catch (e) {
      const err = parseCompileError(e.message)
      if (err?.line) showCompiled(code0, { ok: false, error: err })
      setRunErr(err?.line ? null : e.message)
    } finally { setBusy('') }
  }

  // "Lưu chiến lược" chỉ bật khi: (1) lần chạy XONG của CHÍNH code đang soạn (runCode === code, máy chủ vẫn kiểm lại program_hash) VÀ
  // (2) là chiến lược mới, hoặc mẫu / alpha đã lưu mà code đã khác bản gốc (baseCode) VÀ (3) chương trình này (program_hash) chưa có trong kho alpha người dùng.
  const savedItems = Array.isArray(saved.data) ? saved.data : []
  const isDup = !!jobResult && (savedItems.some((a) => a.program_hash && a.program_hash === jobResult.program_hash) || (!!draft.saved && draft.saved.code === draft.code))
  const unchanged = draft.code === draft.baseCode && !!draft.baseCode.trim()
  const canSave = !!jobResult && draft.runCode === draft.code && !unchanged && !isDup && !busy
  const saveWhy = !draft.jobId ? 'Chạy backtest cho code hiện tại trước khi lưu'
    : !jobResult ? 'Chờ lần chạy hoàn tất'
      : draft.runCode !== draft.code ? 'Chạy lại sau khi sửa'
        : unchanged ? (draft.sampleKey ? 'Mẫu chưa thay đổi: sửa code hoặc tham số rồi chạy lại' : 'Chưa sửa so với bản đã lưu: sửa code rồi chạy lại')
          : isDup ? 'Đã lưu chiến lược này'
            : 'Lưu chiến lược (code + cấu hình + kết quả đầy đủ)'

  function markSaved(res, name) {
    patchById(draft.id, { saved: { alpha_id: res.alpha_id, code: draft.code, name: name || draft.name }, runAlpha: res.alpha_id, name: name || draft.name, stored: null, ...(res.version ? { alphaId: res.alpha_id, alphaVersion: res.version } : {}) })
    saved.reload()
  }

  async function saveForLeave() {
    const name = draft.name.trim() || 'Chiến lược của tôi'
    markSaved(await postSaveUserAlpha({ job_id: draft.jobId, code: draft.code, name, note: '', source: educ ? 'education' : 'alpha-create', alpha_id: draft.alphaId }), name)
  }

  async function openSaved(id) {
    const have = drafts.find((d) => d.saved?.alpha_id === id)
    if (have) { set({ active: have.id }); setTab('results'); return }
    setOpeningId(id); setNote(null)
    try {
      const rec = await getUserAlphaDetail(id)
      const d = newDraft(rec.name || rec.id, rec.code || '', { saved: { alpha_id: rec.id, code: rec.code || '', name: rec.name || rec.id }, stored: rec, runAlpha: rec.id, alphaId: rec.id, alphaVersion: rec.version || 1 })
      set((p) => ({ drafts: [...p.drafts, d], active: d.id, form: { ...p.form, ...configToForm(rec.config, POSITION_KEYS) } }))
      setCompiled(null); setTab('results')
      if (!rec.result) setNote({ tone: 'bad', text: 'Bản ghi cũ không có kết quả đã lưu: đã nạp code và cấu hình, hãy chạy lại.' })
    } catch (e) { setNote({ tone: 'bad', text: `Không mở được: ${e.message}` }) } finally { setOpeningId('') }
  }

  const addDraft = (name, code) => { const d = newDraft(name, code); set((p) => ({ drafts: [...p.drafts, d], active: d.id })) }
  function closeDraft(id) {
    const d0 = drafts.find((d) => d.id === id)
    if (isDraftDirty(d0) && !window.confirm(`“${d0.name || 'Không tên'}” có thay đổi chưa lưu và sẽ mất khi đóng. Đóng không lưu?`)) return
    const rest = drafts.filter((d) => d.id !== id)
    if (!rest.length) { const d = newDraft('Chiến lược 1', ''); setDrafts([d], d.id); return }
    setDrafts(rest, id === draft.id ? rest[Math.max(0, drafts.findIndex((d) => d.id === id) - 1)].id : undefined)
  }

  const dirtyDrafts = drafts.filter(isDraftDirty)
  const dirty = isDraftDirty(draft)
  const blocker = useUnsavedGuard(dirtyDrafts.length > 0)

  const sampleRes = useAsync(getEducationSamples, [])
  const sampleList = Array.isArray(sampleRes.data) ? sampleRes.data : []
  const sampleText = async (code) => { if (!educ) return code; try { return (await postAnnotate(code, { as_comments: true })).annotated_code || code } catch (e) { return code } }

  // Mở trang: tab 1 nạp sẵn mẫu đầu tiên kèm kết quả để view ngay lập tức cả code và kết quả mẫu đó
  const seeding = useRef(false)
  useEffect(() => {
    if (st.seeded || seeding.current || !sampleList.length) return
    if (qJob || qAlpha) { set({ seeded: true }); return }
    seeding.current = true
    const s0 = sampleList[0]
    const matched = findBy(savedItems, s0, (a) => a.id, (a) => a.name)

    sampleText(s0.code).then(async (text) => {
      let rec = null
      if (matched) {
        try { rec = await getUserAlphaDetail(matched.id) } catch (e) { /* fallback */ }
      }
      const s0Res = rec?.result || s0.result || null
      const storedRec = s0Res ? {
        id: rec?.id || s0.key || s0.name,
        name: rec?.name || s0.name,
        result: s0Res,
        metrics: rec?.metrics || s0.metrics || s0Res.metrics || null,
        code: rec?.code || s0.code,
        config: rec?.config || s0Res.config || null,
      } : (rec || null)

      set((p) => {
        const d0 = p.drafts[0]
        const pristine = p.drafts.length === 1 && d0 && !d0.code.trim() && !d0.jobId
        if (!pristine) return { seeded: true }
        const d = newDraft(rec?.name || s0.name, text, {
          sampleKey: s0.key || s0.name,
          saved: storedRec ? { alpha_id: storedRec.id, code: s0.code, name: storedRec.name } : null,
          stored: storedRec,
          runAlpha: storedRec?.id || '',
          alphaId: rec?.id || '',
          alphaVersion: rec?.version || 1,
        })
        return {
          seeded: true,
          drafts: [d],
          active: d.id,
          form: (storedRec?.config) ? { ...p.form, ...configToForm(storedRec.config, POSITION_KEYS) } : p.form,
        }
      })
    })
  }, [sampleList.length, savedItems.length, st.seeded]) // eslint-disable-line react-hooks/exhaustive-deps

  // Giải thích từng dòng (chỉ education) = chú thích `# ▸` trong chính code, do backend sinh (annotate as_comments, idempotent); không có widget nào trong editor.
  const [annBusy, setAnnBusy] = useState(false)
  async function reAnnotate(strip) {
    if (annBusy || !draft.code.trim()) return
    setAnnBusy(true); setNote(null)
    const id0 = draft.id
    try {
      const r = await postAnnotate(draft.code, strip ? { strip: true } : { as_comments: true })
      const next = strip ? r.stripped_code : r.annotated_code
      if (typeof next !== 'string') throw new Error(r?.diagnostics?.[0]?.message_vi || 'Code chưa ở dạng lớp chiến lược nên chưa chú thích được.')
      patchById(id0, { code: next }); setCompiled(null)
    } catch (e) { setNote({ tone: 'bad', text: `Không ${strip ? 'bỏ' : 'tạo'} được chú thích: ${e.message}` }) } finally { setAnnBusy(false) }
  }

  const activateTab = (id) => { set({ active: id }); setTab('results') }

  // Mẫu đang xem chưa có kết quả: lấy kết quả đã tính sẵn của backend (MỘT đường duy nhất). Chưa có (404 NOT_READY) -> không nạp gì, người dùng bấm Chạy.
  const sampleTried = useRef(new Set())
  useEffect(() => {
    const key = draft.sampleKey
    if (!key || draft.stored?.result || draft.jobId || sampleTried.current.has(key)) return
    sampleTried.current.add(key)
    const id = draft.id
    getEducationSampleResult(key).then((resData) => {
      if (!resData) return
      patchById(id, { stored: { id: key, name: draft.name, result: resData, metrics: resData.metrics, code: draft.code, config: resData.config } })
      if (resData.config) set((p) => ({ form: { ...p.form, ...configToForm(resData.config, POSITION_KEYS) } }))
    }).catch(() => { /* NOT_READY / lỗi: không thử lại trong phiên */ })
  }, [draft.id, draft.sampleKey, draft.stored?.result, draft.jobId]) // eslint-disable-line react-hooks/exhaustive-deps

  const tm = compiled?.meta?.timeframe
  const uniText = `${form.symbols.length} tài sản`
  const issue = compiled && !stale && !compiled.ok
  const TABS = [['samples', 'Chiến lược mẫu'], ['results', 'Kết quả']]
  async function useSample(s) {
    // 1. Mẫu đã mở ở một tab -> chọn tab đó (khoá trước, dự phòng theo tên)
    const openDraft = findBy(drafts, s, (d) => d.sampleKey, (d) => d.name)
    if (openDraft) { activateTab(openDraft.id); return }

    // 2. Đã có bản lưu trong kho alpha người dùng -> mở bản lưu
    const matched = findBy(savedItems, s, (a) => a.id, (a) => a.name)
    if (matched) { await openSaved(matched.id); return }

    // 3. Tab mới chứa code mẫu; kết quả tính sẵn (nếu có trong danh sách mẫu) hiện ngay, không có thì effect phía trên thử nạp / để người dùng chạy
    const sampleResData = s.result || null
    const text = await sampleText(s.code)
    const sampleKey = s.key || s.name
    const d = newDraft(s.name, text, sampleResData ? {
      sampleKey,
      stored: { id: sampleKey, name: s.name, result: sampleResData, metrics: s.metrics || sampleResData.metrics, code: s.code, config: sampleResData.config },
      saved: { alpha_id: sampleKey, code: s.code, name: s.name },
      runAlpha: s.key || '',
    } : { sampleKey })
    const formPatch = (p) => (sampleResData?.config ? { ...p.form, ...configToForm(sampleResData.config, POSITION_KEYS) } : p.form)

    set((p) => {
      // Tab đang mở còn trống (chưa có code/ghi chú, chưa chạy, chưa lưu) -> ghi mẫu vào chính tab đó; ngược lại mở tab mới.
      const cur = p.drafts.find((x) => x.id === p.active) || p.drafts[0]
      if (cur && !cur.code.trim() && !cur.jobId && !cur.saved && !cur.alphaId) {
        return { drafts: p.drafts.map((x) => (x.id === cur.id ? { ...d, id: cur.id } : x)), active: cur.id, form: formPatch(p) }
      }
      return { drafts: [...p.drafts, d], active: d.id, form: formPatch(p) }
    })
    setCompiled(null)
    setTab('results')
  }
  const expired = !!draft.jobId && !job && (jobErrStatus === 404 || jobErrStatus === 410)
  const isSampleOrSaved = Boolean(draft.sampleKey || draft.saved || draft.stored || draft.alphaId)
  const chip = isSampleOrSaved ? (dirty ? 'Đã sửa, chưa lưu' : 'Đã lưu') : dirty ? 'Chưa lưu' : 'Nháp'

  return (
    <div className="se-ws">
      <div className="se-left">
        <div className="se-tabs" role="tablist" aria-label="Bản nháp">
          {drafts.map((d) => (
            <div key={d.id} className={`se-tab ${d.id === draft.id ? 'on' : ''}`}>
              <button type="button" role="tab" aria-selected={d.id === draft.id} title={d.name} onClick={() => activateTab(d.id)}>
                {isDraftDirty(d) ? <span className="dirty-dot" title="Có thay đổi chưa lưu" /> : null}
                <span className="file-icon" style={{ opacity: 0.75, fontSize: 12 }}>🐍</span>
                <span>{d.name.endsWith('.py') ? d.name : `${d.name}.py`}</span>
              </button>
              <button type="button" className="x" aria-label={`Đóng ${d.name}`} onClick={() => closeDraft(d.id)}>×</button>
            </div>
          ))}
          <button type="button" className="se-add" title="Thêm file mới" aria-label="Thêm bản nháp" onClick={() => addDraft(`Chiến lược ${drafts.length + 1}`, '')}>+</button>
        </div>

        <div className="se-hd">
          <input className="se-name" aria-label="Tên chiến lược" placeholder="Tên chiến lược" value={draft.name} onChange={(e) => patchDraft({ name: e.target.value })} />
          <div className="se-chips">
            <button type="button" className="se-chip" onClick={() => setSetOpen(true)} title={isSampleOrSaved ? (dirty ? 'Đã sửa so với mẫu gốc' : 'Chiến lược đã lưu trong hệ thống') : (dirty ? 'Chiến lược mới chưa lưu' : 'Bản nháp mới')}><i className={`d ${isSampleOrSaved && !dirty ? 'ok' : ''}`} />{chip}</button>
            <button type="button" className="se-chip" onClick={() => setSetOpen(true)} title="Rổ tài sản"><i className="d" />{uniText}</button>
            {tm && <span className="se-chip"><i className="d" />{tm}</span>}
            {draft.alphaId && (
              <button
                type="button"
                className="se-chip"
                onClick={() => setHistoryOpen(!historyOpen)}
                title={`Lịch sử phiên bản của alpha ${draft.alphaId}. Lưu sẽ tạo phiên bản mới.`}
              >
                <i className="d" />v{draft.alphaVersion || 1} (lịch sử)
              </button>
            )}
          </div>
          <span className="se-sp" />
          <div className="se-btns" ref={setRef}>
            <button type="button" className={`n-icon-btn ${problems.length ? 'warn' : ''}`} aria-label="Cài đặt chạy" aria-expanded={setOpen} title="Cài đặt chạy" onClick={() => setSetOpen(!setOpen)}>{ICON.gear}</button>
            <button type="button" className="n-icon-btn" aria-label="Kiểm tra code" title="Kiểm tra (biên dịch, không chạy)" disabled={!!busy || !draft.code.trim()} onClick={() => { compile(); setStrip(true) }}>{busy === 'compile' ? <Spinner /> : ICON.check}</button>
            {educ && <button type="button" className="n-icon-btn" aria-label="Chú thích" aria-expanded={annOpen} title="Chú thích tiếng Việt `# ▸` trên từng dòng" disabled={annBusy || !draft.code.trim()} onClick={() => setAnnOpen(!annOpen)}>{annBusy ? <Spinner /> : <b style={{ fontSize: 12 }}>▸#</b>}</button>}
            <button type="button" className="n-icon-btn" aria-label="Nhân bản" title="Nhân bản sang tab mới" onClick={() => addDraft(`${draft.name} (bản sao)`, draft.code)}>{ICON.copy}</button>
            {educ && annOpen && (
              <div className="n-pop se-annp" role="menu" aria-label="Chú thích">
                <button type="button" role="menuitem" className="n-btn sm" title="Sinh lại chú thích ngắn `# ▸` (không đổi kết quả chạy)" onClick={() => { setAnnOpen(false); reAnnotate(false) }}>Chú thích lại</button>
                <button type="button" role="menuitem" className="n-btn sm" title="Xoá các dòng chú thích `# ▸` tự sinh (giữ chú thích của bạn)" onClick={() => { setAnnOpen(false); reAnnotate(true) }}>Bỏ chú thích</button>
              </div>
            )}
            {setOpen && (
              <div className="n-pop se-setp" role="dialog" aria-label="Cài đặt chạy">
                <div className="n-pop-h"><b>Cài đặt chạy</b><button type="button" className="n-btn sm" onClick={() => setSetOpen(false)}>Đóng</button></div>
                <div className="se-setb">
                  <RunSettings form={form} setForm={setForm} universe={universe} defaultsError={defaultsError} problems={problems} />
                </div>
              </div>
            )}
            {historyOpen && draft.alphaId && (
              <div className="n-pop se-setp" style={{ maxWidth: 520, width: '90vw' }} role="dialog" aria-label="Lịch sử phiên bản">
                <div className="n-pop-h"><b>Lịch sử phiên bản ({draft.alphaId})</b><button type="button" className="n-btn sm" onClick={() => setHistoryOpen(false)}>Đóng</button></div>
                <div className="se-setb">
                  <UserAlphaVersionHistory
                    alphaId={draft.alphaId}
                    currentVersion={draft.alphaVersion}
                    onSelectVersion={(vRec) => {
                      patchDraft({ code: vRec.code, alphaVersion: vRec.version })
                      setCompiled(null)
                      setHistoryOpen(false)
                    }}
                  />
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
          {!draft.code.trim() && <div className="se-empty-code">Soạn chiến lược Python (lớp kế thừa SimpleAlgorithm) hoặc mở một mẫu ở tab “Mẫu”. Gõ để nhận gợi ý dữ liệu / chỉ báo / toán tử; Ctrl/⌘ + Enter để chạy.</div>}
          <CodeEditor ref={edRef} value={draft.code} onChange={(code) => patchDraft({ code })} onRun={run} errorLine={errLine} errorKey={compiled?.nonce} onAssist={setAssist} />
          <div className="se-vfloat"><AssistChip a={assist} onlyErrors onToggle={() => setStrip(true)} /></div>
          <div className={`se-strip ${strip || issue ? 'open' : ''} ${issue ? 'bad' : ''}`}>
            <button type="button" className="se-strip-h" aria-expanded={strip || issue} onClick={() => setStrip(!(strip || issue))}>
              <span className={`se-dot ${!compiled ? '' : compiled.ok && !stale ? 'ok' : issue ? 'bad' : 'warn'}`} />
              <b>Biên dịch</b>
              <span className="se-strip-s">{note ? note.text : !compiled ? 'Chưa kiểm tra · Ctrl/⌘ + Enter = chạy · Tab = thụt 4 dấu cách' : stale ? 'Code đã sửa sau lần kiểm tra' : compiled.ok ? `Hợp lệ${tm ? ` · khung ${tm}` : ''}` : `Lỗi${compiled.error?.line ? ` · dòng ${compiled.error.line}` : ''}`}</span>
              <span className="se-sp" /><span aria-hidden="true">{strip || issue ? '▾' : '▴'}</span>
            </button>
            {(strip || issue) && (
              <div className="se-strip-b">
                {assist?.status === 'done' && assist.diagnostics?.length > 0 && <AssistList a={assist} onGo={(l, c) => edRef.current?.goTo(l, c)} />}
                <CompileOutput c={compiled} stale={stale} />
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="se-right">
        <div className="se-rtabs" role="tablist" aria-label="Khu vực bên phải">
          {TABS.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} className={tab === k ? 'on' : ''} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        <div className="se-rbody">
          {tab === 'results' && (
            <div className="se-resw">
              <ErrorBox>{runErr}</ErrorBox>
              {note && <p className={`n-note ${note.tone === 'bad' ? 'neg' : ''}`} role={note.tone === 'bad' ? 'alert' : 'status'}>{note.text}</p>}
              {expired && (
                <div className="se-job">
                  <p className="n-note neg" role="alert">Kết quả tạm đã mất (API khởi động lại) — chạy lại.</p>
                  <button type="button" className="n-btn sm" onClick={() => patchDraft({ jobId: '', runCode: '', runAlpha: '' })}>Bỏ kết quả</button>
                </div>
              )}
              {draft.jobId && status !== 'done' && !expired && (
                <div className="se-job">
                  <JobPanel job={job} status={status} error={jobErr} title="Backtest Python" />
                  <button type="button" className="n-btn sm" onClick={() => patchDraft({ jobId: '', runCode: '', runAlpha: '' })} disabled={running}>Bỏ kết quả</button>
                </div>
              )}
              {draft.jobId && status === 'done' && (
                <CustomResult
                  key={draft.jobId}
                  result={jobResult}
                  explain={educ}
                  tourKey={educ ? draft.jobId : ''}
                  jobLine={<JobLine job={job} savedId={draft.saved && draft.saved.alpha_id === draft.runAlpha ? draft.saved.alpha_id : ''} onClear={() => patchDraft({ jobId: '', runCode: '', runAlpha: draft.saved ? draft.saved.alpha_id : '' })} />}
                />
              )}
              {!draft.jobId && draft.stored?.result && <CustomResult key={`s-${draft.stored.id}`} result={draft.stored.result} explain={educ} tourKey="" jobLine={<StoredLine rec={draft.stored} />} />}
              {!draft.jobId && !draft.stored?.result && <Empty title="Chưa có kết quả">Chọn rổ tài sản và khoảng ngày ở biểu tượng cài đặt, rồi bấm “Chạy backtest”. Kết quả (Train / Test / Toàn kỳ, đường lãi lỗ, drawdown, lệnh) hiện ở đây và chỉ là tạm thời cho tới khi bấm “Lưu chiến lược”.</Empty>}
            </div>
          )}
          {tab === 'samples' && sampleRes.error && (
            <div className="se-job">
              <ErrorBox>{`Không tải được danh sách mẫu: ${sampleRes.error.message || sampleRes.error}`}</ErrorBox>
              <button type="button" className="n-btn sm" onClick={sampleRes.reload}>Thử lại</button>
            </div>
          )}
          {tab === 'samples' && sampleRes.loading && !sampleList.length && <Spinner />}
          {tab === 'samples' && !sampleRes.error && (
            <SamplesPane samples={sampleList} onUse={useSample} saved={saved} onOpenSaved={openSaved} openingId={openingId} activeId={draft.saved?.alpha_id || ''} defaultCapital={Number(form.capital) || null} />
          )}
        </div>
      </div>

      <SaveStrategyModal
        isOpen={saveOpen}
        onClose={() => setSaveOpen(false)}
        jobId={draft.jobId}
        code={draft.code}
        defaultName={draft.name}
        result={jobResult}
        source={educ ? 'education' : 'alpha-create'}
        alphaId={draft.alphaId || ''}
        alphaVersion={draft.alphaVersion || 0}
        onSaved={markSaved}
      />
      <LeaveGuardDialog blocker={blocker} dirtyNames={dirtyDrafts.map((d) => d.name || 'Không tên')} canSave={canSave && dirtyDrafts.length === 1 && dirtyDrafts[0].id === draft.id} onSave={saveForLeave} />
    </div>
  )
}
