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
import { useUser } from '../../../meta/UserProvider'
import { defaultExecMode } from '../../../lib/metaDefaults'
import { useRunDefaults, resolveForm } from '../../../lib/runDefaults'
import { POSITION_KEYS, validateRun, buildRunBody } from '../../../lib/runForm'
import { newDraft, isDraftDirty, configToForm } from '../../../lib/studioDraft'
import { postCompileStrategy, postCustomBacktest, postLiveBot, postSaveUserAlpha, getUserAlphas, getUserAlphaDetail, getUserAlphaCode, getUserAlphaVersionCode, getEducationSamples, getEducationSampleResult, postAnnotate, getEduSamplesVisible, getEduStrategy } from '../../../api'
import UserAlphaVersionHistory from './UserAlphaVersionHistory'
import { parseCompileError } from '../../../lib/customResult'
import PromptResearchView from './PromptResearchView'
import '../../../styles/alpha.css'

// Trạng thái trang CHỈ trong bộ nhớ (mất khi đóng / tải lại trang): bản nháp, form chạy, lần chạy. Chỉ "Lưu chiến lược" mới ghi vào kho alpha người dùng.
const STORAGE_PREFIX = 'nora_studio_state_'

function loadSession(mode) {
  try {
    const raw = sessionStorage.getItem(`${STORAGE_PREFIX}${mode}`)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed.drafts) && parsed.drafts.length > 0) {
        const hasContent = parsed.drafts.some((d) => (d.code && d.code.trim()) || d.jobId || d.sampleKey || d.alphaId || d.saved?.alpha_id)
        return {
          drafts: parsed.drafts,
          active: parsed.active || parsed.drafts[0].id,
          form: parsed.form || {},
          seeded: Boolean(hasContent),
        }
      }
    }
  } catch (e) { /* bỏ qua */ }
  return null
}

const DEFAULT_FORM = { pos: {} } // rổ / ngày / train / vốn lấy từ backend (lib/runDefaults.js)
const makeInitial = () => ({ drafts: [newDraft('Chiến lược 1', '')], active: '', form: {}, seeded: false })

const ModeIcon = {
  code: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" /></svg>,
  prompt: <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" /></svg>,
}
function ModeSwitch({ value, onChange }) {
  return (
    <div className="se-mode" role="tablist" aria-label="Chế độ soạn">
      {[['code', 'Code'], ['prompt', 'Prompt']].map(([k, label]) => (
        <button key={k} type="button" role="tab" aria-selected={value === k} className={value === k ? 'on' : ''} onClick={() => onChange(k)}>
          {ModeIcon[k]}<span>{label}</span>
        </button>
      ))}
    </div>
  )
}

/** View chung của /alpha/create và /education (mode = 'create' | 'education'). Khác biệt: ở 'education' CustomResult hiện ghi chú giải thích từng mục (result.explain.notes từ backend) và mẫu mở ra kèm chú thích `# ▸` từng dòng. */
// Đối chiếu mẫu <-> alpha đã lưu: ưu tiên khoá / id, dự phòng theo tên.
const findBy = (list, s, keyOf, nameOf) => list.find((x) => s.key && keyOf(x) === s.key) || list.find((x) => s.name && nameOf(x) === s.name)

