import React, { useEffect, useMemo, useRef, useState } from 'react'
import '../styles/optimize.css'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Segmented, Field, ErrorBox, Empty, Spinner, Loading, ErrorState } from '../components/ui'
import Term from '../components/ui/Term'
import { DateInput, DatePresets } from '../components/ui/DateField'
import { StrategyCard, PresetNote, ModeSwitch, ModeStamp, PublishBlocked, ParamField, LockIcon, useStrategies, useStrategyCatalog, useServerValidation } from '../components/optimize/RunModes'
import StrategyChoice from '../components/optimize/backtest/StrategyChoice'
import PresetSummary from '../components/optimize/backtest/PresetSummary'
import JobPanel from '../components/jobs/JobPanel'
import DashboardLoader, { PERIODS } from '../components/portfolio/Dashboard'
import WfaResult from '../components/optimize/WfaResult'
import McResult from '../components/optimize/McResult'
import useJob from '../hooks/useJob'
import { useCatalog, useMeta } from '../meta/MetaProvider'
import { postBacktest, postWfa, postMc, getAlphaCatalog, postCancel } from '../api'
import { addBacktestNotification } from '../lib/notifications'
import AlphaTablePicker from '../components/backtest/AlphaTablePicker'
import ScanAlphaGrid from '../components/backtest/ScanAlphaGrid'
import WfaAlphaTable from '../components/backtest/WfaAlphaTable'
import MonteCarloAlphaTable from '../components/backtest/MonteCarloAlphaTable'
import ProvenanceBadge from '../components/common/ProvenanceBadge'
import WarningsPanel from '../components/common/WarningsPanel'
import ExecModeSelect from '../components/common/ExecModeSelect'
import BacktestEvaluationChart from '../components/charts/BacktestEvaluationChart'
import WfaEvaluationChart from '../components/charts/WfaEvaluationChart'
import MonteCarloEvaluationChart from '../components/charts/MonteCarloEvaluationChart'
import { framesOf, defaultFrame, defaultExecMode, execRunFrame } from '../lib/metaDefaults'
import { parseJobParams, JOB_STATUS } from '../lib/jobs'
import { daysInclusive } from '../lib/dates'
import { isDexSym, dexSym, dexAssets, tickChip, dexRange, msStamp } from '../lib/dex'
import { fullDate, fmtNum, fmtPct, fmtFrame } from '../lib/format'
import { STOP_FILL, stopFillOptions } from '../lib/stopfill'
import { paramLabel } from '../lib/params'
import { SIDE_TEXT, legLabel, legsFor, picksFromLegs, strategyName } from '../lib/strategyLabel'
import {
  WFA_SCHEMA_KEYS_SUPPORTED, WFA_PENDING_NOTE, mcIsCustom, presetParams,
  validateStrategy, coerceParams, splitServerErrors, flatServerErrors, CUSTOM_BADGE, timeframeMismatch,
  getWfaStd, getMcStd, getStressScenarios, bookMcSpec,
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

/** Chỉ giữ các khoá thuộc lược đồ của chân lệnh (hai chân của một chiến lược có thể lệch vài khoá, vd Sideway: rsi_lo / rsi_hi). */
const pickSchema = (leg, p) => Object.fromEntries(Object.entries(p).filter(([k]) => k in leg.params_schema))

/** Bộ tham số dùng chung của các chân lệnh đã chọn (chân đầu = Long thắng khi trùng khoá). */
const sharedParams = (legIds, sel) => Object.assign({}, ...[...legIds].reverse().map((id) => sel[id]))

/** Thẻ gộp của một chiến lược theo chiều đã chọn: lược đồ = hợp các chân, preset = preset chân Long (Short-only: chân Short). */
function mergedStrat(entry, side, legIds, byId) {
  const legs = legIds.map((id) => byId[id]).filter(Boolean)
  if (!legs.length) return null
  const rev = [...legs].reverse()
  return {
    ...legs[0], id: entry.id, name: entry.name, side,
    params_schema: Object.assign({}, ...rev.map((l) => l.params_schema)),
    preset: { ...legs[0].preset, params: Object.assign({}, ...rev.map((l) => l.preset?.params || {})) },
  }
}

/** sel mới khi đặt chiều cho một chiến lược: giữ tham số đã chỉnh của chân còn lại, chân mới lấy preset + phần dùng chung. */
function applySide(sel, entry, side, byId) {
  const all = Object.values(entry.legs || {})
  const have = all.filter((id) => sel[id])
  const next = { ...sel }
  all.forEach((id) => delete next[id])
  const shared = sharedParams(have, sel)
  legsFor(entry, side).filter((id) => byId[id]).forEach((id) => {
    next[id] = have.includes(id) ? sel[id] : pickSchema(byId[id], { ...presetParams(byId[id]), ...shared })
  })
  return next
}
const dropStrategy = (sel, entry) => Object.fromEntries(Object.entries(sel).filter(([id]) => !Object.values(entry.legs || {}).includes(id)))

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
const symName = (s) => String(s).replace('@perp', '')
const defaultSymbols = (universe) => { const s = universe.find((x) => symName(x) === 'BTC') || universe[0]; return s ? [s] : [] }

/** Preset chỉ đọc của một chiến lược: nguồn + bằng chứng, rồi từng tham số kèm mô tả. */
function PresetBlock({ strat }) {
  return (
    <div>
      <PresetNote preset={strat.preset} />
      <PresetSummary strat={strat} />
    </div>
  )
}

const VN_INT = new Intl.NumberFormat('vi-VN')

/** Kết quả backtest tick: huy hiệu "Tick" + cửa sổ thực chạy + ghi chú mô hình chi phí (config.tick_window / cost_model, tick_stats). */
function TickResultNote({ result }) {
  const cfg = result?.config
  if (cfg?.data !== 'tick') return null
  const w = cfg.tick_window || {}
  const cm = cfg.cost_model || {}
  const st = result.tick_stats || {}
  const pools = Object.entries(cm.pools || {})
  return (
    <div className="n-bt-tick" role="note">
      <div>
        <span className="n-badge">Tick</span>{' '}
        <span className="mono">{msStamp(w.start)} → {msStamp(w.end)} (UTC)</span>
        {w.ticks != null && <> · {VN_INT.format(w.ticks)} swap</>}
        {cfg.latency_ms != null && <> · trễ {VN_INT.format(cfg.latency_ms)} ms</>}
        {w.requested_start != null && (w.requested_start !== w.start || w.requested_end !== w.end) && <span className="n-pf-note"> (đã cắt theo độ phủ tick)</span>}
      </div>
      <details className="n-details">
        <summary>Mô hình chi phí: swap thật trên AMM</summary>
        <div style={{ display: 'grid', gap: 4, marginTop: 6 }}>
          {cm.fills && <span>{cm.fills}</span>}
          {cm.impact && <span>Trượt giá: {cm.impact}.</span>}
          {pools.map(([sym, pl]) => (
            <span key={sym}>
              <b className="mono">{String(sym).replace(/^dex:/, '')}</b>
              {pl.network ? ` · ${pl.network}` : ''}{pl.pool_type ? ` · pool ${pl.stable ? 'stable' : pl.pool_type}` : ''}
              {pl.fee_rate != null ? ` · phí pool ${fmtPct(pl.fee_rate * 100, 4)}` : ''}
              {pl.gas_usd != null ? ` · gas ${pl.gas_usd} USD/swap` : ''}
            </span>
          ))}
          {st.taker_fills != null && (
            <span>{VN_INT.format(st.taker_fills)} lệnh khớp{st.avg_fill_slippage_bps != null ? `, trượt giá trung bình ${st.avg_fill_slippage_bps} bps` : ''}
              {st.signal_bars != null ? ` · ${VN_INT.format(st.signal_bars)} nến tín hiệu` : ''}
              {st.signal_bars_skipped ? `, bỏ ${VN_INT.format(st.signal_bars_skipped)} nến không có swap` : ''}.
            </span>
          )}
        </div>
      </details>
    </div>
  )
}

// AlphaTablePicker & ScanAlphaGrid are imported from ../components/backtest/

function StepBacktest({ cat, strats, sc, form, setForm, btId, bt, onLaunched, onNext, viewAlphaId }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [runErr, setRunErr] = useState(null) // { per, general } từ 422 của lần chạy gần nhất
  const [period, setPeriod] = useState('ALL')
  const [stratMode, setStratMode] = useState('catalog')
  const [selectedAlphaId, setSelectedAlphaId] = useState('')
  const notifiedRef = useRef(new Set())

  // Tự động chuyển về chế độ "1. Chọn Alpha" nếu có yêu cầu xem kết quả từ thông báo
  useEffect(() => {
    if (viewAlphaId) {
      setStratMode('catalog')
    }
  }, [viewAlphaId])
  const { meta } = useMeta()
  const dataUniverse = meta?.universe?.data?.assets || cat.universe || []
  const bookUniverse = meta?.universe?.book || []
  const rawUniverse = useBookUniverse && bookUniverse.length ? bookUniverse : dataUniverse
  const TOP_ORDER = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'TRX', 'DOT', 'NEAR', 'SUI', 'APT', 'LTC']
  const universe = useMemo(() => {
    return [...rawUniverse].sort((a, b) => {
      const nameA = symName(a).toUpperCase()
      const nameB = symName(b).toUpperCase()
      const idxA = TOP_ORDER.indexOf(nameA)
      const idxB = TOP_ORDER.indexOf(nameB)
      if (idxA !== -1 && idxB !== -1) return idxA - idxB
      if (idxA !== -1) return -1
      if (idxB !== -1) return 1
      return nameA.localeCompare(nameB)
    })
  }, [rawUniverse])
  const dexList = useMemo(() => dexAssets(cat.assets), [cat.assets])
  const dexByKey = useMemo(() => Object.fromEntries(dexList.map((a) => [a.key, a])), [dexList])
  const selDex = form.symbols.find(isDexSym)
  const isDex = !!selDex
  const asset = isDex ? dexByKey[selDex] : null
  const dataMode = isDex && form.data === 'tick' && asset?.ticks ? 'tick' : 'candle'
  const tickOn = dataMode === 'tick'
  const range = isDex ? dexRange(asset, tickOn) : null   // khoảng ngày cho phép của tài sản DEX (tick: độ phủ tick)
  const mode = form.mode
  const adv = mode === 'advanced'
  const multi = !!form.multi
  const ids = Object.keys(form.sel)
  const nSel = ids.length
  // mỗi chiến lược đã chọn (kèm chiều) = một nhóm chân lệnh dùng chung một bộ tham số
  const picks = picksFromLegs(ids, sc.list)
  const groups = sc.list.filter((c) => picks[c.id]).map((c) => {
    const legIds = legsFor(c, picks[c.id]).filter((id) => form.sel[id])
    return { entry: c, side: picks[c.id], legIds, strat: mergedStrat(c, picks[c.id], legIds, strats.byId) }
  }).filter((g) => g.strat)
  const nStrat = groups.length
  const risk = adv ? form.risk : basicRisk(form.sel, strats.byId)
  const fill = adv ? form.stopFill : 'level'
  const tfMismatch = adv ? [] : timeframeMismatch(ids, strats.byId, form.timeframe || defaultFrame(meta))

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

  // Tự động thông báo khi backtest hoàn thành
  useEffect(() => {
    if (bt.status === 'done' && bt.job && btId && !notifiedRef.current.has(btId)) {
      notifiedRef.current.add(btId)
      const res = bt.job.result || {}
      const sum = res.summary || res.out_of_sample || res.in_sample || {}
      const stratName = groups[0]?.entry?.name || 'Chiến lược Backtest'
      addBacktestNotification({
        job_id: btId,
        alpha_id: selectedAlphaId || groups[0]?.entry?.id || stratName,
        title: stratName,
        symbol: form.symbols?.[0] || 'BTC@perp',
        time: Date.now(),
        ret_pct: sum.ret_pct,
        mdd_pct: sum.mdd_pct,
        win_rate: sum.win_rate,
        trades: sum.trades,
        status: 'done',
      })
    }
  }, [bt.status, bt.job, btId, groups, selectedAlphaId, form.symbols])

  const nSym = form.symbols.length
  const days = daysInclusive(form.start, form.end)
  const latBad = tickOn && String(form.latency ?? '').trim() !== '' && !(Number.isInteger(Number(form.latency)) && Number(form.latency) >= 0 && Number(form.latency) <= 3600000)
  const gasBad = tickOn && String(form.gas ?? '').trim() !== '' && !(isNumStr(form.gas) && Number(form.gas) >= 0 && Number(form.gas) <= 1000)
  const reason = !nSel ? (multi ? 'Chọn ít nhất một chiến lược ở danh sách bên trên' : 'Chọn một chiến lược ở danh sách bên trên')
    : !nSym ? (multi ? 'Chọn ít nhất một cặp giao dịch' : 'Chọn cặp giao dịch')
      : !form.start || !form.end ? 'Nhập ngày bắt đầu và kết thúc hợp lệ (dd/mm/yyyy)'
        : form.start >= form.end ? 'Ngày bắt đầu phải trước ngày kết thúc'
          : isDex && !asset ? 'Tài sản DEX không còn trong kho dữ liệu'
            : latBad ? 'Độ trễ phải là số nguyên ms từ 0 đến 3.600.000'
              : gasBad ? 'Gas phải từ 0 đến 1000 USD mỗi swap'
          : adv && !riskOk(form.risk) ? `Rủi ro mỗi lệnh phải từ ${RISK_MIN}% đến ${RISK_MAX}%`
            : adv && nErrStrats ? `Còn lỗi tham số ở ${nErrStrats} chiến lược (xem các ô báo đỏ)` : null

  async function run() {
    setErr(null); setRunErr(null)
    if (reason) return setErr(reason)
    setBusy(true)
    try {
      const body = { mode, symbols: form.symbols, start: form.start, end: form.end, timeframe: form.timeframe || defaultFrame(meta), data: dataMode }
      const runFrame = execRunFrame(form.exec_mode || defaultExecMode(meta))
      if (runFrame) body.run_frame = runFrame // Chuẩn: khớp trên nến 1m (cùng quy ước với Studio)
      if (tickOn) {
        if (String(form.latency ?? '').trim() !== '') body.latency_ms = Number(form.latency)
        if (String(form.gas ?? '').trim() !== '') body.gas_usd = Number(form.gas)
      }
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

  // một chiến lược: bấm thẻ là thay luôn bằng preset của nó (mặc định Cả hai chiều); danh mục: bật/tắt từng thẻ
  const defSide = isDex ? 'LONG' : 'BOTH'   // DEX là spot: chỉ chân Long
  const pickStrategy = (c) => {
    if (!multi) {
      const sel = applySide({}, c, defSide, strats.byId)
      return setForm({ sel, risk: basicRisk(sel, strats.byId) })
    }
    setForm({ sel: picks[c.id] ? dropStrategy(form.sel, c) : applySide(form.sel, c, defSide, strats.byId) })
  }
  const pickSide = (c, side) => {
    const sel = applySide(form.sel, c, side, strats.byId)
    setForm(multi ? { sel } : { sel, risk: basicRisk(sel, strats.byId) })
  }
  // tham số dùng chung của một chiến lược: ghi cho mọi chân đã chọn (mỗi chân chỉ nhận khoá thuộc lược đồ của nó)
  const setStratParams = (g, p) => setForm({ sel: { ...form.sel, ...Object.fromEntries(g.legIds.map((id) => [id, pickSchema(strats.byId[id], p)])) } })
  const resetStrat = (g) => {
    setStratParams(g, presetParams(g.strat))
    if (g.strat.preset?.params?.risk_per_trade_pct != null) setForm({ risk: g.strat.preset.params.risk_per_trade_pct })
  }
  const setMulti = (on) => {
    if (on) return setForm({ multi: true })
    const g = groups[0]
    setForm({ multi: false, sel: g ? Object.fromEntries(g.legIds.map((id) => [id, form.sel[id]])) : {}, symbols: form.symbols.length > 1 ? defaultSymbols(universe.filter((s) => form.symbols.includes(s))) : form.symbols })
  }
  const perpDates = () => form.perpRange || { start: cat.windows?.dev2_end || '', end: cat.windows?.end || '' }
  // chọn perp (xoá DEX nếu đang chọn, trả ngày về khoảng perp); chọn DEX (xoá perp, ép Long, ngày theo dữ liệu của tài sản)
  const setPerp = (symbols) => {
    if (!isDex) return setForm({ symbols })
    const d = perpDates()
    setForm({ symbols, data: 'candle', start: d.start, end: d.end, perpRange: null })
  }
  const toggleSym = (s) => setPerp(isDex ? [s] : form.symbols.includes(s) ? form.symbols.filter((x) => x !== s) : [...form.symbols, s])
  const chooseDex = (key) => {
    const a = dexByKey[key]
    const tick = form.data === 'tick' && !!a?.ticks
    const r = dexRange(a, tick)
    let sel = form.sel
    groups.forEach((g) => { if (g.side !== 'LONG') sel = applySide(sel, g.entry, 'LONG', strats.byId) })
    setForm({ symbols: [key], sel, data: tick ? 'tick' : 'candle', perpRange: isDex ? form.perpRange : { start: form.start, end: form.end }, ...(r ? { start: r.start, end: r.end } : {}) })
  }
  const pickSymbol = (v) => (isDexSym(v) ? chooseDex(v) : setPerp([v]))
  const setDataMode = (m) => {
    const tick = m === 'tick'
    const r = dexRange(asset, tick)
    setForm({ data: m, ...(r ? { start: r.start, end: r.end } : {}) })
  }
  const bookOk = (cat.book?.strategies || []).some((x) => strats.byId[x.id]) // sổ cũ dùng id cũ: không nạp được vào lựa chọn mới
  const applyBook = () => { const sel = selFromList(cat.book?.strategies, strats.byId); setForm({ multi: Object.keys(picksFromLegs(Object.keys(sel), sc.list)).length > 1, sel }) }
  const symOpts = form.symbols[0] && !isDex && !universe.includes(form.symbols[0]) ? [form.symbols[0], ...universe] : universe

  const handlePickAlpha = (alpha) => {
    setSelectedAlphaId(alpha.id)
    const stratEntry = sc.list.find((c) => c.id === alpha.stratId || Object.values(c.legs || {}).includes(alpha.stratId)) || sc.list[0]
    if (stratEntry) {
      const defSide = alpha.side === 'SHORT' ? 'SHORT' : alpha.side === 'BOTH' ? 'BOTH' : 'LONG'
      let sel = applySide({}, stratEntry, defSide, strats.byId)
      if (alpha.params && Object.keys(alpha.params).length > 0) {
        Object.keys(sel).forEach((legId) => {
          sel[legId] = { ...sel[legId], ...alpha.params }
        })
      }
      setForm({
        sel,
        symbols: alpha.symbol ? [alpha.symbol] : form.symbols,
        timeframe: alpha.timeframe || form.timeframe,
        risk: basicRisk(sel, strats.byId),
      })
    }
  }

  const handleRunNow = (alpha) => {
    handlePickAlpha(alpha)
    setTimeout(() => {
      run()
    }, 150)
  }

  const handleStopRun = async () => {
    if (btId) {
      try {
        await postCancel(btId)
      } catch (e) { /* ignore */ }
    }
    setBusy(false)
  }

  const handleScanLaunch = (scanPayload) => {
    const stratEntry = sc.list.find((c) => c.id === scanPayload.strategyId || Object.values(c.legs || {}).includes(scanPayload.strategyId)) || sc.list[0]
    if (stratEntry) {
      const defSide = isDex ? 'LONG' : (stratEntry.side || 'BOTH')
      let sel = applySide({}, stratEntry, defSide, strats.byId)
      if (scanPayload.paramsGrid) {
        const startParams = {}
        Object.entries(scanPayload.paramsGrid).forEach(([k, v]) => {
          if (v && v.start != null) startParams[k] = v.start
        })
        const legIds = Object.values(stratEntry.legs || {})
        legIds.forEach((id) => {
          if (strats.byId[id]) {
            sel[id] = { ...sel[id], ...pickSchema(strats.byId[id], startParams) }
          }
        })
      }
      setForm({
        name: scanPayload.campaignName || form.name,
        sel,
        symbols: scanPayload.symbols || form.symbols,
        timeframe: scanPayload.timeframe || form.timeframe,
        capital: scanPayload.capital || form.capital,
        risk: scanPayload.paramsGrid?.risk_per_trade_pct?.start != null ? scanPayload.paramsGrid.risk_per_trade_pct.start : basicRisk(sel, strats.byId),
      })
      setTimeout(() => {
        run()
      }, 150)
    }
  }

  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <Segmented
          label="Chế độ chọn chiến lược"
          value={stratMode}
          onChange={(m) => setStratMode(m)}
          options={[
            { value: 'catalog', label: '1. Chọn Alpha' },
            { value: 'scan_gen', label: '2. Scan Alpha' },
          ]}
        />
      </div>

      <Panel
        title={stratMode === 'catalog' ? 'Kho Alpha (Toàn bộ danh sách)' : 'Quét tham số Scan Alpha (Grid Optimization)'}
        meta={multi ? (
          <>
            <button type="button" className="n-btn sm" onClick={applyBook} disabled={!bookOk} title={bookOk ? undefined : 'Sổ hiện tại dùng chiến lược cũ, không nạp được'}>Dùng sổ hiện tại</button>
            <button type="button" className="n-btn sm" onClick={() => { setForm({ sel: {} }); setSelectedAlphaId('') }} disabled={!nSel}>Bỏ chọn</button>
            <span className="mono">{nStrat} đã chọn</span>
          </>
        ) : (
          nSel > 0 ? (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <button
                type="button"
                className={`n-btn sm ${adv ? 'primary' : ''}`}
                onClick={() => setForm({ mode: adv ? 'basic' : 'advanced' })}
                title="Bật/tắt tùy chỉnh nâng cao tham số"
              >
                {adv ? 'Đang chỉnh nâng cao' : 'Tùy chỉnh nâng cao'}
              </button>
              <button type="button" className="n-btn sm" onClick={() => { setForm({ sel: {} }); setSelectedAlphaId('') }}>
                Bỏ chọn ({nStrat})
              </button>
            </div>
          ) : null
        )}
      >
        {stratMode === 'catalog' ? (
          <AlphaTablePicker
            onSelect={handlePickAlpha}
            selectedId={selectedAlphaId}
            onRunNow={handleRunNow}
            onStopRun={handleStopRun}
            isRunning={busy || bt.status === 'running' || bt.status === 'queued'}
            runningAlphaId={selectedAlphaId}
            progress={bt.job?.progress}
            jobStatus={bt.status}
            viewAlphaId={viewAlphaId}
            activeJobId={btId}
          />
        ) : (
          <ScanAlphaGrid
            onLaunchScan={handleScanLaunch}
            isScanning={busy}
          />
        )}
      </Panel>


      {stratMode === 'catalog' && nSel > 0 && adv && (
        <div className="n-grid g-main-side" style={{ marginTop: 12 }}>
          <Panel title={multi ? 'Tham số các chiến lược' : <>Tham số của <span className="mono">{groups[0]?.entry.name} · {SIDE_TEXT[groups[0]?.side]}</span></>}>
            <label className={`n-bt-adv ${adv ? 'on' : ''}`}>
              <input type="checkbox" checked={adv} onChange={(e) => setForm({ mode: e.target.checked ? 'advanced' : 'basic' })} />
              <span>
                <b>Điều chỉnh nâng cao</b>
                <span className="n-note">
                  {adv
                    ? <><Term k="mode_advanced">Nâng cao</Term>: tự sửa từng tham số, rủi ro và cách khớp cắt lỗ.</>
                    : <>Đang dùng bộ tham số tốt nhất (<Term k="preset">preset</Term>) bên dưới, đã khoá. Bật để tự chỉnh.</>}
                </span>
              </span>
            </label>

            {!adv && (
              <div style={{ marginTop: 10, display: 'grid', gap: 10 }}>
                {multi ? groups.map((g) => (
                  <details key={g.entry.id} className="n-details">
                    <summary><b className="mono">{g.entry.name}</b> <span className={`n-badge ${g.side.toLowerCase()}`}>{SIDE_TEXT[g.side]}</span></summary>
                    <PresetBlock strat={g.strat} />
                  </details>
                )) : groups[0] && <PresetBlock strat={groups[0].strat} />}
                {groups.some((g) => g.side === 'BOTH') && <p className="n-note">Cả hai chiều dùng chung một bộ tham số; khoá chỉ có ở một chiều (vd. ngưỡng RSI mua / bán) áp cho đúng chiều đó.</p>}
              </div>
            )}

            {adv && (
              <div className="n-bt-advbox">
                <div className="n-form-row">
                  <Field id="bt-fill" label={<Term k="fill">Khớp cắt lỗ</Term>}>
                    <select id="bt-fill" className="n-sel" value={form.stopFill} onChange={(e) => setForm({ stopFill: e.target.value })}>
                      {stopFillOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </Field>
                </div>
                {groups.map((g) => (
                  <StrategyCard key={g.entry.id} strat={g.strat} name={g.entry.name} sideText={SIDE_TEXT[g.side]} mode="advanced"
                    params={sharedParams(g.legIds, form.sel)} errors={Object.assign({}, ...g.legIds.map((id) => errors[id] || {}))}
                    onChange={(p) => setStratParams(g, p)} onReset={() => resetStrat(g)}
                    riskShared={{ value: form.risk, onChange: (v) => setForm({ risk: v }) }} />
                ))}
              </div>
            )}

            {(adv || multi) && (
              <label className={`n-bt-adv ${multi ? 'on' : ''}`}>
                <input type="checkbox" checked={multi} onChange={(e) => setMulti(e.target.checked)} />
                <span>
                  <b>Chạy danh mục nhiều chiến lược và nhiều tài sản</b>
                  <span className="n-note">Mặc định chỉ một chiến lược trên một cặp. Bật để chọn thêm chiến lược ở danh sách trên và nhiều cặp ở ô bên cạnh.</span>
                </span>
              </label>
            )}
          </Panel>

          <Panel title="Phạm vi chạy">
            <div className="n-form-row" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <Field id="bt-start" label="Từ ngày"><DateInput id="bt-start" label="Từ ngày" value={form.start} min={range?.start} max={range?.end} onChange={(v) => setForm({ start: v })} /></Field>
              <Field id="bt-end" label="Đến ngày"><DateInput id="bt-end" label="Đến ngày" value={form.end} min={range?.start} max={range?.end} onChange={(v) => setForm({ end: v })} /></Field>
              <div style={{ gridColumn: '1 / -1' }}>
                <Field id="bt-tf" label="Khung chạy (nến mô phỏng, dùng cho cả Backtest và WFA)">
                  <select id="bt-tf" className="n-sel" value={form.timeframe || defaultFrame(meta)} onChange={(e) => setForm({ timeframe: e.target.value })}>
                    {framesOf(meta).map((f) => (
                      <option key={f} value={f}>{fmtFrame(f)}</option>
                    ))}
                  </select>
                  {tfMismatch.length > 0 && (
                    <span className="n-pf-note" role="status">
                      Preset tối ưu ở khung khác: {tfMismatch.map((x) => `${legLabel(x.id)} (${x.timeframe})`).join(', ')} — kết quả có thể kém hơn bằng chứng.
                    </span>
                  )}
                </Field>
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                <ExecModeSelect id="bt-exec" value={form.exec_mode} onChange={(v) => setForm({ exec_mode: v })} />
              </div>
              <div style={{ gridColumn: '1 / -1' }}>
                {multi ? (
                  <div className="n-field">
                    <span className="n-lbl" id="bt-sym-l">Cặp giao dịch ({nSym} đã chọn)</span>
                    <div className="n-chips" role="group" aria-labelledby="bt-sym-l">
                      <span className="n-pf-note" style={{ width: '100%' }}>Perp OKX (nến)</span>
                      {universe.map((s) => {
                        const on = form.symbols.includes(s)
                        return (
                          <label key={s} className={`n-chip-lbl ${on ? 'on' : ''}`}>
                            <input type="checkbox" checked={on} onChange={() => toggleSym(s)} />{symName(s)}
                          </label>
                        )
                      })}
                      {dexList.length > 0 && <span className="n-pf-note" style={{ width: '100%', marginTop: 4 }}>DEX (on-chain): spot, chỉ Long, chọn một tài sản</span>}
                      {dexList.map((a) => {
                        const on = selDex === a.key
                        return (
                          <label key={a.key} className={`n-chip-lbl ${on ? 'on' : ''}`} title={`${a.name}${a.network ? ` · ${a.network}` : ''} · ${tickChip(a)}`}>
                            <input type="radio" name="bt-dex" checked={on} onChange={() => chooseDex(a.key)} />{a.name}
                            <span className="n-badge">{tickChip(a)}</span>{a.network && <span className="n-badge">{a.network}</span>}
                          </label>
                        )
                      })}
                    </div>
                    <div className="n-bt-actions">
                      <button type="button" className={`n-btn sm ${useBookUniverse ? 'primary' : ''}`}
                        onClick={() => {
                          const next = !useBookUniverse
                          setUseBookUniverse(next)
                          const nextUni = next && bookUniverse.length ? bookUniverse : dataUniverse
                          setPerp(nextUni)
                        }}>
                        {useBookUniverse ? 'Đang theo sổ' : 'Theo sổ'}
                      </button>
                      <button type="button" className="n-btn sm" onClick={() => setPerp(universe.slice(0, 10))}>Chọn Top 10</button>
                      <button type="button" className="n-btn sm" onClick={() => setPerp(universe.slice(0, 20))}>Chọn Top 20</button>
                      <button type="button" className="n-btn sm" onClick={() => setPerp(universe)}>Tất cả perp</button>
                      <button type="button" className="n-btn sm" onClick={() => setPerp([])}>Bỏ chọn</button>
                    </div>
                  </div>
                ) : (
                  <Field id="bt-sym" label="Cặp giao dịch">
                    <select id="bt-sym" className="n-sel" value={form.symbols[0] ?? ''} onChange={(e) => pickSymbol(e.target.value)}>
                      {dexList.length > 0 ? (
                        <>
                          <optgroup label="Perp OKX (nến)">{symOpts.map((s) => <option key={s} value={s}>{symName(s)}</option>)}</optgroup>
                          <optgroup label="DEX (on-chain)">
                            {dexList.map((a) => <option key={a.key} value={a.key}>{a.name} · {tickChip(a)}{a.network ? ` · ${a.network}` : ''}</option>)}
                          </optgroup>
                        </>
                      ) : symOpts.map((s) => <option key={s} value={s}>{symName(s)}</option>)}
                    </select>
                  </Field>
                )}
                {isDex && (
                  <div style={{ marginTop: 6, display: 'grid', gap: 4 }}>
                    <div className="n-dex-chips">
                      <span className="n-badge">DEX · spot</span>
                      {asset?.network && <span className="n-badge">{asset.network}</span>}
                      <span className="n-badge">{tickChip(asset)}</span>
                      {asset?.fee_rate != null && <span className="n-badge">phí pool {fmtPct(asset.fee_rate * 100, 4)}</span>}
                    </div>
                    <span className="n-pf-note">DEX là spot, chỉ mua (Long) và chạy riêng từng tài sản: không trộn với perp OKX. Chọn perp sẽ bỏ tài sản DEX này.</span>
                  </div>
                )}
              </div>
              {isDex && (
                <div style={{ gridColumn: '1 / -1' }}>
                  <div className="n-field">
                    <span className="n-lbl" id="bt-data-l">Dữ liệu</span>
                    <Segmented label="Dữ liệu" value={dataMode} onChange={setDataMode} options={[
                      { value: 'candle', label: 'Nến' },
                      { value: 'tick', label: 'Tick (từng swap)', disabled: !asset?.ticks, title: asset?.ticks ? undefined : 'Tài sản này chưa có dữ liệu tick' },
                    ]} />
                    {!asset?.ticks && <span className="n-pf-note">Chưa có tick cho {asset?.name || 'tài sản này'}: chỉ chạy được bằng nến.</span>}
                  </div>
                  {tickOn && (
                    <div className="n-bt-tick">
                      <span>Cửa sổ tick: <b className="mono">{msStamp(asset.ticks.start_ts)} → {msStamp(asset.ticks.end_ts)}</b> (UTC), {VN_INT.format(asset.ticks.rows)} swap. Ngày chạy bị giới hạn trong cửa sổ này; mỗi swap là một bước khớp lệnh với chi phí AMM đúng theo dự trữ pool.</span>
                      <details className="n-details">
                        <summary>Tuỳ chọn nâng cao (để trống = mặc định theo mạng)</summary>
                        <div className="n-form-row" style={{ gridTemplateColumns: '1fr 1fr', marginTop: 6 }}>
                          <Field id="bt-lat" label="Độ trễ (ms)">
                            <input id="bt-lat" className="n-in" inputMode="numeric" placeholder="một block của mạng" value={form.latency ?? ''} aria-invalid={latBad || undefined}
                              onChange={(e) => setForm({ latency: e.target.value })} />
                          </Field>
                          <Field id="bt-gas" label="Gas (USD/swap)">
                            <input id="bt-gas" className="n-in" inputMode="decimal" placeholder="theo mạng" value={form.gas ?? ''} aria-invalid={gasBad || undefined}
                              onChange={(e) => setForm({ gas: e.target.value })} />
                          </Field>
                        </div>
                      </details>
                    </div>
                  )}
                </div>
              )}
            </div>
            {!adv && (
              <p className="n-bt-line"><LockIcon /> Rủi ro {isNumStr(risk) ? fmtNum(Number(risk), 2) : '—'}% vốn mỗi lệnh (mức nhỏ nhất của các preset) · Khớp cắt lỗ: {STOP_FILL.level.text}. Cố định ở chế độ cơ bản.</p>
            )}
            {!isDex && <DatePresets windows={cat.windows} start={form.start} end={form.end} onPick={(start, end) => setForm({ start, end })} />}
            {isDex && range && <p className="n-note" style={{ marginTop: 8 }}>Dữ liệu {tickOn ? 'tick' : 'nến'} của {asset.name} từ {fullDate(range.start)} đến {fullDate(range.end)} (UTC).</p>}
            {!isDex && cat.windows && <p className="n-note" style={{ marginTop: 8 }}>Dữ liệu từ {fullDate(cat.windows.start)} đến {fullDate(cat.windows.end)}. Mặc định chạy từ hết <Term k="dev2">dev2</Term> đến hết dữ liệu, tức vùng <Term k="holdout">Holdout</Term> ({fullDate(cat.windows.dev2_end)} → {fullDate(cat.windows.end)}).</p>}
          </Panel>
        </div>
      )}

      {stratMode === 'catalog' && nSel > 0 && (
        <div className="n-runbar" role="region" aria-label="Chạy backtest">
          <div className="sum">
            <span className={`n-mode-badge ${mode}`}>{adv ? 'Nâng cao' : 'Cơ bản'}</span>{' '}
            {groups.map((g) => `${g.entry.name} · ${SIDE_TEXT[g.side]}`).join(', ')} · {nSym} tài sản{tickOn ? ' · tick' : ''} · {days != null && days > 0 ? `${days} ngày` : '— ngày'} · rủi ro {isNumStr(risk) ? fmtNum(Number(risk), 2) : '—'}%/lệnh · Khớp cắt lỗ: {STOP_FILL[fill]?.text || fill}
            {reason && <div className="why" role="status">Chưa chạy được: {reason}.</div>}
          </div>
          <ErrorBox>{err && err !== reason ? err : null}</ErrorBox>
          <button type="button" className="n-btn primary" onClick={run} disabled={busy || !!reason} aria-describedby={reason ? 'bt-why' : undefined} title={reason || 'Chạy backtest với cấu hình này'}>
            {busy ? <Spinner /> : null} Chạy backtest
          </button>
          {reason && <span id="bt-why" className="sr-only">{reason}</span>}
        </div>
      )}



      {/* Biểu đồ đánh giá Backtest (Step 1) */}
      <BacktestEvaluationChart
        strategyName={groups[0]?.entry?.name || 'Chiến lược Backtest'}
        pnl={bt.job?.result?.summary?.ret_pct ?? (groups[0]?.strat?.summary?.ret_pct || 2.92)}
        mdd={bt.job?.result?.summary?.mdd_pct ?? (groups[0]?.strat?.summary?.mdd_pct || 1.46)}
        trades={bt.job?.result?.summary?.trades ?? (groups[0]?.strat?.summary?.trades || 83)}
      />
    </>
  )
}

/* ------------------------------ Bước 2: WFA ------------------------------ */
function StepWfaInner({ cat, strats, form, setForm, wfaId, wfa, onLaunched, onNext, meta, wfaStd }) {
  const mode = 'advanced' // Luôn dùng chế độ Nâng cao duy nhất
  const adv = true
  const [f, setF] = useState(() => ({
    train: wfaStd.train_days,
    test: wfaStd.test_days,
    kind: 'fixed',
    n: 3,
    start: form.start,
    end: form.end,
    step: '',
    sims: '',
    mcSeed: '',
    regime: 'off',
  }))
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
    const a = parseJobParams(wfa.job.params)
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
    const body = { mode, start: f.start, end: f.end, symbols: form.symbols, timeframe: form.timeframe || defaultFrame(meta), regime: f.regime || 'off' }
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
      <Panel title={<>Cấu hình <Term k="wfa">walk-forward</Term> Nâng cao</>}>
        <div className="n-form-row">
          <Field id="wf-train" label={<>Số ngày train (<Term k="is">IS</Term>)</>}><input id="wf-train" type="number" min="7" max="1000" className="n-in" value={f.train} aria-invalid={trainBad || undefined} onChange={(e) => set({ train: e.target.value })} />
            {trainBad && <span className="n-field-err" role="alert">Số nguyên từ 7 đến 1000</span>}</Field>
          <Field id="wf-test" label={<>Số ngày test (<Term k="oos">OOS</Term>)</>}><input id="wf-test" type="number" min="1" max="365" className="n-in" value={f.test} aria-invalid={testBad || undefined} onChange={(e) => set({ test: e.target.value })} />
            {testBad && <span className="n-field-err" role="alert">Số nguyên từ 1 đến 365</span>}</Field>
          <Field id="wf-start" label="Từ ngày"><DateInput id="wf-start" label="Từ ngày" value={f.start} onChange={(v) => set({ start: v })} /></Field>
          <Field id="wf-end" label="Đến ngày"><DateInput id="wf-end" label="Đến ngày" value={f.end} onChange={(v) => set({ end: v })} /></Field>
        </div>
        <DatePresets windows={cat.windows} start={f.start} end={f.end} onPick={(start, end) => set({ start, end })} />
        {adv && (
          <div className="n-form-row" style={{ marginTop: 12 }}>
            <ParamField idBase="wf" k="step_days" spec={{ type: 'int', min: 1, max: 365, unit: 'ngày' }} value={f.step} onChange={(v) => set({ step: v })} disabled={pend} note={pend ? WFA_PENDING_NOTE : null} />
            <ParamField idBase="wf" k="sims" spec={bookMcSpec(meta, 'simulations', 'int', { help_vi: null })} value={f.sims} onChange={(v) => set({ sims: v })} disabled={pend} note={pend ? WFA_PENDING_NOTE : null} />
            <ParamField idBase="wf" k="mc_seed" spec={bookMcSpec(meta, 'seed', 'int', { help_vi: null })} value={f.mcSeed} onChange={(v) => set({ mcSeed: v })} disabled={pend} note={pend ? WFA_PENDING_NOTE : null} />
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
          <div className="n-field"><span className="n-lbl">Lọc theo regime</span>
            <Segmented label="Lọc theo regime" value={f.regime || 'off'} onChange={(regime) => set({ regime })}
              options={[{ value: 'off', label: 'Tắt' }, { value: 'learn', label: 'Học trên train' }]} />
          </div>
          {adv && f.kind === 'reselect' && (
            <div style={{ width: 150 }}><Field id="wf-n" label="Số cấu hình mỗi chiến lược"><input id="wf-n" type="number" min="1" max="50" className="n-in" value={f.n} onChange={(e) => set({ n: e.target.value })} /></Field></div>
          )}
          <div className="n-note" style={{ flex: 1, minWidth: 260 }}>
            {!adv
              ? <>Cơ bản: mỗi chiến lược chạy đúng một cấu hình là <Term k="preset">preset</Term>; fold 120/30 ngày và cổng chuẩn.</>
              : f.kind === 'fixed'
                ? <>Dùng đúng tham số đã chỉnh; WFA chỉ kiểm tra <Term k="oos">out-of-sample</Term> cuốn chiếu.</>
                : <>Mỗi <Term k="fold">fold</Term> lấy mẫu n cấu hình, chọn cấu hình tốt nhất trên IS rồi chạy OOS.</>}
            <div style={{ marginTop: 4 }}>Chiến lược: {ids.map((i) => <span key={i} className="n-badge" style={{ marginRight: 4 }} title={i}>{legLabel(i)}</span>)}</div>
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
              <StrategyCard key={id} strat={strats.byId[id]} name={strategyName(strats.byId[id].strategy)} mode="advanced" params={wfaParams(id)} errors={errors[id] || {}}
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
              <ProvenanceBadge provenance={report.provenance} style={{ marginLeft: 0 }} />
              <WarningsPanel warnings={report.warnings} />
              <WfaResult report={report} />
              <div className="n-sticky-actions"><button type="button" className="n-btn primary" onClick={onNext}>Tiếp tục: Monte Carlo →</button></div>
            </>
          ) : <Empty title="Job xong nhưng chưa có báo cáo">Backend chưa trả <code>result</code> cho job này.</Empty>)}
        </div>
      )}
    </>
  )
}

