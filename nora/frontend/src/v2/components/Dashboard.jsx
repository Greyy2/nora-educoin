import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Panel, Status, Empty, ErrorBox, Spinner } from './ui'
import AreaLine from './charts/AreaLine'
import UnderwaterStrip from './charts/UnderwaterStrip'
import BarsPosNeg from './charts/BarsPosNeg'
import Histogram from './charts/Histogram'
import HeatmapTable from './charts/HeatmapTable'
import Sparkline from './charts/Sparkline'
import ProgressBar from './charts/ProgressBar'
import { getDashboard } from '../api'
import { fmtNum, fmtMoney, fmtPct, fmtSPct, fmtSigned, signClass, arrow, fmtDateTime, isNum } from '../lib/format'

export const PERIODS = [
  { value: '1M', label: '1T', long: '1 tháng' },
  { value: '3M', label: '3T', long: '3 tháng' },
  { value: 'YTD', label: 'YTD', long: 'từ đầu năm' },
  { value: '1Y', label: '1N', long: '1 năm' },
  { value: 'ALL', label: 'Tất cả', long: 'toàn kỳ' },
]
const periodLong = (p) => PERIODS.find((x) => x.value === p)?.long || p

const STATUS_VI = {
  active: ['Đang chạy', 'ok'], running: ['Đang chạy', 'ok'], paused: ['Tạm dừng', 'warn'], halted: ['Đã dừng', 'bad'], stopped: ['Đã dừng', 'bad'], idle: ['Chờ', ''],
}

function Kpi({ label, children, sub, spark, sparkColor, sparkArea }) {
  return (
    <div className="n-panel n-kpi">
      <div className="lbl">{label}</div>
      <div className="val">{children}</div>
      <div className="sub">{sub}</div>
      {spark && <Sparkline className="spark" values={spark} color={sparkColor} area={sparkArea} label={`Xu hướng ${label}`} />}
    </div>
  )
}

const Delta = ({ v, d = 2, suffix = '' }) => (
  <span className={signClass(v)}>{arrow(v)} {fmtSigned(v, d, suffix)}</span>
)

function KpiRow({ k, period }) {
  const retColor = (k.ret_period_pct ?? 0) >= 0 ? 'var(--n-pos)' : 'var(--n-neg)'
  return (
    <div className="n-grid g-kpi">
      <Kpi label="NAV" spark={k.spark_nav} sparkColor="var(--n-accent)" sparkArea
        sub={<><Delta v={k.nav_change_day} /> <Delta v={k.nav_change_day_pct} suffix="%" /></>}>
        {fmtNum(k.nav, 2)}<small>USDT</small>
      </Kpi>
      <Kpi label="Lãi/lỗ hôm nay"
        sub={<>Tháng <span className={signClass(k.pnl_month)}>{fmtMoney(k.pnl_month, true)}</span> · Năm <span className={signClass(k.pnl_year)}>{fmtMoney(k.pnl_year, true)}</span></>}>
        <span className={signClass(k.pnl_today)}>{arrow(k.pnl_today)} {fmtMoney(k.pnl_today, true)}</span><small>USDT</small>
      </Kpi>
      <Kpi label={`Lợi nhuận ${periodLong(period)}`} spark={k.spark_ret} sparkColor={retColor}
        sub={<>BTC <span className={signClass(k.bench_ret_period_pct)}>{fmtSPct(k.bench_ret_period_pct)}</span> · vượt <span className={signClass(k.excess_pct)}>{fmtSPct(k.excess_pct)}</span></>}>
        <span className={signClass(k.ret_period_pct)}>{arrow(k.ret_period_pct)} {fmtSPct(k.ret_period_pct)}</span>
      </Kpi>
      <Kpi label="Sharpe" sub={<>Sortino {fmtNum(k.sortino)} · Calmar {fmtNum(k.calmar)}</>}>{fmtNum(k.sharpe)}</Kpi>
      <Kpi label="Max drawdown" spark={k.spark_dd} sparkColor="var(--n-neg)"
        sub={<>Hiện tại <span className={signClass(k.dd_now_pct)}>{fmtPct(k.dd_now_pct)}</span></>}>
        <span className="neg">{fmtSPct(k.mdd_pct)}</span>
      </Kpi>
      <Kpi label="VaR 95% (1 ngày)" sub={<>{fmtPct(k.var95_pct)} NAV · CVaR {fmtNum(k.cvar95_1d, 1)} USDT</>}>
        {fmtNum(k.var95_1d, 1)}<small>USDT</small>
      </Kpi>
    </div>
  )
}

