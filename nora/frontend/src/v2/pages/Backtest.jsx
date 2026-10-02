import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Segmented, Field, ErrorBox, Empty, Spinner, Loading, ErrorState } from '../components/ui'
import Term from '../components/Term'
import { DateInput, DatePresets } from '../components/DateField'
import StrategyRunPicker, { StrategyCard, ModeSwitch, ModeStamp, PublishBlocked, ParamField, LockIcon, useStrategies, useServerValidation } from '../components/RunModes'
import JobPanel from '../components/JobPanel'
import DashboardLoader, { PERIODS } from '../components/Dashboard'
import WfaResult from '../components/WfaResult'
import McResult from '../components/McResult'
import useJob from '../hooks/useJob'
import { useCatalog } from '../context/Catalog'
import { postBacktest, postWfa, postMc } from '../api'
import { parseJobArgs, JOB_STATUS } from '../lib/jobs'
import { daysInclusive } from '../lib/dates'
import { fullDate } from '../lib/format'
import { STOP_FILL, stopFillOptions } from '../lib/stopfill'
import { paramLabel } from '../lib/params'
import {
  MC_STD, STRESS, STRESS_ALL, WFA_STD, WFA_SCHEMA_KEYS_SUPPORTED, WFA_PENDING_NOTE, mcIsCustom, presetParams,
  validateStrategy, coerceParams, splitServerErrors, flatServerErrors, CUSTOM_BADGE,
} from '../lib/modes'

function readPrefill(location, sp) {
  const st = location.state?.prefill
  if (st) return st
  const q = sp.get('prefill')
  if (q) { try { return JSON.parse(q) } catch (e) { return null } }
  return null
}

/** { [id]: params đầy đủ } từ danh sách [{id, params?}]: preset làm nền, params ghi đè (khoá không có trong lược đồ bị bỏ). */
function selFromList(list, strategies) {
  const out = {}
  ;(list || []).forEach((s) => {
    const st = strategies[s.id]
    if (!st) return
    const over = {}
    Object.entries(s.params || {}).forEach(([k, v]) => { if (k in st.params_schema) over[k] = v })
    out[s.id] = { ...presetParams(st), ...over }
  })
  return out
}

const isNumStr = (v) => v !== '' && v != null && Number.isFinite(Number(v))
const RISK_MIN = 0.05
const RISK_MAX = 5
const riskOk = (v) => isNumStr(v) && Number(v) >= RISK_MIN && Number(v) <= RISK_MAX

/** Mức rủi ro khoá ở chế độ Cơ bản: nhỏ nhất trong các preset đã chọn (như backend). */
function basicRisk(sel, byId) {
  const r = Object.keys(sel).map((id) => byId[id]?.preset?.params?.risk_per_trade_pct).filter((v) => v != null)
  return r.length ? Math.min(...r) : 0.5
}

/** Lỗi theo (id -> khoá) gộp: máy chủ validate < phía client < lỗi 422 của lần chạy gần nhất. */
function mergeErrors(ids, clientErr, serverVal, runErr) {
  const out = {}
  ids.forEach((id) => { out[id] = { ...(serverVal[id] || {}), ...(clientErr[id] || {}), ...(runErr?.[id] || {}) } })
  return out
}

/** Dòng chỉ đọc có ổ khoá (tham số bị khoá ở chế độ Cơ bản). */
function Locked({ label, children, id, note }) {
  return (
    <div className="n-field n-locked">
      <span className="n-lbl" id={id}><LockIcon /> {label}</span>
      <div className="n-locked-v mono" aria-labelledby={id}>{children}</div>
      {note && <span className="n-pf-note">{note}</span>}
    </div>
  )
}

