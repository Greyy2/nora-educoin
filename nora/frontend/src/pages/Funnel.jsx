import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Status, Spinner, Loading, ErrorState, Empty, Segmented } from '../components/ui'
import JobPanel from '../components/JobPanel'
import FunnelChart from '../components/funnel/FunnelChart'
import StageStats from '../components/funnel/StageStats'
import AlphaTable from '../components/funnel/AlphaTable'
import TradesView from '../components/funnel/TradesView'
import AlphaDrawer from '../components/funnel/AlphaDrawer'
import NewRunForm from '../components/funnel/NewRunForm'
import RunsList from '../components/funnel/RunsList'
import { Headline, FinalSummary } from '../components/funnel/RunSummary'
import '../styles/funnel.css'
import { MockBanner, EmptyStage } from '../components/funnel/parts'
import useAsync from '../hooks/useAsync'
import useJob from '../hooks/useJob'
import { useCatalog } from '../context/Catalog'
import { listFunnelRuns, getFunnelRun, getFunnelStats, getFunnelAlphas } from '../api'
import { STAGES, STAGE_META, RUN_STATUS, shortId, fmtCount, stageShort } from '../lib/funnel'
import { isNum } from '../lib/format'
import { fmtDateTime, fullDate } from '../lib/format'
import { legLabel } from '../lib/strategyLabel'

const isLive = (s) => s === 'running' || s === 'queued'

/* ------------------------------ danh sách lượt ------------------------------ */
function RunsPage() {
  const nav = useNavigate()
  const { data: cat } = useCatalog()
  const runs = useAsync(() => listFunnelRuns(), [], { poll: (d) => (d.some((r) => isLive(r.status)) ? 5000 : 30000) })
  const [open, setOpen] = useState(false)
  const [launched, setLaunched] = useState(null)
  const job = useJob(launched?.job_id)
  const onLaunched = (r) => { setLaunched(r); setOpen(false); runs.reload() }
  return (
    <>
      <PageHead kicker="Kiểm duyệt hàng loạt" title="Phễu kiểm duyệt alpha"
        subtitle="Chạy mọi alpha đã sinh (chiến lược × tham số) qua các tầng ngày càng khắt khe để tìm alpha thắng thật và sống sót được, rồi đưa vào kho alpha cho testnet.">
        <button type="button" className="n-btn primary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? 'Đóng biểu mẫu' : 'Tạo lượt mới'}</button>
      </PageHead>
      <MockBanner />
      {launched && (
        <Panel className="n-fn-launched" title="Lượt vừa tạo" meta={<span className="mono">{launched.run_id}</span>}>
          <JobPanel job={job.job} status={job.status} error={job.error} />
          <div className="n-sticky-actions">
            <button type="button" className="n-btn primary" onClick={() => nav(`/alpha/funnel/${encodeURIComponent(launched.run_id)}`)}>Mở lượt này →</button>
            <button type="button" className="n-btn" onClick={() => setLaunched(null)}>Ẩn</button>
          </div>
        </Panel>
      )}
      {open && <NewRunForm cat={cat} runs={runs.data || []} onLaunched={onLaunched} onCancel={() => setOpen(false)} />}
      <div style={{ marginTop: open || launched ? 12 : 0 }}>
        <RunsList q={runs} onCreate={() => setOpen(true)} />
      </div>
    </>
  )
}

/* ------------------------------- xem một lượt ------------------------------- */
// tầng thật sự lưu lệnh; S2/S4 (chống ăn may, Monte Carlo) và FINAL xem lệnh qua tầng gần nhất có lệnh
const TRADE_STAGES = ['S1_backtest', 'S3_wfa', 'S5_sizing', 'S6_holdout']
const TRADE_STAGE_OF = { S2_antiluck: 'S1_backtest', S4_montecarlo: 'S3_wfa', FINAL: 'S6_holdout' }
const tradeStageOf = (st) => (TRADE_STAGES.includes(st) ? st : TRADE_STAGE_OF[st] || null)
const TABS = [{ value: 'stats', label: 'Thống kê' }, { value: 'alphas', label: 'Alpha' }, { value: 'trades', label: 'Lệnh' }]