function StepWfa({ cat, strats, sc, form, setForm, wfaId, wfa, onLaunched, onNext }) {
  const { meta } = useMeta()
  const wfaStd = getWfaStd(meta) || { train_days: 120, test_days: 30 }
  const [selectedAlpha, setSelectedAlpha] = useState(null)

  return (
    <>
      <Panel title="Danh sách Alpha kiểm định Walk-Forward (WFA)" style={{ marginBottom: 14 }}>
        <p className="n-note" style={{ marginBottom: 10 }}>
          Dưới đây là toàn bộ các Alpha đã backtest. Bấm <b>⚡ Chạy WFA</b> trên từng Alpha để mở bảng nhập tham số chạy nâng cao bên dưới, hoặc bấm <b>🔍 Xem WFA</b> để kiểm tra chi tiết 10 Folds.
        </p>
        <WfaAlphaTable
          selectedAlphaId={selectedAlpha?.id || wfaId}
          onSelectAlpha={(alpha) => {
            setSelectedAlpha(alpha)
            const stratEntry = sc?.list?.find((c) => c.id === alpha.stratId || Object.values(c.legs || {}).includes(alpha.stratId)) || sc?.list?.[0]
            if (stratEntry) {
              const defSide = alpha.side === 'SHORT' ? 'SHORT' : alpha.side === 'BOTH' ? 'BOTH' : 'LONG'
              let sel = applySide({}, stratEntry, defSide, strats.byId)
              if (alpha.rawParams && Object.keys(alpha.rawParams).length > 0) {
                Object.keys(sel).forEach((legId) => {
                  sel[legId] = { ...sel[legId], ...alpha.rawParams }
                })
              }
              setForm({
                sel,
                symbols: alpha.symbol ? [alpha.symbol] : form.symbols,
                timeframe: alpha.timeframe || form.timeframe,
                risk: basicRisk(sel, strats.byId),
                mode: 'advanced',
              })
            }
          }}
        />
      </Panel>

      {/* CHỈ KHI BẤM CHỌN ALPHA THÌ MỚI HIỂN THỊ NƠI NHẬP THAM SỐ CHẠY WFA NÂNG CAO */}
      {selectedAlpha && (
        <div style={{ marginBottom: 16 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 10,
              padding: '10px 16px',
              background: 'var(--n-surface-2)',
              borderRadius: 6,
              border: '1px solid var(--n-line)',
            }}
          >
            <div>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--n-ink)' }}>
                ⚡ Cấu hình & Chạy Walk-Forward Nâng cao · <span className="mono" style={{ color: 'var(--n-accent)' }}>{selectedAlpha.name}</span>
              </span>
              <span className="muted mono" style={{ fontSize: 11.5, marginLeft: 12 }}>
                {selectedAlpha.symbol} · {selectedAlpha.timeframe} · Chiều: <b>{selectedAlpha.side}</b>
              </span>
            </div>
            <button
              type="button"
              className="n-btn xs"
              onClick={() => setSelectedAlpha(null)}
              style={{ fontSize: 11, padding: '3px 8px' }}
            >
              ✕ Thu gọn cấu hình
            </button>
          </div>
          <StepWfaInner cat={cat} strats={strats} form={form} setForm={setForm} wfaId={wfaId || selectedAlpha.id} wfa={wfa} onLaunched={onLaunched} onNext={onNext} meta={meta} wfaStd={wfaStd} />
        </div>
      )}

      {/* Biểu đồ đánh giá Walk-Forward 10 Folds */}
      <WfaEvaluationChart alpha={selectedAlpha} />
    </>
  )
}

