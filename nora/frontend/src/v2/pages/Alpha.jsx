import React, { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Field, ErrorBox, Empty, Spinner, Status } from '../components/ui'
import JobPanel from '../components/JobPanel'
import useJob from '../hooks/useJob'
import { useCatalog } from '../context/Catalog'
import { postBuild, postPublish, getAlphas } from '../api'
import { fmtNum, fmtPct, fmtSPct, signClass, fmtDateTime, isNum } from '../lib/format'

function StrategyCards({ catalog, value, onPick }) {
  return (
    <div className="n-tilegrid" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }} role="radiogroup" aria-label="Chiến lược">
      {catalog.map((c) => (
        <button key={c.id} type="button" role="radio" aria-checked={value === c.id} className={`n-card-sel ${value === c.id ? 'on' : ''}`} onClick={() => onPick(c.id)}>
          <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="id">{c.id}</span>
            <span className={`n-badge ${String(c.side).toLowerCase()}`}>{c.side}</span>
          </span>
          <span className="muted" style={{ fontSize: 11.5 }}>{c.family}</span>
          <span className="ds">{c.description}</span>
          <span className="mono" style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>
            {Object.entries(c.space || {}).map(([k, a]) => `${k}: [${a.join(', ')}]`).join(' · ')}
          </span>
        </button>
      ))}
    </div>
  )
}

