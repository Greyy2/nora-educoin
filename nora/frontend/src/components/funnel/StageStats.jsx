import React, { useMemo } from 'react'
import { Panel, Empty } from '../ui'
import Term from '../Term'
import OverlayHist from '../charts/OverlayHist'
import { AlphaLink, ParamList, StrategyName } from './parts'
import Collapsible from './Collapsible'
import { summarizeParams } from './paramSummary'
import { DIST_KEYS, DIST_UNIT, METRICS, STAGE_META, fmtCount, fmtMetric } from '../../lib/funnel'
import { paramHeader, fmtParamFull } from '../../lib/params'
import { fmtNum, fmtPct, fmtSPct, signClass, isNum } from '../../lib/format'

const DIST_FMT = {
  ret_pct: (v) => fmtNum(v, 0), mdd_pct: (v) => fmtNum(v, 0), sharpe: (v) => fmtNum(v, 1), trades: (v) => fmtNum(v, 0), win_rate: (v) => fmtNum(v, 0), profit_factor: (v) => fmtNum(v, 1),
}

function Kpis({ s }) {
  const rate = s.input > 0 ? (s.passed / s.input) * 100 : null
  return (
    <div className="n-grid g-kpi" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', marginBottom: 12 }}>
      <div className="n-panel n-kpi"><div className="lbl">Vào tầng</div><div className="val">{fmtCount(s.input)}</div><div className="sub">alpha</div></div>
      <div className="n-panel n-kpi"><div className="lbl">Qua tầng</div><div className="val pos">{fmtCount(s.passed)}</div><div className="sub">nhóm ra</div></div>
      <div className="n-panel n-kpi"><div className="lbl">Bị loại</div><div className="val neg">{fmtCount(s.rejected)}</div><div className="sub">{s.reject_reasons.length} lý do</div></div>
      <div className="n-panel n-kpi"><div className="lbl">Tỉ lệ qua</div><div className="val">{rate != null ? fmtPct(rate, rate < 10 ? 2 : 1) : '—'}</div><div className="sub">qua / vào</div></div>
    </div>
  )
}

function Distributions({ s }) {
  const keys = DIST_KEYS.filter((k) => s.distributions[k])
  if (!keys.length) return null
  const first = s.distributions[keys[0]]
  const nIn = first.in?.n ?? first.in?.bins.reduce((a, b) => a + b.count, 0)
  const nOut = first.out?.n ?? first.out?.bins.reduce((a, b) => a + b.count, 0)
  return (
    <Collapsible title="Phân phối chỉ số: nhóm vào so với nhóm qua" sub={<span>{keys.length} chỉ số · vào {fmtCount(nIn)} → qua {fmtCount(nOut)}</span>}>
      <div className="n-fn-tools" style={{ marginBottom: 6 }}>
        <span className="n-legend">
          <span><i className="sq" style={{ background: 'var(--n-bench)', opacity: 0.6 }} />Nhóm vào ({fmtCount(nIn)})</span>
          <span><i className="sq" style={{ background: 'var(--n-blue)' }} />Nhóm qua ({fmtCount(nOut)})</span>
          <span className="muted">▲ trung vị</span>
        </span>
      </div>
      <div className="n-fn-dists">
        {keys.map((k) => {
          const d = s.distributions[k]
          const m = METRICS[k]
          return (
            <figure key={k} className="n-fn-dist">
              <figcaption>{m.term ? <Term k={m.term}>{m.label}</Term> : m.label}
                <span className="muted mono"> · trung vị {fmtMetric(k, d.in?.p50)} → {fmtMetric(k, d.out?.p50)}</span></figcaption>
              <OverlayHist a={d.in} b={d.out} unit={DIST_UNIT[k] || ''} xFormat={DIST_FMT[k]} label={`Phân phối ${m.label}`} height={140} />
            </figure>
          )
        })}
      </div>
      <p className="n-note">Mỗi cột là % số alpha của riêng nhóm đó (để so hình dạng dù nhóm qua nhỏ hơn nhiều); rê chuột để xem số đếm thật. 30 bin cố định theo khoảng phân vị 1–99 của nhóm vào.</p>
      <details className="n-details" style={{ marginTop: 8 }}>
        <summary>Xem bảng phân vị</summary>
        <div className="n-tblwrap">
          <table className="n-tbl">
            <thead><tr><th>Chỉ số</th><th className="r">Vào P5</th><th className="r">Vào P50</th><th className="r">Vào P95</th><th className="r">Qua P5</th><th className="r">Qua P50</th><th className="r">Qua P95</th></tr></thead>
            <tbody>
              {keys.map((k) => { const d = s.distributions[k]; return (
                <tr key={k}><td>{METRICS[k].label}</td>
                  {['p5', 'p50', 'p95'].map((p) => <td key={`i${p}`} className="r">{fmtMetric(k, d.in?.[p])}</td>)}
                  {['p5', 'p50', 'p95'].map((p) => <td key={`o${p}`} className="r">{fmtMetric(k, d.out?.[p])}</td>)}
                </tr>
              ) })}
            </tbody>
          </table>
        </div>
      </details>
    </Collapsible>
  )
}

