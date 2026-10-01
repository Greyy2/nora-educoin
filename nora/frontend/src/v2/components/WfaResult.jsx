import React, { useMemo } from 'react'
import { Panel, Status } from './ui'
import GateList from './GateList'
import Term from './Term'
import { paramLabel, fmtParamFull, sameParams } from '../lib/params'
import { STOP_FILL } from '../lib/stopfill'
import { fullDate } from '../lib/format'
import AreaLine from './charts/AreaLine'
import { fmtNum, fmtSPct, fmtPct, signClass, isNum, arrow } from '../lib/format'

const pick = (v, k = 'extreme') => (v && typeof v === 'object' ? v[k] ?? v.level : v)

function addDays(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

export function chosenText(chosen) {
  return Object.entries(chosen || {}).map(([id, p]) => `${id}: ${p ? Object.entries(p).map(([k, v]) => `${paramLabel(k)} ${fmtParamFull(k, v)}`).join(', ') : 'không chọn (không giao dịch)'}`)
}

/** Tham số chọn của một fold, chỉ in phần khác fold trước: mỗi chiến lược giống hệt thì ghi "như fold trước". */
function ChosenCell({ chosen, prev, first }) {
  const entries = Object.entries(chosen || {})
  if (!entries.length) return <span className="n-fold-same">không chọn (không giao dịch)</span>
  const unchanged = (id, p) => !first && prev && id in prev && (p == null ? prev[id] == null : prev[id] != null && sameParams(p, prev[id]))
  if (entries.every(([id, p]) => unchanged(id, p)) && Object.keys(prev || {}).length === entries.length) return <span className="n-fold-same">như fold trước</span>
  return (
    <>
      {entries.map(([id, p]) => (
        <div className="n-fold-strat" key={id}>
          <span className="id">{id}</span>
          {unchanged(id, p) ? <span className="n-fold-same">như fold trước</span>
            : p == null ? <span className="n-fold-same">không chọn (không giao dịch)</span>
              : (
                <span className="n-plist">
                  {Object.entries(p).map(([k, v]) => <span key={k} title={k}><b>{paramLabel(k)}</b>{fmtParamFull(k, v)}</span>)}
                </span>
              )}
        </div>
      ))}
    </>
  )
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
        <div className="n-panel n-kpi"><div className="lbl">Số <Term k="fold">fold</Term></div><div className="val">{agg.n_traded_folds ?? agg.n_folds ?? folds.length}</div><div className="sub">{agg.n_folds} fold tổng</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Fold <Term k="oos">OOS</Term> có lãi</div><div className="val">{fmtPct(agg.positive_ratio_pct)}</div><div className="sub">{agg.positive_folds}/{agg.n_traded_folds ?? agg.n_folds}</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Lãi kép <Term k="oos">OOS</Term></div><div className={`val ${signClass(pick(agg.compounded_oos_ret_pct))}`}>{fmtSPct(pick(agg.compounded_oos_ret_pct))}</div><div className="sub">{STOP_FILL.extreme.text}<br />{STOP_FILL.level.text} {fmtSPct(pick(agg.compounded_oos_ret_pct, 'level'))}</div></div>
        <div className="n-panel n-kpi"><div className="lbl"><Term k="mdd">MDD</Term> fold tệ nhất</div><div className="val neg">{fmtPct(pick(agg.worst_fold_mdd_pct))}</div><div className="sub">{STOP_FILL.extreme.text}<br />{STOP_FILL.level.text} {fmtPct(pick(agg.worst_fold_mdd_pct, 'level'))}</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Lãi <Term k="is">IS</Term> trung bình</div><div className={`val ${signClass(agg.avg_is_ret_pct)}`}>{fmtSPct(agg.avg_is_ret_pct)}</div><div className="sub">các fold</div></div>
        <div className="n-panel n-kpi"><div className="lbl">Giao dịch OOS</div><div className="val">{fmtNum(pick(agg.oos_trades), 0)}</div><div className="sub">{agg.oos_days} ngày OOS</div></div>
      </div>

      <div className="n-grid g-main-side" style={{ marginBottom: 0 }}>
        <Panel title={<>Đường vốn <Term k="oos">OOS</Term></>} meta={<span className="n-legend"><span><i style={{ borderTopColor: 'var(--n-accent)' }} />{STOP_FILL.extreme.text}</span><span><i className="dash" style={{ borderTopColor: 'var(--n-bench)' }} />{STOP_FILL.level.text}</span></span>}>
          {nDays > 1 ? (
            <AreaLine dates={dates} height={230} label="Đường vốn out-of-sample" valueFormat={(v) => `${fmtNum(v, 2)}%`}
              refLines={[{ y: 0 }]}
              series={[
                { key: 'x', label: STOP_FILL.extreme.text, values: cum(daily.extreme || daily.level), color: 'var(--n-accent)', area: true },
                ...(daily.level && daily.extreme ? [{ key: 'l', label: STOP_FILL.level.text, values: cum(daily.level), color: 'var(--n-bench)', dashed: true }] : []),
              ]} />
          ) : <p className="n-note">Báo cáo chưa có chuỗi lợi suất ngày OOS (oos_daily).</p>}
        </Panel>
        <Panel title="Cổng chấp nhận" meta={mc ? <span><Term k="mc">MC</Term> <Term k="p_mdd">P(MDD≥ruin)</Term> <b className="mono">{fmtPct(mc.p_mdd_ge_ruin_pct)}</b></span> : null}>
          <GateList checks={gate?.checks} passed={gate?.passed} title="Kết quả" />
        </Panel>
      </div>

      <Panel title={<>Các <Term k="fold">fold</Term></>} meta={<span>{folds.length} fold · train {report.config?.train_days} / test {report.config?.test_days} ngày{report.window?.[0] ? ` · ${fullDate(report.window[0])} → ${fullDate(report.window[1])}` : ''}</span>}>
        <div className="n-tblwrap long">
          <table className="n-tbl">
            <thead>
              <tr><th>Fold</th><th><Term k="is">IS</Term> (train)</th><th><Term k="oos">OOS</Term> (test)</th><th>Tham số chọn</th><th className="r">IS lãi</th>
                <th className="r">OOS<small>{STOP_FILL.level.text}</small></th><th className="r">OOS<small>{STOP_FILL.extreme.text}</small></th><th className="r"><Term k="mdd">MDD</Term> OOS</th><th className="r">Lệnh</th><th>Dương</th></tr>
            </thead>
            <tbody>
              {folds.map((f, fi) => {
                const x = f.oos_extreme || {}
                const l = f.oos_level || {}
                return (
                  <tr key={f.fold}>
                    <td className="num">{f.fold}</td>
                    <td className="num">{fullDate(f.train?.[0])} → {fullDate(f.train?.[1])}</td>
                    <td className="num">{fullDate(f.test?.[0])} → {fullDate(f.test?.[1])}</td>
                    <td style={{ whiteSpace: 'normal', minWidth: 260, fontSize: 11.5 }}>
                      <ChosenCell chosen={f.chosen} prev={fi ? folds[fi - 1].chosen : null} first={fi === 0} />
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
