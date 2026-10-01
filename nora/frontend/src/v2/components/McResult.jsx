import React, { useMemo } from 'react'
import { Panel, Status } from './ui'
import FanChart from './charts/FanChart'
import Histogram from './charts/Histogram'
import GateList from './GateList'
import { fmtNum, fmtSPct, fmtPct, signClass, isNum } from '../lib/format'

// Quạt có thể là % lợi nhuận (bắt đầu 0), hệ số vốn (bắt đầu 1) hoặc chỉ số (bắt đầu 100): quy về %.
export function normalizeFan(fan) {
  if (!fan?.p50?.length) return fan
  const s = fan.p50[0]
  let f = null
  if (Math.abs(s - 1) < 0.05) f = (v) => (v - 1) * 100
  else if (Math.abs(s - 100) < 5) f = (v) => v - 100
  if (!f) return fan
  const out = { days: fan.days }
  ;['p5', 'p25', 'p50', 'p75', 'p95'].forEach((k) => { out[k] = (fan[k] || []).map((v) => (isNum(v) ? f(v) : v)) })
  return out
}

export default function McResult({ mc, ruinPct }) {
  const fan = useMemo(() => normalizeFan(mc.fan), [mc.fan])
  const sm = mc.summary || {}
  const ruin = mc.params?.ruin_threshold_pct ?? ruinPct ?? 30
  const gate = mc.gate || {}
  const gateChecks = [{ key: 'ruin', label: `P(MDD ≥ ${ruin}%) trong ${mc.params?.horizon_days ?? '—'} ngày`, required: `≤ ${gate.ruin_max_pct}%`, actual: sm.p_mdd_ge_ruin_pct, passed: gate.passed }]
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div className="n-grid g-kpi" style={{ marginBottom: 0 }}>
        <div className="n-panel n-kpi"><div className="lbl">Lợi nhuận trung vị</div><div className={`val ${signClass(sm.median_ret_pct)}`}>{fmtSPct(sm.median_ret_pct, 1)}</div><div className="sub">P50 cuối kỳ</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Lợi nhuận P5</div><div className={`val ${signClass(sm.p05_ret_pct)}`}>{fmtSPct(sm.p05_ret_pct, 1)}</div><div className="sub">kịch bản xấu 5%</div></div>
        <div className="n-panel n-kpi"><div className="lbl">MDD trung vị</div><div className="val neg">{fmtPct(sm.mdd_p50_pct, 1)}</div><div className="sub">P50</div></div>
        <div className="n-panel n-kpi"><div className="lbl">MDD P95</div><div className="val neg">{fmtPct(sm.mdd_p95_pct, 1)}</div><div className="sub">kịch bản xấu 5%</div></div>
        <div className="n-panel n-kpi"><div className="lbl">P(MDD ≥ {ruin}%)</div><div className="val">{fmtPct(sm.p_mdd_ge_ruin_pct, 1)}</div><div className="sub">ngưỡng phá sản</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Cổng Monte Carlo</div><div className="val" style={{ fontSize: 16, marginTop: 4 }}><Status tone={gate.passed ? 'ok' : 'bad'}>{gate.passed ? '✓ Đạt' : '✗ Không đạt'}</Status></div><div className="sub">ruin tối đa {fmtPct(gate.ruin_max_pct, 1)}</div></div>
      </div>
      <Panel title="Quạt lợi nhuận tích luỹ" meta={<span className="n-legend"><span><i style={{ borderTopColor: 'var(--n-blue)' }} />P50</span><span><i className="sq" style={{ background: 'var(--n-blue)', opacity: 0.4 }} />P25–P75</span><span><i className="sq" style={{ background: 'var(--n-blue)', opacity: 0.18 }} />P5–P95</span></span>}>
        <FanChart fan={fan} height={270} />
        <p className="n-note">Trục x: số ngày kể từ đầu mô phỏng. {mc.params && <span className="mono">{fmtNum(mc.params.simulations, 0)} mô phỏng · khối {mc.params.block_days} ngày · seed {mc.params.seed}</span>}</p>
      </Panel>
      <div className="n-grid g-2" style={{ marginBottom: 0 }}>
        <Panel title="Phân phối max drawdown" meta={<span>ngưỡng phá sản <b className="mono neg">{ruin}%</b></span>}>
          <Histogram bins={mc.mdd_hist?.bins || []} height={200} unit="%" xFormat={(v) => `${fmtNum(v, 0)}%`} label="Phân phối max drawdown"
            colorOf={(b) => (b.lo >= ruin ? 'var(--n-neg)' : 'var(--n-blue)')} marker={{ x: ruin, label: `ruin ${ruin}%` }} />
        </Panel>
        <Panel title="Phân phối lợi nhuận cuối kỳ" meta={<span>P5 <b className="mono">{fmtSPct(sm.p05_ret_pct, 1)}</b></span>}>
          <Histogram bins={mc.ret_hist?.bins || []} height={200} unit="%" xFormat={(v) => `${fmtNum(v, 0)}%`} label="Phân phối lợi nhuận cuối kỳ"
            colorOf={(b) => (b.hi <= 0 ? 'var(--n-neg)' : 'var(--n-teal)')} />
        </Panel>
      </div>
      <Panel title="Cổng chấp nhận"><GateList checks={gateChecks} passed={gate.passed} title="Rủi ro phá sản" /></Panel>
    </div>
  )
}