/* ---------------------------- Bước 1: Backtest ---------------------------- */
function StepBacktest({ cat, strats, form, setForm, btId, bt, onLaunched, onNext }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [runErr, setRunErr] = useState(null) // { per, general } từ 422 của lần chạy gần nhất
  const [period, setPeriod] = useState('ALL')
  const universe = cat.universe || []
  const mode = form.mode
  const adv = mode === 'advanced'
  const ids = Object.keys(form.sel)
  const nSel = ids.length
  const risk = adv ? form.risk : basicRisk(form.sel, strats.byId)
  const fill = adv ? form.stopFill : 'level'

  const paramsFor = (id) => ({ ...form.sel[id], risk_per_trade_pct: form.risk })
  const clientErr = useMemo(() => {
    const o = {}
    ids.forEach((id) => { if (strats.byId[id]) o[id] = validateStrategy(strats.byId[id].params_schema, paramsFor(id)) })
    return o
  }, [form.sel, form.risk, strats.byId]) // eslint-disable-line react-hooks/exhaustive-deps
  const serverVal = useServerValidation(strats.byId, Object.fromEntries(ids.map((id) => [id, paramsFor(id)])), adv)
  const errors = mergeErrors(ids, clientErr, serverVal, runErr?.per)
  const nErrStrats = ids.filter((id) => Object.keys(errors[id]).length).length
  useEffect(() => { setRunErr(null) }, [form.sel, form.risk, form.mode])

  const nSym = form.symbols.length
  const days = daysInclusive(form.start, form.end)
  const reason = !nSel ? 'Chọn ít nhất một chiến lược ở bảng bên trên'
    : !nSym ? 'Chọn ít nhất một cặp giao dịch'
      : !form.start || !form.end ? 'Nhập ngày bắt đầu và kết thúc hợp lệ (dd/mm/yyyy)'
        : form.start >= form.end ? 'Ngày bắt đầu phải trước ngày kết thúc'
          : adv && !riskOk(form.risk) ? `Rủi ro mỗi lệnh phải từ ${RISK_MIN}% đến ${RISK_MAX}%`
            : adv && nErrStrats ? `Còn lỗi tham số ở ${nErrStrats} chiến lược (xem các ô báo đỏ)` : null

  async function run() {
    setErr(null); setRunErr(null)
    if (reason) return setErr(reason)
    setBusy(true)
    try {
      const body = { mode, symbols: form.symbols, start: form.start, end: form.end }
      if (adv) {
        body.strategies = ids.map((id) => ({ id, params: coerceParams(strats.byId[id].params_schema, paramsFor(id)) }))
        body.risk_per_trade_pct = Number(form.risk)
        body.stop_fill = form.stopFill
      } else body.strategies = ids.map((id) => ({ id }))
      const r = await postBacktest(body)
      onLaunched(r.job_id)
    } catch (e) {
      const sp = splitServerErrors(e.fields, ids)
      if (e.fields?.length) { setRunErr(sp); setErr(sp.general.length ? sp.general.join('; ') : 'Máy chủ từ chối một số tham số: xem các ô báo đỏ.') } else setErr(e.message)
    } finally { setBusy(false) }
  }

  const toggleSym = (s) => setForm({ symbols: form.symbols.includes(s) ? form.symbols.filter((x) => x !== s) : [...form.symbols, s] })
  const useBook = () => setForm({ sel: selFromList(cat.book?.strategies, strats.byId) })

  return (
    <>
      <ModeSwitch mode={mode} onChange={(m) => setForm({ mode: m })} />
      <div className="n-grid g-main-side">
        <Panel title="Chiến lược" meta={
          <>
            <button type="button" className="n-btn sm" onClick={useBook} disabled={!cat.book?.strategies?.length}>Dùng sổ hiện tại</button>
            <button type="button" className="n-btn sm" onClick={() => setForm({ sel: {} })} disabled={!nSel}>Bỏ chọn</button>
            <span className="mono">{nSel} đã chọn</span>
          </>
        }>
          <StrategyRunPicker strategies={strats.list} mode={mode} sel={form.sel} setSel={(sel) => setForm({ sel })} errors={errors}
            riskShared={adv ? { value: form.risk, onChange: (v) => setForm({ risk: v }) } : null} />
        </Panel>
        <div style={{ display: 'grid', gap: 12, alignContent: 'start' }}>
          <Panel title="Phạm vi chạy">
            <div className="n-form-row" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <Field id="bt-start" label="Từ ngày"><DateInput id="bt-start" label="Từ ngày" value={form.start} onChange={(v) => setForm({ start: v })} /></Field>
              <Field id="bt-end" label="Đến ngày"><DateInput id="bt-end" label="Đến ngày" value={form.end} onChange={(v) => setForm({ end: v })} /></Field>
              {adv ? (
                <>
                  <Field id="bt-risk" label="Rủi ro mỗi lệnh (%)">
                    <input id="bt-risk" type="number" step="0.05" min={RISK_MIN} max={RISK_MAX} className="n-in" value={form.risk} aria-invalid={!riskOk(form.risk) || undefined} onChange={(e) => setForm({ risk: e.target.value })} />
                    {!riskOk(form.risk) && <span className="n-field-err" role="alert">Phải nằm trong khoảng {RISK_MIN} đến {RISK_MAX}% vốn</span>}
                  </Field>
                  <div style={{ gridColumn: '1 / -1' }}>
                    <Field id="bt-fill" label={<Term k="fill">Khớp cắt lỗ</Term>}>
                      <select id="bt-fill" className="n-sel" value={form.stopFill} onChange={(e) => setForm({ stopFill: e.target.value })}>
                        {stopFillOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </Field>
                  </div>
                </>
              ) : (
                <>
                  <Locked label="Rủi ro mỗi lệnh" id="lk-risk" note="mức nhỏ nhất của các preset đã chọn">{String(+Number(risk).toFixed(2))}% vốn</Locked>
                  <Locked label="Khớp cắt lỗ" id="lk-fill">{STOP_FILL.level.text}</Locked>
                </>
              )}
            </div>
            <DatePresets windows={cat.windows} start={form.start} end={form.end} onPick={(start, end) => setForm({ start, end })} />
            {cat.windows && <p className="n-note" style={{ marginTop: 8 }}>Dữ liệu từ {fullDate(cat.windows.start)} đến {fullDate(cat.windows.end)}. Mặc định chạy từ hết <Term k="dev2">dev2</Term> đến hết dữ liệu, tức vùng <Term k="holdout">Holdout</Term> ({fullDate(cat.windows.dev2_end)} → {fullDate(cat.windows.end)}).</p>}
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

      <div className="n-runbar" role="region" aria-label="Chạy backtest">
        <div className="sum">
          <span className={`n-mode-badge ${mode}`}>{adv ? 'Nâng cao' : 'Cơ bản'}</span>{' '}
          {nSel} chiến lược · {nSym} tài sản · {days != null && days > 0 ? `${days} ngày` : '— ngày'} · rủi ro {isNumStr(risk) ? String(+Number(risk).toFixed(2)) : '—'}%/lệnh · Khớp cắt lỗ: {STOP_FILL[fill]?.text || fill}
          {reason && <div className="why" role="status">Chưa chạy được: {reason}.</div>}
        </div>
        <ErrorBox>{err && err !== reason ? err : null}</ErrorBox>
        <button type="button" className="n-btn primary" onClick={run} disabled={busy || !!reason} aria-describedby={reason ? 'bt-why' : undefined} title={reason || 'Chạy backtest với cấu hình này'}>
          {busy ? <Spinner /> : null} Chạy backtest
        </button>
        {reason && <span id="bt-why" className="sr-only">{reason}</span>}
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
function StepWfa({ cat, strats, form, setForm, wfaId, wfa, onLaunched, onNext }) {
  const mode = form.mode
  const adv = mode === 'advanced'
  const [f, setF] = useState({ train: WFA_STD.train_days, test: WFA_STD.test_days, kind: 'fixed', n: 3, start: form.start, end: form.end, step: '', sims: '', mcSeed: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [runErr, setRunErr] = useState(null)
  const ids = Object.keys(form.sel)
  const set = (p) => setF((x) => ({ ...x, ...p }))
  const spaceOf = (id) => Object.keys(cat.catalog.find((c) => c.id === id)?.space || {})

  // tham số WFA: chỉ khoá thuộc `space` lấy từ bước 1; phần còn lại là preset (backend chưa cho đổi) — hiện khoá và ghi chú
  const [wp, setWp] = useState({})
  const wfaParams = (id) => {
    const st = strats.byId[id]
    const base = presetParams(st)
    if (WFA_SCHEMA_KEYS_SUPPORTED) return { ...base, ...(form.sel[id] || {}), ...(wp[id] || {}) }
    const out = { ...base }
    spaceOf(id).forEach((k) => { out[k] = (wp[id] && k in wp[id]) ? wp[id][k] : (form.sel[id]?.[k] ?? base[k]) })
    out.risk_per_trade_pct = form.risk
    return out
  }
  const clientErr = useMemo(() => {
    const o = {}
    ids.forEach((id) => { if (strats.byId[id]) o[id] = validateStrategy(strats.byId[id].params_schema, wfaParams(id)) })
    return o
  }, [form.sel, form.risk, wp, strats.byId]) // eslint-disable-line react-hooks/exhaustive-deps
  const errors = mergeErrors(ids, clientErr, {}, runErr?.per)
  useEffect(() => { setRunErr(null) }, [wp, f.kind, mode])

  // mở bằng link ?wfa=…: điền form WFA theo tham số của job đã chạy (không phải ngày của backtest); mỗi job chỉ áp một lần
  const syncedFor = useRef('')
  useEffect(() => {
    if (!wfaId || !wfa.job || syncedFor.current === wfaId) return
    syncedFor.current = wfaId
    const a = parseJobArgs(wfa.job.args)
    const r = wfa.job.result
    const rs = wfa.job.resolved
    const train = rs?.train_days ?? a.train_days ?? r?.config?.train_days
    const test = rs?.test_days ?? a.test_days ?? r?.config?.test_days
    setF((x) => ({
      ...x,
      train: train ?? x.train, test: test ?? x.test,
      start: a.start || r?.window?.[0] || x.start, end: a.end || r?.window?.[1] || x.end,
      kind: a.fixed == null ? x.kind : a.fixed ? 'fixed' : 'reselect', n: a.n ?? x.n,
    }))
  }, [wfaId, wfa.job]) // eslint-disable-line react-hooks/exhaustive-deps

  const trainBad = adv && !(Number.isInteger(Number(f.train)) && Number(f.train) >= 7 && Number(f.train) <= 1000)
  const testBad = adv && !(Number.isInteger(Number(f.test)) && Number(f.test) >= 1 && Number(f.test) <= 365)
  const nErr = ids.filter((id) => Object.keys(errors[id]).length).length
  const reason = !ids.length ? 'Chưa có chiến lược: quay lại bước 1 để chọn'
    : !f.start || !f.end ? 'Nhập ngày bắt đầu và kết thúc hợp lệ (dd/mm/yyyy)'
      : f.start >= f.end ? 'Ngày bắt đầu phải trước ngày kết thúc'
        : trainBad ? 'Số ngày train phải là số nguyên từ 7 đến 1000' : testBad ? 'Số ngày test phải là số nguyên từ 1 đến 365'
          : adv && f.kind === 'fixed' && nErr ? `Còn lỗi tham số ở ${nErr} chiến lược` : null

  async function run() {
    setErr(null); setRunErr(null)
    if (reason) return setErr(`${reason}.`)
    const body = { mode, start: f.start, end: f.end, symbols: form.symbols }
    if (adv) {
      Object.assign(body, { train_days: Number(f.train), test_days: Number(f.test), risk_per_trade_pct: Number(form.risk) })
      if (WFA_SCHEMA_KEYS_SUPPORTED) {
        if (f.step !== '') body.step_days = Number(f.step)
        if (f.sims !== '') body.sims = Number(f.sims)
        if (f.mcSeed !== '') body.mc_seed = Number(f.mcSeed)
      }
      if (f.kind === 'fixed') {
        body.strategies = ids.map((id) => {
          const full = coerceParams(strats.byId[id].params_schema, wfaParams(id))
          const keys = WFA_SCHEMA_KEYS_SUPPORTED ? Object.keys(full) : spaceOf(id)
          return { id, configs: [Object.fromEntries(keys.map((k) => [k, full[k]]))] }
        })
      } else { body.candidates = ids; body.n = Number(f.n) }
    } else body.candidates = ids // Cơ bản: preset cố định, fold 120/30, cổng chuẩn
    setBusy(true)
    try { const r = await postWfa(body); onLaunched(r.job_id) } catch (e) {
      const sp = splitServerErrors(e.fields, ids)
      const flat = flatServerErrors(e.fields)
      if (e.fields?.length) {
        setRunErr(sp)
        setErr([...sp.general, ...Object.entries(flat.byName).map(([k, m]) => `${k}: ${m}`)].join('; ') || 'Máy chủ từ chối một số tham số: xem các ô báo đỏ.')
      } else setErr(e.message)
    } finally { setBusy(false) }
  }

  const report = wfa.job?.result
  const pend = !WFA_SCHEMA_KEYS_SUPPORTED
  return (
    <>
      <ModeSwitch mode={mode} onChange={(m) => setForm({ mode: m })} />
      <Panel title={<>Cấu hình <Term k="wfa">walk-forward</Term></>}>
        <div className="n-form-row">
          {adv ? (
            <>
              <Field id="wf-train" label={<>Số ngày train (<Term k="is">IS</Term>)</>}><input id="wf-train" type="number" min="7" max="1000" className="n-in" value={f.train} aria-invalid={trainBad || undefined} onChange={(e) => set({ train: e.target.value })} />
                {trainBad && <span className="n-field-err" role="alert">Số nguyên từ 7 đến 1000</span>}</Field>
              <Field id="wf-test" label={<>Số ngày test (<Term k="oos">OOS</Term>)</>}><input id="wf-test" type="number" min="1" max="365" className="n-in" value={f.test} aria-invalid={testBad || undefined} onChange={(e) => set({ test: e.target.value })} />
                {testBad && <span className="n-field-err" role="alert">Số nguyên từ 1 đến 365</span>}</Field>
            </>
          ) : (
            <>
              <Locked label={<>Số ngày train (<Term k="is">IS</Term>)</>} id="lk-train">{WFA_STD.train_days}</Locked>
              <Locked label={<>Số ngày test (<Term k="oos">OOS</Term>)</>} id="lk-test">{WFA_STD.test_days}</Locked>
            </>
          )}
          <Field id="wf-start" label="Từ ngày"><DateInput id="wf-start" label="Từ ngày" value={f.start} onChange={(v) => set({ start: v })} /></Field>
          <Field id="wf-end" label="Đến ngày"><DateInput id="wf-end" label="Đến ngày" value={f.end} onChange={(v) => set({ end: v })} /></Field>
        </div>
        <DatePresets windows={cat.windows} start={f.start} end={f.end} onPick={(start, end) => set({ start, end })} />
        {adv && (
          <div className="n-form-row" style={{ marginTop: 12 }}>
            <ParamField idBase="wf" k="step_days" spec={{ type: 'int', min: 1, max: 365, unit: 'ngày' }} value={f.step} onChange={(v) => set({ step: v })} disabled={pend} note={pend ? WFA_PENDING_NOTE : null} />
            <ParamField idBase="wf" k="sims" spec={{ type: 'int', min: 100, max: 50000, unit: 'kịch bản' }} value={f.sims} onChange={(v) => set({ sims: v })} disabled={pend} note={pend ? WFA_PENDING_NOTE : null} />
            <ParamField idBase="wf" k="mc_seed" spec={{ type: 'int', min: 0, max: 2147483647 }} value={f.mcSeed} onChange={(v) => set({ mcSeed: v })} disabled={pend} note={pend ? WFA_PENDING_NOTE : null} />
          </div>
        )}
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 12 }}>
          {adv ? (
            <div className="n-field"><span className="n-lbl">Cách chọn tham số</span>
              <Segmented label="Cách chọn tham số WFA" value={f.kind} onChange={(kind) => set({ kind })} options={[{ value: 'fixed', label: 'Cố định tham số' }, { value: 'reselect', label: 'Chọn lại trên IS' }]} />
            </div>
          ) : (
            <div className="n-field"><span className="n-lbl"><LockIcon /> Cách chọn tham số</span><div className="n-locked-v">Preset cố định (WFA chỉ kiểm tra OOS cuốn chiếu)</div></div>
          )}
          {adv && f.kind === 'reselect' && (
            <div style={{ width: 150 }}><Field id="wf-n" label="Số cấu hình mỗi chiến lược"><input id="wf-n" type="number" min="1" max="50" className="n-in" value={f.n} onChange={(e) => set({ n: e.target.value })} /></Field></div>
          )}
          <div className="n-note" style={{ flex: 1, minWidth: 260 }}>
            {!adv
              ? <>Cơ bản: mỗi chiến lược chạy đúng một cấu hình là <Term k="preset">preset</Term>; fold 120/30 ngày và cổng chuẩn.</>
              : f.kind === 'fixed'
                ? <>Dùng đúng tham số đã chỉnh; WFA chỉ kiểm tra <Term k="oos">out-of-sample</Term> cuốn chiếu.</>
                : <>Mỗi <Term k="fold">fold</Term> lấy mẫu n cấu hình, chọn cấu hình tốt nhất trên IS rồi chạy OOS.</>}
            <div style={{ marginTop: 4 }}>Chiến lược: {ids.map((i) => <span key={i} className="n-badge" style={{ marginRight: 4 }}>{i}</span>)}</div>
          </div>
        </div>

        {adv && f.kind === 'fixed' && pend && (
          <div className="n-banner" style={{ marginTop: 12, marginBottom: 0 }} role="note">
            <span>WFA hiện chỉ nhận các khoá thuộc <b>không gian tối ưu</b> (ngưỡng, thoát lệnh). Chu kỳ chỉ báo, khung thời gian, rủi ro cùng bước trượt / số kịch bản / seed đang bị khoá — {WFA_PENDING_NOTE}. Muốn thử chúng hãy dùng Backtest.</span>
          </div>
        )}
        {adv && f.kind === 'fixed' && (
          <div style={{ marginTop: 12 }}>
            {ids.map((id) => strats.byId[id] && (
              <StrategyCard key={id} strat={strats.byId[id]} mode="advanced" params={wfaParams(id)} errors={errors[id] || {}}
                editableKeys={WFA_SCHEMA_KEYS_SUPPORTED ? null : spaceOf(id)}
                locked={pend ? { risk_per_trade_pct: `lấy từ bước 1 (${form.risk}%)` } : {}}
                onChange={(p) => setWp((x) => ({ ...x, [id]: p }))}
                onReset={() => setWp((x) => { const n = { ...x }; delete n[id]; return n })} />
            ))}
          </div>
        )}
        <div className="n-sticky-actions">
          <button type="button" className="n-btn primary" onClick={run} disabled={busy || !!reason} title={reason || undefined}>{busy ? <Spinner /> : null} Chạy walk-forward</button>
          <ErrorBox>{err}</ErrorBox>
        </div>
      </Panel>

      {wfaId && (
        <div style={{ marginTop: 12, display: 'grid', gap: 12 }}>
          <Panel title="Tiến trình WFA" meta={<span className="mono">{wfaId}</span>}>
            <JobPanel job={wfa.job} status={wfa.status} error={wfa.error} />
            {wfa.status === 'done' && <PublishBlocked customGates={wfa.job?.custom_gates} promotable={wfa.job?.promotable} />}
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
const MC_FIELDS = [
  { k: 'simulations', spec: { type: 'int', min: 100, max: 50000, step: 1000 }, std: MC_STD.simulations, cust: true },
  { k: 'block_days', spec: { type: 'int', min: 1, max: 30 }, std: MC_STD.block_days },
  { k: 'horizon_days', spec: { type: 'int', min: 5, max: 730 }, std: MC_STD.horizon_days },
  { k: 'seed', spec: { type: 'int', min: 0, max: 2147483647 }, std: MC_STD.seed },
  { k: 'scale', spec: { type: 'float', min: 0.1, max: 10, step: 0.1 }, std: MC_STD.scale },
  { k: 'ruin_threshold_pct', spec: { type: 'float', min: 1, max: 100 }, std: MC_STD.ruin_threshold_pct, cust: true },
  { k: 'stress_max_mdd_pct', spec: { type: 'float', min: 1, max: 100 }, std: MC_STD.stress_max_mdd_pct, cust: true },
]

function mcCheck(spec, v) {
  if (v === '' || v == null || !Number.isFinite(Number(v))) return 'Nhập một số'
  const n = Number(v)
  if (spec.type === 'int' && !Number.isInteger(n)) return 'Phải là số nguyên'
  if (n < spec.min || n > spec.max) return `Phải nằm trong khoảng ${spec.min} đến ${spec.max}`
  return null
}

function StepMc({ wfaId, wfa, form, setForm }) {
  const mode = form.mode
  const adv = mode === 'advanced'
  const [f, setF] = useState({ ...MC_STD, extra_cost_daily_pct: '', stress: STRESS_ALL, basis: 'extreme' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [srvErr, setSrvErr] = useState({})
  const [res, setRes] = useState(null)
  const set = (p) => { setSrvErr({}); setF((x) => ({ ...x, ...p })) }
  const fe = {}
  if (adv) {
    MC_FIELDS.forEach((m) => { const e = mcCheck(m.spec, f[m.k]); if (e) fe[m.k] = e })
    if (f.extra_cost_daily_pct !== '') { const e = mcCheck({ type: 'float', min: 0, max: 5 }, f.extra_cost_daily_pct); if (e) fe.extra_cost_daily_pct = e }
    if (!f.stress.length) fe.stress_scenarios = 'Chọn ít nhất một kịch bản cực xấu'
  }
  const errs = { ...srvErr, ...fe }
  const hasErr = Object.keys(fe).length > 0
  const custom = adv && !hasErr && mcIsCustom(f)

  async function run() {
    setErr(null); setSrvErr({})
    if (hasErr) return setErr('Còn ô nhập không hợp lệ: xem các ô báo đỏ.')
    setBusy(true)
    try {
      const body = { wfa_job_id: wfaId, basis: f.basis, mode }
      if (adv) {
        Object.assign(body, {
          simulations: Number(f.simulations), block_days: Number(f.block_days), horizon_days: Number(f.horizon_days), ruin_threshold_pct: Number(f.ruin_threshold_pct),
          seed: Number(f.seed), scale: Number(f.scale), stress_max_mdd_pct: Number(f.stress_max_mdd_pct), stress_scenarios: f.stress,
        })
        if (f.extra_cost_daily_pct !== '') body.extra_cost_daily_pct = Number(f.extra_cost_daily_pct)
      }
      setRes(await postMc(body))
    } catch (e) {
      const flat = flatServerErrors(e.fields)
      if (e.fields?.length) { setSrvErr(flat.byName); setErr(flat.rest.join('; ') || 'Máy chủ từ chối một số tham số: xem các ô báo đỏ.') } else setErr(e.message)
    } finally { setBusy(false) }
  }
  const toggleStress = (n) => set({ stress: f.stress.includes(n) ? f.stress.filter((x) => x !== n) : STRESS_ALL.filter((x) => x === n || f.stress.includes(x)) })
  return (
    <>
      <ModeSwitch mode={mode} onChange={(m) => setForm({ mode: m })} />
      <Panel title={<>Cấu hình <Term k="mc">Monte Carlo</Term> (<Term k="bootstrap">bootstrap theo khối</Term>, mark-to-market ngày)</>}>
        <div className="n-form-row">
          {adv ? MC_FIELDS.map((m) => (
            <ParamField key={m.k} idBase="mc" k={m.k} spec={m.spec} value={f[m.k]} onChange={(v) => set({ [m.k]: v })} error={errs[m.k]} />
          )) : MC_FIELDS.map((m) => (
            <Locked key={m.k} label={paramLabel(m.k)} id={`lk-${m.k}`}>{Number(m.std).toLocaleString('vi-VN')}</Locked>
          ))}
          {adv && <ParamField idBase="mc" k="extra_cost_daily_pct" spec={{ type: 'float', min: 0, max: 5, unit: '%/ngày' }} value={f.extra_cost_daily_pct} onChange={(v) => set({ extra_cost_daily_pct: v })} error={errs.extra_cost_daily_pct} />}
          <div style={{ gridColumn: 'span 2' }}><Field id="mc-basis" label={<Term k="fill">Khớp cắt lỗ (cơ sở lợi suất)</Term>}>
            <select id="mc-basis" className="n-sel" value={f.basis} onChange={(e) => set({ basis: e.target.value })}>
              <option value="extreme">{STOP_FILL.extreme.text}</option><option value="level">{STOP_FILL.level.text}</option>
            </select>
          </Field></div>
        </div>
        <fieldset className="n-pgroup" style={{ marginTop: 12 }}>
          <legend><Term k="stress">Kịch bản cực xấu</Term>{!adv ? <> · <LockIcon /> đủ 6 kịch bản</> : null}</legend>
          <div className="n-chips" role="group" aria-label="Kịch bản cực xấu">
            {STRESS.map((s) => {
              const on = !adv || f.stress.includes(s.name)
              return (
                <label key={s.name} className={`n-chip ${on ? 'on' : ''}`} style={!adv ? { opacity: 0.8, cursor: 'default' } : undefined}>
                  <input type="checkbox" checked={on} disabled={!adv} onChange={() => toggleStress(s.name)} />{s.label}
                </label>
              )
            })}
          </div>
          {errs.stress_scenarios && <span className="n-field-err" role="alert">{errs.stress_scenarios}</span>}
        </fieldset>
        {!adv && <p className="n-note" style={{ marginTop: 8 }}>Cơ bản: {MC_STD.simulations.toLocaleString('vi-VN')} mô phỏng, cổng chuẩn (P(MDD ≥ 30%) ≤ 5%, mọi kịch bản cực xấu MDD &lt; 50%); chỉ nguồn WFA được lấy từ bước 2.</p>}
        {custom && (
          <div className="n-banner" role="alert" style={{ borderLeftColor: 'var(--n-warn)', marginTop: 12, marginBottom: 0 }}>
            <span className="n-custom-badge">⚠ {CUSTOM_BADGE}</span>
            <span>Cổng khác chuẩn (dưới 10.000 mô phỏng, ngưỡng phá sản ≠ 30%, MDD cực xấu ≠ 50% hoặc thiếu kịch bản): kết quả chỉ để thử nghiệm.</span>
          </div>
        )}
        <div className="n-sticky-actions">
          <button type="button" className="n-btn primary" onClick={run} disabled={busy || hasErr} title={hasErr ? 'Sửa các ô báo đỏ' : undefined}>{busy ? <Spinner /> : null} Chạy Monte Carlo</button>
          <span className="mono muted">từ WFA {wfaId}</span>
          <ErrorBox>{err}</ErrorBox>
        </div>
      </Panel>
      {res && (
        <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
          <ModeStamp mode={res.params?.mode || mode} customGates={res.params?.custom_gates ?? res.gate?.custom_gates} promotable={res.params?.promotable} ignored={res.params?.ignored_client_params} />
          <PublishBlocked customGates={res.params?.custom_gates ?? res.gate?.custom_gates} promotable={res.params?.promotable} />
          <McResult mc={res} ruinPct={Number(res.params?.ruin_threshold_pct ?? f.ruin_threshold_pct)} />
        </div>
      )}
    </>
  )
}

/* --------------------------------- Trang --------------------------------- */
export default function Backtest() {
  const { data: cat, loading, error, reload } = useCatalog()
  const strats = useStrategies()
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

  // khởi tạo form từ danh mục + preset + dữ liệu truyền từ trang Alpha (có tham số riêng -> chế độ Nâng cao)
  useEffect(() => {
    if (!cat || !strats.list.length || form) return
    const pre = readPrefill(location, sp)
    const w = cat.windows || {}
    const sel = selFromList(pre?.strategies || cat.book?.strategies, strats.byId)
    if (pre) seeded.current = true
    const customPre = !!pre?.strategies?.some((s) => s.params && Object.keys(s.params).length)
    setFormRaw({
      mode: pre?.mode || (customPre ? 'advanced' : 'basic'), sel,
      symbols: pre?.symbols || cat.universe || [], start: pre?.start || w.dev2_end || '', end: pre?.end || w.end || '',
      risk: pre?.risk_per_trade_pct ?? cat.book?.risk_per_trade_pct ?? 0.5, stopFill: pre?.stop_fill || 'level',
    })
  }, [cat, strats.list]) // eslint-disable-line react-hooks/exhaustive-deps

  // vào bằng link ?job=… (không có prefill): đồng bộ form theo `resolved` (đầy đủ) hoặc args của job đã chạy
  useEffect(() => {
    if (!form || !cat || seeded.current || !bt.job) return
    seeded.current = true
    const a = parseJobArgs(bt.job.args)
    const rs = bt.job.resolved
    const list = rs?.strategies || a.strategies
    setFormRaw((f) => ({
      ...f,
      mode: bt.job.mode || f.mode,
      sel: list ? selFromList(list.map((s) => ({ id: s.id, params: s.params })), strats.byId) : f.sel,
      symbols: (rs?.symbols || a.symbols || f.symbols).map((s) => (cat.universe?.includes(s) || String(s).includes('@') ? s : `${s}@perp`)),
      start: rs?.start || a.start || f.start, end: rs?.end || a.end || f.end,
      risk: rs?.risk_per_trade_pct ?? a.risk_per_trade_pct ?? f.risk, stopFill: rs?.stop_fill || a.stop_fill || f.stopFill,
    }))
  }, [bt.job, form, cat]) // eslint-disable-line react-hooks/exhaustive-deps

  const btDone = bt.status === 'done'
  const wfaDone = wfa.status === 'done'
  const step = stepQ >= 3 && wfaDone ? 3 : stepQ >= 2 && (btDone || !!wfaId) ? 2 : 1  // link ?wfa=…&step=2 mở thẳng bước 2

  const steps = useMemo(() => [
    { n: 1, title: 'Backtest', st: bt.status ? (JOB_STATUS[bt.status]?.text || 'Đang tải') : 'Chưa chạy', locked: false, done: btDone },
    { n: 2, title: 'Walk-forward (WFA)', st: !btDone && !wfaId ? 'Mở khoá sau backtest' : wfa.status ? (JOB_STATUS[wfa.status]?.text || 'Đang tải') : 'Chưa chạy', locked: !btDone && !wfaId, done: wfaDone },
    { n: 3, title: 'Monte Carlo', st: !wfaDone ? 'Mở khoá sau WFA' : 'Sẵn sàng', locked: !wfaDone, done: false },
  ], [bt.status, wfa.status, btDone, wfaDone, wfaId])

  const ready = cat && form && strats.list.length > 0
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

      {error && <ErrorState title="Không tải được danh mục chiến lược" error={error} onRetry={reload} />}
      {strats.error && <ErrorState title="Không tải được lược đồ tham số và preset" error={strats.error} onRetry={strats.reload} />}
      {(loading || strats.loading) && !ready && !error && !strats.error && <Loading what="danh mục chiến lược" />}
      {ready && step === 1 && (
        <StepBacktest cat={cat} strats={strats} form={form} setForm={setForm} btId={btId} bt={bt}
          onLaunched={(id) => patch({ job: id, wfa: null, step: 1 })} onNext={() => patch({ step: 2 })} />
      )}
      {ready && step === 2 && (
        <StepWfa key={btId} cat={cat} strats={strats} form={form} setForm={setForm} wfaId={wfaId} wfa={wfa}
          onLaunched={(id) => patch({ wfa: id, step: 2 })} onNext={() => patch({ step: 3 })} />
      )}
      {ready && step === 3 && <StepMc key={wfaId} wfaId={wfaId} wfa={wfa} form={form} setForm={setForm} />}
    </>
  )
}
