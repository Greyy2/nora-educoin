import React, { useEffect, useState } from 'react'
import { Panel, Segmented, Field, ErrorBox, Spinner } from '../../ui'
import StrategyChoice from '../backtest/StrategyChoice'
import { useStrategyCatalog } from '../RunModes'
import { legsFor, legLabel } from '../../../lib/strategyLabel'
import Term from '../../ui/Term'
import { DateInput } from '../../ui/DateField'
import { postFunnelRun, getFunnelEstimate } from '../../../api'
import { fmtEta, fmtCount } from '../../../lib/funnel'
import { daysInclusive } from '../../../lib/dates'
import { fullDate, fmtNum, fmtFrame } from '../../../lib/format'
import { useMeta } from '../../../meta/MetaProvider'

const MAX_TOTAL = 1000000
const LARGE_TOTAL = 200000
const N_PRESETS = [100, 1000, 10000, 100000]
const gridSize = (c) => Object.values(c.space || {}).reduce((p, a) => p * Math.max(1, a.length), 1)

export default function NewRunForm({ cat, onLaunched, onCancel }) {
  const meta = useMeta()
  const catalog = cat?.catalog || []
  const dataUniverse = meta?.universe?.data?.assets || cat?.universe || []
  const bookUniverse = meta?.universe?.book || []
  const [useBookUniverse, setUseBookUniverse] = useState(false)
  const universe = useBookUniverse && bookUniverse.length ? bookUniverse : dataUniverse

  const sc = useStrategyCatalog()
  // chọn theo chiến lược + chiều ({ kema: 'BOTH', ... }); chưa chạm thì mặc định mọi chiến lược đã có, cả hai chiều
  const [picksRaw, setPicks] = useState(null)
  const picks = picksRaw || Object.fromEntries(sc.list.filter((c) => !c.coming && Object.keys(c.legs || {}).length).map((c) => [c.id, 'BOTH']))
  const legIds = new Set(catalog.map((c) => c.id))
  const sel = sc.list.flatMap((c) => (picks[c.id] ? legsFor(c, picks[c.id]) : [])).filter((id) => legIds.has(id)) // id chân lệnh gửi cho phễu
  const [mode, setMode] = useState('n')
  const [n, setN] = useState(1000)
  const [seed, setSeed] = useState(42)
  const frames = meta?.frames?.funnel || ['15m', '1h', '4h']
  const [timeframe, setTimeframe] = useState(frames[0] || '15m')
  const [regime, setRegime] = useState('off')          // off | learn | both (mỗi biến thể là một alpha -> DSR/PBO đếm đủ)
  const [symbols, setSymbols] = useState(universe)
  useEffect(() => {
    if (universe.length) {
      setSymbols(universe)
    }
  }, [useBookUniverse, universe.join(',')])
  const [winMode, setWinMode] = useState('default')
  const w0 = cat?.windows || {}
  const [win, setWin] = useState({ start: w0.start || '', dev1_end: w0.dev1_end || '', dev2_end: w0.dev2_end || '', end: w0.end || '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [force, setForce] = useState(false)
  const [srvEst, setSrvEst] = useState({ state: 'idle', data: null, error: null }) // ước tính do máy chủ (GET /estimate)

  const chosen = catalog.filter((c) => sel.includes(c.id))
  const total = mode === 'full' ? chosen.reduce((s, c) => s + gridSize(c), 0) : chosen.length * (Number(n) || 0)
  const selKey = sel.join(',')
  useEffect(() => { setConfirming(false) }, [selKey, mode, n, seed, timeframe, regime, symbols, winMode, win])
  // ước tính do máy chủ (đo thực): gọi lại sau 400 ms kể từ lần chỉnh cuối
  useEffect(() => {
    if (!chosen.length || (mode === 'n' && !(Number(n) >= 1))) { setSrvEst({ state: 'idle', data: null, error: null }); return undefined }
    setSrvEst((x) => ({ ...x, state: 'loading' }))
    let dead = false
    const t = setTimeout(() => {
      getFunnelEstimate({ strategies: sel, nPerStrategy: Number(n), fullGrid: mode === 'full', timeframe, regime })   // workers bỏ trống: máy chủ dùng số worker mặc định của nó
        .then((d) => { if (!dead) setSrvEst({ state: 'ok', data: d, error: null }) }, (e) => { if (!dead) setSrvEst({ state: 'error', data: null, error: e.message }) })
    }, 400)
    return () => { dead = true; clearTimeout(t) }
  }, [selKey, mode, n, timeframe, regime]) // eslint-disable-line react-hooks/exhaustive-deps
  const srv = srvEst.state === 'ok' ? srvEst.data : null
  const totalShown = srv ? srv.total_alphas : total
  const winOk = winMode === 'default' || (win.start && win.dev1_end && win.dev2_end && win.end && win.start < win.dev1_end && win.dev1_end < win.dev2_end && win.dev2_end < win.end)
  const reason = !chosen.length ? 'Chọn ít nhất một chiến lược (và chiều giao dịch)'
    : mode === 'n' && !(Number(n) >= 1) ? 'Số alpha mỗi chiều phải ≥ 1'
      : totalShown > MAX_TOTAL ? `Tổng ${fmtCount(totalShown)} vượt giới hạn ${fmtCount(MAX_TOTAL)} alpha`
        : !symbols.length ? 'Chọn ít nhất một cặp giao dịch'
          : !Number.isInteger(Number(seed)) ? 'Seed phải là số nguyên'
            : !winOk ? 'Các mốc ngày phải hợp lệ và tăng dần: bắt đầu < hết dev1 < hết dev2 < kết thúc' : null
  const pickStrategy = (c) => setPicks((p) => { const n = { ...(p || picks) }; if (n[c.id]) delete n[c.id]; else n[c.id] = 'BOTH'; return n })
  const pickSide = (c, side) => setPicks((p) => ({ ...(p || picks), [c.id]: side }))
  const gridOf = (c) => legsFor(c, picks[c.id]).reduce((t, id) => t + gridSize(catalog.find((x) => x.id === id) || {}), 0)
  const toggleSym = (s) => setSymbols((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]))

  async function submit() {
    setErr(null)
    if (reason) return setErr(reason)
    setBusy(true)
    try {
      const body = { strategies: sel, seed: Number(seed), symbols, timeframe, regime }
      if (mode === 'full') body.full_grid = true
      else body.n_per_strategy = Number(n)
      if (winMode === 'custom') body.windows = win
      if (force || totalShown > LARGE_TOTAL) body.force_large = force
      const r = await postFunnelRun(body)
      onLaunched(r)
    } catch (e) { setErr(`${e.status ? `Lỗi ${e.status}: ` : ''}${e.message}`); setConfirming(true) } finally { setBusy(false) }
  }

  return (
    <Panel title="Tạo lượt phễu mới" meta={<button type="button" className="n-btn sm" onClick={onCancel}>Đóng</button>}>
      <div className="n-grid g-main-side" style={{ marginBottom: 0 }}>
        <div style={{ display: 'grid', gap: 14, alignContent: 'start' }}>
          <div>
            <div className="n-fn-sub">
              <b>Chiến lược</b><span className="muted mono">{Object.keys(picks).length}/{sc.list.filter((c) => !c.coming).length} đã chọn · {sel.length} chân lệnh</span>
              <span className="sp" />
              <button type="button" className="n-btn sm" onClick={() => setPicks(Object.fromEntries(sc.list.filter((c) => !c.coming && Object.keys(c.legs || {}).length).map((c) => [c.id, 'BOTH'])))}>Chọn tất cả</button>
              <button type="button" className="n-btn sm" onClick={() => setPicks({})} disabled={!sel.length}>Bỏ chọn</button>
            </div>
            <StrategyChoice catalog={sc.list} picks={picks} multi onPick={pickStrategy} onSide={pickSide}
              extra={(c) => picks[c.id] && <span className="muted" style={{ fontSize: 11.5 }}>lưới {fmtCount(gridOf(c))} tổ hợp theo chiều đã chọn</span>} />
            {sc.error && <ErrorBox>{`Không tải được danh mục chiến lược: ${sc.error}`}</ErrorBox>}
          </div>
          <div>
            <div className="n-fn-sub"><b>Cặp giao dịch</b>
              <span className="sp" />
              <button type="button" className={`n-btn sm ${useBookUniverse ? 'primary' : ''}`}
                onClick={() => {
                  const next = !useBookUniverse
                  setUseBookUniverse(next)
                  setSymbols(next && bookUniverse.length ? bookUniverse : dataUniverse)
                }}>
                {useBookUniverse ? 'Đang theo sổ' : 'Theo sổ'}
              </button>
              <button type="button" className="n-btn sm" onClick={() => setSymbols(universe)}>Tất cả</button>
              <button type="button" className="n-btn sm" onClick={() => setSymbols([])}>Bỏ chọn</button></div>
            <div className="n-chips" role="group" aria-label="Cặp giao dịch">
              {universe.map((s) => {
                const on = symbols.includes(s)
                return <label key={s} className={`n-chip-lbl ${on ? 'on' : ''}`}><input type="checkbox" checked={on} onChange={() => toggleSym(s)} />{s.replace('@perp', '')}</label>
              })}
            </div>
          </div>
        </div>
        <div style={{ display: 'grid', gap: 12, alignContent: 'start' }}>
          <Panel title="Quy mô">
            <Segmented label="Cách chọn số alpha" value={mode} onChange={setMode} options={[{ value: 'n', label: 'Số alpha mỗi chiều' }, { value: 'full', label: 'Toàn bộ lưới' }]} />
            {mode === 'n' ? (
              <div style={{ marginTop: 10 }}>
                <Field id="fr-n" label="Số alpha mỗi chiều (mỗi chiến lược · chiều)"><input id="fr-n" type="number" min="1" step="1" className="n-in" value={n} onChange={(e) => setN(e.target.value)} /></Field>
                <div className="n-presets">{N_PRESETS.map((p) => <button key={p} type="button" className={`n-chip-btn ${Number(n) === p ? 'on' : ''}`} onClick={() => setN(p)}>{fmtCount(p)}</button>)}</div>
              </div>
            ) : <p className="n-note" style={{ marginTop: 8 }}>Chạy mọi tổ hợp tham số của từng chiều đã chọn (lưới hiện có trong danh mục).</p>}
            <div className="n-form-row" style={{ gridTemplateColumns: '1fr auto', marginTop: 10, alignItems: 'end' }}>
              <Field id="fr-seed" label="Seed (lấy mẫu lặp lại được)"><input id="fr-seed" type="number" step="1" className="n-in" value={seed} onChange={(e) => setSeed(e.target.value)} /></Field>
              <button type="button" className="n-btn" onClick={() => setSeed(Math.floor(Math.random() * 100000))}>Ngẫu nhiên</button>
            </div>
          </Panel>
          <Panel title={<>Khung chạy</>}>
            <Segmented label="Khung chạy" value={timeframe} onChange={setTimeframe}
              options={frames.map((f) => ({ value: f, label: fmtFrame(f) }))} />
            <p className="n-note" style={{ marginTop: 8 }}>Nến dùng để mô phỏng khớp lệnh. Khung tín hiệu của mọi alpha được sinh ≥ khung này
              (nhỏ hơn thì nâng lên); chiến lược không có khung tín hiệu đủ lớn sẽ bị từ chối.</p>
          </Panel>
          <Panel title={<>Regime</>}>
            <Segmented label="Regime" value={regime} onChange={setRegime}
              options={[{ value: 'off', label: 'Tắt' }, { value: 'learn', label: 'Học trên train' }, { value: 'both', label: 'Cả hai' }]} />
            <p className="n-note" style={{ marginTop: 8 }}>Học trên train: mỗi alpha chặn các regime mà nó lỗ trên dữ liệu học (WFA học trên train
              của từng fold). Cả hai: mỗi bộ tham số chạy hai biến thể — số alpha gấp đôi và DSR/PBO đếm đủ số lần thử.</p>
          </Panel>
          <Panel title={<>Cửa sổ dữ liệu</>}>
            <Segmented label="Cửa sổ dữ liệu" value={winMode} onChange={setWinMode} options={[{ value: 'default', label: 'Mặc định' }, { value: 'custom', label: 'Tuỳ chỉnh' }]} />
            {winMode === 'default' ? (
              <p className="n-note" style={{ marginTop: 8 }}>
                {w0.start ? <>Dữ liệu {fullDate(w0.start)} → {fullDate(w0.end)}: <Term k="dev1">dev1</Term> tới {fullDate(w0.dev1_end)}, <Term k="dev2">dev2</Term> tới {fullDate(w0.dev2_end)}, <Term k="holdout">holdout</Term> phần còn lại ({daysInclusive(w0.dev2_end, w0.end)} ngày).</> : 'Dùng cửa sổ mặc định của dữ liệu hiện có.'}
              </p>
            ) : (
              <div className="n-form-row" style={{ gridTemplateColumns: '1fr 1fr', marginTop: 10 }}>
                <Field id="fw-s" label="Bắt đầu"><DateInput id="fw-s" label="Bắt đầu" value={win.start} onChange={(v) => setWin((x) => ({ ...x, start: v }))} /></Field>
                <Field id="fw-1" label="Hết dev1"><DateInput id="fw-1" label="Hết dev1" value={win.dev1_end} onChange={(v) => setWin((x) => ({ ...x, dev1_end: v }))} /></Field>
                <Field id="fw-2" label="Hết dev2"><DateInput id="fw-2" label="Hết dev2" value={win.dev2_end} onChange={(v) => setWin((x) => ({ ...x, dev2_end: v }))} /></Field>
                <Field id="fw-e" label="Kết thúc"><DateInput id="fw-e" label="Kết thúc" value={win.end} onChange={(v) => setWin((x) => ({ ...x, end: v }))} /></Field>
              </div>
            )}
          </Panel>
        </div>
      </div>
      <div className="n-runbar n-runbar-inline" role="region" aria-label="Ước tính và chạy">
        <div className="sum">
          <b>{fmtCount(totalShown)} alpha</b> · {Object.keys(picks).length} chiến lược · {chosen.length} chiều · {mode === 'full' ? 'toàn bộ lưới' : `${fmtCount(Number(n) || 0)}/chiều`} · {symbols.length} cặp · seed {seed}
          <div className="est" role="status">
            {srv
              ? (srv.s1_eta_s != null
                ? <>Ước tính S1 khoảng <b>{fmtEta(srv.s1_eta_s)}</b> <span className="muted">({fmtCount(srv.total_alphas)} alpha × {fmtNum(srv.sec_per_backtest, 3)} giây/backtest / {srv.workers} worker, trung vị {srv.measure?.n_runs} lượt đã chạy; các tầng sau chỉ chạy trên alpha còn sống nên thường ngắn hơn)</span></>
                : <>Ước tính S1: <b className="n-na" title={srv.measure?.reason || undefined}>chưa có số đo</b> <span className="muted">({srv.measure?.reason || 'chưa có lượt tham chiếu'}; {srv.workers} worker)</span></>)
              : srvEst.state === 'loading' ? <><Spinner /> Đang ước tính…</>
                : <>Ước tính S1: <b>chưa có số đo</b> <span className="muted">{srvEst.state === 'error' ? `(máy chủ không ước tính được: ${srvEst.error})` : '(chọn chiến lược và số alpha)'}</span></>}
          </div>
          {reason && <div className="why" role="status">Chưa chạy được: {reason}.</div>}
        </div>
        {!confirming && <button type="button" className="n-btn primary" onClick={() => { setErr(null); setConfirming(true) }} disabled={busy || !!reason}>Chạy phễu…</button>}
      </div>
      {confirming && !reason && (
        <div className="n-confirm" role="alertdialog" aria-label="Xác nhận chạy phễu" style={{ marginTop: 12 }}>
          <p><b>Xác nhận chạy phễu {fmtCount(totalShown)} alpha?</b></p>
          <div className="n-estimate">
            <span>Chiến lược: <span className="mono">{chosen.map((c) => `${legLabel(c.id)} ${fmtCount(srv?.per_strategy?.[c.id] ?? (mode === 'full' ? gridSize(c) : Number(n)))}`).join(' · ')}</span></span>
            <span>Cửa sổ: <span className="mono">{winMode === 'default' ? 'mặc định' : `${win.start} → ${win.end}`}</span> · {symbols.length} cặp · seed {seed} · khung chạy {timeframe}</span>
            <span>Ước tính S1: {srv?.s1_eta_s != null ? <><b className="mono">{fmtEta(srv.s1_eta_s)}</b><span className="muted"> ({fmtNum(srv.sec_per_backtest, 3)} giây/backtest, {srv.workers} worker)</span></> : <b className="n-na" title={srv?.measure?.reason || undefined}>chưa có số đo</b>}</span>
            <span className="muted">Job chạy nền trong hàng đợi, dùng nhiều CPU/RAM; có thể huỷ và chạy tiếp (resume).</span>
          </div>
          {totalShown > LARGE_TOTAL && (
            <label className="n-chip-lbl" style={{ marginTop: 8 }}><input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> Tôi hiểu: vượt {fmtCount(LARGE_TOTAL)} alpha (force_large)</label>
          )}
          <ErrorBox>{err}</ErrorBox>
          <div className="n-sticky-actions" style={{ marginTop: 8 }}>
            <button type="button" className="n-btn primary" onClick={submit} disabled={busy || (totalShown > LARGE_TOTAL && !force)}>{busy ? <Spinner /> : null} Xác nhận chạy</button>
            <button type="button" className="n-btn" onClick={() => { setConfirming(false); setErr(null) }} disabled={busy}>Quay lại</button>
          </div>
        </div>
      )}
    </Panel>
  )
}