function RejectReasons({ s }) {
  const max = Math.max(1, ...s.reject_reasons.map((r) => r.count))
  const total = s.reject_reasons.reduce((a, r) => a + r.count, 0)
  return (
    <Panel title="Lý do loại" meta={<span className="mono">{fmtCount(total)} alpha bị loại</span>}>
      {!s.reject_reasons.length && <p className="n-note">Không có alpha nào bị loại ở tầng này.</p>}
      <ul className="n-rr">
        {s.reject_reasons.map((r) => (
          <li key={r.code}>
            <span className="lb" title={r.code}>{r.label || r.code}<span className="code mono muted">{r.code}</span></span>
            <span className="fbar"><i style={{ width: `${(r.count / max) * 100}%` }} /></span>
            <span className="v mono">{fmtCount(r.count)}<span className="muted"> · {total ? fmtPct((r.count / total) * 100, 0) : '—'}</span></span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function ByStrategy({ s, catalog }) {
  if (!s.by_strategy.length) return null
  return (
    <Panel title="Theo chiến lược">
      <div className="n-tblwrap">
        <table className="n-tbl">
          <thead><tr><th>Chiến lược</th><th className="r">Vào</th><th className="r">Qua</th><th className="r">Tỉ lệ qua</th><th className="r">Lãi trung vị</th><th className="r"><Term k="mdd">MDD</Term> trung vị</th></tr></thead>
          <tbody>
            {s.by_strategy.map((r) => (
              <tr key={r.strategy}>
                <td><StrategyName id={r.strategy} catalog={catalog} /></td>
                <td className="r">{fmtCount(r.input)}</td><td className="r">{fmtCount(r.passed)}</td>
                <td className="r"><span className="n-wbar"><span className="tr"><i style={{ width: `${Math.min(100, r.pass_rate || 0)}%` }} /></span><b>{fmtPct(r.pass_rate, 1)}</b></span></td>
                <td className={`r ${signClass(r.median_ret_pct)}`}>{fmtSPct(r.median_ret_pct, 1)}</td>
                <td className="r">{isNum(r.median_mdd_pct) ? fmtPct(r.median_mdd_pct, 1) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

/** Toàn bộ lưới: mỗi chiến lược một khối, mỗi tham số một hàng, mỗi giá trị một ô (tỉ lệ qua + qua/vào); màu xanh đậm dần theo tỉ lệ. Chỉ dựng khi mở. */
function ParamGrid({ s }) {
  const byStrat = new Map()
  s.param_survival.forEach((p) => { if (!byStrat.has(p.strategy)) byStrat.set(p.strategy, []); byStrat.get(p.strategy).push(p) })
  return (
    <>
      <div className="n-ps">
        {[...byStrat.entries()].map(([sid, params]) => {
          const rates = params.flatMap((p) => p.values.map((v) => (v.input > 0 ? (v.passed / v.input) * 100 : 0)))
          const mx = Math.max(1, ...rates)
          return (
            <div key={sid} className="n-ps-blk">
              <h4 className="mono">{sid}</h4>
              {params.map((p) => (
                <div className="n-ps-row" key={p.param}>
                  <span className="pl" title={p.param}>{paramHeader(p.param)}</span>
                  <span className="cells">
                    {p.values.map((v) => {
                      const r = v.input > 0 ? (v.passed / v.input) * 100 : 0
                      return (
                        <span key={String(v.value)} className="cell" style={{ background: `color-mix(in srgb, var(--n-blue) ${Math.round(8 + (r / mx) * 46)}%, transparent)` }}
                          title={`${paramHeader(p.param)} = ${fmtParamFull(p.param, v.value)}: ${v.passed}/${v.input} qua`}>
                          <b>{fmtParamFull(p.param, v.value)}</b>
                          <span className="mono">{v.input ? fmtPct(r, r < 10 ? 1 : 0) : '—'}</span>
                          <small className="mono muted">{fmtCount(v.passed)}/{fmtCount(v.input)}</small>
                        </span>
                      )
                    })}
                  </span>
                </div>
              ))}
            </div>
          )
        })}
      </div>
      <p className="n-note">Mỗi ô là một giá trị của tham số: tỉ lệ alpha mang giá trị đó qua tầng (đậm hơn là sống sót tốt hơn) và số qua / số vào.</p>
    </>
  )
}

/** Sống sót theo tham số, rút gọn: mỗi chiến lược chỉ 2–3 tham số làm đổi tỉ lệ qua nhiều nhất + khoảng giá trị tốt nhất; lưới đầy đủ nằm trong "Chi tiết" (đóng sẵn). */
function ParamSurvival({ s }) {
  const sums = useMemo(() => summarizeParams(s.param_survival), [s.param_survival])
  if (!s.param_survival.length) return null
  const overall = s.input > 0 ? (s.passed / s.input) * 100 : 0
  const nParams = s.param_survival.length
  return (
    <Panel title="Tham số ảnh hưởng nhất đến việc qua tầng" meta={<span>chung toàn tầng <b className="mono">{fmtPct(overall, 1)}</b></span>}>
      <div className="n-fs-strats">
        {sums.map((c) => (
          <div className="n-fs-card" key={c.strategy}>
            <h4><span className="mono">{c.strategy}</span><span className="rt mono">qua {fmtPct(c.rate, c.rate < 10 ? 1 : 0)} · {fmtCount(c.passed)}/{fmtCount(c.input)}</span></h4>
            {!c.rows.length && <div className="none">Không tham số nào làm đổi rõ tỉ lệ qua.</div>}
            {c.rows.map((r) => (
              <div className="n-fs-prm" key={r.param}>
                <span className="pl" title={r.param}>{paramHeader(r.param)}</span>
                <span className="best">tốt nhất <b>{r.best.label}</b> <span className="mono">{fmtPct(r.best.rate, r.best.rate < 10 ? 1 : 0)}</span></span>
                <span className="bad">kém nhất {r.worst.label} <span className="mono">{fmtPct(r.worst.rate, r.worst.rate < 10 ? 1 : 0)}</span></span>
              </div>
            ))}
          </div>
        ))}
      </div>
      <p className="n-note" style={{ margin: '8px 0' }}>Tỉ lệ alpha qua tầng theo khoảng giá trị (giá trị số được gộp tối đa 4 khoảng; bỏ khoảng quá ít alpha). Chỉ liệt kê tham số chênh từ 5 điểm % trở lên.</p>
      <Collapsible title="Chi tiết: toàn bộ lưới giá trị tham số" sub={`${nParams} tham số`}>{() => <ParamGrid s={s} />}</Collapsible>
    </Panel>
  )
}

function TopTable({ rows, withS, onOpen, catalog }) {
  return (
    <div className="n-tblwrap">
      <table className="n-tbl">
        <thead><tr><th>Mã</th><th>Chiến lược</th><th>Tham số</th><th className="r">Lãi</th><th className="r"><Term k="mdd">MDD</Term></th><th className="r"><Term k="sharpe">Sharpe</Term></th><th className="r">Lệnh</th>{withS && <th className="r"><Term k="scale_s">s</Term></th>}</tr></thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.alpha_id}>
              <td><AlphaLink id={a.alpha_id} onOpen={onOpen} /></td>
              <td><StrategyName id={a.strategy} catalog={catalog} /></td>
              <td className="wrap"><ParamList params={a.params} /></td>
              <td className={`r ${signClass(a.metrics?.ret_pct)}`}>{fmtSPct(a.metrics?.ret_pct, 1)}</td>
              <td className="r">{fmtMetric('mdd_pct', a.metrics?.mdd_pct)}</td>
              <td className="r">{fmtMetric('sharpe', a.metrics?.sharpe)}</td>
              <td className="r">{fmtMetric('trades', a.metrics?.trades)}</td>
              {withS && <td className="r">{fmtMetric('final_scale', a.final_scale ?? a.metrics?.final_scale)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const TOP_SHOWN = 5

function TopAlphas({ s, stage, onOpen, catalog }) {
  if (!s.top.length) return null
  const withS = ['S5_sizing', 'S6_holdout', 'FINAL'].includes(stage)
  const head = s.top.slice(0, TOP_SHOWN)
  const rest = s.top.slice(TOP_SHOWN)
  return (
    <Panel title="Alpha nổi bật" meta={<span>top {head.length} theo Sharpe</span>}>
      <TopTable rows={head} withS={withS} onOpen={onOpen} catalog={catalog} />
      {rest.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <Collapsible title={`Chi tiết: ${rest.length} alpha tiếp theo`}>{() => <TopTable rows={rest} withS={withS} onOpen={onOpen} catalog={catalog} />}</Collapsible>
        </div>
      )}
    </Panel>
  )
}

export default function StageStats({ stats, stage, onOpen, catalog }) {
  if (!stats) return null
  const meta = STAGE_META[stage]
  const noDist = !Object.keys(stats.distributions).length
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div className="n-banner" style={{ marginBottom: 0 }}><span><b>{meta?.name}</b>{meta?.data ? ` · dữ liệu ${meta.data}` : ''}. Điều kiện qua: {meta?.rule}.</span></div>
      <Kpis s={stats} />
      <div className="n-grid g-2" style={{ marginBottom: 0 }}>
        <RejectReasons s={stats} />
        <ByStrategy s={stats} catalog={catalog} />
      </div>
      <ParamSurvival s={stats} />
      <TopAlphas s={stats} stage={stage} onOpen={onOpen} catalog={catalog} />
      {noDist
        ? <Empty title="Chưa có phân phối cho tầng này">{stage === 'S0_generate' ? 'Tầng sinh alpha chỉ có số lượng và phân bổ theo chiến lược.' : 'Backend chưa trả phân phối chỉ số cho tầng này.'}</Empty>
        : <Distributions s={stats} />}
    </div>
  )
}
