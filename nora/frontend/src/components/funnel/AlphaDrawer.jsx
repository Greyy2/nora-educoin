import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Panel, Segmented, Status, Loading, ErrorState, ErrorBox, Spinner } from '../ui'
import Term from '../Term'
import McResult from '../McResult'
import AreaLine from '../charts/AreaLine'
import TradesView from './TradesView'
import { ParamList, AlphaStatus, StrategyName } from './parts'
import useAsync from '../../hooks/useAsync'
import { getFunnelAlpha, postFunnelPromote } from '../../api'
import { STAGE_META, STAGES, METRICS, stageName, stageShort, stageHasTrades, fmtMetric, metricLabel } from '../../lib/funnel'
import { fmtNum, fmtPct, fmtSPct, signClass, isNum } from '../../lib/format'

const ICON = { pass: '✓', fail: '✗', none: '–' }

function Journey({ d }) {
  return (
    <ol className="n-jr" aria-label="Hành trình qua các tầng">
      {d.stages.map((s) => (
        <li key={s.stage} className={s.status}>
          <span className="ic" aria-hidden="true">{ICON[s.status]}</span>
          <span className="tx">
            <b title={STAGE_META[s.stage]?.rule}>{stageShort(s.stage)} · {stageName(s.stage)}</b>
            <span className="sr-only">{s.status === 'pass' ? 'Qua' : s.status === 'fail' ? 'Bị loại' : 'Chưa tới'}</span>
            {s.status === 'fail' && <span className="why">{s.msg || s.code}</span>}
            {s.status === 'none' && <span className="muted">chưa tới</span>}
          </span>
        </li>
      ))}
    </ol>
  )
}