function RunMeta({ run }) {
  const st = RUN_STATUS[run.status] || { text: run.status, cls: '' }
  return (
    <div className="n-srcline" style={{ flexWrap: 'wrap' }}>
      <Status tone={st.cls}>{isLive(run.status) && <Spinner />}{st.text}</Status>
      <span>Tạo lúc <b className="mono">{fmtDateTime(run.created)}</b></span>
      <span>Chiến lược <b>{run.strategies.map(legLabel).join(', ') || '—'}</b></span>
      <span>{run.full_grid ? 'Toàn bộ lưới' : <><b className="mono">{fmtCount(run.n_per_strategy)}</b>/chiến lược</>} · tổng <b className="mono">{fmtCount(run.total_alphas)}</b> alpha</span>
      {run.seed != null && <span>seed <b className="mono">{run.seed}</b></span>}
      <details className="n-details" style={{ marginLeft: 'auto' }}>
        <summary>Cấu hình lượt chạy</summary>
        <div className="n-fn-cfg mono">
          <div>symbols: {run.symbols.join(', ') || '—'}</div>
          {run.windows && <div>windows: {Object.entries(run.windows).map(([k, v]) => `${k} ${fullDate(v)}`).join(' · ')}</div>}
          {run.config?.commit && <div>commit: {run.config.commit}</div>}
          {run.config?.data_sha256 && <div>dữ liệu sha256: {String(run.config.data_sha256).slice(0, 16)}…</div>}
          <div>job: {run.job_id || '—'}</div>
        </div>
      </details>
    </div>
  )
}

