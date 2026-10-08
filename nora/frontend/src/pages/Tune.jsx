import React, { useEffect, useState } from 'react'
import '../styles/alpha.css'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Field, ErrorBox, Empty, Spinner, Status, Loading, ErrorState } from '../components/ui'
import Term from '../components/ui/Term'
import { paramHeader, paramLabel, fmtParam, fmtParamFull } from '../lib/params'
import { stopFillText } from '../lib/stopfill'
import JobPanel from '../components/jobs/JobPanel'
import { CUSTOM_BADGE, CUSTOM_REASON } from '../lib/modes'
import useJob from '../hooks/useJob'
import { useCatalog } from '../context/Catalog'
import { useMeta } from '../meta/MetaProvider'
import { postBuild, postPublish, getAlphas } from '../api'
import { fmtNum, fmtPct, fmtSPct, signClass, fmtDateTime, isNum, fullDate, fmtFrame } from '../lib/format'
import { legLabel } from '../lib/strategyLabel'
import EngineWarning, { EngineStamp } from '../components/optimize/EngineWarning'

function StrategyCards({ catalog, value, onPick }) {
  return (
    <div className="n-tilegrid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }} role="radiogroup" aria-label="Chiến lược">
      {catalog.map((c) => (
        <button key={c.id} type="button" role="radio" aria-checked={value === c.id} className={`n-card-sel ${value === c.id ? 'on' : ''}`} onClick={() => onPick(c.id)}>
          <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="id" title={c.id}>{legLabel(c.id)}</span>
          </span>
          <span className="muted" style={{ fontSize: 11.5 }}>{c.family}</span>
          <span className="ds">{c.description}</span>
          <span className="n-pspace">
            {Object.entries(c.space || {}).map(([k, a]) => (
              <div key={k} title={k}><b>{paramHeader(k)}:</b><span>{a.map((x) => fmtParam(k, x)).join(' · ')}</span></div>
            ))}
          </span>
        </button>
      ))}
    </div>
  )
}

const PHASE_LABEL = {
  dev1: <><Term k="dev1">Dev1</Term> (tối ưu)</>,
  dev2_level: <><Term k="dev2">Dev2</Term> · {stopFillText('level')}</>, dev2_extreme: <><Term k="dev2">Dev2</Term> · {stopFillText('extreme')}</>,
  holdout_level: <><Term k="holdout">Holdout</Term> · {stopFillText('level')}</>, holdout_extreme: <><Term k="holdout">Holdout</Term> · {stopFillText('extreme')}</>,
}