function MetricMatrix({ d }) {
  const cols = d.stages.filter((s) => s.metrics)
  const order = Object.keys(METRICS)
  // chỉ hiện chỉ số đã có nhãn và là giá trị đơn (bỏ khoá thô/đối tượng lồng như by_symbol, fold_detail, sr_daily, skew, kurt)
  const scalar = (v) => v == null || ['number', 'string', 'boolean'].includes(typeof v)
  const keys = [...new Set(cols.flatMap((s) => Object.keys(s.metrics)))].filter((k) => METRICS[k] && cols.every((s) => scalar(s.metrics[k]))).sort((a, b) => {
    const ia = order.indexOf(a); const ib = order.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
  if (!cols.length) return <p className="n-note">Chưa có chỉ số theo tầng.</p>
  return (
    <div className="n-tblwrap">
      <table className="n-tbl">
        <thead><tr><th>Chỉ số</th>{cols.map((s) => <th key={s.stage} className="r" title={stageName(s.stage)}>{stageShort(s.stage)} <span className={s.status === 'fail' ? 'neg' : s.status === 'pass' ? 'pos' : ''}>{ICON[s.status]}</span></th>)}</tr></thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td>{METRICS[k]?.term ? <Term k={METRICS[k].term}>{metricLabel(k)}</Term> : metricLabel(k)}</td>
              {cols.map((s) => {
                const v = s.metrics[k]
                return <td key={s.stage} className={`r ${METRICS[k]?.tone && isNum(v) ? signClass(v) : ''}`}>{v == null ? <span className="muted">·</span> : fmtMetric(k, v)}</td>
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function NavSection({ d }) {
  const stages = STAGES.filter((s) => d.nav[s])
  const [st, setSt] = useState(stages[0] || null)
  const cur = d.nav[st] ? st : stages[0]
  if (!cur) return <p className="n-note">Chưa có đường NAV cho alpha này.</p>
  const n = d.nav[cur]
  return (
    <>
      <div className="n-fn-tools" style={{ marginBottom: 6 }}>
        <Segmented label="Tầng của đường NAV" value={cur} onChange={setSt} options={stages.map((s) => ({ value: s, label: `${stageShort(s)} · ${stageName(s)}` }))} />
        <span className="n-note mono">{n.values.length} ngày · {fmtNum(n.values[0], 0)} → {fmtNum(n.values[n.values.length - 1], 0)} USDT ({fmtSPct((n.values[n.values.length - 1] / n.values[0] - 1) * 100, 1)})</span>
      </div>
      <AreaLine key={cur} dates={n.dates} series={[{ key: 'nav', label: 'NAV (USDT)', values: n.values, color: 'var(--n-blue)', area: true }]} height={220}
        valueFormat={(v) => fmtNum(v, 0)} label={`Đường NAV ở tầng ${stageName(cur)}`} />
    </>
  )
}

function ScalePanel({ d }) {
  const s = d.final_scale
  if (!isNum(s) && !d.scale_search) return null
  const tone = !isNum(s) ? '' : s < 0.2 ? 'neg' : s < 0.5 ? 'warn' : 'pos'
  return (
    <Panel title={<><Term k="scale_s">Khối lượng sống sót (s)</Term></>} meta={d.stages.find((x) => x.stage === 'S5_sizing')?.status === 'fail' ? <Status tone="bad">✗ s dưới 0,2</Status> : null}>
      <div className="n-scale">
        <div>
          <div className={`n-scale-v mono ${tone}`}>{isNum(s) ? fmtNum(s, 2) : '—'}</div>
          <div className="n-note">≈ {isNum(s) ? fmtPct(s * 100, 0) : '—'} cỡ lệnh gốc</div>
        </div>
        <div className="n-scale-bar" role="img" aria-label={`s = ${isNum(s) ? fmtNum(s, 2) : 'chưa có'} trên thang 0 đến 1, ngưỡng loại 0,2`}>
          <div className="trk"><i className={tone} style={{ width: `${Math.max(0, Math.min(1, s || 0)) * 100}%` }} /><span className="mk" style={{ left: '20%' }} title="Ngưỡng loại s = 0,2" /></div>
          <div className="sc mono"><span>0</span><span style={{ marginLeft: '12%' }}>0,2 (ngưỡng loại)</span><span style={{ marginLeft: 'auto' }}>1</span></div>
        </div>
      </div>
      {d.scale_search?.length > 0 && (
        <details className="n-details" open>
          <summary>Các bước tìm nhị phân s ({d.scale_search.length})</summary>
          <div className="n-tblwrap">
            <table className="n-tbl">
              <thead><tr><th className="r">s thử</th><th className="r">P(MDD ≥ 30%)</th><th className="r">MDD kịch bản cực xấu</th><th>Qua điều kiện S4</th></tr></thead>
              <tbody>
                {[...d.scale_search].sort((a, b) => b.s - a.s).map((r) => (
                  <tr key={r.s}><td className="r">{fmtNum(r.s, 2)}</td><td className="r">{fmtPct(r.p_mdd_ge_30, 1)}</td><td className="r">{fmtPct(r.stress_max_mdd, 1)}</td>
                    <td>{r.measured === false ? <span title={r.note_vi}><Status tone="warn">Không đo được</Status></span> : r.passed ? <Status tone="ok">✓ Đạt</Status> : <Status tone="bad">✗ Không đạt</Status>}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="n-note">Tìm nhị phân trên chuỗi ngày nhân s; kết quả cuối được xác nhận lại bằng backtest + walk-forward + Monte Carlo thật ở s.</p>
        </details>
      )}
    </Panel>
  )
}

/** Monte Carlo rút gọn khi payload không đúng dạng của McResult (thiếu quạt/tóm tắt). */
function CompactMc({ mc }) {
  const sm = mc.summary || mc
  const entries = Object.entries(sm).filter(([, v]) => isNum(v))
  const stress = mc.stress || mc.stress_scenarios || []
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div className="n-tiles" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', margin: 0 }}>
        {entries.map(([k, v]) => <div className="n-tile" key={k}><div className="l">{METRICS[k]?.label || k}</div><div className="v">{fmtMetric(k, v)}</div></div>)}
      </div>
      {stress.length > 0 && (
        <div className="n-tblwrap"><table className="n-tbl"><thead><tr><th>Kịch bản</th><th className="r">MDD</th><th>Kết quả</th></tr></thead>
          <tbody>{stress.map((r, i) => <tr key={r.name || i}><td>{r.label_vi || r.name}</td><td className="r">{fmtPct(r.mdd_pct, 1)}</td><td>{r.passed ? <Status tone="ok">✓ Đạt</Status> : <Status tone="bad">✗ Không đạt</Status>}</td></tr>)}</tbody></table></div>
      )}
    </div>
  )
}

function PromoteBar({ runId, d, onDone }) {
  const [step, setStep] = useState('idle') // idle | confirm | busy | done
  const [err, setErr] = useState(null)
  const [res, setRes] = useState(null)
  async function go() {
    setStep('busy'); setErr(null)
    try { setRes(await postFunnelPromote(runId, d.alpha_id)); setStep('done'); onDone && onDone() } catch (e) { setErr(`${e.status ? `Lỗi ${e.status}: ` : ''}${e.message}`); setStep('confirm') }
  }
  if (d.promoted && step === 'idle') return <div className="n-promote"><Status tone="ok">✓ Đã có trong kho alpha</Status></div>
  return (
    <div className="n-promote" role="region" aria-label="Đưa vào kho alpha">
      {step === 'idle' && (
        <>
          <button type="button" className="n-btn primary" onClick={() => setStep('confirm')}>Đưa vào kho alpha</button>
          <span className="n-note">Alpha FINAL đủ điều kiện testnet với <Term k="scale_s">s</Term> = <b className="mono">{fmtNum(d.final_scale, 2)}</b>.</span>
        </>
      )}
      {(step === 'confirm' || step === 'busy') && (
        <div className="n-confirm">
          <p><b>Xác nhận đưa alpha {d.alpha_id.slice(0, 8)} vào kho alpha?</b></p>
          <p className="n-note">Việc này ghi alpha vào <span className="mono">data/alphas/registry.json</span> kèm hệ số s = {fmtNum(d.final_scale, 2)} và toàn bộ bằng chứng, đồng thời tạo cấu hình testnet. Chưa có lệnh thật nào được đặt.</p>
          <ErrorBox>{err}</ErrorBox>
          <div className="n-sticky-actions" style={{ marginTop: 8 }}>
            <button type="button" className="n-btn primary" onClick={go} disabled={step === 'busy'}>{step === 'busy' ? <Spinner /> : null} Xác nhận đưa vào kho</button>
            <button type="button" className="n-btn" onClick={() => { setStep('idle'); setErr(null) }} disabled={step === 'busy'}>Huỷ</button>
          </div>
        </div>
      )}
      {step === 'done' && (
        <div>
          <Status tone="ok">✓ Đã đưa vào kho alpha</Status>
          <p className="n-note" style={{ marginTop: 6 }}>{res?.registry_path ? <>Đã ghi <span className="mono">{res.registry_path}</span>{res.testnet_config ? <> và <span className="mono">{typeof res.testnet_config === 'string' ? res.testnet_config : `testnet/funnel__${d.strategy}__${d.alpha_id}.json`}</span></> : null}{res.registry_alpha_id ? <> (mục <span className="mono">{res.registry_alpha_id}</span>)</> : null}.</> : 'Đã ghi vào kho alpha và cấu hình testnet.'}</p>
        </div>
      )}
    </div>
  )
}

export default function AlphaDrawer({ runId, alphaId, onClose, onTrades }) {
  const q = useAsync(() => getFunnelAlpha(runId, alphaId), [runId, alphaId])
  const d = q.data
  const [tradeStage, setTradeStage] = useState('')
  const opener = useRef(null)
  const box = useRef(null)
  useEffect(() => {
    opener.current = document.activeElement
    box.current?.focus()
    const key = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); try { opener.current?.focus?.() } catch (e) { /* bỏ qua */ } }
  }, [onClose])
  useEffect(() => { setTradeStage('') }, [alphaId])
  // tầng có danh sách lệnh: theo `stored_trades` của backend nếu có (S2/S4 không sinh lệnh riêng); ưu tiên tầng đã lưu sẵn
  const tStages = useMemo(() => {
    if (!d) return []
    const st = d.stored_trades
    return d.stages.filter((s) => s.status !== 'none' && stageHasTrades(s.stage) && (!st || s.stage in st)).map((s) => s.stage)
  }, [d])
  const ts = tradeStage || tStages.find((s) => d?.stored_trades?.[s]) || tStages[0] || ''
  const mc = d?.mc
  const mcFits = mc && mc.fan?.p50?.length > 1 && mc.summary
  return (
    <div className="n-drawer-wrap">
      <div className="n-drawer-bg" onClick={onClose} aria-hidden="true" />
      <aside className="n-drawer" role="dialog" aria-modal="true" aria-label={`Chi tiết alpha ${alphaId}`} tabIndex={-1} ref={box}>
        <header className="n-drawer-h">
          <div style={{ minWidth: 0 }}>
            <div className="kick muted">Chi tiết alpha</div>
            <h2 className="mono" title={alphaId}>{alphaId}</h2>
          </div>
          <button type="button" className="n-btn" onClick={onClose} aria-label="Đóng chi tiết">Đóng ✕</button>
        </header>
        <div className="n-drawer-b">
          {q.error && <ErrorState title="Không tải được chi tiết alpha" error={q.error} onRetry={q.reload} />}
          {!q.error && !d && <Loading what="chi tiết alpha" />}
          {d && (
            <div style={{ display: 'grid', gap: 12 }}>
              <div className="n-drawer-id">
                <StrategyName id={d.strategy} />
                <AlphaStatus a={d} />
                {isNum(d.final_scale) && <span>s = <b className="mono">{fmtNum(d.final_scale, 2)}</b></span>}
                <div className="params"><ParamList params={d.params} /></div>
              </div>
              <Panel title="Hành trình qua các tầng"><Journey d={d} /></Panel>
              <Panel title="Chỉ số từng tầng"><MetricMatrix d={d} /></Panel>
              <Panel title="NAV theo tầng"><NavSection d={d} /></Panel>
              <Panel title="Lệnh theo tầng / fold" meta={ts ? <button type="button" className="n-btn sm" onClick={() => onTrades(alphaId, ts)}>Mở ở tab Lệnh →</button> : null}>
                {!tStages.length ? <p className="n-note">Alpha chưa tới tầng nào có danh sách lệnh.</p> : (
                  <>
                    <div style={{ marginBottom: 8 }}><Segmented label="Tầng của danh sách lệnh" value={ts} onChange={setTradeStage} options={tStages.map((s) => ({ value: s, label: stageShort(s) }))} /></div>
                    <TradesView key={`${alphaId}-${ts}`} runId={runId} alphaId={alphaId} stage={ts} compact />
                  </>
                )}
              </Panel>
              {mc && (
                <section aria-label="Monte Carlo">
                  <h3 className="n-sec-h">Monte Carlo · <Term k="stress">kịch bản cực xấu</Term></h3>
                  {mcFits ? <McResult mc={mc} /> : <Panel title="Monte Carlo (rút gọn)"><CompactMc mc={mc} /></Panel>}
                </section>
              )}
              <ScalePanel d={d} />
              {d.isFinal && <PromoteBar runId={runId} d={d} />}
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}
