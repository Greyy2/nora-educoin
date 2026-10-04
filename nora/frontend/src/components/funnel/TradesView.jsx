import React, { useMemo, useState } from 'react'
import { Loading, ErrorState, Empty, Status, Spinner } from '../ui'
import Pager from './Pager'
import TradeChartDrawer from '../chart/TradeChartDrawer'
import useAsync from '../../hooks/useAsync'
import { getFunnelTrades } from '../../api'
import { stageName, shortId } from '../../lib/funnel'
import { fmtNum, fmtMoney, fmtSPct, signClass, fullDate, isNum } from '../../lib/format'

const EXIT = { TP: 'Chốt lời', SL: 'Cắt lỗ', TRAIL: 'Trailing', TIMEOUT: 'Hết hạn', CLOSED: 'Đã đóng', OPEN: 'Đang mở' }
const ts = (iso) => (typeof iso === 'string' && iso.length >= 16 ? `${fullDate(iso.slice(0, 10))} ${iso.slice(11, 16)}` : '—')
const iso = (v) => { const m = typeof v === 'string' ? Date.parse(v) : NaN; return Number.isNaN(m) ? null : m }
const price = (v) => (isNum(v) ? fmtNum(v, Math.abs(v) >= 100 ? 2 : 4) : '—')

/** Danh sách lệnh của một alpha ở một tầng. Tầng walk-forward gom theo fold. Lệnh chưa lưu (alpha bị loại ở S1) thì có nút "Tính lại". */
export default function TradesView({ runId, alphaId, stage, compact = false }) {
  const [fold, setFold] = useState('')
  const [recompute, setRecompute] = useState(false)
  const [chart, setChart] = useState(null) // lệnh đang mở biểu đồ
  const [pg, setPg] = useState({ offset: 0, limit: compact ? 25 : 50 })
  const q = useAsync(() => getFunnelTrades(runId, alphaId, { stage, fold, offset: pg.offset, limit: pg.limit, recompute: recompute ? 'true' : '' }),
    [runId, alphaId, stage, fold, pg.offset, pg.limit, recompute])
  const d = q.data
  const folds = useMemo(() => d?.folds || [...new Set((d?.items || []).map((t) => t.fold).filter((f) => f != null))].sort((a, b) => a - b), [d])
  const grouped = folds.length > 0 && !fold

  if (recompute && q.loading && !d?.recomputed) {
    return (
      <div className="n-recompute" role="status" aria-live="polite">
        <Spinner /> <span><b>Đang tính lại danh sách lệnh</b> bằng backtest tất định trên dev1 (tiến trình con, có thể mất vài phút lần đầu; lần sau lấy từ bộ đệm). Đừng đóng trang.</span>
      </div>
    )
  }
  if (q.error) return <ErrorState title={recompute ? 'Không tính lại được danh sách lệnh' : 'Không tải được danh sách lệnh'} error={q.error} onRetry={q.reload} />
  if (!d) return <Loading what="danh sách lệnh" />
  if (!d.stored && !recompute && d.raw?.can_recompute === false) {
    return <Empty title="Không có lệnh được lưu cho tầng này">Tầng này không lưu danh sách lệnh của alpha này (alpha chưa vào tầng, hoặc tầng không sinh lệnh).</Empty>
  }
  if (!d.stored && !recompute) {
    return (
      <Empty title="Danh sách lệnh chưa được lưu">
        <p>Alpha bị loại ở tầng S1 chỉ lưu thống kê. Lệnh có thể <b>tính lại</b> bằng cách chạy lại backtest tất định (trùng từng bit với lần chạy gốc).</p>
        <div className="n-sticky-actions" style={{ justifyContent: 'center' }}>
          <button type="button" className="n-btn primary" onClick={() => setRecompute(true)}>Tính lại danh sách lệnh</button>
        </div>
      </Empty>
    )
  }
  const rows = []
  let lastFold = Symbol('none')
  d.items.forEach((t, i) => {
    if (grouped && t.fold !== lastFold) {
      lastFold = t.fold
      const sub = d.items.filter((x) => x.fold === t.fold)
      rows.push({ head: true, key: `h${t.fold}-${i}`, fold: t.fold, n: sub.length, pnl: sub.reduce((s, x) => s + (x.pnl_usd || 0), 0) })
    }
    rows.push({ key: `t${i}`, t })
  })
  const colSpan = 14 + (grouped ? 0 : folds.length ? 1 : 0)
  return (
    <div>
      <div className="n-fn-tools" style={{ marginBottom: 8 }}>
        <span className="n-note"><b>{stageName(stage)}</b> · alpha <span className="mono">{shortId(alphaId)}</span> · <span className="mono">{d.total.toLocaleString('en-US')}</span> lệnh</span>
        {(d.recomputed || recompute) && <Status tone="info">tính lại</Status>}
        {folds.length > 0 && (
          <div className="n-presets" style={{ margin: 0 }} role="group" aria-label="Lọc theo fold">
            <button type="button" className={`n-chip-btn ${fold === '' ? 'on' : ''}`} aria-pressed={fold === ''} onClick={() => { setFold(''); setPg((p) => ({ ...p, offset: 0 })) }}>Mọi fold</button>
            {folds.map((f) => (
              <button key={f} type="button" className={`n-chip-btn ${String(fold) === String(f) ? 'on' : ''}`} aria-pressed={String(fold) === String(f)} onClick={() => { setFold(f); setPg((p) => ({ ...p, offset: 0 })) }}>Fold {f}</button>
            ))}
          </div>
        )}
      </div>
      <div className={`n-tblwrap long ${q.loading ? 'busy' : ''}`}>
        <table className="n-tbl n-fn-tbl">
          <thead>
            <tr><th>Vào lúc</th><th>Đóng lúc</th><th>Cặp</th><th>Hướng</th><th className="r">Giá vào</th><th className="r">Giá ra</th><th className="r">Khối lượng</th>
              <th className="r">Lãi/lỗ (USD)</th><th className="r">Lãi/lỗ (%)</th><th className="r">Phí</th><th className="r">Funding</th><th>Thoát</th><th className="r">Lớp</th><th className="r">MAE %</th><th>Biểu đồ</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => r.head ? (
              <tr key={r.key} className="grp"><td colSpan={colSpan + 1}><b>Fold {r.fold}</b><span className="muted mono"> · {r.n} lệnh trên trang · </span><span className={`mono ${signClass(r.pnl)}`}>{fmtMoney(r.pnl, true)} USD</span></td></tr>
            ) : (
              <tr key={r.key}>
                <td className="num">{ts(r.t.enter_time)}</td><td className="num">{ts(r.t.close_time)}</td>
                <td>{String(r.t.symbol || '').replace('@perp', '')}</td>
                <td><span className={`n-badge ${String(r.t.side).toLowerCase()}`}>{r.t.side}</span></td>
                <td className="r">{price(r.t.enter_price)}</td><td className="r">{price(r.t.close_price)}</td><td className="r">{fmtNum(r.t.qty, 4)}</td>
                <td className={`r ${signClass(r.t.pnl_usd)}`}>{fmtMoney(r.t.pnl_usd, true)}</td>
                <td className={`r ${signClass(r.t.pnl_pct)}`}>{fmtSPct(r.t.pnl_pct, 2)}</td>
                <td className="r">{fmtNum(r.t.fees_usd, 2)}</td><td className={`r ${signClass(-(r.t.funding_usd || 0))}`}>{fmtNum(r.t.funding_usd, 2)}</td>
                <td title={r.t.status}>{EXIT[r.t.status] || r.t.status || '—'}</td><td className="r">{r.t.layers ?? '—'}</td><td className="r">{isNum(r.t.mae_pct) ? fmtSPct(r.t.mae_pct, 2) : '—'}</td>
                <td>{iso(r.t.enter_time) != null && <button type="button" className="n-btn sm" onClick={() => setChart(r.t)}>Biểu đồ</button>}</td>
              </tr>
            ))}
            {!rows.length && <tr><td colSpan={15}><Empty title="Không có lệnh nào" /></td></tr>}
          </tbody>
        </table>
      </div>
      <Pager total={d.total} offset={pg.offset} limit={pg.limit} onChange={setPg} />
      {chart && (
        <TradeChartDrawer open onClose={() => setChart(null)} title={`${String(chart.symbol || '').replace('@perp', '')} ${chart.side} · ${ts(chart.enter_time)}`}
          request={{ run_id: runId, alpha_id: alphaId, symbol: String(chart.symbol || '').replace('@perp', ''), source: 'data' }}
          trade={{ enter_ms: iso(chart.enter_time), close_ms: iso(chart.close_time), enter_price: chart.enter_price, close_price: chart.close_price, side: chart.side, reason: EXIT[chart.status] || chart.status, pnl: chart.pnl_usd }} />
      )}
    </div>
  )
}