function RunView({ runId }) {
  const nav = useNavigate()
  const [sp, setSp] = useSearchParams()
  const runQ = useAsync(() => getFunnelRun(runId), [runId], { poll: (r) => (isLive(r.status) ? 4000 : 0) })
  const run = runQ.data
  const live = !!run && isLive(run.status)
  const jobQ = useJob(run?.job_id && (live || run?.status === 'failed') ? run.job_id : null)

  const stage = STAGES.includes(sp.get('stage')) ? sp.get('stage') : 'S1_backtest'
  const tab = TABS.some((t) => t.value === sp.get('tab')) ? sp.get('tab') : 'stats'
  const sel = sp.get('sel') || ''
  // mặc định chỉ hiện tóm tắt; phần chi tiết tầng (và dữ liệu nặng của nó) chỉ mở khi chọn tầng / tab / alpha
  const detail = sp.has('stage') || sp.has('tab') || sp.has('sel')
  const drawer = sp.get('alpha') || ''
  const setParams = useCallback((patch, replace = true) => {
    const n = new URLSearchParams(sp)
    Object.entries(patch).forEach(([k, v]) => { if (v) n.set(k, v); else n.delete(k) })
    setSp(n, { replace })
  }, [sp, setSp])

  // thống kê tầng (S1 ~450 KB): chỉ tải khi mở tab Thống kê của một tầng
  const wantStats = detail && tab === 'stats'
  const statsQ = useAsync(wantStats ? () => getFunnelStats(runId, stage) : null, [runId, stage, run?.status, wantStats], { poll: () => (live ? 8000 : 0) })
  const stats = statsQ.data
  // tóm tắt FINAL ở trang tổng quan (~45 KB), chỉ khi đã có alpha FINAL
  const finalCount = run?.counts?.[7]?.passed
  const finalQ = useAsync(isNum(finalCount) && finalCount > 0 ? () => getFunnelStats(runId, 'FINAL') : null, [runId, finalCount, run?.status])
  // danh sách alpha cho ô chọn ở tab Lệnh: nhẹ hơn nhiều so với /stats
  const tStage = tradeStageOf(stage) || 'S1_backtest'
  const pickQ = useAsync(detail && tab === 'trades' ? () => getFunnelAlphas(runId, { stage: tStage, status: 'passed', sort: '-sharpe', limit: 25 }) : null, [runId, tStage, detail, tab])

  // lý do loại chính của mọi tầng: nếu backend không kèm trong `counts` thì lấy từ /stats từng tầng (tuần tự, sau khi lượt không còn chạy)
  const [tops, setTops] = useState({})
  const needTops = !!run && !run.counts.some((c) => c.top_reject)
  useEffect(() => {
    if (!needTops || live) return undefined
    let dead = false
    ;(async () => {
      for (const st of STAGES.slice(1)) {
        if (dead) return
        try {
          const s = await getFunnelStats(runId, st)
          if (dead) return
          if (s.reject_reasons[0]) setTops((t) => ({ ...t, [st]: s.reject_reasons[0] }))
        } catch (e) { /* tầng chưa có số liệu */ }
      }
    })()
    return () => { dead = true }
  }, [runId, needTops, live])
  useEffect(() => { setTops({}) }, [runId])

  // tầng xa nhất có số liệu; nếu không alpha nào qua và lượt không còn chạy => phễu đã tắc ở đó
  const known = run ? run.counts.filter((c) => isNum(c.passed)) : []
  const lastKnown = known.length ? known[known.length - 1] : null
  const deadAt = run && !live && lastKnown && lastKnown.stage !== 'S0_generate' && lastKnown.passed === 0 ? lastKnown : null
  const deadQ = useAsync(deadAt ? () => getFunnelStats(runId, deadAt.stage) : null, [runId, deadAt?.stage])

  // mở phần chi tiết tầng (hoặc vào thẳng bằng đường dẫn có ?tab=…) thì cuộn tới nó, vì phần tóm tắt nằm phía trên
  const barRef = useRef(null)
  const loaded = !!run && (!(finalCount > 0) || !!finalQ.data || !!finalQ.error)
  const bodyReady = !!statsQ.data || !!pickQ.data || tab === 'alphas' // nội dung đủ cao rồi mới cuộn được tới đỉnh
  useEffect(() => { if (detail && loaded) barRef.current?.scrollIntoView({ block: 'start' }) }, [detail, loaded, bodyReady])

  const openAlpha = useCallback((id) => setParams({ alpha: id }, false), [setParams])
  const closeAlpha = useCallback(() => setParams({ alpha: '' }, false), [setParams])
  const toTrades = useCallback((id, st) => setParams({ alpha: '', sel: id, tab: 'trades', stage: tradeStageOf(st) || 'S1_backtest' }, false), [setParams])
  const closeDetail = () => setParams({ stage: '', tab: '', sel: '' }, false)
  const pickStage = (st) => (detail && st === stage ? closeDetail() : setParams({ stage: st, tab: st === 'S0_generate' && tab !== 'stats' ? 'stats' : tab }, false))
  const openFinal = () => setParams({ stage: 'FINAL', tab: 'alphas', sel: '' }, false)

  if (runQ.error && !run) return <><PageHead kicker="Phễu kiểm duyệt" title={`Lượt ${runId}`} /><MockBanner /><ErrorState title="Không tải được lượt chạy" error={runQ.error} onRetry={runQ.reload} /><p><Link to="/alpha/funnel" className="n-btn" style={{ marginTop: 10 }}>← Danh sách lượt</Link></p></>
  if (!run) return <Loading what="lượt chạy" />

  const strategies = run.strategies
  const deadIdx = deadAt ? STAGES.indexOf(deadAt.stage) : -1
  const stageCount = run.counts.find((c) => c.stage === stage)
  const stageIn = stageCount?.input ?? (deadIdx >= 0 && STAGES.indexOf(stage) > deadIdx ? 0 : null)
  const stageEmpty = stage !== 'S0_generate' && stageIn === 0
  const prevStage = STAGES[STAGES.indexOf(stage) - 1]
  const prevCount = run.counts.find((c) => c.stage === prevStage)
  const deadReasons = deadQ.data?.reject_reasons?.length ? deadQ.data.reject_reasons : (deadAt?.top_reject ? [deadAt.top_reject] : [])
  const finalPassed = isNum(run.counts[7].passed) ? run.counts[7].passed : (deadAt ? 0 : null)
  const tradesOk = stage !== 'S0_generate'
  const topAlphas = pickQ.data?.items || []
  const tradeAlpha = sel || topAlphas[0]?.alpha_id || ''
  const alphaOptions = [...new Map([...(sel ? [[sel, { alpha_id: sel }]] : []), ...topAlphas.map((a) => [a.alpha_id, a])]).values()]
  const jobLike = jobQ.job || (run.progress ? { job_id: run.job_id, created: run.created, started: run.started, progress: run.progress } : null)

  return (
    <>
      <PageHead kicker={<Link to="/alpha/funnel" className="n-back">← Tất cả lượt chạy</Link>} title={`Phễu · ${run.run_id}`}
        subtitle="Tóm tắt một lượt kiểm duyệt: số alpha còn lại sau từng tầng, lý do loại chính và kết quả FINAL. Bấm một tầng để xem chi tiết." />
      <MockBanner />
      <RunMeta run={run} />
      {(live || run.status === 'failed' || run.status === 'cancelled') && (
        <Panel title="Tiến độ lượt chạy" className="n-fn-prog">
          <JobPanel job={jobLike} status={jobQ.job ? jobQ.status : run.status} error={jobQ.job || !run.progress ? jobQ.error : null} onCancelled={runQ.reload} />
        </Panel>
      )}
      <div className="n-fs-stack" style={{ marginBottom: 12 }}>
        <Headline run={run} finalPassed={finalPassed} fin={finalQ.data} />
      </div>
      <Panel title="Phễu kiểm duyệt" meta={<span className="mono">{fmtCount(run.counts[0].passed)} alpha → {fmtCount(finalPassed)} FINAL</span>}>
        {deadAt && (
          <div className="n-fn-dead" role="status">
            <h3>{fmtCount(0)} alpha qua {stageShort(deadAt.stage)}</h3>
            <span className="n-note">Cả {fmtCount(deadAt.input)} alpha vào {stageShort(deadAt.stage)} đều bị loại, nên các tầng sau ({stageShort(STAGES[deadIdx + 1])} → FINAL) chưa có alpha nào và chưa chạy.</span>
            {deadReasons.length > 0 && (
              <ul aria-label="Lý do loại chính">
                {deadReasons.slice(0, 4).map((r) => <li key={r.code}>{r.label || r.code} <span className="mono muted">{r.code}</span> · <b className="mono">{fmtCount(r.count)}</b> alpha ({deadAt.input ? Math.round((r.count / deadAt.input) * 100) : 0}%)</li>)}
              </ul>
            )}
          </div>
        )}
        <FunnelChart counts={run.counts} selected={detail ? stage : null} onSelect={pickStage} tops={tops} running={live} deadAt={deadAt?.stage || null} />
      </Panel>

      <div style={{ marginTop: 12 }}>
        <FinalSummary run={run} finalPassed={finalPassed} q={finalQ} onOpen={openAlpha} onAll={openFinal} live={live} />
      </div>

      {detail && <>
      <div className="n-fn-stagebar" ref={barRef} style={{ scrollMarginTop: 8 }}>
        <h2><span className="code">{STAGE_META[stage].short}</span> {STAGE_META[stage].name}</h2>
        <div className="n-tabs" role="tablist" aria-label="Nội dung của tầng">
          {TABS.map((t) => {
            const dis = (t.value === 'trades' && !tradesOk) || (t.value === 'alphas' && stage === 'S0_generate')
            return (
              <button key={t.value} type="button" role="tab" aria-selected={tab === t.value} disabled={dis} title={dis ? 'Tầng này không có dữ liệu mục này' : undefined}
                className={tab === t.value ? 'on' : ''} onClick={() => setParams({ tab: t.value })}>{t.label}</button>
            )
          })}
        </div>
        <button type="button" className="n-btn sm n-fs-close" onClick={closeDetail}>Đóng chi tiết ✕</button>
      </div>

      <div key={`${stage}-${tab}`} role="tabpanel">
        {stageEmpty && <EmptyStage stage={stage} prev={prevCount ? { stage: prevStage, passed: prevCount.passed, input: prevCount.input } : null}
          reasons={prevCount && prevCount.stage === deadAt?.stage ? deadReasons : []} />}
        {!stageEmpty && tab === 'stats' && (
          statsQ.error && !stats ? <ErrorState title="Không tải được thống kê tầng" error={statsQ.error} onRetry={statsQ.reload} />
            : !stats ? <Loading what="thống kê tầng" /> : <StageStats stats={stats} stage={stage} onOpen={openAlpha} />
        )}
        {!stageEmpty && tab === 'alphas' && <AlphaTable runId={runId} stage={stage} strategies={strategies} selected={sel}
          onSelect={(id) => setParams({ sel: id })} onOpen={openAlpha} onTrades={(id) => toTrades(id, stage)} />}
        {!stageEmpty && tab === 'trades' && (
          <Panel title="Lệnh của alpha đang chọn" meta={
            <>
              <Segmented label="Tầng của danh sách lệnh" value={tStage} onChange={(st) => setParams({ stage: st })}
                options={TRADE_STAGES.map((st) => ({ value: st, label: stageShort(st) }))} />
              <label className="n-lbl" htmlFor="tr-alpha">Alpha</label>
              <select id="tr-alpha" className="n-sel n-fs-pick" value={tradeAlpha} onChange={(e) => setParams({ sel: e.target.value })}>
                {!alphaOptions.length && <option value="">{pickQ.loading ? 'Đang tải…' : 'Chưa có alpha'}</option>}
                {alphaOptions.map((a) => <option key={a.alpha_id} value={a.alpha_id}>{shortId(a.alpha_id)}{a.strategy ? ` · ${legLabel(a.strategy)}` : ''}</option>)}
              </select>
              {tradeAlpha && <button type="button" className="n-btn sm" onClick={() => openAlpha(tradeAlpha)}>Chi tiết alpha</button>}
            </>
          }>
            {!tradesOk ? <Empty title="Tầng này không có lệnh">Tầng sinh alpha chưa chạy backtest.</Empty>
              : !tradeAlpha ? (pickQ.loading ? <Loading what="danh sách alpha" /> : <Empty title="Chọn một alpha">Chọn alpha ở danh sách trên hoặc bấm "Lệnh →" ở tab Alpha để xem lệnh của nó ở tầng này.</Empty>)
                : <TradesView key={`${tradeAlpha}-${tStage}`} runId={runId} alphaId={tradeAlpha} stage={tStage} />}
          </Panel>
        )}
      </div>
      </>}

      {drawer && <AlphaDrawer key={drawer} runId={runId} alphaId={drawer} onClose={closeAlpha} onTrades={toTrades} />}
    </>
  )
}

export default function Funnel() {
  const { runId } = useParams()
  return runId ? <RunView key={runId} runId={decodeURIComponent(runId)} /> : <RunsPage />
}
