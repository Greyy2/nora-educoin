import React from 'react'
import { Panel, Loading } from '../ui'
import Term from '../Term'
import { AlphaLink, StrategyName } from './parts'
import { fmtCount, fmtMetric, shortId } from '../../lib/funnel'
import { fmtPct, fmtSPct, fmtDuration, signClass, isNum } from '../../lib/format'

const bySharpe = (top) => [...(top || [])].sort((a, b) => (b.metrics?.sharpe ?? -Infinity) - (a.metrics?.sharpe ?? -Infinity))
const pct = (a, b) => (isNum(a) && isNum(b) && b > 0 ? fmtPct((a / b) * 100, (a / b) * 100 < 10 ? 2 : 1) : '—')

/** Vài con số chính của lượt chạy (bốn ô). `fin` = thống kê tầng FINAL (có thể chưa tải xong). */
export function Headline({ run, finalPassed, fin }) {
  const c = run.counts
  const best = bySharpe(fin?.top)[0]
  const secs = isNum(run.finished) && isNum(run.started) ? run.finished - run.started : null
  return (
    <div className="n-fs-kpis" aria-label="Số liệu chính">
      <div className="n-panel n-kpi"><div className="lbl">Alpha sinh ra</div><div className="val">{fmtCount(run.total_alphas)}</div>
        <div className="sub">{fmtCount(c[0].passed)} hợp lệ{secs != null ? ` · chạy ${fmtDuration(secs)}` : ''}</div></div>
      <div className="n-panel n-kpi"><div className="lbl">Qua backtest sàng lọc (S1)</div><div className="val">{fmtCount(c[1].passed)}</div>
        <div className="sub">{pct(c[1].passed, c[1].input)} số alpha vào S1</div></div>
      <div className="n-panel n-kpi"><div className="lbl">Đủ điều kiện testnet (FINAL)</div><div className={`val ${finalPassed > 0 ? 'pos' : ''}`}>{fmtCount(finalPassed)}</div>
        <div className="sub">{pct(finalPassed, c[0].passed)} số alpha hợp lệ</div></div>
      <div className="n-panel n-kpi"><div className="lbl">Sharpe cao nhất trong FINAL</div><div className="val">{best ? fmtMetric('sharpe', best.metrics?.sharpe) : '—'}</div>
        <div className="sub">{best ? <>{best.strategy} · {shortId(best.alpha_id)}</> : 'chưa có'}</div></div>
    </div>
  )
}

/** Kết quả FINAL rút gọn: số FINAL theo chiến lược + vài alpha tốt nhất theo Sharpe. Chi tiết đầy đủ nằm ở tầng FINAL. */
export function FinalSummary({ run, finalPassed, q, catalog, onOpen, onAll, live }) {
  const fin = q.data
  const none = finalPassed === 0 && !live
  const strategies = fin?.by_strategy || []
  const empty = run.strategies.filter((s) => !strategies.some((b) => b.strategy === s))
  const top = bySharpe(fin?.top).slice(0, 5)
  return (
    <Panel title="Kết quả FINAL" meta={isNum(finalPassed) && finalPassed > 0 ? <span className="mono">{fmtCount(finalPassed)} alpha · {strategies.length} chiến lược</span> : null}>
      {none && <p className="n-note">Chưa có alpha nào qua mọi tầng ở lượt này.</p>}
      {!none && !isNum(finalPassed) && <p className="n-note">Chưa có kết quả FINAL (lượt chưa chạy tới tầng cuối).</p>}
      {finalPassed > 0 && !fin && !q.error && <Loading what="kết quả FINAL" />}
      {q.error && !fin && <p className="n-note">Không tải được tóm tắt FINAL: {q.error}</p>}
      {fin && finalPassed > 0 && (
        <>
          <div className="n-fs-final">
            <div>
              <h3>Số FINAL theo chiến lược</h3>
              <div className="n-tblwrap">
                <table className="n-tbl">
                  <thead><tr><th>Chiến lược</th><th className="r">FINAL</th><th className="r">Lãi trung vị</th><th className="r"><Term k="mdd">MDD</Term> trung vị</th></tr></thead>
                  <tbody>
                    {strategies.map((r) => (
                      <tr key={r.strategy}>
                        <td><StrategyName id={r.strategy} catalog={catalog} /></td>
                        <td className="r"><b>{fmtCount(r.passed)}</b></td>
                        <td className={`r ${signClass(r.median_ret_pct)}`}>{fmtSPct(r.median_ret_pct, 1)}</td>
                        <td className="r">{isNum(r.median_mdd_pct) ? fmtPct(r.median_mdd_pct, 1) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {empty.length > 0 && <p className="n-note" style={{ marginTop: 6 }}>Không có FINAL: <span className="mono">{empty.join(', ')}</span></p>}
            </div>
            <div>
              <h3>{top.length} alpha tốt nhất theo Sharpe</h3>
              <div className="n-tblwrap">
                <table className="n-tbl">
                  <thead><tr><th>Mã</th><th>Chiến lược</th><th className="r">Lãi</th><th className="r"><Term k="mdd">MDD</Term></th><th className="r"><Term k="sharpe">Sharpe</Term></th><th className="r"><Term k="scale_s">s</Term></th></tr></thead>
                  <tbody>
                    {top.map((a) => (
                      <tr key={a.alpha_id}>
                        <td><AlphaLink id={a.alpha_id} onOpen={onOpen} /></td>
                        <td><StrategyName id={a.strategy} catalog={catalog} /></td>
                        <td className={`r ${signClass(a.metrics?.ret_pct)}`}>{fmtSPct(a.metrics?.ret_pct, 1)}</td>
                        <td className="r">{fmtMetric('mdd_pct', a.metrics?.mdd_pct)}</td>
                        <td className="r">{fmtMetric('sharpe', a.metrics?.sharpe)}</td>
                        <td className="r">{fmtMetric('final_scale', a.final_scale ?? a.metrics?.final_scale)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
          <div className="n-fs-foot">
            <button type="button" className="n-btn" onClick={onAll}>Xem toàn bộ {fmtCount(finalPassed)} alpha FINAL →</button>
            <span className="n-note">Bấm mã alpha để xem hành trình, NAV, Monte Carlo và lệnh.</span>
          </div>
        </>
      )}
    </Panel>
  )
}