const PHASE_LABEL = { dev1: 'Dev1 (tối ưu)', dev2_level: 'Dev2 · level', dev2_extreme: 'Dev2 · extreme', holdout_level: 'Holdout · level', holdout_extreme: 'Holdout · extreme' }

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
    <Panel title={hasHoldout ? 'Kiểm chứng dev2 / holdout' : 'Kiểm chứng dev2'} meta={
      <>
        {cand.accepted != null && <Status tone={cand.accepted ? 'ok' : 'bad'}>{cand.accepted ? '✓ Được nhận' : '✗ Bị loại'}</Status>}
        {top.dev2_pass != null && <Status tone={top.dev2_pass ? 'ok' : 'bad'}>{top.dev2_pass ? 'Qua cổng dev2' : 'Trượt cổng dev2'}</Status>}
        {cand.stability != null && <span>Độ ổn định (top-3 qua dev2) <b className="mono">{isNum(cand.stability) ? fmtNum(cand.stability) : String(cand.stability)}</b></span>}
        {book && book.holdout_pass != null && <Status tone={book.holdout_pass ? 'ok' : 'bad'}>{book.holdout_pass ? 'Holdout đạt' : 'Holdout không đạt'}</Status>}
      </>
    }>
      <div className="n-tblwrap">
        <table className="n-tbl">
          <thead><tr><th>Giai đoạn</th><th className="r">Lãi</th><th className="r">MDD</th><th className="r">Sharpe</th><th className="r">Lệnh</th><th className="r">Cặp dương</th></tr></thead>
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
function PublishBar({ jobId }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [done, setDone] = useState(null)
  async function publish() {
    const ok = window.confirm('Xuất bản sổ này sẽ THAY THẾ sổ đang xuất bản (alphas/book.json, và cấu hình testnet nếu có). Bạn có chắc chắn?')
    if (!ok) return
    setErr(null); setBusy(true)
    try { setDone(await postPublish(jobId)) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="n-sticky-actions">
      <button type="button" className="n-btn primary" onClick={publish} disabled={busy}>{busy ? <Spinner /> : null} Xuất bản sổ này</button>
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
    <div className="n-tblwrap">
      <table className="n-tbl">
        <thead>
          <tr><th>#</th>{keys.map((k) => <th key={k} className="r">{k}</th>)}<th className="r">Lãi dev1</th><th className="r">MDD</th><th className="r">Lệnh</th><th className="r">Cặp dương</th><th className="r">Sharpe</th><th className="r">Điểm</th><th>Đạt</th><th /></tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i}>
              <td className="num">{i + 1}</td>
              {keys.map((k) => <td key={k} className="r">{r.params?.[k] ?? '—'}</td>)}
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
  const [st, setSt] = useState({ loading: true, data: null, error: null })
  useEffect(() => {
    let dead = false
    getAlphas().then((data) => !dead && setSt({ loading: false, data, error: null }), (e) => !dead && setSt({ loading: false, data: null, error: e.message }))
    return () => { dead = true }
  }, [])
  if (st.loading) return <Empty title="Đang tải kho alpha"><Spinner /></Empty>
  if (st.error) return <ErrorBox>Không tải được kho alpha: {st.error}</ErrorBox>
  const { registry, book } = st.data || {}
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
                </div>
                <div className="n-stats" style={{ marginTop: 6 }}>
                  {Object.entries({ ...(a.position || {}), ...(a.signal_params || {}) }).slice(0, 8).map(([k, v]) => (
                    <div key={k}><span className="k">{k}</span><span className="v">{String(v)}</span></div>
                  ))}
                </div>
                {best && <p className="n-note" style={{ marginTop: 6 }}>Cấu hình tốt nhất khi sàng lọc: lãi <b className={`mono ${signClass(best.ret)}`}>{fmtSPct(best.ret, 1)}</b>, MDD <b className="mono">{fmtPct(best.mdd, 1)}</b>, {best.n} lệnh.</p>}
                {w && <p className="n-note">Cửa sổ: {w.start} → {w.end}{w.holdout ? ` · holdout từ ${w.holdout}` : ''}</p>}
              </div>
            )
          })}
        </div>
      </Panel>
      <Panel title="Sổ chiến lược (book)" meta={book ? <Status tone={bookTone}>{book.status === 'READY_FOR_TESTNET' ? '✓ ' : '✗ '}{book.status}</Status> : null}>
        {!book && <p className="n-note">Chưa có alphas/book.json.</p>}
        {book && (
          <>
            <p className="n-note">Tạo lúc {fmtDateTime(book.generated_at)}{book.windows ? ` · dữ liệu ${book.windows.start} → ${book.windows.end}` : ''}</p>
            <div className="n-tblwrap">
              <table className="n-tbl">
                <thead><tr><th>Chiến lược</th><th>Tham số</th></tr></thead>
                <tbody>
                  {(book.strategies || []).map((s) => (
                    <tr key={s.id}><td className="mono"><b>{s.id}</b></td>
                      <td className="mono" style={{ whiteSpace: 'normal', fontSize: 11.5 }}>{Object.entries(s.params || {}).map(([k, v]) => `${k}=${v}`).join(', ')}</td></tr>
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
  const { data: cat, loading, error } = useCatalog()
  const [sp, setSp] = useSearchParams()
  const nav = useNavigate()
  const jobId = sp.get('job') || ''
  const picked = sp.get('s') || ''
  const [n, setN] = useState(24)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const job = useJob(jobId)

  const patch = (o) => {
    const q = new URLSearchParams(sp)
    Object.entries(o).forEach(([k, v]) => (v ? q.set(k, v) : q.delete(k)))
    setSp(q)
  }
  const strat = cat?.catalog.find((c) => c.id === picked)

  async function run() {
    if (!strat) return setErr('Chọn một chiến lược.')
    setErr(null); setBusy(true)
    try { const r = await postBuild({ only: [strat.id], n: Number(n) }); patch({ job: r.job_id }) } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const send = (id, params) => nav('/backtest', { state: { prefill: { strategies: [{ id, params }] } } })

  const result = job.job?.result
  const sid = strat?.id || Object.keys(result?.stage_a || {})[0]
  const rows = result?.stage_a?.[sid] || []
  const cand = result?.candidates?.[sid]

  return (
    <>
      <PageHead kicker="Bước đầu của vòng kiểm chứng" title="Alpha · Hiệu chỉnh tham số"
        subtitle="Chọn một chiến lược có sẵn, thử n cấu hình tham số trên dev1, xếp hạng theo điểm, rồi gửi cấu hình tốt sang Backtest." />
      {error && <ErrorBox>Không tải được danh mục chiến lược: {error}</ErrorBox>}
      {loading && !cat && <Empty title="Đang tải danh mục"><Spinner /></Empty>}
      {cat && (
        <Panel title="Chiến lược" meta={<span>{cat.catalog.length} chiến lược</span>}>
          <StrategyCards catalog={cat.catalog} value={picked} onPick={(id) => patch({ s: id })} />
          <div className="n-sticky-actions">
            <div style={{ width: 170 }}><Field id="al-n" label="Số cấu hình thử (n)"><input id="al-n" type="number" min="1" max="200" className="n-in" value={n} onChange={(e) => setN(e.target.value)} /></Field></div>
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
              <Panel title={`Xếp hạng cấu hình · ${sid}`} meta={<span>{rows.length} cấu hình · xếp theo điểm</span>}>
                <RankTable id={sid} rows={rows} space={cat?.catalog.find((c) => c.id === sid)?.space} onSend={send} />
              </Panel>
              {cand && <CandidateSummary cand={cand} book={result?.book} />}
              {result?.book && <PublishBar jobId={jobId} />}
            </>
          ) : <Empty title="Chưa có bảng xếp hạng">Job xong nhưng backend chưa trả <code>result.stage_a</code>.</Empty>)}
        </div>
      )}

      <h2 style={{ fontSize: 15, margin: '22px 0 10px' }}>Kho alpha</h2>
      <AlphaVault />
    </>
  )
}
