import React, { useMemo } from 'react'
import { Panel, Status } from './ui'
import GateList from './GateList'
import AreaLine from './charts/AreaLine'
import { fmtNum, fmtSPct, fmtPct, signClass, isNum, arrow } from '../lib/format'

const pick = (v, k = 'extreme') => (v && typeof v === 'object' ? v[k] ?? v.level : v)

function addDays(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

export function chosenText(chosen) {
  return Object.entries(chosen || {}).map(([id, p]) => `${id}: ${p ? Object.entries(p).map(([k, v]) => `${k}=${v}`).join(', ') : 'không chọn (không giao dịch)'}`)
}

/** Cum lợi nhuận % từ chuỗi lợi suất ngày (phân số). */
function cum(r = []) {
  let v = 1
  return r.map((x) => { v *= 1 + (isNum(x) ? x : 0); return +((v - 1) * 100).toFixed(3) })
}

export default function WfaResult({ report }) {
  const agg = report.aggregate || report.summary || {}
  const gate = report.gate
  const mc = report.mc || agg.mc
  const folds = report.folds || []
  const daily = agg.oos_daily || {}
  const nDays = (daily.extreme || daily.level || []).length
  const dates = useMemo(() => {
    // oos_daily_dates có thể là mảng, hoặc {level:[...], extreme:[...]} song song với oos_daily
    const raw = agg.oos_daily_dates
    const arr = Array.isArray(raw) ? raw : raw?.extreme || raw?.level
    if (Array.isArray(arr) && arr.length === nDays) return arr
    const start = folds[0]?.test?.[0]
    return start ? Array.from({ length: nDays }, (_, i) => addDays(start, i)) : []
  }, [agg.oos_daily_dates, folds, nDays])
  const ok = (f) => (pick(f.oos_extreme, 'ret_pct') ?? f.oos_extreme?.ret_pct) > 0

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div className="n-grid g-kpi" style={{ marginBottom: 0 }}>
        <div className="n-panel n-kpi"><div className="lbl">Số fold</div><div className="val">{agg.n_traded_folds ?? agg.n_folds ?? folds.length}</div><div className="sub">{agg.n_folds} fold tổng</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Fold OOS có lãi</div><div className="val">{fmtPct(agg.positive_ratio_pct, 0)}</div><div className="sub">{agg.positive_folds}/{agg.n_traded_folds ?? agg.n_folds}</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Lãi kép OOS (extreme)</div><div className={`val ${signClass(pick(agg.compounded_oos_ret_pct))}`}>{fmtSPct(pick(agg.compounded_oos_ret_pct), 1)}</div><div className="sub">level {fmtSPct(pick(agg.compounded_oos_ret_pct, 'level'), 1)}</div></div>
        <div className="n-panel n-kpi"><div className="lbl">MDD fold tệ nhất</div><div className="val neg">{fmtPct(pick(agg.worst_fold_mdd_pct), 1)}</div><div className="sub">level {fmtPct(pick(agg.worst_fold_mdd_pct, 'level'), 1)}</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Lãi IS trung bình</div><div className={`val ${signClass(agg.avg_is_ret_pct)}`}>{fmtSPct(agg.avg_is_ret_pct, 1)}</div><div className="sub">các fold</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Giao dịch OOS</div><div className="val">{fmtNum(pick(agg.oos_trades), 0)}</div><div className="sub">{agg.oos_days} ngày OOS</div></div>
      </div>

      <div className="n-grid g-main-side" style={{ marginBottom: 0 }}>
        <Panel title="Đường vốn OOS" meta={<span className="n-legend"><span><i style={{ borderTopColor: 'var(--n-accent)' }} />Extreme</span><span><i className="dash" style={{ borderTopColor: 'var(--n-bench)' }} />Level</span></span>}>
          {nDays > 1 ? (
            <AreaLine dates={dates} height={230} label="Đường vốn out-of-sample" valueFormat={(v) => `${fmtNum(v, 2)}%`}
              refLines={[{ y: 0 }]}
              series={[
                { key: 'x', label: 'Extreme', values: cum(daily.extreme || daily.level), color: 'var(--n-accent)', area: true },
                ...(daily.level && daily.extreme ? [{ key: 'l', label: 'Level', values: cum(daily.level), color: 'var(--n-bench)', dashed: true }] : []),
              ]} />
          ) : <p className="n-note">Báo cáo chưa có chuỗi lợi suất ngày OOS (oos_daily).</p>}
        </Panel>
        <Panel title="Cổng chấp nhận" meta={mc ? <span>MC P(MDD≥ruin) <b className="mono">{fmtPct(mc.p_mdd_ge_ruin_pct, 1)}</b></span> : null}>
          <GateList checks={gate?.checks} passed={gate?.passed} title="Kết quả" />
        </Panel>
      </div>

      <Panel title="Các fold" meta={<span>{folds.length} fold · train {report.config?.train_days}/{report.config?.test_days} ngày</span>}>
        <div className="n-tblwrap">
          <table className="n-tbl">
            <thead>
              <tr><th>Fold</th><th>IS (train)</th><th>OOS (test)</th><th>Tham số chọn</th><th className="r">IS lãi</th>
                <th className="r">OOS level</th><th className="r">OOS extreme</th><th className="r">MDD OOS</th><th className="r">Lệnh</th><th>Dương</th></tr>
            </thead>
            <tbody>
              {folds.map((f) => {
                const x = f.oos_extreme || {}
                const l = f.oos_level || {}
                return (
                  <tr key={f.fold}>
                    <td className="num">{f.fold}</td>
                    <td className="num">{f.train?.[0]} → {f.train?.[1]}</td>
                    <td className="num">{f.test?.[0]} → {f.test?.[1]}</td>
                    <td style={{ whiteSpace: 'normal', minWidth: 220, fontSize: 11.5 }} className="mono">
                      {chosenText(f.chosen).map((t) => <div key={t}>{t}</div>)}
                    </td>
                    <td className={`r ${signClass(f.is_ret_pct)}`}>{fmtSPct(f.is_ret_pct)}</td>
                    <td className={`r ${signClass(l.ret_pct)}`}>{arrow(l.ret_pct)} {fmtSPct(l.ret_pct)}</td>
                    <td className={`r ${signClass(x.ret_pct)}`}>{arrow(x.ret_pct)} {fmtSPct(x.ret_pct)}</td>
                    <td className="r">{fmtPct(x.mdd_pct ?? l.mdd_pct)}</td>
                    <td className="r">{x.trades ?? l.trades ?? '—'}</td>
                    <td>{(f.status && f.status !== 'TRADED') || !(x.trades ?? l.trades) ? <Status>{f.status && f.status !== 'TRADED' ? f.status : 'Không có lệnh'}</Status> : <Status tone={ok(f) ? 'ok' : 'bad'}>{ok(f) ? '✓ Có' : '✗ Không'}</Status>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