function RiskPanel({ r }) {
  const marginNull = !isNum(r.margin_used_pct)
  const mk = (r.by_market || [])
  const mx = Math.max(1, ...mk.flatMap((m) => [m.long_pct || 0, m.short_pct || 0])) * 1.4
  return (
    <Panel title="Rủi ro và ký quỹ">
      <div className="n-meter-top">
        <span>Ký quỹ đã dùng</span>
        <span className="v">{marginNull ? '—' : fmtPct(r.margin_used_pct, 1)}</span>
      </div>
      <ProgressBar value={r.margin_used_pct} marks={[50, 70]} warnAt={50} critAt={70} label="Ký quỹ đã dùng" />
      <div className="n-meter-scale"><span>0</span><span>cảnh báo 50 · dừng lệnh mới 70</span><span>100</span></div>
      {marginNull && <p className="n-note" style={{ marginTop: 6 }}>Backtest không có tài khoản ký quỹ nên chưa có số liệu này.</p>}
      <div className="n-tiles">
        <div className="n-tile"><div className="l">Exposure gộp</div><div className="v">{fmtPct(r.exposure_gross_pct, 0)}</div></div>
        <div className="n-tile"><div className="l">Exposure ròng</div><div className={`v ${signClass(r.exposure_net_pct)}`}>{fmtSPct(r.exposure_net_pct, 0)}</div></div>
      </div>
      {mk.length > 0 && (
        <div className="n-ls" role="group" aria-label="Long/short theo thị trường">
          <div />
          <div className="hd"><span>Short</span><span>Long</span></div>
          {mk.map((m) => (
            <React.Fragment key={m.name}>
              <b>{m.name}</b>
              <div className="bars">
                <div className="s" style={{ width: `${((m.short_pct || 0) / mx) * 100}%` }}><em>{fmtNum(m.short_pct, 0)}%</em></div>
                <div className="l" style={{ width: `${((m.long_pct || 0) / mx) * 100}%` }}><em>{fmtNum(m.long_pct, 0)}%</em></div>
              </div>
            </React.Fragment>
          ))}
        </div>
      )}
      <div className="n-stats">
        <div><span className="k">CAGR</span><span className={`v ${signClass(r.cagr_pct)}`}>{fmtSPct(r.cagr_pct, 1)}</span></div>
        <div><span className="k">Biến động năm</span><span className="v">{fmtPct(r.vol_annual_pct, 1)}</span></div>
        <div><span className="k">Tỉ lệ ngày lãi (ngày có giao dịch)</span><span className="v">{fmtPct(r.win_days_pct, 1)}</span></div>
        <div><span className="k">Profit factor</span><span className="v">{fmtNum(r.profit_factor)}</span></div>
        <div><span className="k">Vị thế mở</span><span className="v">{r.open_positions ?? '—'}</span></div>
        <div><span className="k">Chiến thuật đang chạy</span><span className="v">{r.strategies_running ?? '—'}</span></div>
      </div>
    </Panel>
  )
}

