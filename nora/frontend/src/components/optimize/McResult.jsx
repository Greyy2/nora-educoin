import React, { useMemo } from 'react'
import { Panel, Status } from '../ui'
import FanChart from '../charts/FanChart'
import Histogram from '../charts/Histogram'
import GateList from './GateList'
import Term from '../ui/Term'
import { stopFillText } from '../../lib/stopfill'
import { fmtNum, fmtSPct, fmtPct, signClass, isNum } from '../../lib/format'

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

// Kịch bản cực xấu vẽ chồng lên quạt: đường bootstrap tệ nhất (đỏ, liền) và ngày lỗ xếp trước (cam, nét đứt) — khác màu quạt xanh.
const OVERLAYS = [
  { name: 'worst_bootstrap', label: 'Bootstrap tệ nhất', color: 'var(--n-neg)', dash: false },
  { name: 'worst_days_first', label: 'Ngày lỗ xếp trước', color: 'var(--n-warn)', dash: true },
]

function StressChip({ r }) {
  if (r.measured === false) return <Status tone="warn">Không đo được</Status>
  if (r.ruin) return <Status tone="bad">✗ Cháy vốn</Status>
  return r.passed ? <Status tone="ok">✓ Đạt</Status> : <Status tone="bad">✗ Không đạt</Status>
}

