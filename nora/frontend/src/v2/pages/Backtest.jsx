import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Segmented, Field, ErrorBox, Empty, Spinner, Status } from '../components/ui'
import StrategyPicker from '../components/StrategyPicker'
import JobPanel from '../components/JobPanel'
import DashboardLoader, { PERIODS } from '../components/Dashboard'
import WfaResult from '../components/WfaResult'
import McResult from '../components/McResult'
import useJob from '../hooks/useJob'
import { useCatalog } from '../context/Catalog'
import { postBacktest, postWfa, postMc } from '../api'
import { parseJobArgs, JOB_STATUS } from '../lib/jobs'

function readPrefill(location, sp) {
  const st = location.state?.prefill
  if (st) return st
  const q = sp.get('prefill')
  if (q) { try { return JSON.parse(q) } catch (e) { return null } }
  return null
}

function selFromStrategies(list, catalog) {
  const out = {}
  ;(list || []).forEach((s) => {
    const c = catalog.find((x) => x.id === s.id)
    if (c) out[s.id] = { ...(c.default_params || {}), ...(s.params || {}) }
  })
  return out
}

function LockIcon() {
  return (
    <svg className="n-ico" width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
  )
}

/* ---------------------------- Bước 1: Backtest ---------------------------- */
function StepBacktest({ cat, form, setForm, btId, bt, onLaunched, onNext }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [period, setPeriod] = useState('ALL')
  const universe = cat.universe || []
  const nSel = Object.keys(form.sel).length

  async function run() {
    setErr(null)
    if (!nSel) return setErr('Chọn ít nhất một chiến lược.')
    if (!form.symbols.length) return setErr('Chọn ít nhất một cặp giao dịch.')
    if (!form.start || !form.end || form.start >= form.end) return setErr('Ngày bắt đầu phải trước ngày kết thúc.')
    setBusy(true)
    try {
      const r = await postBacktest({
        strategies: Object.entries(form.sel).map(([id, params]) => ({ id, params })),
        symbols: form.symbols, start: form.start, end: form.end,
        risk_per_trade_pct: Number(form.risk), stop_fill: form.stopFill,
      })
      onLaunched(r.job_id)
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const toggleSym = (s) => setForm({ symbols: form.symbols.includes(s) ? form.symbols.filter((x) => x !== s) : [...form.symbols, s] })
  const useBook = () => setForm({ sel: selFromStrategies(cat.book?.strategies, cat.catalog) })

  return (
    <>
      <div className="n-grid g-main-side">
        <Panel title="Chiến lược" meta={
          <>
            <button type="button" className="n-btn sm" onClick={useBook} disabled={!cat.book?.strategies?.length}>Dùng sổ hiện tại</button>
            <button type="button" className="n-btn sm" onClick={() => setForm({ sel: {} })} disabled={!nSel}>Bỏ chọn</button>
            <span className="mono">{nSel} đã chọn</span>
          </>
        }>
          <StrategyPicker catalog={cat.catalog} sel={form.sel} setSel={(sel) => setForm({ sel })} />
        </Panel>
        <div style={{ display: 'grid', gap: 12, alignContent: 'start' }}>
          <Panel title="Phạm vi chạy">
            <div className="n-form-row" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <Field id="bt-start" label="Từ ngày"><input id="bt-start" type="date" className="n-in" value={form.start} onChange={(e) => setForm({ start: e.target.value })} /></Field>
              <Field id="bt-end" label="Đến ngày"><input id="bt-end" type="date" className="n-in" value={form.end} onChange={(e) => setForm({ end: e.target.value })} /></Field>
              <Field id="bt-risk" label="Rủi ro mỗi lệnh (%)"><input id="bt-risk" type="number" step="0.1" min="0.01" max="5" className="n-in" value={form.risk} onChange={(e) => setForm({ risk: e.target.value })} /></Field>
              <Field id="bt-fill" label="Mức khớp cắt lỗ">
                <select id="bt-fill" className="n-sel" value={form.stopFill} onChange={(e) => setForm({ stopFill: e.target.value })}>
                  <option value="level">level</option>
                  <option value="extreme">extreme</option>
                </select>
              </Field>
            </div>
            {cat.windows && <p className="n-note" style={{ marginTop: 8 }}>Dữ liệu từ {cat.windows.start} đến {cat.windows.end}. Mặc định chạy vùng dev2 → hết dữ liệu ({cat.windows.dev2_end} → {cat.windows.end}).</p>}
          </Panel>
          <Panel title="Cặp giao dịch" meta={
            <>
              <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: universe })}>Tất cả</button>
              <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: [] })}>Bỏ chọn</button>
            </>
          }>
            <div className="n-chips" role="group" aria-label="Cặp giao dịch">
              {universe.map((s) => {
                const on = form.symbols.includes(s)
                return (
                  <label key={s} className={`n-chip ${on ? 'on' : ''}`}>
                    <input type="checkbox" checked={on} onChange={() => toggleSym(s)} />{s.replace('@perp', '')}
                  </label>
                )
              })}
              {!universe.length && <span className="n-note">Chưa có danh sách cặp.</span>}
            </div>
          </Panel>
        </div>
      </div>

      <div className="n-sticky-actions" style={{ marginBottom: 12 }}>
        <button type="button" className="n-btn primary" onClick={run} disabled={busy}>{busy ? <Spinner /> : null} Chạy backtest</button>
        <ErrorBox>{err}</ErrorBox>
      </div>

      {btId && (
        <Panel title="Tiến trình backtest" className="" meta={<span className="mono">{btId}</span>}>
          <JobPanel job={bt.job} status={bt.status} error={bt.error} />
          {bt.status === 'done' && (
            <div className="n-sticky-actions">
              <button type="button" className="n-btn primary" onClick={onNext}>Tiếp tục: Walk-forward →</button>
            </div>
          )}
        </Panel>
      )}

      {btId && bt.status === 'done' && (
        <div style={{ marginTop: 12 }}>
          <div className="n-page-h" style={{ marginBottom: 8 }}>
            <div className="n-ctrls">
              <Segmented label="Kỳ xem" value={period} onChange={setPeriod} options={PERIODS} />
            </div>
            <Link className="n-btn" to="/portfolio" onClick={() => { try { localStorage.setItem('nora-v2-portfolio', JSON.stringify({ source: 'backtest', jobId: btId, period })) } catch (e) { /* bỏ qua */ } }}>
              Mở trên Danh mục ↗
            </Link>
          </div>
          <DashboardLoader source="backtest" jobId={btId} period={period} />
        </div>
      )}
    </>
  )
}

