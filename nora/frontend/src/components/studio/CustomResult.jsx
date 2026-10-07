import React, { useMemo, useState } from 'react'
import { Segmented, Empty } from '../ui'
import Term from '../Term'
import Pager from '../funnel/Pager'
import RangeBrush from './RangeBrush'
import AreaLine from '../charts/AreaLine'
import UnderwaterStrip from '../charts/UnderwaterStrip'
import { fmtNum, fmtSPct, fmtPct, fmtMoney, signClass, isNum, toMs, fmtSigned } from '../../lib/format'
import Diagnostics, { InsightList } from './Diagnostics'
import { normMetrics, normYearly, stagePlot, normWarnings, resolveCols, TRADE_COLS, SYMBOL_COLS, POSITION_COLS } from '../../lib/customResult'

const STAGES = [
  { value: 'train', label: 'Train', block: 'train' },
  { value: 'test', label: 'Test', block: 'test' },
  { value: 'all', label: 'Toàn kỳ', block: 'simulate' },
]
const BENCH_LABEL = 'Luôn long (benchmark)'
// MỘT định nghĩa cho mỗi chỉ số; cơ sở nêu một lần (BASIS_NOTE): năm = 365 ngày, lợi suất ngày = vốn mark-to-market cuối ngày UTC, win rate / profit factor theo lệnh đã đóng.
const BASIS_NOTE = 'Cơ sở: năm = 365 ngày; Sharpe, Sortino, CAGR, Calmar, Max drawdown tính trên lợi suất ngày (vốn cuối ngày UTC); tỉ lệ thắng và Profit factor tính theo từng lệnh đã đóng.'
const STAGE_VI = { train: 'Train', test: 'Test', simulate: 'Toàn kỳ' }

const p2 = (n) => String(n).padStart(2, '0')
function fmtStamp(v) {
  const ms = toMs(v)
  if (ms == null) return '—'
  const d = new Date(ms)
  return `${p2(d.getUTCDate())}/${p2(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ${p2(d.getUTCHours())}:${p2(d.getUTCMinutes())}`
}

function Tile({ label, title, children, cls = '' }) {
  return <div className="n-tile" title={title}><div className="l">{label}</div><div className={`v ${cls}`}>{children}</div></div>
}

function MetricTiles({ m }) {
  const win = (v) => (isNum(v) ? fmtPct(v, 1) : '—')
  return (
    <div className="n-tilegrid se-tiles" title={BASIS_NOTE}>
      <Tile label="Lợi nhuận" cls={signClass(m.ret)}>{fmtSPct(m.ret)}</Tile>
      <Tile label={<Term k="cagr">CAGR</Term>} cls={signClass(m.cagr)}>{fmtSPct(m.cagr)}</Tile>
      <Tile label={<Term k="sharpe">Sharpe</Term>}>{fmtNum(m.sharpe)}</Tile>
      <Tile label={<Term k="sortino">Sortino</Term>}>{fmtNum(m.sortino)}</Tile>
      <Tile label={<Term k="mdd">Max drawdown</Term>} cls={isNum(m.mdd) && m.mdd !== 0 ? 'neg' : ''}>{fmtSPct(m.mdd)}</Tile>
      <Tile label={<Term k="calmar">Calmar</Term>}>{fmtNum(m.calmar)}</Tile>
      <Tile label="Tỉ lệ thắng" title="Số lệnh lãi chia tổng số lệnh đã đóng">{win(m.winTrades)}</Tile>
      <Tile label="Profit factor" title="Tổng lãi chia tổng lỗ của các lệnh đã đóng">{fmtNum(m.pfTrades)}</Tile>
      <Tile label="Số lệnh">{isNum(m.trades) ? fmtNum(m.trades, 0) : '—'}</Tile>
      <Tile label="Phí (USDT)">{isNum(m.fees) ? fmtMoney(m.fees) : '—'}</Tile>
    </div>
  )
}

function Cell({ kind, v }) {
  if (v == null || v === '') return <>—</>
  switch (kind) {
    case 'time': return <>{fmtStamp(v)}</>
    case 'sym': return <b>{String(v).replace('@perp', '')}</b>
    case 'side': return <span className={`n-badge ${String(v).toLowerCase()}`}>{String(v).toUpperCase()}</span>
    case 'price': return <>{fmtNum(v, Math.abs(v) >= 100 ? 2 : 4)}</>
    case 'qty': return <>{fmtNum(v, Math.abs(v) >= 100 ? 1 : 4)}</>
    case 'int': return <>{fmtNum(v, 0)}</>
    case 'spct': return <span className={signClass(v)}>{fmtSPct(v)}</span>
    case 'money': return <span className={signClass(v)}>{fmtSigned(v, 2)}</span>
    case 'num': return <>{isNum(v) ? fmtNum(v) : String(v)}</>
    default: return <>{String(v)}</>
  }
}