export default function StudioWorkspace({ mode = 'create' }) {
  const educ = mode === 'education'
  const [studioMode, setStudioMode] = useState('code') // 'code' | 'prompt' (chỉ ở Coin mode)
  const [st, set] = useMemState(() => loadSession(mode) || makeInitial())
  const { meta } = useMeta()
  const { defaults, universe, error: defaultsError } = useRunDefaults()
  const form = resolveForm(DEFAULT_FORM, st.form, defaults)
  const drafts = st.drafts
  const draft = drafts.find((d) => d.id === st.active) || drafts[0]
  const setForm = (patch) => set((p) => ({ form: { ...p.form, ...patch } }))
  const setDrafts = (next, active) => set({ drafts: next, ...(active ? { active } : {}) })
  const patchById = (id, patch) => set((p) => ({ drafts: p.drafts.map((d) => (d.id === id ? { ...d, ...patch } : d)) }))
  const patchDraft = (patch) => patchById(draft.id, patch)

  // Lưu bản nháp vào sessionStorage để tránh mất khi chuyển tab/tải lại trang
  // Chỉ lưu trường NHẸ (code, id job…); kết quả backtest (stored.result) nạp lại từ job/mẫu/alpha — tránh vượt quota & giật khi gõ. Debounce 400 ms.
  useEffect(() => {
    const h = setTimeout(() => {
      try {
        if (st.drafts?.length) {
          const light = st.drafts.map(({ stored, ...d }) => ({
            ...d,
            storedId: stored?.id || d.saved?.alpha_id || d.alphaId || d.sampleKey || '',
          }))
          sessionStorage.setItem(`${STORAGE_PREFIX}${mode}`, JSON.stringify({ drafts: light, active: st.active, form: st.form }))
        }
      } catch (e) { /* quota / chế độ riêng tư: bỏ qua, bản nháp vẫn còn trong RAM */ }
    }, 400)
    return () => clearTimeout(h)
  }, [st.drafts, st.active, st.form, mode])

  const { me, loading: meLoading } = useUser()
  const saved = useResource('alphas', () => getUserAlphas(me?.id ? { owner_id: me.id } : {}), { deps: [me?.id] })

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
  const [syntaxOpen, setSyntaxOpen] = useState(false)
  const [strip, setStrip] = useState(false)
  const setRef = useRef(null)
  useEffect(() => {
    if (!setOpen && !historyOpen && !annOpen && !syntaxOpen) return undefined
    const click = (e) => { if (setRef.current && !setRef.current.contains(e.target)) { setSetOpen(false); setHistoryOpen(false); setAnnOpen(false); setSyntaxOpen(false) } }
    const key = (e) => { if (e.key === 'Escape') { setSetOpen(false); setHistoryOpen(false); setAnnOpen(false); setSyntaxOpen(false) } }
    document.addEventListener('mousedown', click); document.addEventListener('keydown', key)
    return () => { document.removeEventListener('mousedown', click); document.removeEventListener('keydown', key) }
  }, [setOpen, historyOpen, annOpen, syntaxOpen])

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
      const ver = Number(qVer) || rc?.version || rec?.version || 1
      const code = rc?.code || rec?.code || ''
      const name = rc?.name || rec?.name || qAlpha
      const storedRec = rec ? {
        id: rec.id || qAlpha,
        name,
        result: rec.result || null,
        metrics: rec.metrics || rec.result?.metrics || null,
        code,
        config: rec.config || rec.result?.config || null,
      } : null
      const d = newDraft(name, code, {
        alphaId: qAlpha,
        alphaVersion: ver,
        saved: { alpha_id: qAlpha, code, name },
        stored: storedRec,
        runAlpha: qAlpha,
        baseCode: code,
      })
      set((p) => ({ drafts: [...p.drafts, d], active: d.id, form: (rc?.config || rec?.config) ? { ...p.form, ...configToForm(rc?.config || rec.config, POSITION_KEYS) } : p.form }))
      setCompiled(null); setTab('results')
      setNote({ tone: 'ok', text: `Đã nạp “${d.name}” (phiên bản ${ver}) để sửa. Chạy backtest rồi “Lưu chiến lược” sẽ tạo phiên bản mới của alpha này.` })
    }, (e) => setNote({ tone: 'bad', text: `Không mở được alpha để sửa: ${e.message}` })).finally(() => setOpeningId(''))
  }, [qAlpha, qVer]) // eslint-disable-line react-hooks/exhaustive-deps
  // Sao chép chiến lược công khai của người khác: /edu/studio?fork=<id> -> bản nháp mới kèm tên tác giả
  const qFork = sp.get('fork')
  const forked = useRef('')
  useEffect(() => {
    if (!qFork || forked.current === qFork) return
    forked.current = qFork
    setOpeningId(qFork); setNote(null)
    getEduStrategy(qFork).then((r) => {
      const ownerTag = r.owner?.handle ? `@${r.owner.handle}` : (r.owner?.display_name || '')
      const nameSuffix = ownerTag ? ` (bản sao từ ${ownerTag})` : ' (bản sao)'
      const forkedName = `${r.name || 'Chiến lược'}${nameSuffix}`
      const storedRec = r.result ? {
        id: r.id,
        name: forkedName,
        result: r.result,
        metrics: r.result.metrics || null,
        code: r.code || '',
        config: r.result.config || null,
      } : null
      const d = newDraft(forkedName, r.code || '', {
        stored: storedRec,
        baseCode: r.code || '',
        baseConfig: r.result?.config || null,
      })
      set((p) => ({
        seeded: true,
        drafts: [...p.drafts.filter((x) => x.code.trim() || x.jobId), d],
        active: d.id,
        form: r.result?.config ? { ...p.form, ...configToForm(r.result.config, POSITION_KEYS) } : p.form,
      }))
      setCompiled(null); setTab('results')
      setNote({ tone: 'ok', text: `Đã sao chép “${r.name}” của ${ownerTag || 'người dùng khác'}. Chạy backtest rồi lưu để thành chiến lược của bạn.` })
    }, (e) => setNote({ tone: 'bad', text: `Không sao chép được chiến lược: ${e.message}` })).finally(() => setOpeningId(''))
  }, [qFork]) // eslint-disable-line react-hooks/exhaustive-deps
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
    if (educ && compiled?.route?.engine === 'native') {
      setRunErr('Chiến lược này phức tạp — hãy chuyển sang Studio Coin để sử dụng toàn bộ tính năng Nautilus Trader bản địa.')
      return
    }
    setBusy('run'); setRunErr(null); setNote(null)
    const id0 = draft.id
    const code0 = draft.code
    try {
      if (form.run_mode && form.run_mode !== 'backtest') {
        const r = await postLiveBot({
          mode: form.run_mode,
          code: code0,
          symbols: form.symbols?.length ? form.symbols : (universe?.length ? universe.slice(0, 10) : ['BTC/USDT']),
          capital: Number(form.capital) || 10000,
          base_frame: form.timeframe || '1h',
        })
        const id = r?.job_id || r?.id
        const botId = r?.bot_id
        if (!id) throw new Error('Máy chủ không trả mã job bot.')
        patchById(id0, { jobId: id, botId, runCode: code0, runAlpha: '', stored: null })
        setTab('results')
      } else {
        const r = await postCustomBacktest(buildRunBody(form, code0, null, defaultExecMode(meta)))
        const id = r?.job_id || r?.id
        if (!id) throw new Error('Máy chủ không trả mã job.')
        patchById(id0, { jobId: id, botId: null, runCode: code0, runAlpha: '', stored: null })
        setTab('results')
      }
    } catch (e) {
      const err = parseCompileError(e.message)
      if (err?.line) showCompiled(code0, { ok: false, error: err })
      setRunErr(err?.line ? null : e.message)
    } finally { setBusy('') }
  }

  const rawSavedItems = Array.isArray(saved.data) ? saved.data : []
  const savedItems = useMemo(() => {
    if (!me?.id) return rawSavedItems.filter((item) => !item.owner_id)
    return rawSavedItems.filter((item) => item.owner_id === me.id)
  }, [rawSavedItems, me?.id])
  const codeChanged = draft.baseCode ? draft.code !== draft.baseCode : true
  const configChanged = (() => {
    if (!draft.baseConfig || !jobResult?.config) return false
    const kList = ['symbols', 'start', 'end', 'train_ratio', 'initial_capital', 'timeframe']
    const diffCore = kList.some((k) => JSON.stringify(draft.baseConfig[k]) !== JSON.stringify(jobResult.config[k]))
    if (diffCore) return true
    return JSON.stringify(draft.baseConfig.position) !== JSON.stringify(jobResult.config.position)
  })()
  const changed = codeChanged || configChanged || !draft.baseCode

  // Chỉ coi là trùng lặp nếu trùng cả mã hash code VÀ cấu hình tham số với một alpha khác đã lưu
  const isDup = !draft.alphaId && !!jobResult && savedItems.some((a) => {
    if (!a.program_hash || a.program_hash !== jobResult.program_hash) return false
    if (a.config && jobResult.config) {
      const kList = ['symbols', 'start', 'end', 'train_ratio', 'initial_capital', 'timeframe']
      const sameCore = kList.every((k) => JSON.stringify(a.config[k]) === JSON.stringify(jobResult.config[k]))
      if (sameCore && JSON.stringify(a.config.position) === JSON.stringify(jobResult.config.position)) {
        return true
      }
      return false
    }
    return !configChanged && !codeChanged
  })

  const canSave = educ
    ? (draft.code.trim().length > 0 && changed && !isDup && !busy)
    : (!!jobResult && draft.runCode === draft.code && changed && !isDup && !busy)

  const saveWhy = educ
    ? (!draft.code.trim() ? 'Nhập mã chiến lược trước khi lưu'
      : !changed ? 'Chưa sửa so với bản đã lưu'
      : isDup ? 'Đã lưu chiến lược có cùng code này'
      : 'Lưu chiến lược vào danh mục của bạn')
    : (!draft.jobId ? 'Chạy backtest cho code hiện tại trước khi lưu'
      : !jobResult ? 'Chờ lần chạy hoàn tất'
      : draft.runCode !== draft.code ? 'Chạy lại sau khi sửa'
      : !changed ? (draft.sampleKey ? 'Mẫu chưa thay đổi: sửa code hoặc tham số rồi chạy lại' : 'Chưa sửa so với bản đã lưu: sửa code hoặc tham số rồi chạy lại')
      : isDup ? 'Đã lưu chiến lược có cùng code và tham số này'
      : 'Lưu chiến lược (code + cấu hình + kết quả đầy đủ)')

  function markSaved(res, name) {
    const savedName = name || draft.name
    patchById(draft.id, {
      saved: { alpha_id: res.alpha_id, code: draft.code, name: savedName },
      runAlpha: res.alpha_id,
      name: savedName,
      stored: {
        id: res.alpha_id,
        name: savedName,
        result: jobResult || draft.stored?.result,
        metrics: jobResult?.metrics || draft.stored?.metrics,
        code: draft.code,
        config: jobResult?.config || draft.stored?.config,
      },
      alphaId: res.alpha_id,
      alphaVersion: res.version || 1,
      baseCode: draft.code,
      sampleKey: '',
    })
    saved.reload()
    if (educ) sampleRes.reload()
  }

  async function saveForLeave() {
    const name = draft.name.trim() || 'Chiến lược của tôi'
    markSaved(await postSaveUserAlpha({ job_id: draft.jobId, code: draft.code, name, note: '', source: educ ? 'education' : 'alpha-create', alpha_id: draft.alphaId }), name)
  }

  async function openSaved(id) {
    const have = drafts.find((d) => d.saved?.alpha_id === id)
    if (have) {
      set((p) => ({
        active: have.id,
        form: have.stored?.config ? { ...p.form, ...configToForm(have.stored.config, POSITION_KEYS) } : p.form,
      }))
      setTab('results')
      return
    }
    setOpeningId(id); setNote(null)
    try {
      const rec = await getUserAlphaDetail(id)
      const d = newDraft(rec.name || rec.id, rec.code || '', {
        saved: { alpha_id: rec.id, code: rec.code || '', name: rec.name || rec.id },
        stored: rec,
        runAlpha: rec.id,
        alphaId: rec.id,
        alphaVersion: rec.version || 1,
        baseCode: rec.code || '',
        baseConfig: rec.config || null,
      })
      set((p) => ({ drafts: [...p.drafts.filter((x) => x.code.trim() || x.jobId || x.saved || x.alphaId), d], active: d.id, form: { ...p.form, ...configToForm(rec.config, POSITION_KEYS) } }))
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

  // Education: chỉ user chưa lưu chiến lược nào thấy đúng 1 mẫu hướng dẫn (backend quyết định); user đã có chiến lược không thấy mục mẫu.
  const sampleRes = useAsync(educ ? () => getEduSamplesVisible().then((r) => r.samples || []) : getEducationSamples, [educ, me?.id, meLoading])
  const sampleList = Array.isArray(sampleRes.data) ? sampleRes.data : []
  const sampleText = async (code) => {
    if (!code) return code
    const text = code
    if (!educ) return text
    try { return (await postAnnotate(text, { as_comments: true })).annotated_code || text } catch (e) { return text }
  }

  // ─── TỰ ĐỘNG NẠP BAN ĐẦU (SEEDING) ──────────────────────────────────────────
  // Yêu cầu: khi vào Studio (hoặc vào lại Studio khi chưa run gì cả):
  // - Nếu user CHƯA có chiến lược: view code mẫu + view KẾT QUẢ của code mẫu đó luôn.
  // - Nếu user ĐÃ có chiến lược: view code + view KẾT QUẢ của chiến lược ĐẦU TIÊN (savedItems[0]).
  // => Đảm bảo view kết quả (CustomResult) KHÔNG BAO GIỜ BỊ TRỐNG.
  const prevUserIdRef = useRef(me?.id)
  const seedingRef = useRef(false)

  // Khi đổi user đăng nhập trong header: reset cờ để nạp đúng chiến lược / mẫu của user mới
  useEffect(() => {
    if (prevUserIdRef.current !== me?.id) {
      prevUserIdRef.current = me?.id
      seedingRef.current = false
      set({ seeded: false })
    }
  }, [me?.id])

  useEffect(() => {
    if (meLoading || saved.loading) return
    if (qJob || qAlpha || qFork) { set({ seeded: true }); return }
    if (seedingRef.current) return

    const d0 = drafts.find((d) => d.id === st.active) || drafts[0]
    const hasResultOrJob = !!d0?.jobId || !!d0?.stored?.result

    // Nếu đã seeded VÀ bản nháp hiện tại đã có code và kết quả -> giữ nguyên; nếu chưa có kết quả -> nạp ngay alpha đầu tiên
    if (st.seeded && hasResultOrJob && d0?.code?.trim()) return

    const hasSaved = savedItems.length > 0

    if (hasSaved) {
      // User ĐÃ CÓ chiến lược: nạp code và kết quả chiến lược ĐẦU TIÊN trong danh sách
      const firstStrat = savedItems[0]
      seedingRef.current = true
      getUserAlphaDetail(firstStrat.id).then((rec) => {
        const d = newDraft(rec.name || firstStrat.name || firstStrat.id, rec.code || '', {
          saved: { alpha_id: rec.id, code: rec.code || '', name: rec.name || rec.id },
          stored: rec,
          runAlpha: rec.id,
          alphaId: rec.id,
          alphaVersion: rec.version || 1,
          baseCode: rec.code || '',
          baseConfig: rec.config || null,
        })
        set((p) => ({
          seeded: true,
          drafts: [d],
          active: d.id,
          form: rec.config ? { ...p.form, ...configToForm(rec.config, POSITION_KEYS) } : p.form,
        }))
        setCompiled(null)
        setTab('results')
      }).catch(() => {
        set({ seeded: true })
      }).finally(() => {
        seedingRef.current = false
      })
    } else {
      // User CHƯA CÓ chiến lược: nạp code mẫu VÀ kết quả của code mẫu đó
      const s0 = sampleList[0]
      if (!s0 && sampleRes.loading) return // Đợi danh sách mẫu tải xong
      seedingRef.current = true

      const fetchSample = async () => {
        let sampleObj = s0
        if (!sampleObj) {
          try {
            const allSamples = await getEducationSamples()
            if (Array.isArray(allSamples) && allSamples.length) sampleObj = allSamples[0]
          } catch (e) { /* fallback */ }
        }
        if (!sampleObj) { set({ seeded: true }); seedingRef.current = false; return }

        const text = await sampleText(sampleObj.code)
        let sampleResData = sampleObj.result || null
        if (!sampleResData && sampleObj.key) {
          try {
            sampleResData = await getEducationSampleResult(sampleObj.key)
          } catch (e) { /* fallback */ }
        }

        const sampleKey = sampleObj.key || sampleObj.name
        const storedRec = sampleResData ? {
          id: sampleKey,
          name: sampleObj.name,
          result: sampleResData,
          metrics: sampleObj.metrics || sampleResData?.metrics || null,
          code: sampleObj.code,
          config: sampleResData?.config || null,
        } : null

        const d = newDraft(sampleObj.name, text, {
          sampleKey,
          baseCode: text,
          stored: storedRec,
          saved: storedRec ? { alpha_id: sampleKey, code: sampleObj.code, name: sampleObj.name } : null,
          runAlpha: sampleKey,
          alphaId: '',
          alphaVersion: 1,
        })

        set((p) => ({
          seeded: true,
          drafts: [d],
          active: d.id,
          form: (storedRec?.config) ? { ...p.form, ...configToForm(storedRec.config, POSITION_KEYS) } : p.form,
        }))
        setCompiled(null)
        setTab('results')
      }

      fetchSample().catch(() => set({ seeded: true })).finally(() => { seedingRef.current = false })
    }
  }, [meLoading, saved.loading, savedItems.length, sampleList.length, sampleRes.loading, st.seeded, drafts]) // eslint-disable-line react-hooks/exhaustive-deps

  // ─── HYDRATION KẾT QUẢ KHI VÀO LẠI / TẢI LẠI TRANG ──────────────────────────
  // 1. Alpha đã lưu: nếu draft đang trỏ tới một alpha nhưng kết quả bị rỗng -> nạp lại từ backend
  const savedHydrated = useRef(new Set())
  useEffect(() => {
    let targetId = draft.saved?.alpha_id || draft.alphaId || (draft.storedId && !draft.sampleKey ? draft.storedId : '')
    if (!targetId && savedItems?.length) {
      const match = savedItems.find((s) => s.name === draft.name || s.id === draft.name)
      if (match) targetId = match.id
    }
    if (!targetId || draft.stored?.result || draft.jobId || savedHydrated.current.has(targetId)) return
    savedHydrated.current.add(targetId)
    const id = draft.id
    getUserAlphaDetail(targetId).then((rec) => {
      if (!rec?.result) return
      patchById(id, {
        stored: rec,
        saved: { alpha_id: rec.id, code: rec.code || draft.code, name: rec.name || draft.name },
        name: rec.name || draft.name,
        code: draft.code || rec.code || '',
        baseCode: draft.baseCode || rec.code || '',
        alphaId: rec.id,
        alphaVersion: rec.version || 1,
      })
      if (rec.config) set((p) => ({ form: { ...p.form, ...configToForm(rec.config, POSITION_KEYS) } }))
    }).catch(() => { /* bỏ qua */ })
  }, [draft.id, draft.name, draft.saved?.alpha_id, draft.alphaId, draft.storedId, draft.sampleKey, draft.stored?.result, draft.jobId, savedItems]) // eslint-disable-line react-hooks/exhaustive-deps

  // 2. Mẫu: nếu draft đang trỏ tới mẫu nhưng kết quả bị rỗng -> nạp kết quả tính sẵn từ backend
  const sampleTried = useRef(new Set())
  useEffect(() => {
    let key = draft.sampleKey || (draft.storedId && !draft.alphaId && !draft.saved?.alpha_id ? draft.storedId : '')
    if (!key && sampleList?.length) {
      const match = sampleList.find((s) => s.name === draft.name || s.key === draft.name)
      if (match) key = match.key
    }
    if (!key || draft.stored?.result || draft.jobId || sampleTried.current.has(key)) return
    sampleTried.current.add(key)
    const id = draft.id
    getEducationSampleResult(key).then((resData) => {
      if (!resData) return
      patchById(id, {
        stored: { id: key, name: draft.name, result: resData, metrics: resData.metrics, code: draft.code, config: resData.config },
        sampleKey: key,
      })
      if (resData.config) set((p) => ({ form: { ...p.form, ...configToForm(resData.config, POSITION_KEYS) } }))
    }).catch(() => { /* NOT_READY / lỗi: không thử lại trong phiên */ })
  }, [draft.id, draft.name, draft.sampleKey, draft.storedId, draft.alphaId, draft.saved?.alpha_id, draft.stored?.result, draft.jobId, sampleList]) // eslint-disable-line react-hooks/exhaustive-deps

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

  const tm = compiled?.meta?.timeframe
  const uniText = `${form.symbols.length} tài sản`
  const issue = compiled && !stale && !compiled.ok
  const allStrategies = useMemo(() => {
    const list = []
    sampleList.forEach((s) => {
      const b = s.backtest?.out_of_sample || s.summary || s.result?.metrics?.simulate || s.metrics || {}
      list.push({
        id: s.key || s.name,
        name: s.name,
        code: s.code,
        result: s.result,
        metrics: { simulate: b },
        isSample: true,
        tag: 'Mẫu hệ thống',
        raw: s,
      })
    })
    savedItems.forEach((u) => {
      list.push({
        id: u.id,
        name: u.name || u.id,
        code: u.code,
        result: u.result,
        metrics: u.metrics || u.result?.metrics,
        checklist: u.checklist,
        version: u.version,
        updated_at: u.updated_at,
        isSample: false,
        tag: 'Đã lưu',
        raw: u,
      })
    })
    return list
  }, [sampleList, savedItems])

  const TABS = useMemo(() => {
    if (!educ) {
      return [
        ['alphas', `Chiến lược (${allStrategies.length})`],
        ['results', 'Kết quả'],
      ]
    }
    const tabs = []
    if (sampleList.length > 0) {
      tabs.push(['samples', 'Mẫu hướng dẫn'])
    }
    tabs.push(['alphas', `Chiến lược (${savedItems.length})`])
    tabs.push(['results', 'Kết quả'])
    return tabs
  }, [educ, allStrategies.length, sampleList.length, savedItems.length])

  async function useSample(s) {
    // 1. Mẫu đã mở ở một tab -> chọn tab đó (khoá trước, dự phòng theo tên)
    const openDraft = findBy(drafts, s, (d) => d.sampleKey, (d) => d.name)
    if (openDraft) { activateTab(openDraft.id); return }

    // 2. Đã có bản lưu trong kho alpha người dùng -> mở bản lưu
    const matched = findBy(savedItems, s, (a) => a.id, (a) => a.name)
    if (matched) { await openSaved(matched.id); return }

    // 3. Tab mới chứa code mẫu; tự động nạp kết quả tính sẵn để view ngay lập tức không bị trống
    let sampleResData = s.result || null
    if (!sampleResData && s.key) {
      try {
        sampleResData = await getEducationSampleResult(s.key)
      } catch (e) { /* fallback */ }
    }
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

  if (!educ && studioMode === 'prompt') {
    return (
      <div className="se-ws" style={{ display: 'block', padding: '16px 20px', overflowY: 'auto', height: '100%' }}>
        <div style={{ marginBottom: 14, display: 'flex' }}><ModeSwitch value="prompt" onChange={setStudioMode} /></div>
        <PromptResearchView
          onOpenCode={(data) => {
            if (typeof data === 'string') {
              patchDraft({ code: data })
            } else if (data && typeof data === 'object') {
              const { code, name, symbol, timeframe } = data
              patchDraft({
                code: code || '',
                name: name || draft.name,
              })
              if (symbol || timeframe) {
                setForm((prev) => ({
                  ...prev,
                  ...(symbol ? { symbols: [symbol.replace('-', '/')] } : {}),
                  ...(timeframe ? { timeframe } : {}),
                }))
              }
            }
            setStudioMode('code')
          }}
          onSaved={() => saved.refetch?.()}
        />
      </div>
    )
  }

  const onCodeChange = (code) => {
    // Khi sửa code khác mẫu gốc: xoá cờ sampleKey & stored để không tự động nạp lại kết quả mẫu
    const isCustomized = draft.sampleKey && code !== draft.baseCode
    patchDraft({
      code,
      ...(isCustomized ? { sampleKey: '', stored: null, saved: null, alphaId: '' } : {}),
    })
  }

  return (
    <div className="se-ws">
      <div className="se-left">
        <div className="se-top">
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
        {!educ && <ModeSwitch value="code" onChange={setStudioMode} />}
        </div>

        <div className="se-hd">
          <input className="se-name" aria-label="Tên chiến lược" placeholder="Tên chiến lược" value={draft.name} onChange={(e) => patchDraft({ name: e.target.value })} />
          <div className="se-chips" data-tour="code-settings">
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
            <button type="button" className="n-icon-btn" aria-label="Tài liệu cú pháp Nora" aria-expanded={syntaxOpen} title="Tài liệu & Cú pháp Nora Strategy (Python)" onClick={() => setSyntaxOpen(!syntaxOpen)}>📖</button>
            <button type="button" className={`n-icon-btn ${problems.length ? 'warn' : ''}`} aria-label="Cài đặt chạy" aria-expanded={setOpen} title="Cài đặt chạy" onClick={() => setSetOpen(!setOpen)}>{ICON.gear}</button>
            <button type="button" className="n-icon-btn" aria-label="Kiểm tra code" title="Kiểm tra (biên dịch, không chạy)" disabled={!!busy || !draft.code.trim()} onClick={() => { compile(); setStrip(true) }}>{busy === 'compile' ? <Spinner /> : ICON.check}</button>
            {educ && <button type="button" className="n-icon-btn" aria-label="Chú thích" aria-expanded={annOpen} title="Chú thích tiếng Việt `# ▸` trên từng dòng" disabled={annBusy || !draft.code.trim()} onClick={() => setAnnOpen(!annOpen)}>{annBusy ? <Spinner /> : <b style={{ fontSize: 12 }}>▸#</b>}</button>}
            <button type="button" className="n-icon-btn" aria-label="Nhân bản" title="Nhân bản sang tab mới" onClick={() => addDraft(`${draft.name} (bản sao)`, draft.code)}>{ICON.copy}</button>
            {syntaxOpen && (
              <div className="n-pop se-setp" style={{ maxWidth: 540, width: '92vw', maxHeight: '80vh', overflowY: 'auto' }} role="dialog" aria-label="Tài liệu cú pháp Nora">
                <div className="n-pop-h">
                  <b>Tài liệu Cú pháp Nora Strategy (Python)</b>
                  <button type="button" className="n-btn sm" onClick={() => setSyntaxOpen(false)}>Đóng</button>
                </div>
                <div className="se-setb" style={{ fontSize: 13, lineHeight: 1.6, padding: '12px 16px' }}>
                  <p style={{ margin: '0 0 10px 0' }}>
                    Chiến lược trong Nora Studio tuân thủ định dạng <b>Nora DSL / SimpleAlgorithm</b> thực thi trên nền tảng <b>NautilusTrader</b> có kiểm soát an toàn bộ nhớ (4 GB/job).
                  </p>
                  <h4 style={{ margin: '12px 0 6px 0', fontSize: 13.5 }}>1. Cấu trúc lớp chiến lược</h4>
                  <pre style={{ background: 'var(--n-surface)', padding: 10, borderRadius: 6, fontSize: 12, overflowX: 'auto' }}>
{`class Strategy(SimpleAlgorithm):
    def initialize(self):
        # Đăng ký các chỉ báo cần dùng
        self.fast = self.ema(period=12)
        self.slow = self.ema(period=26)
        self.rsi = self.rsi(period=14)

    def on_bar(self, bar):
        # Logic giao dịch theo từng nến đóng
        if self.fast.value > self.slow.value and self.rsi.value < 70:
            self.buy()
        elif self.fast.value < self.slow.value:
            self.close()`}
                  </pre>
                  <h4 style={{ margin: '12px 0 6px 0', fontSize: 13.5 }}>2. Các chỉ báo hỗ trợ sẵn</h4>
                  <ul style={{ paddingLeft: 18, margin: '4px 0' }}>
                    <li><code>self.ema(period)</code>: Exponential Moving Average</li>
                    <li><code>self.sma(period)</code>: Simple Moving Average</li>
                    <li><code>self.rsi(period)</code>: Relative Strength Index</li>
                    <li><code>self.atr(period)</code>: Average True Range</li>
                    <li><code>self.bollinger(period, std)</code>: Bollinger Bands</li>
                    <li><code>self.macd(fast, slow, signal)</code>: MACD</li>
                  </ul>
                  <h4 style={{ margin: '12px 0 6px 0', fontSize: 13.5 }}>3. Hành động giao dịch & Quản lý rủi ro</h4>
                  <ul style={{ paddingLeft: 18, margin: '4px 0' }}>
                    <li><code>self.buy(qty=None)</code>: Mở vị thế Long</li>
                    <li><code>self.sell(qty=None)</code>: Mở vị thế Short</li>
                    <li><code>self.close()</code>: Đóng toàn bộ vị thế</li>
                    <li><code>self.set_stop_loss(pct)</code>: Đặt dừng lỗ tự động theo % giá</li>
                  </ul>
                  <div style={{ marginTop: 12, padding: '8px 10px', borderRadius: 6, background: 'rgba(239, 68, 68, 0.1)', color: 'var(--n-neg)', fontSize: 12 }}>
                    ⚠️ <b>Lưu ý an toàn:</b> Hệ thống không cho phép import các module hệ thống không an toàn (như <code>os</code>, <code>sys</code>, <code>subprocess</code>, <code>socket</code>). Mọi phép tính số liệu do backend NautilusTrader thực hiện; tiến trình bị giới hạn cứng 4 GB RAM.
                  </div>
                </div>
              </div>
            )}
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
                  <RunSettings
                    form={form}
                    setForm={setForm}
                    universe={universe}
                    defaultsError={defaultsError}
                    problems={problems}
                    specDefaults={compiled?.meta?.position_overrides || {}}
                    specHash={compiled?.hash || null}
                  />
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
          {!educ && compiled?.route && (
            <span
              className={`n-badge ${compiled.route.engine === 'native' ? 'warn' : 'ok'}`}
              style={{ alignSelf: 'center', marginRight: 6, fontSize: 11, padding: '3px 8px' }}
              title={(compiled.route.reasons || []).join(' · ')}
            >
              {compiled.route.engine === 'native' ? 'Biên dịch: Nautilus native' : 'Biên dịch: Nora DSL'}
            </span>
          )}
          <button type="button" className="se-save" onClick={() => setSaveOpen(true)} disabled={!canSave} title={saveWhy}>{ICON.save} Lưu chiến lược</button>
          <button type="button" className="se-run" data-tour="code-run" onClick={run} disabled={!!busy || running || problems.length > 0} title={problems[0] || 'Ctrl/⌘ + Enter'}>
            {busy === 'run' || running ? <><Spinner /> {status === 'queued' ? 'Đang xếp hàng…' : 'Đang chạy…'}</> : <>{ICON.play} {form.run_mode === 'paper' ? 'Chạy Paper Bot' : form.run_mode === 'testnet' ? 'Chạy Testnet Bot' : form.run_mode === 'live' ? 'Chạy Live Bot' : 'Chạy backtest'}</>}
          </button>
        </div>

        {educ && compiled?.route?.engine === 'native' && (
          <div className="n-note" role="alert" style={{ margin: '8px 12px 0', padding: '8px 12px', border: '1px solid var(--n-border)', borderRadius: 6, background: 'rgba(234, 179, 8, 0.1)' }}>
            ⚠️ <b>Chiến lược phức tạp:</b> Mã này có dấu hiệu khớp lệnh / sự kiện Nautilus bản địa. Vui lòng chuyển sang <a href="/coin/alpha/create" style={{ color: 'var(--n-accent, #38bdf8)', textDecoration: 'underline' }}>Coin Studio</a> để chạy.
          </div>
        )}

        <div className="se-code" data-tour="code-editor">
          {!draft.code.trim() && <div className="se-empty-code">Soạn chiến lược Python (lớp kế thừa SimpleAlgorithm) hoặc mở một mẫu ở tab “Mẫu”. Gõ để nhận gợi ý dữ liệu / chỉ báo / toán tử; Ctrl/⌘ + Enter để chạy.</div>}
          <CodeEditor ref={edRef} value={draft.code} onChange={onCodeChange} onRun={run} errorLine={errLine} errorKey={compiled?.nonce} onAssist={setAssist} />
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
                  <JobPanel job={job} status={status} error={jobErr} title="Backtest Python" isBacktest={true} />
                  <button type="button" className="n-btn sm" onClick={() => patchDraft({ jobId: '', runCode: '', runAlpha: '' })} disabled={running}>Bỏ kết quả</button>
                </div>
              )}
              {draft.jobId && status === 'done' && (
                <CustomResult
                  key={draft.jobId}
                  result={jobResult}
                  explain={educ}
                  tourKey={''}
                  jobLine={<JobLine job={job} savedId={draft.saved && draft.saved.alpha_id === draft.runAlpha ? draft.saved.alpha_id : ''} onClear={() => patchDraft({ jobId: '', runCode: '', runAlpha: draft.saved ? draft.saved.alpha_id : '' })} />}
                />
              )}
              {!draft.jobId && draft.stored?.result && (
                <CustomResult
                  key={`s-${draft.stored.id}`}
                  result={draft.stored.result}
                  explain={educ}
                  tourKey={educ && savedItems.length === 0 ? `sample-${draft.stored.id || draft.sampleKey || 's0'}` : ''}
                  jobLine={<StoredLine rec={draft.stored} />}
                />
              )}
              {!draft.jobId && !draft.stored?.result && <Empty title="Chưa có kết quả">Chọn rổ tài sản và khoảng ngày ở biểu tượng cài đặt, rồi bấm “Chạy backtest”. Kết quả (Train / Test / Toàn kỳ, đường lãi lỗ, drawdown, lệnh) hiện ở đây và chỉ là tạm thời cho tới khi bấm “Lưu chiến lược”.</Empty>}
            </div>
          )}
          {tab === 'alphas' && (
            <div className="se-samples">
              <div className="se-cards-hdr" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <h3 className="se-h3" style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>
                  {!educ ? `Chiến lược (${allStrategies.length})` : `Chiến lược đã lưu (${savedItems.length})`}
                </h3>
                {saved?.loading && <span className="muted" style={{ fontSize: 12 }}><Spinner /> Đang tải...</span>}
              </div>
              <div className="se-cards">
                {(!educ ? allStrategies : savedItems).length === 0 && (
                  <Empty title="Chưa có chiến lược">
                    Chưa có chiến lược nào trong danh mục.
                  </Empty>
                )}
                {(!educ ? allStrategies : savedItems).map((item) => {
                  const isActive = draft.saved?.alpha_id === item.id || draft.alphaId === item.id || draft.sampleKey === item.id
                  const isOpening = openingId === item.id
                  const sim = item.metrics?.simulate || item.metrics?.all || item.result?.metrics?.simulate || item.result?.metrics?.all || null
                  const retPct = sim ? (sim.ret_pct ?? sim.return_pct ?? sim.total_return_pct ?? sim.ret) : null
                  const mddPct = sim ? (sim.mdd_pct ?? sim.max_drawdown_pct ?? sim.mdd) : null
                  const sharpe = sim ? (sim.sharpe ?? sim.sharpe_ratio) : null
                  const winRate = sim ? (sim.win_rate_trades ?? sim.win_rate ?? sim.win_rate_pct) : null
                  const checklistItems = Array.isArray(item.checklist)
                    ? item.checklist
                    : Array.isArray(item.checklist?.items)
                      ? item.checklist.items
                      : null
                  const passAnalyst = Boolean(
                    item.pass_analyst ||
                    item.card?.pass_analyst ||
                    item.checklist?.all_passed ||
                    item.checklist?.pass ||
                    (checklistItems && checklistItems.length > 0 && checklistItems.every((c) => c.ok || c.state === 'pass' || c.passed === true))
                  )

                  const handleItemClick = () => {
                    if (item.isSample) {
                      useSample(item.raw)
                    } else {
                      openSaved(item.id)
                    }
                  }

                  return (
                    <div
                      key={item.id}
                      className={`n-card-sel se-sample-card ${isActive ? 'on' : ''}`}
                      role="button"
                      tabIndex={0}
                      onClick={handleItemClick}
                      onKeyDown={(e) => { if (e.key === 'Enter') handleItemClick() }}
                      style={{ cursor: 'pointer', padding: '12px 14px', marginBottom: 10 }}
                    >
                      <div className="se-card-h" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                        <b className="se-card-title" style={{ fontSize: 14 }}>{item.name || item.id}</b>
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                          <span className="n-badge" style={{ fontSize: 10 }}>
                            {item.tag || (item.isSample ? 'Mẫu hệ thống' : 'Đã lưu')}
                          </span>
                          {passAnalyst && (
                            <span style={{ fontSize: 10.5, padding: '2px 6px', borderRadius: 4, background: 'rgba(16, 185, 129, 0.15)', color: 'var(--n-pos, #10b981)', fontWeight: 600 }}>
                              Đạt Analyst ✓
                            </span>
                          )}
                        </div>
                      </div>

                      {sim ? (
                        <div className="se-card-metrics" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 12px', fontSize: 12 }}>
                          <div className="se-metric-row">
                            <span className="se-metric-lbl" style={{ color: 'var(--n-ink-2)' }}>Lãi/Lỗ:</span>
                            <span className={`se-metric-val ${retPct > 0 ? 'pos' : retPct < 0 ? 'neg' : ''}`} style={{ fontWeight: 600 }}>
                              {retPct != null ? (retPct >= 0 ? `+${Number(retPct).toFixed(2)}%` : `${Number(retPct).toFixed(2)}%`) : '—'}
                            </span>
                          </div>
                          <div className="se-metric-row">
                            <span className="se-metric-lbl" style={{ color: 'var(--n-ink-2)' }}>MDD:</span>
                            <span className="se-metric-val neg" style={{ fontWeight: 600 }}>
                              {mddPct != null ? `${(-Math.abs(Number(mddPct))).toFixed(2)}%` : '—'}
                            </span>
                          </div>
                          <div className="se-metric-row">
                            <span className="se-metric-lbl" style={{ color: 'var(--n-ink-2)' }}>Sharpe:</span>
                            <span className="se-metric-val" style={{ fontWeight: 600 }}>
                              {sharpe != null ? Number(sharpe).toFixed(2) : '—'}
                            </span>
                          </div>
                          <div className="se-metric-row">
                            <span className="se-metric-lbl" style={{ color: 'var(--n-ink-2)' }}>Win rate:</span>
                            <span className="se-metric-val" style={{ fontWeight: 600 }}>
                              {winRate != null ? `${Number(winRate).toFixed(1)}%` : '—'}
                            </span>
                          </div>
                        </div>
                      ) : (
                        <div className="se-card-metrics"><span className="muted" style={{ fontSize: 12 }}>Chưa có kết quả đã lưu</span></div>
                      )}

                      <div style={{ marginTop: 8, fontSize: 11, color: 'var(--n-ink-2)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span>{item.isSample ? 'Mẫu chuẩn hệ thống' : `Phiên bản: v${item.version || 1}`}</span>
                        <span>{item.updated_at ? String(item.updated_at).slice(0, 10) : ''}</span>
                      </div>
                      {isOpening && <Spinner />}
                    </div>
                  )
                })}
              </div>
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