/** Kiểm chứng của một chiến lược: số liệu top-1 ở `candidates[id].dev1_top[0]` (dev1, dev2 level/extreme) + holdout của cả sổ (`book.final`). */
function CandidateSummary({ cand, book }) {
  if (!cand || typeof cand !== 'object') return null
  const top = (cand.dev1_top || [])[0] || {}
  const final = book?.final || {}
  const rows = [
    ['dev1', top.dev1], ['dev2_level', top.dev2_level], ['dev2_extreme', top.dev2_extreme],
    ['holdout_level', final.holdout_level], ['holdout_extreme', final.holdout_extreme],
  ].filter(([, m]) => m && typeof m === 'object')
  const hasHoldout = rows.some(([k]) => k.startsWith('holdout'))
  return (
    <Panel title={hasHoldout ? <>Kiểm chứng <Term k="dev2">dev2</Term> / <Term k="holdout">holdout</Term></> : <>Kiểm chứng <Term k="dev2">dev2</Term></>} meta={
      <>
        {cand.accepted != null && <Status tone={cand.accepted ? 'ok' : 'bad'}>{cand.accepted ? '✓ Được nhận' : '✗ Bị loại'}</Status>}
        {top.dev2_pass != null && <Status tone={top.dev2_pass ? 'ok' : 'bad'}>{top.dev2_pass ? 'Qua cổng dev2' : 'Trượt cổng dev2'}</Status>}
        {cand.stability != null && <span>Độ ổn định (top-3 qua dev2) <b className="mono">{isNum(cand.stability) ? fmtNum(cand.stability) : String(cand.stability)}</b></span>}
        {book && book.holdout_pass != null && <Status tone={book.holdout_pass ? 'ok' : 'bad'}>{book.holdout_pass ? 'Holdout đạt' : 'Holdout không đạt'}</Status>}
      </>
    }>
      <div className="n-tblwrap">
        <table className="n-tbl">
          <thead><tr><th>Giai đoạn</th><th className="r">Lãi</th><th className="r"><Term k="mdd">MDD</Term></th><th className="r"><Term k="sharpe">Sharpe</Term></th><th className="r">Lệnh</th><th className="r">Cặp dương</th></tr></thead>
          <tbody>
            {rows.map(([k, m]) => (
              <tr key={k}><td>{PHASE_LABEL[k] || k}</td>
                <td className={`r ${signClass(m.ret_pct)}`}>{fmtSPct(m.ret_pct)}</td><td className="r">{fmtPct(m.mdd_pct)}</td>
                <td className="r">{fmtNum(m.sharpe)}</td><td className="r">{m.trades ?? '—'}</td><td className="r">{m.symbols_positive ?? '—'}</td></tr>
            ))}
            {!rows.length && <tr><td colSpan={6} className="muted">Chưa có số liệu dev2/holdout cho chiến lược này.</td></tr>}
          </tbody>
        </table>
      </div>
      {book && <p className="n-note" style={{ marginTop: 6 }}>Holdout là kết quả của cả sổ vừa dựng, chấm đúng một lần và không dùng để chọn tham số.</p>}
    </Panel>
  )
}