function StrategiesTable({ rows = [] }) {
  return (
    <div className="n-tblwrap">
      <table className="n-tbl">
        <thead>
          <tr><th>Chiến thuật</th><th>Trạng thái</th><th>Tỉ trọng</th><th className="r">Lãi/lỗ kỳ</th><th className="r">Đóng góp</th><th className="r">Sharpe</th><th className="r">MDD</th><th>30 ngày</th></tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const [txt, tone] = STATUS_VI[s.status] || [s.status || '—', '']
            return (
              <tr key={s.id}>
                <td><b className="mono">{s.id}</b> {s.side && <span className={`n-badge ${String(s.side).toLowerCase()}`}>{s.side}</span>}</td>
                <td><Status tone={tone}>{txt}</Status></td>
                <td><span className="n-wbar"><span className="tr"><i style={{ width: `${Math.min(100, s.weight_pct || 0)}%` }} /></span><span className="mono">{fmtNum(s.weight_pct, 0)}%</span></span></td>
                <td className={`r ${signClass(s.pnl)}`}>{arrow(s.pnl)} {fmtMoney(s.pnl, true)}</td>
                <td className={`r ${signClass(s.contribution_pct)}`}>{fmtSPct(s.contribution_pct)}</td>
                <td className="r">{fmtNum(s.sharpe)}</td>
                <td className="r neg">{fmtSPct(s.mdd_pct)}</td>
                <td style={{ width: 110 }}><Sparkline values={s.pnl_30d} color="var(--n-accent)" label={`30 ngày ${s.id}`} className="spk" /></td>
              </tr>
            )
          })}
          {!rows.length && <tr><td colSpan={8} className="muted">Chưa có chiến thuật.</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

const LEVEL = { crit: ['●', 'neg', 'Nghiêm trọng'], warn: ['▲', 'warn', 'Cảnh báo'], info: ['ℹ', 'muted', 'Thông tin'] }
function Events({ rows = [] }) {
  if (!rows.length) return <p className="n-note">Không có sự kiện rủi ro trong kỳ.</p>
  return (
    <ul className="n-events">
      {rows.map((e, i) => {
        const [ic, cls, lbl] = LEVEL[e.level] || LEVEL.info
        return (
          <li key={i}>
            <span className={`ic ${cls}`} role="img" aria-label={lbl}>{ic}</span>
            <span className="tx">{e.text}</span>
            <time>{fmtDateTime(e.time)}</time>
          </li>
        )
      })}
    </ul>
  )
}

export function DashboardView({ data }) {
  const { kpis: k = {}, series: s = {}, distribution: dist, monthly, risk = {}, strategies = [], events = [], source = {}, period } = data
  const [hi, setHi] = useState(null)
  const dates = s.dates || []
  const nDays = dates.length
  const pl = (s.daily_pnl || []).filter(isNum)
  const winDays = pl.length ? (pl.filter((x) => x > 0).length / (pl.filter((x) => x !== 0).length || 1)) * 100 : null
  const varPct = dist?.var95_pct
  const bench = source.benchmark || 'BTC@perp'
  return (
    <>
      <KpiRow k={k} period={period} />
      <div className="n-grid g-main-side">
        <Panel title={`NAV so với ${bench.replace('@perp', '')}`} meta={
          <>
            <span className="mono">{nDays} ngày</span>
            <span className="n-legend">
              <span><i style={{ borderTopColor: 'var(--n-accent)' }} />NAV</span>
              <span><i className="dash" style={{ borderTopColor: 'var(--n-bench)' }} />{bench}</span>
              <span><i className="sq" style={{ background: 'var(--n-neg)', opacity: 0.6 }} />Drawdown</span>
            </span>
          </>
        }>
          <AreaLine dates={dates} height={250} hover={hi} onHover={setHi} label="NAV so với benchmark"
            series={[
              { key: 'nav', label: 'NAV', values: s.nav || [], color: 'var(--n-accent)', area: true },
              { key: 'bench', label: bench, values: s.bench || [], color: 'var(--n-bench)', dashed: true },
            ]} />
          <div className="n-uw-h">Underwater (sụt giảm từ đỉnh)</div>
          <UnderwaterStrip dates={dates} values={s.drawdown_pct || []} hover={hi} onHover={setHi} />
        </Panel>
        <RiskPanel r={risk} />
      </div>

      <div className="n-grid g-main-side">
        <Panel title="Lãi/lỗ theo ngày" meta={<><span>Ngày lãi (ngày có giao dịch) <b className="mono">{fmtPct(risk.win_days_pct ?? winDays, 1)}</b>{isNum(risk.active_days) ? <span className="muted"> · {risk.active_days} ngày</span> : null}</span><span>Profit factor <b className="mono">{fmtNum(risk.profit_factor)}</b></span></>}>
          <BarsPosNeg dates={dates} values={s.daily_pnl || []} height={200} />
        </Panel>
        <Panel title="Phân phối lợi nhuận ngày" meta={<span>VaR 95% <b className="mono neg">{fmtSPct(varPct)}</b></span>}>
          <Histogram bins={dist?.bins || []} height={200} unit="%" xFormat={(v) => `${fmtNum(v, 1)}%`} label="Phân phối lợi nhuận ngày"
            colorOf={(b) => (isNum(varPct) && b.hi <= varPct + 1e-9 ? 'var(--n-neg)' : 'var(--n-teal)')}
            marker={isNum(varPct) ? { x: varPct, label: 'VaR 95%' } : null} />
          <div className="n-legend" style={{ marginTop: 6 }}><span><i className="sq" style={{ background: 'var(--n-neg)' }} />Vùng VaR (đuôi lỗ 5%)</span><span><i className="sq" style={{ background: 'var(--n-teal)' }} />Còn lại</span></div>
        </Panel>
      </div>

      {/* ít năm (heatmap thấp): xếp dọc để không có khoảng trống; từ 3 năm trở lên: heatmap + Sharpe cạnh nhau */}
      <div className={`n-grid ${(monthly?.years || []).length >= 3 ? 'g-6-4' : ''}`} style={{ alignItems: 'start' }}>
        <Panel title="Lợi nhuận theo tháng" meta={<span>toàn bộ lịch sử, %</span>}>
          <HeatmapTable years={monthly?.years || []} />
        </Panel>
        <Panel title="Sharpe cuốn chiếu 3 tháng" meta={<span className="n-legend"><span><i style={{ borderTopColor: 'var(--n-blue)' }} />Sharpe 63 ngày</span><span><i className="dash" />Mốc 1.0</span></span>}>
          <AreaLine dates={dates} height={200} label="Sharpe cuốn chiếu 63 ngày" refLines={[{ y: 1, label: '1.0' }]}
            series={[{ key: 'sh', label: 'Sharpe 63 ngày', values: s.rolling_sharpe_63 || [], color: 'var(--n-blue)' }]} valueFormat={(v) => fmtNum(v)} />
        </Panel>
      </div>

      <div className="n-grid g-table-ev">
        <Panel title="Hiệu suất chiến thuật" meta={<span>{strategies.length} chiến thuật · kỳ {periodLong(period)}</span>}>
          <StrategiesTable rows={strategies} />
        </Panel>
        <Panel title="Sự kiện rủi ro" meta={<span>trong kỳ</span>}>
          <Events rows={events} />
        </Panel>
      </div>
    </>
  )
}

/** Tải payload Danh mục theo nguồn và hiển thị: rỗng (kèm lý do) / lỗi / dashboard. */
export default function DashboardLoader({ source, jobId, period, onLoaded, openLink }) {
  const [st, setSt] = useState({ loading: true, data: null, error: null })
  useEffect(() => {
    if (source === 'backtest' && !jobId) { setSt({ loading: false, data: null, error: null }); return undefined }
    let dead = false
    setSt((s) => ({ ...s, loading: true, error: null }))
    getDashboard({ source, jobId, period }).then(
      (data) => { if (!dead) { setSt({ loading: false, data, error: null }); onLoaded && data.available && onLoaded(data) } },
      (e) => { if (!dead) setSt({ loading: false, data: null, error: e.message }) },
    )
    return () => { dead = true }
  }, [source, jobId, period]) // eslint-disable-line react-hooks/exhaustive-deps
  if (st.error) return <ErrorBox>Không tải được dữ liệu danh mục: {st.error}</ErrorBox>
  if (st.loading && !st.data) return <Empty title="Đang tải danh mục"><Spinner /></Empty>
  if (source === 'backtest' && !jobId) return <Empty title="Chưa chọn lần backtest">Chọn một backtest đã chạy xong ở trên, hoặc chạy mới tại <Link to="/backtest">Backtest</Link>.</Empty>
  if (!st.data?.available) {
    return <Empty title="Chưa có dữ liệu cho nguồn này">{st.data?.reason || 'Nguồn dữ liệu chưa khả dụng.'}</Empty>
  }
  return (
    <div style={{ opacity: st.loading ? 0.6 : 1, transition: 'opacity .15s' }}>
      {openLink}
      <DashboardView data={st.data} />
    </div>
  )
}