/* ------------------------------ Bước 2: WFA ------------------------------ */
function StepWfa({ cat, form, wfaId, wfa, onLaunched, onNext }) {
  const [f, setF] = useState({ train: 120, test: 30, mode: 'fixed', n: 3, start: form.start, end: form.end })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const ids = Object.keys(form.sel)
  const set = (p) => setF((x) => ({ ...x, ...p }))

  // mở bằng link ?wfa=…: điền form WFA theo tham số của job đã chạy (không phải ngày của backtest); mỗi job chỉ áp một lần
  const syncedFor = useRef('')
  useEffect(() => {
    if (!wfaId || !wfa.job || syncedFor.current === wfaId) return
    syncedFor.current = wfaId
    const a = parseJobArgs(wfa.job.args)
    const r = wfa.job.result
    const train = a.train_days ?? r?.config?.train_days
    const test = a.test_days ?? r?.config?.test_days
    setF((x) => ({
      ...x,
      train: train ?? x.train, test: test ?? x.test,
      start: a.start || r?.window?.[0] || x.start, end: a.end || r?.window?.[1] || x.end,
      mode: a.fixed == null ? x.mode : a.fixed ? 'fixed' : 'reselect', n: a.n ?? x.n,
    }))
  }, [wfaId, wfa.job]) // eslint-disable-line react-hooks/exhaustive-deps

  async function run() {
    setErr(null)
    if (!ids.length) return setErr('Chưa có chiến lược: quay lại bước 1 để chọn.')
    if (f.start >= f.end) return setErr('Ngày bắt đầu phải trước ngày kết thúc.')
    const body = {
      start: f.start, end: f.end, train_days: Number(f.train), test_days: Number(f.test),
      symbols: form.symbols, risk_per_trade_pct: Number(form.risk),
    }
    if (f.mode === 'fixed') body.strategies = ids.map((id) => ({ id, configs: [form.sel[id]] }))
    else { body.candidates = ids; body.n = Number(f.n) }
    setBusy(true)
    try { const r = await postWfa(body); onLaunched(r.job_id) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const report = wfa.job?.result
  return (
    <>
      <Panel title="Cấu hình walk-forward">
        <div className="n-form-row">
          <Field id="wf-train" label="Số ngày train (IS)"><input id="wf-train" type="number" min="7" max="1000" className="n-in" value={f.train} onChange={(e) => set({ train: e.target.value })} /></Field>
          <Field id="wf-test" label="Số ngày test (OOS)"><input id="wf-test" type="number" min="1" max="365" className="n-in" value={f.test} onChange={(e) => set({ test: e.target.value })} /></Field>
          <Field id="wf-start" label="Từ ngày"><input id="wf-start" type="date" className="n-in" value={f.start} onChange={(e) => set({ start: e.target.value })} /></Field>
          <Field id="wf-end" label="Đến ngày"><input id="wf-end" type="date" className="n-in" value={f.end} onChange={(e) => set({ end: e.target.value })} /></Field>
        </div>
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 12 }}>
          <div className="n-field"><span className="n-lbl">Chế độ</span>
            <Segmented label="Chế độ WFA" value={f.mode} onChange={(mode) => set({ mode })} options={[{ value: 'fixed', label: 'Cố định tham số' }, { value: 'reselect', label: 'Chọn lại trên IS' }]} />
          </div>
          {f.mode === 'reselect' && (
            <div style={{ width: 150 }}><Field id="wf-n" label="Số cấu hình mỗi chiến lược"><input id="wf-n" type="number" min="1" max="50" className="n-in" value={f.n} onChange={(e) => set({ n: e.target.value })} /></Field></div>
          )}
          <div className="n-note" style={{ flex: 1, minWidth: 260 }}>
            {f.mode === 'fixed'
              ? 'Dùng đúng tham số đã chỉnh ở bước 1; WFA chỉ kiểm tra out-of-sample cuốn chiếu.'
              : 'Mỗi fold lấy mẫu n cấu hình, chọn cấu hình tốt nhất trên IS rồi chạy OOS.'}
            <div style={{ marginTop: 4 }}>Chiến lược: {ids.map((i) => <span key={i} className="n-badge" style={{ marginRight: 4 }}>{i}</span>)}</div>
          </div>
        </div>
        <div className="n-sticky-actions">
          <button type="button" className="n-btn primary" onClick={run} disabled={busy}>{busy ? <Spinner /> : null} Chạy walk-forward</button>
          <ErrorBox>{err}</ErrorBox>
        </div>
      </Panel>

      {wfaId && (
        <div style={{ marginTop: 12, display: 'grid', gap: 12 }}>
          <Panel title="Tiến trình WFA" meta={<span className="mono">{wfaId}</span>}>
            <JobPanel job={wfa.job} status={wfa.status} error={wfa.error} />
          </Panel>
          {wfa.status === 'done' && (report?.folds ? (
            <>
              <WfaResult report={report} />
              <div className="n-sticky-actions"><button type="button" className="n-btn primary" onClick={onNext}>Tiếp tục: Monte Carlo →</button></div>
            </>
          ) : <Empty title="Job xong nhưng chưa có báo cáo">Backend chưa trả <code>result</code> cho job này.</Empty>)}
        </div>
      )}
    </>
  )
}