/** Xuất bản sổ vừa dựng (chép sang alphas/): có hộp xác nhận vì thay sổ đang dùng. */
function PublishBar({ jobId, blocked }) {
  const meta = useMeta()
  const bookPath = meta?.paths?.book || 'data/alpha/book.json'
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [done, setDone] = useState(null)
  async function publish() {
    const ok = window.confirm(`Xuất bản sổ này sẽ THAY THẾ sổ đang xuất bản (${bookPath}, và cấu hình testnet nếu có). Bạn có chắc chắn?`)
    if (!ok) return
    setErr(null); setBusy(true)
    try { setDone(await postPublish(jobId)) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="n-sticky-actions">
      <button type="button" className="n-btn primary" onClick={publish} disabled={busy || blocked} title={blocked ? CUSTOM_REASON : undefined}>{busy ? <Spinner /> : null} Xuất bản sổ này</button>
      {blocked && <span className="n-custom-badge" role="status">⚠ {CUSTOM_BADGE}</span>}
      <span className="n-note" style={{ alignSelf: 'center' }}>Sổ vừa dựng chỉ nằm trong job này; chỉ khi xuất bản mới thay sổ hiện hành ở mục Kho alpha.</span>
      {done && <Status tone="ok">Đã xuất bản · {done.status}{done.testnet_removed ? ' · đã xoá cấu hình testnet cũ' : ''}</Status>}
      <ErrorBox>{err}</ErrorBox>
    </div>
  )
}

function RankTable({ id, rows, space, onSend }) {
  const used = [...new Set(rows.flatMap((r) => Object.keys(r.params || {})))]
  const keys = used.length ? used : Object.keys(space || {})
  const sorted = [...rows].sort((a, b) => (b.score ?? -1e9) - (a.score ?? -1e9))
  return (
    <div className="n-tblwrap long">
      <table className="n-tbl">
        <thead>
          <tr><th>#</th>{keys.map((k) => <th key={k} className="r" title={k}>{paramHeader(k)}</th>)}<th className="r">Lãi <Term k="dev1">dev1</Term></th><th className="r"><Term k="mdd">MDD</Term></th><th className="r">Lệnh</th><th className="r">Cặp dương</th><th className="r"><Term k="sharpe">Sharpe</Term></th><th className="r"><Term k="score">Điểm</Term></th><th>Đạt</th><th /></tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i}>
              <td className="num">{i + 1}</td>
              {keys.map((k) => <td key={k} className="r" title={`${k} = ${r.params?.[k] ?? '—'}`}>{r.params?.[k] != null ? fmtParam(k, r.params[k]) : '—'}</td>)}
              <td className={`r ${signClass(r.dev1?.ret_pct)}`}>{fmtSPct(r.dev1?.ret_pct)}</td>
              <td className="r">{fmtPct(r.dev1?.mdd_pct)}</td>
              <td className="r">{r.dev1?.trades ?? '—'}</td>
              <td className="r">{r.dev1?.symbols_positive ?? '—'}</td>
              <td className="r">{fmtNum(r.dev1?.sharpe)}</td>
              <td className="r"><b>{fmtNum(r.score)}</b></td>
              <td><Status tone={r.passed ? 'ok' : ''}>{r.passed ? '✓ Đạt' : '✗ Chưa'}</Status></td>
              <td><button type="button" className="n-btn sm" onClick={() => onSend(id, r.params)}>Gửi sang Backtest →</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AlphaVault() {
  const meta = useMeta()
  const bookPath = meta?.paths?.book || 'data/alpha/book.json'
  const [st, setSt] = useState({ loading: true, data: null, error: null })
  const [tryN, setTry] = useState(0)
  useEffect(() => {
    let dead = false
    setSt((x) => ({ ...x, loading: true, error: null }))
    getAlphas().then((data) => !dead && setSt({ loading: false, data, error: null }), (e) => !dead && setSt({ loading: false, data: null, error: e.message }))
    return () => { dead = true }
  }, [tryN])
  if (st.loading) return <Loading what="kho alpha" />
  if (st.error) return <ErrorState title="Không tải được kho alpha" error={st.error} onRetry={() => setTry((n) => n + 1)} />
  const { registry, book, engine, registry_status: regStatus } = st.data || {}
  const statusOf = Object.fromEntries((regStatus || []).map((r) => [r.alpha_id, r]))   // trạng thái + nguồn gốc do backend tính (registry_provenance)
  const alphas = registry?.alphas || []
  const bookTone = book?.status === 'READY_FOR_TESTNET' ? 'ok' : book?.status === 'HOLDOUT_FAILED' ? 'bad' : 'warn'
  return (
    <div className="n-grid g-2">
      <Panel title="Alpha đơn tài sản (registry)" meta={<span>{alphas.length} alpha{registry?.generated_at ? ` · cập nhật ${fmtDateTime(registry.generated_at)}` : ''}</span>}>
        {!alphas.length && <p className="n-note">Chưa có alpha nào vượt cổng. Chạy tối ưu tham số rồi kiểm chứng để đưa vào kho.</p>}
        <div style={{ display: 'grid', gap: 10 }}>
          {alphas.map((a) => {
            const best = a.evidence?.screen?.best?.[0]
            const w = a.evidence?.windows
            return (
              <div className="n-strat on" key={a.alpha_id}>
                <div className="n-strat-h">
                  <span className="id">{a.alpha_id}</span>
                  <span className={`n-badge ${String(a.side).toLowerCase()}`}>{a.side}</span>
                  <span className="muted">{a.family} · {a.market}</span>
                  {(() => {
                    const rs = statusOf[a.alpha_id] || {}
                    return rs.status
                      ? <Status tone={rs.status === 'retired' ? 'bad' : 'ok'}>{rs.status === 'retired' ? '✗ ' : '✓ '}{rs.status}</Status>
                      : <span className="n-na muted" title={rs.status_note || undefined}>trạng thái —</span>
                  })()}
                </div>
                {statusOf[a.alpha_id] && (
                  <p className="n-note" style={{ marginTop: 4 }}>
                    {statusOf[a.alpha_id].status_label ? <b>{statusOf[a.alpha_id].status_label}</b> : null}
                    {statusOf[a.alpha_id].status_note ? <>{statusOf[a.alpha_id].status_label ? ': ' : ''}{statusOf[a.alpha_id].status_note}</> : null}
                    {statusOf[a.alpha_id].checked_at ? <span className="muted"> · kiểm lại {fmtDateTime(statusOf[a.alpha_id].checked_at)}</span> : null}
                    <br /><span className="muted">Nguồn gốc: {statusOf[a.alpha_id].provenance}</span>
                  </p>
                )}
                <div className="n-stats" style={{ marginTop: 6 }}>
                  {Object.entries({ ...(a.position || {}), ...(a.signal_params || {}) }).slice(0, 8).map(([k, v]) => (
                    <div key={k} title={k}><span className="k">{paramLabel(k)}</span><span className="v">{fmtParamFull(k, v)}</span></div>
                  ))}
                </div>
                {best && <p className="n-note" style={{ marginTop: 6 }}>Cấu hình tốt nhất khi sàng lọc: lãi <b className={`mono ${signClass(best.ret)}`}>{fmtSPct(best.ret, 1)}</b>, MDD <b className="mono">{fmtPct(best.mdd, 1)}</b>, {best.n} lệnh.</p>}
                {w && <p className="n-note">Cửa sổ: {fullDate(w.start)} → {fullDate(w.end)}{w.holdout ? <> · <Term k="holdout">holdout</Term> từ {fullDate(w.holdout)}</> : ''}</p>}
              </div>
            )
          })}
        </div>
      </Panel>
      <Panel title="Sổ chiến lược (book)" meta={book ? <Status tone={bookTone}>{book.status === 'READY_FOR_TESTNET' ? '✓ ' : '✗ '}{book.status}</Status> : null}>
        {!book && <p className="n-note">Chưa có {bookPath}.</p>}
        <EngineWarning status={engine?.main} label={`chính (${meta?.paths?.book || 'alpha/book.json'})`} />
        <EngineWarning status={engine?.explore} label={`thử nghiệm (${meta?.paths?.explore_book || 'alpha/explore/book.json'})`} />
        {book && (
          <>
            <EngineStamp book={book} />
            <p className="n-note">Tạo lúc {fmtDateTime(book.generated_at)}{book.windows ? ` · dữ liệu ${fullDate(book.windows.start)} → ${fullDate(book.windows.end)}` : ''}</p>
            <div className="n-tblwrap">
              <table className="n-tbl">
                <thead><tr><th>Chiến lược</th><th>Tham số</th></tr></thead>
                <tbody>
                  {(book.strategies || []).map((s) => (
                    <tr key={s.id}><td title={s.id}><b>{legLabel(s.id)}</b></td>
                      <td style={{ whiteSpace: 'normal', fontSize: 11.5 }}>
                        <span className="n-plist">{Object.entries(s.params || {}).map(([k, v]) => <span key={k} title={k}><b>{paramLabel(k)}</b>{fmtParamFull(k, v)}</span>)}</span>
                      </td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Panel>
    </div>
  )
}

export default function Alpha() {
  const { data: cat, loading, error, reload } = useCatalog()
  const meta = useMeta()
  const [sp, setSp] = useSearchParams()
  const nav = useNavigate()
  const jobId = sp.get('build') || sp.get('job') || ''   // ?build=<id> (link từ Lịch sử chạy); ?job= là tên cũ
  const picked = sp.get('s') || ''
  const [n, setN] = useState(24)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const frames = meta?.frames?.funnel || meta?.frames?.all || ['15m', '1h', '4h']
  const [timeframe, setTimeframe] = useState(frames[0] || '15m')
  const job = useJob(jobId)

  const patch = (o) => {
    const q = new URLSearchParams(sp)
    if ('build' in o) q.delete('job')
    Object.entries(o).forEach(([k, v]) => (v ? q.set(k, v) : q.delete(k)))
    setSp(q)
  }
  const strat = cat?.catalog.find((c) => c.id === picked)

  async function run() {
    if (!strat) return setErr('Chọn một chiến lược.')
    setErr(null); setBusy(true)
    try { const r = await postBuild({ only: [strat.id], n: Number(n), timeframe }); patch({ build: r.job_id }) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const send = (id, params) => nav('/backtest', { state: { prefill: { strategies: [{ id, params }] } } })

  const result = job.job?.result
  const sid = strat?.id || Object.keys(result?.stage_a || {})[0]
  const rows = result?.stage_a?.[sid] || []
  const cand = result?.candidates?.[sid]
  const counts = result?.stage_a_counts?.[sid]   // build lớn: result.stage_a chỉ có top-K, đủ số đếm ở đây (toàn bộ hàng: GET /book/jobs/{id}/stage_a)

  return (
    <>
      <PageHead kicker="Bước đầu của vòng kiểm chứng" title="Alpha · Hiệu chỉnh tham số"
        subtitle={<>Chọn một chiến lược có sẵn, thử n cấu hình tham số trên <Term k="dev1">dev1</Term>, xếp hạng theo <Term k="score">điểm</Term>, rồi gửi cấu hình tốt sang Backtest.</>} />
      {error && <ErrorState title="Không tải được danh mục chiến lược" error={error} onRetry={reload} />}
      {loading && !cat && <Loading what="danh mục chiến lược" />}
      {cat && (
        <Panel title="Chiến lược" meta={<span>{cat.catalog.length} chiến lược</span>}>
          <StrategyCards catalog={cat.catalog} value={picked} onPick={(id) => patch({ s: id })} />
          <div className="n-sticky-actions">
            <div style={{ width: 170 }}><Field id="al-n" label="Số cấu hình thử (n)"><input id="al-n" type="number" min="1" max="200" className="n-in" value={n} onChange={(e) => setN(e.target.value)} /></Field></div>
            <div style={{ width: 150 }}><Field id="al-tf" label="Khung chạy">
              <select id="al-tf" className="n-sel" value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
                {frames.map((f) => <option key={f} value={f}>{fmtFrame(f)}</option>)}
              </select></Field></div>
            <button type="button" className="n-btn primary" style={{ alignSelf: 'flex-end' }} onClick={run} disabled={busy || !strat}>{busy ? <Spinner /> : null} Chạy tối ưu</button>
            {!strat && <span className="n-note" style={{ alignSelf: 'flex-end' }}>Chọn một chiến lược để bắt đầu.</span>}
            <ErrorBox>{err}</ErrorBox>
          </div>
        </Panel>
      )}

      {jobId && (
        <div style={{ display: 'grid', gap: 12, marginTop: 12 }}>
          <Panel title="Tiến trình tối ưu" meta={<span className="mono">{jobId}</span>}><JobPanel job={job.job} status={job.status} error={job.error} /></Panel>
          {job.status === 'done' && (rows.length ? (
            <>
              <Panel title={`Xếp hạng cấu hình · ${legLabel(sid)}`} meta={<span>{counts?.tried > rows.length ? `Top ${rows.length}/${counts.tried.toLocaleString('vi-VN')} cấu hình` : `${rows.length} cấu hình`} · xếp theo điểm</span>}>
                <RankTable id={sid} rows={rows} space={cat?.catalog.find((c) => c.id === sid)?.space} onSend={send} />
              </Panel>
              {cand && <CandidateSummary cand={cand} book={result?.book} />}
              {result?.book && <PublishBar jobId={jobId} blocked={!!job.job?.custom_gates || job.job?.promotable === false} />}
            </>
          ) : <Empty title="Chưa có bảng xếp hạng">Job xong nhưng backend chưa trả <code>result.stage_a</code>.</Empty>)}
        </div>
      )}

      <h2 style={{ fontSize: 15, margin: '22px 0 10px' }}>Kho alpha</h2>
      <AlphaVault />
    </>
  )
}