export default function McResult({ mc }) {
  const fan = useMemo(() => normalizeFan(mc.fan), [mc.fan])
  const sm = mc.summary || {}
  const gate = mc.gate || {}
  // Ngưỡng cổng chỉ lấy từ payload backend (gate.* / params): không có hằng số dự phòng. Thiếu (kết quả cũ) -> '—' + gate.thresholds_note.
  const ruin = mc.params?.ruin_threshold_pct ?? gate.ruin_threshold_pct
  const ruinTxt = isNum(ruin) ? fmtNum(ruin, 0) : '—'
  const thr = (v, d = 0) => (isNum(v) ? fmtNum(v, d) : '—')
  const stress = mc.stress || []
  const stressMax = gate.stress_max_mdd_pct
  const minSims = gate.min_simulations
  const eligible = gate.gate_eligible !== false     // kết quả cũ không có trường này: coi như đủ điều kiện
  const overlays = useMemo(
    () => OVERLAYS.map((o) => ({ ...o, key: o.name, path: stress.find((r) => r.name === o.name)?.path })).filter((o) => o.path?.days?.length > 1)
      .map((o) => ({ key: o.key, label: o.label, color: o.color, dash: o.dash, days: o.path.days, ret_pct: o.path.ret_pct })),
    [stress])
  // Cổng: kiểm tra thực tế so với yêu cầu (backend). Kết quả cũ chỉ có ruin_max_pct nên dựng một dòng như trước.
  const gateChecks = gate.checks
    ? Object.entries(gate.checks).map(([k, c]) => ({
      key: k, ...c,
      label: k === 'ruin' ? `P(MDD ≥ ${ruinTxt}%) trong ${mc.params?.horizon_days ?? '—'} ngày` : (c.detail ? `${c.label} (${c.detail})` : c.label),
    }))
    : [{ key: 'ruin', unit: '%', label: `P(MDD ≥ ${ruinTxt}%) trong ${mc.params?.horizon_days ?? '—'} ngày`, required: `≤ ${fmtNum(gate.ruin_max_pct, 2)}%`, actual: sm.p_mdd_ge_ruin_pct, passed: gate.passed }]
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {gate.thresholds_note && <div className="n-warnbox" role="note">Ngưỡng cổng thiếu trong kết quả này ({gate.thresholds_note}); các ô tương ứng hiện "—".</div>}
      {!eligible && (
        <div className="n-banner" role="alert" style={{ borderLeftColor: 'var(--n-warn)', marginBottom: 0 }}>
          <Status tone="warn">⚠ gate_eligible: false</Status>
          <span>Chỉ {fmtNum(mc.params?.simulations, 0)} mô phỏng (cần ≥ {thr(minSims)}): kết quả chỉ để tham khảo, <b>không dùng làm cổng chấp nhận</b>. Chạy lại với {thr(minSims)} mô phỏng trở lên.</span>
        </div>
      )}
      <div className="n-grid g-kpi" style={{ marginBottom: 0 }}>
        <div className="n-panel n-kpi"><div className="lbl">Lợi nhuận trung vị</div><div className={`val ${signClass(sm.median_ret_pct)}`}>{fmtSPct(sm.median_ret_pct)}</div><div className="sub">P50 cuối kỳ</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Lợi nhuận P5</div><div className={`val ${signClass(sm.p05_ret_pct)}`}>{fmtSPct(sm.p05_ret_pct)}</div><div className="sub">kịch bản xấu 5%</div></div>
        <div className="n-panel n-kpi"><div className="lbl"><Term k="mdd">MDD</Term> trung vị</div><div className="val neg">{fmtPct(sm.mdd_p50_pct)}</div><div className="sub">P50</div></div>
        <div className="n-panel n-kpi"><div className="lbl"><Term k="mdd">MDD</Term> P95</div><div className="val neg">{fmtPct(sm.mdd_p95_pct)}</div><div className="sub">kịch bản xấu 5%</div></div>
        <div className="n-panel n-kpi"><div className="lbl"><Term k="p_mdd">P(MDD ≥ {ruinTxt}%)</Term></div><div className="val">{fmtPct(sm.p_mdd_ge_ruin_pct)}</div><div className="sub">ngưỡng phá sản</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Cổng <Term k="mc">Monte Carlo</Term></div><div className="val" style={{ fontSize: 16, marginTop: 4 }}><Status tone={gate.passed ? 'ok' : 'bad'}>{gate.passed ? '✓ Đạt' : '✗ Không đạt'}</Status></div><div className="sub">ruin ≤ {fmtPct(gate.ruin_max_pct)} · kịch bản cực xấu &lt; {thr(stressMax)}%</div></div>
      </div>
      <Panel title={<>Quạt lợi nhuận tích luỹ (<Term k="fan">P5–P95</Term>)</>} meta={<span className="n-legend"><span><i style={{ borderTopColor: 'var(--n-blue)' }} />P50</span><span><i className="sq" style={{ background: 'var(--n-blue)', opacity: 0.4 }} />P25–P75</span><span><i className="sq" style={{ background: 'var(--n-blue)', opacity: 0.18 }} />P5–P95</span>
        {overlays.map((o) => <span key={o.key}><i className={o.dash ? 'dash' : ''} style={{ borderTopColor: o.color }} />{o.label}</span>)}</span>}>
        <FanChart fan={fan} height={270} overlays={overlays} />
        <p className="n-note">Trục x: số ngày kể từ đầu mô phỏng. {mc.params && <span className="mono">{fmtNum(mc.params.simulations, 0)} mô phỏng · <Term k="bootstrap">khối</Term> {mc.params.block_days} ngày · seed {mc.params.seed}{mc.params.basis ? ` · khớp cắt lỗ: ${stopFillText(mc.params.basis)}` : ''}</span>}</p>
      </Panel>
      <div className="n-grid g-2" style={{ marginBottom: 0 }}>
        <Panel title="Phân phối max drawdown" meta={<span>ngưỡng phá sản <b className="mono neg">{ruinTxt}%</b></span>}>
          <Histogram bins={mc.mdd_hist?.bins || []} height={200} unit="%" xFormat={(v) => `${fmtNum(v, 0)}%`} label="Phân phối max drawdown"
            colorOf={(b) => (isNum(ruin) && b.lo >= ruin ? 'var(--n-neg)' : 'var(--n-blue)')} marker={isNum(ruin) ? { x: ruin, label: `ruin ${ruin}%` } : undefined} />
        </Panel>
        <Panel title="Phân phối lợi nhuận cuối kỳ" meta={<span>P5 <b className="mono">{fmtSPct(sm.p05_ret_pct, 1)}</b></span>}>
          <Histogram bins={mc.ret_hist?.bins || []} height={200} unit="%" xFormat={(v) => `${fmtNum(v, 0)}%`} label="Phân phối lợi nhuận cuối kỳ"
            colorOf={(b) => (b.hi <= 0 ? 'var(--n-neg)' : 'var(--n-teal)')} />
        </Panel>
      </div>
      {stress.length > 0 && (
        <Panel title="Kịch bản cực xấu" meta={<span>mỗi kịch bản phải có MDD &lt; <b className="mono">{thr(stressMax)}%</b> và không cháy vốn</span>}>
          <div className="n-tblwrap">
            <table className="n-tbl">
              <thead><tr><th>Kịch bản</th><th className="r"><Term k="mdd">MDD</Term></th><th className="r">Lãi cuối</th><th className="r">Ngày tệ nhất</th><th className="r">Ngày dưới đỉnh</th><th>Kết quả</th></tr></thead>
              <tbody>
                {stress.map((r) => (
                  <tr key={r.name}>
                    <td title={r.note_vi || undefined}>{r.label_vi || r.name}<div className="muted mono" style={{ fontSize: 11 }}>{r.name}{r.days ? ` · ${r.days} ngày` : ''}</div>{r.measured === false && <div className="n-note">{r.note_vi}</div>}</td>
                    <td className={`r ${isNum(stressMax) && r.mdd_pct >= stressMax ? 'neg' : ''}`}>{fmtPct(r.mdd_pct)}</td>
                    <td className={`r ${signClass(r.terminal_ret_pct)}`}>{fmtSPct(r.terminal_ret_pct)}</td>
                    <td className="r neg">{fmtSPct(r.worst_day_pct)}</td>
                    <td className="r">{fmtNum(r.days_underwater, 0)}{r.days ? <span className="muted"> / {fmtNum(r.days, 0)}</span> : null}</td>
                    <td><StressChip r={r} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="n-note">Kịch bản dựng tất định từ chính chuỗi lợi suất ngày (không ngẫu nhiên): xếp ngày lỗ lên trước, đảo ngược thứ tự, một ngày sập gấp đôi ngày tệ nhất, chi phí giao dịch gấp đôi, chuỗi thua dài nhất lặp 2 lần — cộng với đường bootstrap tệ nhất trong {fmtNum(mc.params?.simulations, 0)} mô phỏng.
            {stress.find((r) => r.note_vi) && <> {stress.find((r) => r.note_vi).note_vi}.</>}</p>
        </Panel>
      )}
      <Panel title="Cổng chấp nhận"><GateList checks={gateChecks} passed={gate.passed} title="Rủi ro phá sản và kịch bản cực xấu" /></Panel>
    </div>
  )
}