/* --------------------------- Bước 3: Monte Carlo --------------------------- */
function StepMc({ wfaId }) {
  const [f, setF] = useState({ sims: 4000, block: 5, horizon: 365, seed: 7, basis: 'extreme', scale: 1, ruin: 30 })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [res, setRes] = useState(null)
  const set = (p) => setF((x) => ({ ...x, ...p }))
  async function run() {
    setErr(null); setBusy(true)
    try {
      setRes(await postMc({
        wfa_job_id: wfaId, basis: f.basis, simulations: Number(f.sims), block_days: Number(f.block), horizon_days: Number(f.horizon),
        ruin_threshold_pct: Number(f.ruin), seed: Number(f.seed), scale: Number(f.scale),
      }))
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <>
      <Panel title="Cấu hình Monte Carlo (bootstrap theo khối, mark-to-market ngày)">
        <div className="n-form-row">
          <Field id="mc-sims" label="Số mô phỏng (≤ 10000)"><input id="mc-sims" type="number" min="100" max="10000" className="n-in" value={f.sims} onChange={(e) => set({ sims: e.target.value })} /></Field>
          <Field id="mc-block" label="Độ dài khối (ngày)"><input id="mc-block" type="number" min="1" max="60" className="n-in" value={f.block} onChange={(e) => set({ block: e.target.value })} /></Field>
          <Field id="mc-hz" label="Chân trời (ngày ≤ 730)"><input id="mc-hz" type="number" min="5" max="730" className="n-in" value={f.horizon} onChange={(e) => set({ horizon: e.target.value })} /></Field>
          <Field id="mc-seed" label="Seed"><input id="mc-seed" type="number" className="n-in" value={f.seed} onChange={(e) => set({ seed: e.target.value })} /></Field>
          <Field id="mc-basis" label="Cơ sở lợi suất">
            <select id="mc-basis" className="n-sel" value={f.basis} onChange={(e) => set({ basis: e.target.value })}>
              <option value="extreme">extreme</option><option value="level">level</option>
            </select>
          </Field>
          <Field id="mc-scale" label="Hệ số quy mô"><input id="mc-scale" type="number" step="0.1" min="0.1" className="n-in" value={f.scale} onChange={(e) => set({ scale: e.target.value })} /></Field>
          <Field id="mc-ruin" label="Ngưỡng phá sản MDD (%)"><input id="mc-ruin" type="number" min="1" max="100" className="n-in" value={f.ruin} onChange={(e) => set({ ruin: e.target.value })} /></Field>
        </div>
        <div className="n-sticky-actions">
          <button type="button" className="n-btn primary" onClick={run} disabled={busy}>{busy ? <Spinner /> : null} Chạy Monte Carlo</button>
          <span className="mono muted">từ WFA {wfaId}</span>
          <ErrorBox>{err}</ErrorBox>
        </div>
      </Panel>
      {res && <div style={{ marginTop: 12 }}><McResult mc={res} ruinPct={Number(f.ruin)} /></div>}
    </>
  )
}

/* --------------------------------- Trang --------------------------------- */
export default function Backtest() {
  const { data: cat, loading, error } = useCatalog()
  const [sp, setSp] = useSearchParams()
  const location = useLocation()
  const btId = sp.get('job') || ''
  const wfaId = sp.get('wfa') || ''
  const stepQ = Number(sp.get('step')) || 1
  const bt = useJob(btId)
  const wfa = useJob(wfaId)
  const [form, setFormRaw] = useState(null)
  const seeded = useRef(false)

  const patch = (o, replace = false) => {
    const n = new URLSearchParams(sp)
    Object.entries(o).forEach(([k, v]) => (v == null || v === '' ? n.delete(k) : n.set(k, String(v))))
    setSp(n, { replace })
  }
  const setForm = (p) => setFormRaw((f) => ({ ...f, ...p }))

  // khởi tạo form từ danh mục + dữ liệu truyền từ trang Alpha
  useEffect(() => {
    if (!cat || form) return
    const pre = readPrefill(location, sp)
    const w = cat.windows || {}
    let sel = pre?.strategies ? selFromStrategies(pre.strategies, cat.catalog) : selFromStrategies(cat.book?.strategies, cat.catalog)
    if (pre) seeded.current = true
    setFormRaw({
      sel, symbols: pre?.symbols || cat.universe || [], start: pre?.start || w.dev2_end || '', end: pre?.end || w.end || '',
      risk: pre?.risk_per_trade_pct ?? cat.book?.risk_per_trade_pct ?? 0.5, stopFill: pre?.stop_fill || 'level',
    })
  }, [cat]) // eslint-disable-line react-hooks/exhaustive-deps

  // vào bằng link ?job=… (không có prefill): đồng bộ form theo tham số job đã chạy
  useEffect(() => {
    if (!form || !cat || seeded.current || !bt.job) return
    seeded.current = true
    const a = parseJobArgs(bt.job.args)
    setFormRaw((f) => ({
      ...f,
      sel: a.strategies ? selFromStrategies(a.strategies, cat.catalog) : f.sel,
      symbols: a.symbols || f.symbols, start: a.start || f.start, end: a.end || f.end,
      risk: a.risk_per_trade_pct ?? f.risk, stopFill: a.stop_fill || f.stopFill,
    }))
  }, [bt.job, form, cat])

  const btDone = bt.status === 'done'
  const wfaDone = wfa.status === 'done'
  const step = stepQ >= 3 && wfaDone ? 3 : stepQ >= 2 && btDone ? 2 : 1

  const steps = useMemo(() => [
    { n: 1, title: 'Backtest', st: bt.status ? (JOB_STATUS[bt.status]?.text || 'Đang tải') : 'Chưa chạy', locked: false, done: btDone },
    { n: 2, title: 'Walk-forward (WFA)', st: !btDone ? 'Mở khoá sau backtest' : wfa.status ? (JOB_STATUS[wfa.status]?.text || 'Đang tải') : 'Chưa chạy', locked: !btDone, done: wfaDone },
    { n: 3, title: 'Monte Carlo', st: !wfaDone ? 'Mở khoá sau WFA' : 'Sẵn sàng', locked: !wfaDone, done: false },
  ], [bt.status, wfa.status, btDone, wfaDone])

  return (
    <>
      <PageHead kicker="Một vòng kiểm chứng" title="Backtest · WFA · Monte Carlo"
        subtitle="Chạy backtest danh mục, kiểm tra out-of-sample bằng walk-forward, rồi mô phỏng Monte Carlo để đo rủi ro phá sản. Mỗi bước mở khoá sau khi bước trước chạy xong." />
      <div className="n-stepper" role="tablist" aria-label="Các bước">
        {steps.map((s) => (
          <button key={s.n} type="button" role="tab" aria-selected={step === s.n} disabled={s.locked}
            className={`n-step ${step === s.n ? 'on' : ''} ${s.done && step !== s.n ? 'done' : ''}`}
            onClick={() => patch({ step: s.n })}>
            <span className="no">{s.done ? '✓' : s.n}</span>
            <span><span className="tt">{s.title}</span><span className="st">{s.locked ? <LockIcon /> : null}{s.st}</span></span>
          </button>
        ))}
      </div>

      {error && <ErrorBox>Không tải được danh mục chiến lược: {error}</ErrorBox>}
      {loading && !cat && <Empty title="Đang tải danh mục chiến lược"><Spinner /></Empty>}
      {cat && form && step === 1 && (
        <StepBacktest cat={cat} form={form} setForm={setForm} btId={btId} bt={bt}
          onLaunched={(id) => patch({ job: id, wfa: null, step: 1 })} onNext={() => patch({ step: 2 })} />
      )}
      {cat && form && step === 2 && (
        <StepWfa key={btId} cat={cat} form={form} wfaId={wfaId} wfa={wfa}
          onLaunched={(id) => patch({ wfa: id, step: 2 })} onNext={() => patch({ step: 3 })} />
      )}
      {step === 3 && <StepMc key={wfaId} wfaId={wfaId} />}
    </>
  )
}