/** Bảng dữ liệu theo danh sách cột đã giải quyết (resolveCols). */
function Rows({ rows, spec, empty }) {
  const cols = useMemo(() => resolveCols(rows, spec), [rows, spec])
  if (!rows.length) return <p className="n-note">{empty}</p>
  return (
    <div className="n-tblwrap">
      <table className="n-tbl">
        <thead><tr>{cols.map((c) => <th key={c.key} className={c.r ? 'r' : ''}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c.key} className={c.r ? 'r' : ''}><Cell kind={c.kind} v={r[c.key]} /></td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TradesTable({ trades }) {
  const [pg, setPg] = useState({ offset: 0, limit: 50 })
  const slice = trades.slice(pg.offset, pg.offset + pg.limit)
  return (
    <>
      <Rows rows={slice} spec={TRADE_COLS} empty="Không có lệnh nào được đóng trong kỳ." />
      {trades.length > 25 && <Pager total={trades.length} offset={pg.offset} limit={pg.limit} onChange={setPg} />}
    </>
  )
}


const SUBS = [{ value: 'overview', label: 'Tổng quan' }, { value: 'perf', label: 'Hiệu suất' }, { value: 'analysis', label: 'Phân tích' }]
const CHARTS = [
  { key: 'equity', label: 'Đường vốn (Equity)' },
  { key: 'pnl', label: 'Lãi lỗ (PnL)' },
  { key: 'dd', label: 'Drawdown' },
  { key: 'ret', label: 'Lợi suất ngày' },
]
const I = {
  min: <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 12h12" /></svg>,
  max: <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg>,
}

function Agg({ m }) {
  const c = (v) => (isNum(v) ? signClass(v) : '')
  return (
    <div className="se-agg">
      <div className="se-agg-t">Dữ liệu tổng hợp</div>
      <div className="se-agg-c"><span className="l">Sharpe</span><b>{fmtNum(m?.sharpe)}</b></div>
      <div className="se-agg-c"><span className="l">CAGR</span><b className={c(m?.cagr)}>{fmtSPct(m?.cagr)}</b></div>
      <div className="se-agg-c"><span className="l">Drawdown</span><b className={isNum(m?.mdd) && m.mdd !== 0 ? 'neg' : ''}>{fmtSPct(m?.mdd)}</b></div>
      <div className="se-agg-c"><span className="l">Profit Factor</span><b>{fmtNum(m?.pfTrades)}</b></div>
      <div className="se-agg-c"><span className="l">Calmar</span><b>{fmtNum(m?.calmar)}</b></div>
    </div>
  )
}

function YearlyTable({ rows }) {
  if (!rows.length) return <p className="n-note se-pad">Không có số liệu theo năm cho giai đoạn này.</p>
  return (
    <div className="se-yr n-tblwrap">
      <table className="n-tbl">
        <thead><tr><th>Năm</th><th>Sharpe</th><th>CAGR</th><th>Max Drawdown</th><th>Profit Factor</th><th>Calmar</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.year}-${r.stage}-${i}`}>
              <td className="mono">{r.year}</td><td className="mono">{fmtNum(r.sharpe)}</td>
              <td className={`mono ${signClass(r.cagr)}`}>{fmtSPct(r.cagr)}</td><td className="mono neg">{fmtSPct(r.mdd)}</td>
              <td className="mono">{fmtNum(r.pf)}</td><td className="mono">{fmtNum(r.calmar)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ChartCard({ title, children, tall = 1 }) {
  const [min, setMin] = useState(false)
  const [big, setBig] = useState(false)
  return (
    <section className="se-cc">
      <div className="se-cc-h"><b>{title}</b><span className="sp" />
        <button type="button" className="n-icon-btn" aria-label={min ? 'Mở rộng' : 'Thu nhỏ'} title={min ? 'Mở rộng' : 'Thu nhỏ'} onClick={() => setMin(!min)}>{I.min}</button>
        <button type="button" className="n-icon-btn" aria-label="Phóng to" title="Phóng to / thu về" onClick={() => { setBig(!big); setMin(false) }}>{I.max}</button>
      </div>
      {!min && <div className="se-cc-b">{children(big ? 1.7 : tall)}</div>}
    </section>
  )
}

/** Kết quả một lần chạy: result = result.json của job custom_backtest. Bố cục: hàng Giai đoạn, Tổng quan / Hiệu suất / Phân tích, Biểu đồ. */
export default function CustomResult({ result, jobLine }) {
  const [stage, setStage] = useState('all')
  const [sub, setSub] = useState('overview')
  const [shown, setShown] = useState({ equity: true, pnl: true, dd: true, ret: false })
  const [pick, setPick] = useState(false)
  const [range, setRange] = useState([0, 1])
  const [hi, setHi] = useState(null)
  const metrics = useMemo(() => Object.fromEntries(STAGES.map((s) => [s.value, normMetrics(result?.metrics?.[s.block])])), [result])
  const ser = useMemo(() => stagePlot(result?.series, stage), [result, stage])      // chuỗi do backend tính (series.stages); trình duyệt chỉ vẽ
  const bench = ser?.bench || null
  const yearlyAll = useMemo(() => normYearly(result?.yearly), [result])
  const hasM = (r) => [r.sharpe, r.cagr, r.mdd, r.pf, r.calmar].some(isNum)
  const yearly = (stage === 'all' ? yearlyAll : yearlyAll.filter((r) => r.stage === stage)).filter(hasM)
  const warnings = normWarnings(result?.warnings)
  const trades = Array.isArray(result?.trades) ? result.trades : []
  const bySym = Array.isArray(result?.by_symbol) ? result.by_symbol : []
  const open = Array.isArray(result?.positions_open) ? result.positions_open : []
  if (!result || typeof result !== 'object') return <Empty title="Chưa có kết quả">Job đã xong nhưng máy chủ không trả <code>result</code>.</Empty>

  const cfg = result.config || {}
  const m = metrics[stage] || metrics.all
  const opts = STAGES.map((s) => ({ ...s, disabled: !metrics[s.value], title: metrics[s.value] ? undefined : 'Không có số liệu cho giai đoạn này' }))
  const sl = (arr) => {
    const n = arr.length
    const a = Math.floor(range[0] * n)
    const b = Math.max(a + 2, Math.ceil(range[1] * n))
    return arr.slice(a, b)
  }
  const a0 = ser ? Math.floor(range[0] * ser.dates.length) : 0
  const marks = ser && ser.splitIdx - a0 > 0 && stage === 'all' ? [{ i: ser.splitIdx - a0, label: 'Train | Test' }] : []
  const body = (k) => (ser ? {
    equity: (f) => <AreaLine dates={sl(ser.dates)} height={Math.round(260 * f)} hover={hi} onHover={setHi} marks={marks} label="Đường vốn" series={[{ key: 'e', label: 'Vốn (USDT)', values: sl(ser.equity), color: 'var(--n-brand, #3b82f6)', area: true }, ...(bench ? [{ key: 'b', label: BENCH_LABEL, values: sl(bench.equity), color: 'var(--n-bench)', dashed: true }] : [])]} />,
    pnl: (f) => <AreaLine dates={sl(ser.dates)} height={Math.round(260 * f)} hover={hi} onHover={setHi} marks={marks} label="Lãi lỗ" series={[{ key: 'p', label: 'PnL (USDT)', values: sl(ser.pnl), color: 'var(--n-pos)', area: true }, ...(bench ? [{ key: 'b', label: BENCH_LABEL, values: sl(bench.pnl), color: 'var(--n-bench)', dashed: true }] : [])]} />,
    dd: (f) => <UnderwaterStrip dates={sl(ser.dates)} values={sl(ser.dd)} height={Math.round(180 * f)} hover={hi} onHover={setHi} marks={marks} />,
    ret: (f) => <AreaLine dates={sl(ser.dates)} height={Math.round(180 * f)} hover={hi} onHover={setHi} label="Lợi suất ngày" valueFormat={(v) => `${fmtNum(v, 1)}%`} series={[{ key: 'r', label: 'Lợi suất ngày (%)', values: sl(ser.ret), color: 'var(--n-info)' }]} />,
  }[k] : null)

  return (
    <div className="se-res">
      <div className="se-row1">
        <span className="se-lbl">Giai đoạn:</span>
        <Segmented label="Giai đoạn" value={stage} onChange={setStage} options={opts} />
        <span className="se-sp" />
        {jobLine}
        {result.program_hash && <span className="mono muted" title="Mã băm chương trình đã biên dịch">{String(result.program_hash).slice(0, 12)}</span>}
      </div>
      <div className="se-row2">
        <Segmented label="Chế độ xem" value={sub} onChange={setSub} options={SUBS} />
        <span className="se-sp" />
        {sub === 'overview' && (
          <div className="se-pick">
            <span className="se-lbl">Biểu đồ:</span>
            <button type="button" className="n-sel se-pickb" aria-haspopup="true" aria-expanded={pick} onClick={() => setPick(!pick)}>
              {CHARTS.filter((c) => shown[c.key]).length} đã chọn ▾
            </button>
            {pick && (
              <div className="n-pop se-pickp" role="group" aria-label="Chọn biểu đồ">
                {CHARTS.map((c) => (
                  <label key={c.key}><input type="checkbox" checked={!!shown[c.key]} onChange={() => setShown({ ...shown, [c.key]: !shown[c.key] })} />{c.label}</label>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {!(metrics.train || metrics.test || metrics.all) && <p className="n-note">Kết quả không có khối <code>metrics</code>.</p>}

      {sub === 'overview' && (
        <>
          <Agg m={m} />
          {Array.isArray(result?.insights) && result.insights.length > 0 && (
            <section className="se-cc">
              <div className="se-cc-h">
                <b>Nhận xét định lượng</b>
                <span className="sp" />
                <span className="muted">{result.insights.length} phát hiện</span>
              </div>
              <div className="se-cc-b"><InsightList insights={result.insights} /></div>
            </section>
          )}
          <YearlyTable rows={yearly} />
          {yearly.length > 0 && <p className="n-note se-pad">{BASIS_NOTE}</p>}
          {!ser && <p className="n-note se-pad">Không có chuỗi vốn cho giai đoạn này.</p>}
          {ser && bench && (shown.equity || shown.pnl) && <p className="n-note se-pad">Đường nét đứt: benchmark luôn long (cùng rổ, vốn và khoảng ngày){stage === 'test' ? ', được backend chạy lại trên chính cửa sổ Test từ vốn đầu' : ''}.</p>}
          {ser && !bench && (shown.equity || shown.pnl) && <p className="n-note se-pad">Không có benchmark cho giai đoạn này.</p>}
          {ser?.downsample?.step > 1 && <p className="n-note se-pad">Biểu đồ đã hạ mẫu ở backend: mỗi điểm gộp {ser.downsample.step} ngày ({fmtNum(ser.downsample.source_points, 0)} → {fmtNum(ser.downsample.points, 0)} điểm); equity lấy cuối nhóm, drawdown lấy đáy nhóm, lợi suất là lãi kép của nhóm.</p>}
          {ser && CHARTS.filter((c) => shown[c.key]).map((c, i, arr) => (
            <ChartCard key={c.key} title={c.label}>
              {(f) => <>
                {body(c.key)(f)}
                {i === 0 && <RangeBrush values={ser.equity} range={range} onChange={setRange} />}
              </>}
            </ChartCard>
          ))}
        </>
      )}

      {sub === 'perf' && (
        <>
          {m ? <section className="se-cc"><div className="se-cc-h"><b>Chỉ số</b></div><div className="se-cc-b"><MetricTiles m={m} />
            <p className="n-note" style={{ marginTop: 8 }}>{BASIS_NOTE}</p></div></section>
            : <p className="n-note se-pad">Không có số liệu cho giai đoạn này.</p>}
          {bySym.length > 0 && <section className="se-cc"><div className="se-cc-h"><b>Theo tài sản</b><span className="sp" /><span className="muted">{bySym.length} tài sản</span></div><div className="se-cc-b"><Rows rows={bySym} spec={SYMBOL_COLS} empty="" /></div></section>}
        </>
      )}

      {sub === 'analysis' && (
        <>
          <Diagnostics result={result} />
          {Array.isArray(result?.trades) ? <section className="se-cc"><div className="se-cc-h"><b>Danh sách lệnh</b><span className="sp" /><span className="muted">{fmtNum(trades.length, 0)} lệnh</span></div><div className="se-cc-b"><TradesTable trades={trades} /></div></section>
            : <p className="n-note se-pad">Kết quả không kèm danh sách lệnh.</p>}
          {open.length > 0 && <section className="se-cc"><div className="se-cc-h"><b>Vị thế còn mở cuối kỳ</b><span className="sp" /><span className="muted">{open.length}</span></div><div className="se-cc-b"><Rows rows={open} spec={POSITION_COLS} empty="" /></div></section>}
          {warnings.length > 0 && (
            <section className="se-cc"><div className="se-cc-h"><b>Cảnh báo</b><span className="sp" /><span className="muted">{warnings.length}</span></div><div className="se-cc-b">
              <ul className="n-events">{warnings.map((w, i) => <li key={i}><span className="ic warn" role="img" aria-label="Cảnh báo">▲</span><span className="tx">{w}</span></li>)}</ul></div></section>
          )}
        </>
      )}
    </div>
  )
}