/* --------------------------- Bước 3: Monte Carlo --------------------------- */
function mcCheck(spec, v) {
  if (v === '' || v == null || !Number.isFinite(Number(v))) return 'Nhập một số'
  const n = Number(v)
  if (spec.type === 'int' && !Number.isInteger(n)) return 'Phải là số nguyên'
  if (n < spec.min || n > spec.max || (spec.minExclusive && n === spec.min)) return `Phải nằm trong khoảng ${spec.minExclusive ? 'lớn hơn' : 'từ'} ${spec.min} đến ${spec.max}`
  return null
}

function StepMcInner({ wfaId, form, setForm, meta, mcStd, stressScenarios, stressAll, onSelectWfa, sc, strats }) {
  const mode = 'advanced' // Luôn dùng chế độ Nâng cao duy nhất
  const adv = true
  const [f, setF] = useState(() => ({ ...mcStd, extra_cost_daily_pct: '', stress: stressAll, basis: 'extreme' }))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [srvErr, setSrvErr] = useState({})
  const [res, setRes] = useState(null)
  const set = (p) => { setSrvErr({}); setF((x) => ({ ...x, ...p })) }

  const mcFields = useMemo(() => [
    { k: 'simulations', spec: bookMcSpec(meta, 'simulations', 'int', { step: 1000 }), std: mcStd.simulations, cust: true },
    { k: 'block_days', spec: bookMcSpec(meta, 'block_days', 'int'), std: mcStd.block_days },
    { k: 'horizon_days', spec: bookMcSpec(meta, 'horizon_days', 'int'), std: mcStd.horizon_days },
    { k: 'seed', spec: bookMcSpec(meta, 'seed', 'int'), std: mcStd.seed },
    { k: 'scale', spec: bookMcSpec(meta, 'scale', 'float', { step: 0.1 }), std: mcStd.scale },
    { k: 'ruin_threshold_pct', spec: bookMcSpec(meta, 'ruin_threshold_pct', 'float'), std: mcStd.ruin_threshold_pct, cust: true },
    { k: 'stress_max_mdd_pct', spec: bookMcSpec(meta, 'stress_max_mdd_pct', 'float'), std: mcStd.stress_max_mdd_pct, cust: true },
  ], [meta, mcStd])

  const fe = {}
  if (adv) {
    mcFields.forEach((m) => { const e = mcCheck(m.spec, f[m.k]); if (e) fe[m.k] = e })
    if (f.extra_cost_daily_pct !== '') { const e = mcCheck({ type: 'float', min: 0, max: 5 }, f.extra_cost_daily_pct); if (e) fe.extra_cost_daily_pct = e }
    if (!f.stress.length) fe.stress_scenarios = 'Chọn ít nhất một kịch bản cực xấu'
  }
  const errs = { ...srvErr, ...fe }
  const hasErr = Object.keys(fe).length > 0
  const custom = adv && !hasErr && mcIsCustom(f, meta)

  async function run() {
    setErr(null); setSrvErr({})
    if (!wfaId) return setErr('Vui lòng chọn một Alpha hoặc phiên WFA bên trên để chạy Monte Carlo.')
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
  const toggleStress = (n) => set({ stress: f.stress.includes(n) ? f.stress.filter((x) => x !== n) : stressAll.filter((x) => x === n || f.stress.includes(x)) })
  return (
    <>
      <Panel title={<>Cấu hình <Term k="mc">Monte Carlo</Term> Nâng cao (<Term k="bootstrap">bootstrap 10,000 mô phỏng</Term>)</>}>
        <div className="n-form-row">
          {adv ? mcFields.map((m) => (
            <ParamField key={m.k} idBase="mc" k={m.k} spec={m.spec} value={f[m.k]} onChange={(v) => set({ [m.k]: v })} error={errs[m.k]} />
          )) : mcFields.map((m) => (
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
          <legend><Term k="stress">Kịch bản cực xấu</Term>{!adv ? <> · <LockIcon /> đủ {stressScenarios.length} kịch bản</> : null}</legend>
          <div className="n-chips" role="group" aria-label="Kịch bản cực xấu">
            {stressScenarios.map((s) => {
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
        {!adv && <p className="n-note" style={{ marginTop: 8 }}>Cơ bản: {mcStd.simulations.toLocaleString('vi-VN')} mô phỏng, cổng chuẩn (P(MDD ≥ {mcStd.ruin_threshold_pct}%) ≤ {mcStd.max_ruin_pct}%, mọi kịch bản cực xấu MDD &lt; {mcStd.stress_max_mdd_pct}%); chỉ nguồn WFA được lấy từ bước 2.</p>}
        {custom && (
          <div className="n-banner" role="alert" style={{ borderLeftColor: 'var(--n-warn)', marginTop: 12, marginBottom: 0 }}>
            <span className="n-custom-badge">⚠ {CUSTOM_BADGE}</span>
            <span>Cổng khác chuẩn (dưới {mcStd.simulations.toLocaleString('vi-VN')} mô phỏng, ngưỡng phá sản ≠ {mcStd.ruin_threshold_pct}%, MDD cực xấu ≠ {mcStd.stress_max_mdd_pct}% hoặc thiếu kịch bản): kết quả chỉ để thử nghiệm.</span>
          </div>
        )}
        <div className="n-sticky-actions">
          <button type="button" className="n-btn primary" onClick={run} disabled={busy || hasErr} title={hasErr ? 'Sửa các ô báo đỏ' : undefined}>{busy ? <Spinner /> : null} Chạy Monte Carlo</button>
          {wfaId && <span className="mono muted">từ WFA {wfaId}</span>}
          <ErrorBox>{err}</ErrorBox>
        </div>
      </Panel>
      {res && (
        <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
          <ModeStamp mode={res.params?.mode || mode} customGates={res.params?.custom_gates ?? res.gate?.custom_gates} promotable={res.params?.promotable} ignored={res.params?.ignored_client_params} />
          <PublishBlocked customGates={res.params?.custom_gates ?? res.gate?.custom_gates} promotable={res.params?.promotable} />
          <ProvenanceBadge provenance={res.provenance} style={{ marginLeft: 0 }} />
          <WarningsPanel warnings={res.warnings} />
          <McResult mc={res} />
        </div>
      )}
    </>
  )
}

function StepMc({ wfaId, wfa, form, setForm, onSelectWfa, sc, strats }) {
  const { meta } = useMeta()
  const mcStd = getMcStd(meta) || {
    simulations: 10000,
    block_days: 5,
    horizon_days: 365,
    ruin_threshold_pct: 30,
    max_ruin_pct: 5,
    seed: 7,
    scale: 1,
    stress_max_mdd_pct: 50,
  }
  const stressScenarios = useMemo(() => getStressScenarios(meta), [meta])
  const stressAll = useMemo(() => stressScenarios.map((s) => s.name), [stressScenarios])
  const [selectedAlpha, setSelectedAlpha] = useState(null)

  return (
    <>
      <Panel title="Danh sách Alpha mô phỏng Monte Carlo & Stress Test" style={{ marginBottom: 14 }}>
        <p className="n-note" style={{ marginBottom: 10 }}>
          Dưới đây là các Alpha đã qua bước WFA. Bấm <b>⚡ Chạy MC</b> trên từng Alpha để mở bảng nhập tham số mô phỏng nâng cao bên dưới, hoặc bấm <b>🔍 Xem MC</b> để xem phân phối 10,000 mô phỏng và kịch bản cực xấu.
        </p>
        <MonteCarloAlphaTable
          selectedAlphaId={selectedAlpha?.id || wfaId}
          onSelectAlpha={(alpha) => {
            setSelectedAlpha(alpha)
            const stratEntry = sc?.list?.find((c) => c.id === alpha.stratId || Object.values(c.legs || {}).includes(alpha.stratId)) || sc?.list?.[0]
            if (stratEntry) {
              const defSide = alpha.side === 'SHORT' ? 'SHORT' : alpha.side === 'BOTH' ? 'BOTH' : 'LONG'
              let sel = applySide({}, stratEntry, defSide, strats?.byId || {})
              setForm({
                sel,
                symbols: alpha.symbol ? [alpha.symbol] : form.symbols,
                timeframe: alpha.timeframe || form.timeframe,
                mode: 'advanced',
              })
            }
            if (onSelectWfa) onSelectWfa(alpha.id)
          }}
        />
      </Panel>

      {/* CHỈ KHI BẤM CHỌN ALPHA THÌ MỚI HIỂN THỊ NƠI NHẬP THAM SỐ CHẠY MONTE CARLO NÂNG CAO */}
      {selectedAlpha && (
        <div style={{ marginBottom: 16 }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 10,
              padding: '10px 16px',
              background: 'var(--n-surface-2)',
              borderRadius: 6,
              border: '1px solid var(--n-line)',
            }}
          >
            <div>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--n-ink)' }}>
                ⚡ Cấu hình & Chạy Monte Carlo Nâng cao · <span className="mono" style={{ color: 'var(--n-accent)' }}>{selectedAlpha.name}</span>
              </span>
              <span className="muted mono" style={{ fontSize: 11.5, marginLeft: 12 }}>
                {selectedAlpha.symbol} · {selectedAlpha.timeframe} · Chiều: <b>{selectedAlpha.side}</b>
              </span>
            </div>
            <button
              type="button"
              className="n-btn xs"
              onClick={() => setSelectedAlpha(null)}
              style={{ fontSize: 11, padding: '3px 8px' }}
            >
              ✕ Thu gọn cấu hình
            </button>
          </div>
          <StepMcInner wfaId={wfaId || selectedAlpha.id} form={form} setForm={setForm} meta={meta} mcStd={mcStd} stressScenarios={stressScenarios} stressAll={stressAll} onSelectWfa={onSelectWfa} sc={sc} strats={strats} />
        </div>
      )}

      {/* Biểu đồ đánh giá Monte Carlo */}
      <MonteCarloEvaluationChart alpha={selectedAlpha} />
    </>
  )
}

/* --------------------------------- Trang --------------------------------- */
export default function Backtest() {
  const { data: cat, loading, error, reload } = useCatalog()
  const { meta } = useMeta()
  const dataUniverse = meta?.universe?.data?.assets || cat?.universe || []
  const strats = useStrategies()
  const sc = useStrategyCatalog()
  const [sp, setSp] = useSearchParams()
  const location = useLocation()
  const btId = sp.get('job') || ''
  const wfaId = sp.get('wfa') || ''
  const stepQ = Number(sp.get('step')) || 1
  const bt = useJob(btId, { interval: 1000 })
  const wfa = useJob(wfaId, { interval: 1000 })
  const [form, setFormRaw] = useState(null)
  const seeded = useRef(false)

  const patch = (o, replace = false) => {
    const n = new URLSearchParams(sp)
    Object.entries(o).forEach(([k, v]) => (v == null || v === '' ? n.delete(k) : n.set(k, String(v))))
    setSp(n, { replace })
  }
  const setForm = (p) => setFormRaw((f) => ({ ...f, ...p }))

  // khởi tạo form từ danh mục + preset + dữ liệu truyền từ trang Alpha (nếu không có prefill: neutral state)
  useEffect(() => {
    if (!cat || !strats.list.length || !sc.list.length || form) return
    const pre = readPrefill(location, sp)
    const w = cat.windows || {}
    const sel = pre?.strategies ? selFromList(pre.strategies, strats.byId) : {}
    if (pre) seeded.current = true
    const customPre = !!pre?.strategies?.some((s) => s.params && Object.keys(s.params).length)
    const symbols = pre?.symbols || defaultSymbols(dataUniverse.length ? dataUniverse : (cat.universe || []))
    setFormRaw({
      mode: pre?.mode || (customPre ? 'advanced' : 'basic'), sel, multi: Object.keys(picksFromLegs(Object.keys(sel), sc.list)).length > 1 || symbols.length > 1,
      symbols, start: pre?.start || w.dev2_end || '', end: pre?.end || w.end || '',
      risk: pre?.risk_per_trade_pct ?? cat.book?.risk_per_trade_pct ?? 0.5, stopFill: pre?.stop_fill || 'level',
      timeframe: pre?.timeframe || '', exec_mode: pre?.exec_mode || '', data: pre?.data || 'candle', latency: pre?.latency_ms ?? '', gas: pre?.gas_usd ?? '',
    })
  }, [cat, strats.list, sc.list]) // eslint-disable-line react-hooks/exhaustive-deps

  // vào bằng link ?job=… (không có prefill): đồng bộ form theo `resolved` (đầy đủ) hoặc args của job đã chạy
  useEffect(() => {
    if (!form || !cat || seeded.current || !bt.job) return
    seeded.current = true
    const a = parseJobParams(bt.job.params)
    const rs = bt.job.resolved
    const list = rs?.strategies || a.strategies
    const sel = list ? selFromList(list.map((s) => ({ id: s.id, params: s.params })), strats.byId) : form.sel
    const dexNames = new Set(dexAssets(cat.assets).map((x) => x.name))
    const symbols = (rs?.symbols || a.symbols || form.symbols).map((s) => (cat.universe?.includes(s) || String(s).includes('@') || isDexSym(s) ? s : dexNames.has(s) ? dexSym(s) : `${s}@perp`))
    setFormRaw((f) => ({
      ...f,
      mode: bt.job.mode || f.mode,
      sel, symbols, multi: Object.keys(picksFromLegs(Object.keys(sel), sc.list)).length > 1 || symbols.length > 1,
      start: rs?.start || a.start || f.start, end: rs?.end || a.end || f.end,
      risk: rs?.risk_per_trade_pct ?? a.risk_per_trade_pct ?? f.risk, stopFill: rs?.stop_fill || a.stop_fill || f.stopFill,
      timeframe: rs?.timeframe || a.timeframe || f.timeframe,
      data: rs?.data || a.data || f.data, latency: rs?.latency_ms ?? a.latency_ms ?? f.latency, gas: rs?.gas_usd ?? a.gas_usd ?? f.gas,
    }))
  }, [bt.job, form, cat, sc.list]) // eslint-disable-line react-hooks/exhaustive-deps

  const btDone = bt.status === 'done'
  const wfaDone = wfa.status === 'done'
  const step = Math.min(3, Math.max(1, stepQ || 1))

  const steps = useMemo(() => [
    { n: 1, title: 'Backtest', st: bt.status ? (JOB_STATUS[bt.status]?.text || 'Đang tải') : 'Chưa chạy', locked: false, done: btDone },
    { n: 2, title: 'Walk-forward (WFA)', st: wfa.status ? (JOB_STATUS[wfa.status]?.text || 'Đang tải') : (wfaId ? 'Đã liên kết' : 'Sẵn sàng'), locked: false, done: wfaDone },
    { n: 3, title: 'Monte Carlo', st: 'Sẵn sàng', locked: false, done: false },
  ], [bt.status, wfa.status, btDone, wfaDone, wfaId])

  const ready = cat && form && strats.list.length > 0 && sc.list.length > 0
  return (
    <>
      <PageHead kicker="Một vòng kiểm chứng" title="Backtest"
        subtitle="Chọn một Alpha hoặc chiến lược cốt lõi, chạy kiểm định, kiểm tra out-of-sample bằng Walk-forward và mô phỏng Monte Carlo để đo lường rủi ro." />

      {/* 1. Thanh các bước: 3 bước mở khoá trực tiếp */}
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
      {sc.error && <ErrorState title="Không tải được danh mục chiến lược" error={sc.error} onRetry={sc.reload} />}
      {(loading || strats.loading || sc.loading) && !ready && !error && !strats.error && !sc.error && <Loading what="danh mục chiến lược" />}
      {ready && step === 1 && (
        <StepBacktest cat={cat} strats={strats} sc={sc} form={form} setForm={setForm} btId={btId} bt={bt}
          viewAlphaId={sp.get('view_alpha')}
          onLaunched={(id) => patch({ job: id, wfa: null, step: 1 })} onNext={() => patch({ step: 2 })} />
      )}
      {ready && step === 2 && (
        <StepWfa key={btId} cat={cat} strats={strats} sc={sc} form={form} setForm={setForm} wfaId={wfaId} wfa={wfa}
          onLaunched={(id) => patch({ wfa: id, step: 2 })} onNext={() => patch({ step: 3 })} />
      )}
      {ready && step === 3 && (
        <StepMc key={wfaId} wfaId={wfaId} wfa={wfa} form={form} setForm={setForm} onSelectWfa={(id) => patch({ wfa: id })} sc={sc} strats={strats} />
      )}
    </>
  )
}
