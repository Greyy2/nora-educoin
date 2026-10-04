import React, { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Panel, Status, Empty, Loading, ErrorState } from './ui'
import Term from './Term'
import { FamilyStatsPanel, TradesPanel, RegimePanel } from './OverviewExtras'
import DetailSection from './portfolio/DetailSection'
import AreaLine from './charts/AreaLine'
import UnderwaterStrip from './charts/UnderwaterStrip'
import BarsPosNeg from './charts/BarsPosNeg'
import Histogram from './charts/Histogram'
import HeatmapTable from './charts/HeatmapTable'
import Sparkline from './charts/Sparkline'
import ProgressBar from './charts/ProgressBar'
import { getDashboard } from '../api'
import { fmtNum, fmtMoney, fmtPct, fmtSPct, fmtSigned, signClass, arrow, fmtDateTime, isNum } from '../lib/format'
import { legLabel } from '../lib/strategyLabel'


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

function Kpi({ label, labelText, children, sub, spark, sparkColor, sparkArea }) {
  return (
    <div className="n-panel n-kpi">
      <div className="lbl">{label}</div>
      <div className="val">{children}</div>
      <div className="sub">{sub}</div>
      {spark && <Sparkline className="spark" values={spark} color={sparkColor} area={sparkArea} label={`Xu hướng ${labelText || (typeof label === 'string' ? label : '')}`.trim()} />}
    </div>
  )
}

const Delta = ({ v, d = 2, suffix = '' }) => (
  <span className={signClass(v)}>{arrow(v)} {fmtSigned(v, d, suffix)}</span>
)

// "BTC +26.45% · chênh −12.60 điểm %": chênh lệch (điểm phần trăm) = lợi nhuận danh mục − lợi nhuận benchmark, tô màu theo dấu
function BenchSub({ bench, k }) {
  const excess = isNum(k.excess_pct) ? k.excess_pct : (isNum(k.ret_period_pct) && isNum(k.bench_ret_period_pct) ? k.ret_period_pct - k.bench_ret_period_pct : null)
  return (
    <>
      {bench} <span className={signClass(k.bench_ret_period_pct)}>{fmtSPct(k.bench_ret_period_pct)}</span>
      {' · '}<span style={{ whiteSpace: 'nowrap' }}>chênh <span className={signClass(excess)}>{fmtSigned(excess, 2)} điểm %</span></span>
    </>
  )
}

function KpiRow({ k, period, bench = 'BTC' }) {
  const retColor = (k.ret_period_pct ?? 0) >= 0 ? 'var(--n-pos)' : 'var(--n-neg)'
  return (
    <div className="n-grid g-kpi">
      <Kpi label={<Term k="nav">NAV</Term>} labelText="NAV" spark={k.spark_nav} sparkColor="var(--n-accent)" sparkArea
        sub={<><Delta v={k.nav_change_day} /> <Delta v={k.nav_change_day_pct} suffix="%" /></>}>
        {fmtNum(k.nav, 2)}<small>USDT</small>
      </Kpi>
      <Kpi label="Lãi/lỗ hôm nay"
        sub={<>Tháng <span className={signClass(k.pnl_month)}>{fmtMoney(k.pnl_month, true)}</span> · Năm <span className={signClass(k.pnl_year)}>{fmtMoney(k.pnl_year, true)}</span></>}>
        <span className={signClass(k.pnl_today)}>{arrow(k.pnl_today)} {fmtMoney(k.pnl_today, true)}</span><small>USDT</small>
      </Kpi>
      <Kpi label={`Lợi nhuận ${periodLong(period)}`} labelText={`Lợi nhuận ${periodLong(period)}`} spark={k.spark_ret} sparkColor={retColor}
        sub={<BenchSub bench={bench} k={k} />}>
        <span className={signClass(k.ret_period_pct)}>{arrow(k.ret_period_pct)} {fmtSPct(k.ret_period_pct)}</span>
      </Kpi>
      <Kpi label={<Term k="sharpe">Sharpe</Term>} sub={<><Term k="sortino">Sortino</Term> {fmtNum(k.sortino)} · <Term k="calmar">Calmar</Term> {fmtNum(k.calmar)}</>}>{fmtNum(k.sharpe)}</Kpi>
      <Kpi label={<Term k="mdd">Max drawdown</Term>} labelText="Max drawdown" spark={k.spark_dd} sparkColor="var(--n-neg)"
        sub={<>Hiện tại <span className={signClass(k.dd_now_pct)}>{fmtPct(k.dd_now_pct)}</span></>}>
        <span className="neg">{fmtSPct(k.mdd_pct)}</span>
      </Kpi>
      <Kpi label={<Term k="var95">VaR 95% (1 ngày)</Term>} sub={<>{fmtPct(k.var95_pct)} NAV · <Term k="cvar">CVaR</Term> {fmtNum(k.cvar95_1d, 1)} USDT</>}>
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
      {!marginNull && (
        <>
          <div className="n-meter-top">
            <span><Term k="margin_used">Ký quỹ đã dùng</Term></span>
            <span className="v">{fmtPct(r.margin_used_pct)}</span>
          </div>
          <ProgressBar value={r.margin_used_pct} marks={[50, 70]} warnAt={50} critAt={70} label="Ký quỹ đã dùng" />
          <div className="n-meter-scale"><span>0</span><span>cảnh báo 50 · dừng lệnh mới 70</span><span>100</span></div>
        </>
      )}
      {marginNull && <p className="n-note" style={{ marginTop: 6 }}>Backtest không có tài khoản ký quỹ nên chưa có số liệu này.</p>}
      {(isNum(r.exposure_gross_pct) || isNum(r.exposure_net_pct)) && (
        <div className="n-tiles">
          {isNum(r.exposure_gross_pct) && <div className="n-tile"><div className="l"><Term k="exposure_gross">Exposure gộp</Term></div><div className="v">{fmtPct(r.exposure_gross_pct)}</div></div>}
          {isNum(r.exposure_net_pct) && <div className="n-tile"><div className="l"><Term k="exposure_net">Exposure ròng</Term></div><div className={`v ${signClass(r.exposure_net_pct)}`}>{fmtSPct(r.exposure_net_pct)}</div></div>}
        </div>
      )}
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
        {[
          [<Term k="cagr">CAGR</Term>, r.cagr_pct, fmtSPct(r.cagr_pct), signClass(r.cagr_pct)],
          [<Term k="vol_annual">Biến động năm</Term>, r.vol_annual_pct, fmtPct(r.vol_annual_pct)],
          [<><Term k="win_days">Tỉ lệ ngày lãi</Term> (ngày có giao dịch)</>, r.win_days_pct, fmtPct(r.win_days_pct)],
          [<Term k="profit_factor">Profit factor</Term>, r.profit_factor, fmtNum(r.profit_factor)],
          ['Vị thế mở', r.open_positions, r.open_positions],
          ['Chiến thuật đang chạy', r.strategies_running, r.strategies_running],
        ].filter(([, raw]) => isNum(raw)).map(([k, , v, cls], i) => <div key={i}><span className="k">{k}</span><span className={`v ${cls || ''}`}>{v}</span></div>)}
      </div>
    </Panel>
  )
}

function StrategiesTable({ rows = [] }) {
  return (
    <div className="n-tblwrap">
      <table className="n-tbl">
        <thead>
          <tr><th>Chiến thuật</th><th>Trạng thái</th><th>Tỉ trọng</th><th className="r">Lãi/lỗ kỳ</th><th className="r">Đóng góp</th><th className="r"><Term k="sharpe">Sharpe</Term></th><th className="r"><Term k="mdd">MDD</Term></th><th>30 ngày</th></tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const [txt, tone] = STATUS_VI[s.status] || [s.status || '—', '']
            return (
              <tr key={s.id}>
                <td><b title={s.id}>{legLabel(s.id)}</b> {s.side && legLabel(s.id) === s.id && <span className={`n-badge ${String(s.side).toLowerCase()}`}>{s.side}</span>}</td>
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

function PositionsTable({ rows = [] }) {
  return (
    <div className="n-tblwrap">
      <table className="n-tbl">
        <thead>
          <tr><th>Tài sản</th><th>Chiến thuật</th><th>Chiều</th><th className="r">Khối lượng</th><th className="r">Giá vào</th><th className="r">Giá hiện tại</th>
            <th className="r">Giá trị</th><th className="r">Lãi/lỗ chưa chốt</th><th>Mở lúc</th></tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={`${p.symbol}|${p.strategy}|${p.opened}`}>
              <td><b className="mono">{String(p.symbol).replace('@perp', '')}</b></td>
              <td title={p.strategy}>{legLabel(p.strategy)}</td>
              <td><span className={`n-badge ${String(p.side).toLowerCase()}`}>{p.side}</span></td>
              <td className="r">{fmtNum(p.qty, p.qty >= 100 ? 1 : 4)}</td>
              <td className="r">{fmtNum(p.entry_price, p.entry_price >= 100 ? 2 : 4)}</td>
              <td className="r">{fmtNum(p.mark_price, p.mark_price >= 100 ? 2 : 4)}</td>
              <td className="r">{fmtNum(p.notional, 2)}<small className="muted"> USDT</small></td>
              <td className={`r ${signClass(p.unrealized_pnl)}`}>{arrow(p.unrealized_pnl)} {fmtMoney(p.unrealized_pnl, true)}</td>
              <td className="mono">{fmtDateTime(p.opened)}</td>
            </tr>
          ))}
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

/** Biểu đồ phụ (lãi/lỗ ngày, phân phối, theo tháng, Sharpe cuốn chiếu); khối nào thiếu dữ liệu thì ẩn hẳn. */
function ExtraCharts({ s, dist, monthly, risk }) {
  const dates = s.dates || []
  const pl = (s.daily_pnl || []).filter(isNum)
  const winDays = pl.length ? (pl.filter((x) => x > 0).length / (pl.filter((x) => x !== 0).length || 1)) * 100 : null
  const varPct = dist?.var95_pct
  const hasRoll = (s.rolling_sharpe_63 || []).filter(isNum).length >= 2
  const years = monthly?.years || []
  return (
    <>
      {(pl.length > 0 || (dist?.bins || []).length > 0) && (
        <div className="n-grid g-main-side">
          {pl.length > 0 && (
            <Panel title="Lãi/lỗ theo ngày" meta={<><span><Term k="win_days">Ngày lãi</Term> (ngày có giao dịch) <b className="mono">{fmtPct(risk.win_days_pct ?? winDays)}</b>{isNum(risk.active_days) ? <span className="muted"> · {risk.active_days} ngày</span> : null}</span>{isNum(risk.profit_factor) && <span><Term k="profit_factor">Profit factor</Term> <b className="mono">{fmtNum(risk.profit_factor)}</b></span>}</>}>
              <BarsPosNeg dates={dates} values={s.daily_pnl || []} height={200} />
            </Panel>
          )}
          {(dist?.bins || []).length > 0 && (
            <Panel title="Phân phối lợi nhuận ngày" meta={isNum(varPct) ? <span><Term k="var95">VaR 95%</Term> <b className="mono neg">{fmtSPct(varPct)}</b></span> : null}>
              <Histogram bins={dist.bins} height={200} unit="%" xFormat={(v) => `${fmtNum(v, 1)}%`} label="Phân phối lợi nhuận ngày"
                colorOf={(b) => (isNum(varPct) && b.hi <= varPct + 1e-9 ? 'var(--n-neg)' : 'var(--n-teal)')}
                marker={isNum(varPct) ? { x: varPct, label: 'VaR 95%' } : null} />
              <div className="n-legend" style={{ marginTop: 6 }}><span><i className="sq" style={{ background: 'var(--n-neg)' }} />Vùng VaR (đuôi lỗ 5%)</span><span><i className="sq" style={{ background: 'var(--n-teal)' }} />Còn lại</span></div>
            </Panel>
          )}
        </div>
      )}
      {/* ít năm (heatmap thấp): xếp dọc để không có khoảng trống; từ 3 năm trở lên: heatmap + Sharpe cạnh nhau */}
      {(years.length > 0 || hasRoll) && (
        <div className={`n-grid ${years.length >= 3 && hasRoll ? 'g-6-4' : ''}`} style={{ alignItems: 'start' }}>
          {years.length > 0 && (
            <Panel title="Lợi nhuận theo tháng" meta={<span>toàn bộ lịch sử, %</span>}>
              <HeatmapTable years={years} />
            </Panel>
          )}
          {hasRoll && (
            <Panel title={<><Term k="sharpe">Sharpe</Term> cuốn chiếu 3 tháng</>} meta={<span className="n-legend"><span><i style={{ borderTopColor: 'var(--n-blue)' }} />Sharpe 63 ngày</span><span><i className="dash" />Mốc 1.0</span></span>}>
              <AreaLine dates={dates} height={200} label="Sharpe cuốn chiếu 63 ngày" refLines={[{ y: 1, label: '1.0' }]}
                series={[{ key: 'sh', label: 'Sharpe 63 ngày', values: s.rolling_sharpe_63 || [], color: 'var(--n-blue)' }]} valueFormat={(v) => fmtNum(v)} />
            </Panel>
          )}
        </div>
      )}
    </>
  )
}

const unrealizedOf = (positions) => positions.reduce((a, p) => a + (isNum(p.unrealized_pnl) ? p.unrealized_pnl : 0), 0)

/** Tổng quan ngắn gọn: hàng KPI, một biểu đồ NAV, vài khối tóm tắt; mọi thứ chi tiết nằm trong các mục thu gọn. */
function OverviewView({ data, ctx }) {
  const { kpis: k = {}, series: s = {}, risk = {}, strategies = [], events = [], positions = [], source = {}, period } = data
  const st = data.stats || {}
  const t = st.trades || {}
  const bench = (source.benchmark || 'BTC@perp').replace('@perp', '')
  const dates = s.dates || []
  const [hi, setHi] = useState(null)
  const net = unrealizedOf(positions)
  const retColor = (k.ret_period_pct ?? 0) >= 0 ? 'var(--n-pos)' : 'var(--n-neg)'
  const sortino = isNum(k.sortino) ? <><Term k="sortino">Sortino</Term> {fmtNum(k.sortino)}</> : null
  const calmar = isNum(k.calmar) ? <><Term k="calmar">Calmar</Term> {fmtNum(k.calmar)}</> : null
  const kpis = [
    isNum(k.nav) && (
      <Kpi key="nav" label={<Term k="nav">NAV</Term>} labelText="NAV" spark={k.spark_nav} sparkColor="var(--n-accent)" sparkArea
        sub={isNum(k.nav_change_day) ? <><Delta v={k.nav_change_day} /> <Delta v={k.nav_change_day_pct} suffix="%" /> hôm nay</> : null}>
        {fmtNum(k.nav, 2)}<small>USDT</small>
      </Kpi>
    ),
    isNum(k.ret_period_pct) && (
      <Kpi key="ret" label={`Lợi nhuận ${periodLong(period)}`} spark={k.spark_ret} sparkColor={retColor} sub={isNum(k.bench_ret_period_pct) ? <BenchSub bench={bench} k={k} /> : null}>
        <span className={signClass(k.ret_period_pct)}>{arrow(k.ret_period_pct)} {fmtSPct(k.ret_period_pct)}</span>
      </Kpi>
    ),
    isNum(k.mdd_pct) && (
      <Kpi key="mdd" label={<Term k="mdd">Max drawdown</Term>} labelText="Max drawdown" spark={k.spark_dd} sparkColor="var(--n-neg)"
        sub={isNum(k.dd_now_pct) ? <>Hiện tại <span className={signClass(k.dd_now_pct)}>{fmtPct(k.dd_now_pct)}</span></> : null}>
        <span className="neg">{fmtSPct(k.mdd_pct)}</span>
      </Kpi>
    ),
    isNum(k.sharpe) && (
      <Kpi key="sharpe" label={<Term k="sharpe">Sharpe</Term>} sub={sortino || calmar ? <>{sortino}{sortino && calmar ? ' · ' : ''}{calmar}</> : null}>{fmtNum(k.sharpe)}</Kpi>
    ),
    isNum(t.trades) && (
      <Kpi key="trades" label="Số lệnh" sub={<>toàn kỳ chạy{t.long?.trades >= 0 && t.short?.trades >= 0 ? ` · Long ${t.long.trades} · Short ${t.short.trades}` : ''}</>}>{t.trades}</Kpi>
    ),
    isNum(t.win_rate) && (
      <Kpi key="win" label="Tỉ lệ thắng" sub={isNum(t.profit_factor) ? <><Term k="profit_factor">Profit factor</Term> {fmtNum(t.profit_factor)}</> : null}>{fmtPct(t.win_rate, 1)}</Kpi>
    ),
  ].filter(Boolean)

  const TOP = 5
  const hasRisk = isNum(risk.margin_used_pct) || isNum(risk.exposure_gross_pct) || positions.length > 0
  return (
    <>
      {kpis.length > 0 && <div className="pf-kpis">{kpis}</div>}

      {dates.length > 1 && (
        <Panel title={<><Term k="nav">NAV</Term> so với {bench}</>} meta={
          <>
            <span className="mono">{dates.length} ngày</span>
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
          <div className="n-uw-h"><Term k="underwater">Underwater</Term> (sụt giảm từ đỉnh)</div>
          <UnderwaterStrip dates={dates} values={s.drawdown_pct || []} hover={hi} onHover={setHi} />
        </Panel>
      )}

      <div className="pf-blocks" style={{ marginTop: 12 }}>
        {strategies.length > 0 && (
          <Panel title="Chiến thuật" meta={<span>kỳ {periodLong(period)}</span>}>
            <div className="n-tblwrap">
              <table className="n-tbl">
                <thead><tr><th>Chiến thuật</th><th className="r">Lãi/lỗ</th><th className="r">Đóng góp</th></tr></thead>
                <tbody>
                  {strategies.slice(0, TOP).map((x) => (
                    <tr key={x.id}>
                      <td><b title={x.id}>{legLabel(x.id)}</b> {x.side && legLabel(x.id) === x.id && <span className={`n-badge ${String(x.side).toLowerCase()}`}>{x.side}</span>}</td>
                      <td className={`r ${signClass(x.pnl)}`}>{arrow(x.pnl)} {fmtMoney(x.pnl, true)}</td>
                      <td className={`r ${signClass(x.contribution_pct)}`}>{fmtSPct(x.contribution_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {strategies.length > TOP && <p className="pf-more">+{strategies.length - TOP} chiến thuật khác trong mục Chi tiết bên dưới.</p>}
          </Panel>
        )}
        {hasRisk && (
          <Panel title="Rủi ro và vị thế">
            {isNum(risk.margin_used_pct) && (
              <>
                <div className="n-meter-top">
                  <span><Term k="margin_used">Ký quỹ đã dùng</Term></span>
                  <span className="v">{fmtPct(risk.margin_used_pct)}</span>
                </div>
                <ProgressBar value={risk.margin_used_pct} marks={[50, 70]} warnAt={50} critAt={70} label="Ký quỹ đã dùng" />
              </>
            )}
            {(isNum(risk.exposure_gross_pct) || isNum(risk.exposure_net_pct)) && (
              <div className="n-tiles">
                {isNum(risk.exposure_gross_pct) && <div className="n-tile"><div className="l"><Term k="exposure_gross">Exposure gộp</Term></div><div className="v">{fmtPct(risk.exposure_gross_pct)}</div></div>}
                {isNum(risk.exposure_net_pct) && <div className="n-tile"><div className="l"><Term k="exposure_net">Exposure ròng</Term></div><div className={`v ${signClass(risk.exposure_net_pct)}`}>{fmtSPct(risk.exposure_net_pct)}</div></div>}
              </div>
            )}
            {positions.length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div className="pf-line"><span className="k">Vị thế đang mở</span><span className="v">{positions.length}</span></div>
                <div className="pf-line"><span className="k">Lãi/lỗ chưa chốt</span><span className={`v ${signClass(net)}`}>{fmtMoney(net, true)} USDT</span></div>
              </div>
            )}
          </Panel>
        )}
      </div>

      <h2 className="pf-details-h">Chi tiết</h2>
      {(strategies.length > 0 || events.length > 0 || (data.strategy_stats || []).length > 0) && (
        <DetailSection title="Chiến thuật và sự kiện rủi ro" hint={`${strategies.length} chiến thuật${events.length ? ` · ${events.length} sự kiện` : ''}`}>
          {strategies.length > 0 && (
            <Panel title="Hiệu suất chiến thuật" meta={<span>{strategies.length} chiến thuật · kỳ {periodLong(period)}</span>}>
              <StrategiesTable rows={strategies} />
            </Panel>
          )}
          {events.length > 0 && (
            <Panel title="Sự kiện rủi ro" meta={<span>trong kỳ</span>} className="pf-gap"><Events rows={events} /></Panel>
          )}
          {(data.strategy_stats || []).length > 0 && <div className="pf-gap"><FamilyStatsPanel rows={data.strategy_stats} period={periodLong(period)} /></div>}
        </DetailSection>
      )}
      {positions.length > 0 && (
        <DetailSection title="Vị thế đang mở" hint={`${positions.length} vị thế · chưa chốt ${fmtMoney(net, true)} USDT`}>
          <PositionsTable rows={positions} />
        </DetailSection>
      )}
      <DetailSection title="Biểu đồ phụ" hint="lãi/lỗ ngày, phân phối, theo tháng, Sharpe cuốn chiếu">
        <ExtraCharts s={s} dist={data.distribution} monthly={data.monthly} risk={risk} />
      </DetailSection>
      {data.stats && (
        <DetailSection title="Số đo chi tiết" hint="toàn kỳ chạy">
          <StatsPanel stats={data.stats} mdd={data.mdd} bare />
        </DetailSection>
      )}
      <DetailSection title="Regime thị trường" hint="theo từng tài sản">
        <RegimePanel bare />
      </DetailSection>
      {ctx && (
        <DetailSection title="Danh sách lệnh" hint="lọc, sắp xếp, tải CSV">
          <TradesPanel jobId={ctx.jobId} period={period} bare />
        </DetailSection>
      )}
    </>
  )
}

export function DashboardView({ compact = false, ...props }) {
  return compact ? <OverviewView {...props} /> : <FullView {...props} />
}

/** Bản đầy đủ (dùng ở trang Backtest). */
function FullView({ data, ctx }) {
  const { kpis: k = {}, series: s = {}, distribution: dist, monthly, risk = {}, strategies = [], events = [], positions = [], source = {}, period } = data
  const [hi, setHi] = useState(null)
  const dates = s.dates || []
  const nDays = dates.length
  const bench = source.benchmark || 'BTC@perp'
  const net = unrealizedOf(positions)
  return (
    <>
      <KpiRow k={k} period={period} bench={bench.replace('@perp', '')} />
      <div className="n-grid g-main-side">
        <Panel title={<><Term k="nav">NAV</Term> so với {bench.replace('@perp', '')}</>} meta={
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
          <div className="n-uw-h"><Term k="underwater">Underwater</Term> (sụt giảm từ đỉnh)</div>
          <UnderwaterStrip dates={dates} values={s.drawdown_pct || []} hover={hi} onHover={setHi} />
        </Panel>
        <RiskPanel r={risk} />
      </div>

      <ExtraCharts s={s} dist={dist} monthly={monthly} risk={risk} />

      <div className="n-grid g-table-ev">
        <Panel title="Hiệu suất chiến thuật" meta={<span>{strategies.length} chiến thuật · kỳ {periodLong(period)}</span>}>
          <StrategiesTable rows={strategies} />
        </Panel>
        <Panel title="Sự kiện rủi ro" meta={<span>trong kỳ</span>}>
          <Events rows={events} />
        </Panel>
      </div>

      <FamilyStatsPanel rows={data.strategy_stats} period={periodLong(period)} />

      {data.stats && <StatsPanel stats={data.stats} mdd={data.mdd} />}

      {positions.length > 0 && (
        <Panel title="Vị thế đang mở" meta={<><span>{positions.length} vị thế</span><span>Lãi/lỗ chưa chốt <b className={`mono ${signClass(net)}`}>{fmtMoney(net, true)}</b> USDT</span></>}>
          <PositionsTable rows={positions} />
        </Panel>
      )}

      {ctx && <TradesPanel jobId={ctx.jobId} period={period} />}
    </>
  )
}

/** Bộ số đo chuẩn toàn kỳ chạy (core/metrics): lợi nhuận, sụt giảm, rủi ro, theo lệnh, DCA/đòn bẩy, danh mục. */
const STAT_GROUPS = [
  ['Lợi nhuận', 'returns', [['ret_pct', 'Lãi kỳ', 'pct'], ['cagr_pct', 'CAGR', 'pct', 'cagr'], ['vol_ann_pct', 'Biến động năm', 'pct'],
    ['win_days_pct', 'Tỉ lệ ngày lãi', 'pct'], ['best_day_pct', 'Ngày tốt nhất', 'spct'], ['worst_day_pct', 'Ngày tệ nhất', 'spct']]],
  ['Sụt giảm', 'returns', [['mdd_daily_pct', 'MDD theo ngày', 'pct', 'mdd_daily'], ['max_dd_days', 'Đợt sụt dài nhất (ngày)', 'int'],
    ['recovery_days', 'Hồi phục sau MDD (ngày)', 'int'], ['ulcer_index', 'Ulcer index', 'num', 'ulcer']]],
  ['Rủi ro / lợi nhuận', 'returns', [['sharpe', 'Sharpe', 'num', 'sharpe'], ['sortino', 'Sortino', 'num', 'sortino'], ['calmar', 'Calmar', 'num', 'calmar'],
    ['var95_pct', 'VaR 95% (1 ngày)', 'pct', 'var95'], ['cvar95_pct', 'CVaR 95% (1 ngày)', 'pct'], ['skew', 'Độ lệch', 'num'], ['kurt', 'Độ nhọn', 'num']]],
  ['Theo lệnh', 'trades', [['trades', 'Số lệnh', 'int'], ['win_rate', 'Win rate', 'pct'], ['breakeven', 'Lệnh hoà', 'int'],
    ['profit_factor', 'Profit factor', 'num', 'profit_factor'], ['payoff', 'Payoff (TB lãi / TB lỗ)', 'num', 'payoff'], ['expectancy_usd', 'Kỳ vọng / lệnh (USDT)', 'money', 'expectancy'],
    ['expectancy_pct', 'Kỳ vọng / lệnh (%)', 'spct'], ['max_consec_losses', 'Chuỗi thua dài nhất', 'int'], ['top5_share_pct', '5 lệnh lãi nhất / tổng lãi', 'pct'],
    ['avg_hold_h', 'Giữ lệnh TB (giờ)', 'num'], ['fee_drag_pct', 'Phí / lãi trước phí', 'pct', 'fee_drag'], ['funding_usd', 'Funding (USDT)', 'money']]],
  ['DCA / đòn bẩy', 'trades', [['layers_avg', 'Số tầng TB', 'num'], ['layers_max', 'Số tầng tối đa', 'int'], ['mae_avg_pct', 'Lỗ treo TB', 'spct'],
    ['mae_worst_pct', 'Lỗ treo tệ nhất', 'spct', 'mae'], ['liq_proximity_max_pct', 'Gần thanh lý nhất (% ký quỹ mất)', 'pct', 'liq_proximity'], ['liquidations', 'Số lần thanh lý', 'int']]],
  ['Danh mục', 'exposure', [['time_in_market_pct', '% thời gian có vị thế', 'pct'], ['peak_margin_pct', 'Ký quỹ đỉnh (% vốn)', 'pct'],
    ['exposure_gross_avg_pct', 'Exposure gộp TB', 'pct'], ['exposure_gross_max_pct', 'Exposure gộp max', 'pct'],
    ['exposure_net_max_pct', 'Exposure ròng max', 'pct'], ['max_concurrent', 'Vị thế đồng thời max', 'int']]],
]

function fmtStat(v, kind) {
  if (!isNum(v)) return '—'
  if (kind === 'pct') return fmtPct(v)
  if (kind === 'spct') return fmtSPct(v)
  if (kind === 'int') return String(Math.round(v))
  if (kind === 'money') return fmtMoney(v, true)
  return fmtNum(v)
}

function StatsPanel({ stats, mdd, bare = false }) {
  const t = stats.trades || {}
  const corr = stats.correlation
  return (
    <Panel className={bare ? 'pf-bare' : ''} title={bare ? null : 'Số đo chi tiết'}
      meta={<span>toàn kỳ chạy{isNum(mdd?.intrabar_pct) && <> · <Term k="mdd_intrabar">MDD trong nến</Term> <b className="mono">{fmtPct(mdd.intrabar_pct)}</b></>}{isNum(mdd?.daily_pct) && <> · <Term k="mdd_daily">theo ngày</Term> <b className="mono">{fmtPct(mdd.daily_pct)}</b></>}</span>}>
      <div className="n-mx">
        {STAT_GROUPS.map(([title, src, all]) => [title, src, all.filter(([k]) => isNum((stats[src] || {})[k]))]).filter(([, , items]) => items.length > 0).map(([title, src, items]) => (
          <div key={title} className="n-mx-group">
            <h4>{title}</h4>
            <dl>
              {items.map(([k, label, kind, term]) => (
                <React.Fragment key={k}>
                  <dt>{term ? <Term k={term}>{label}</Term> : label}</dt>
                  <dd className="mono">{fmtStat((stats[src] || {})[k], kind)}</dd>
                </React.Fragment>
              ))}
              {title === 'Theo lệnh' && ['long', 'short'].map((side) => t[side] && t[side].trades > 0 && (
                <React.Fragment key={side}>
                  <dt>{side === 'long' ? 'Long' : 'Short'}: lệnh · win · PnL</dt>
                  <dd className="mono">{t[side].trades} · {fmtPct(t[side].win_rate, 0)} · {fmtMoney(t[side].pnl_usd, true)}</dd>
                </React.Fragment>
              ))}
              {title === 'Danh mục' && corr && (
                <React.Fragment>
                  <dt>Tương quan PnL ngày giữa chiến thuật (TB · max)</dt>
                  <dd className="mono">{fmtNum(corr.avg)} · {fmtNum(corr.max)}</dd>
                </React.Fragment>
              )}
            </dl>
          </div>
        ))}
      </div>
    </Panel>
  )
}

/** Tải payload Danh mục của một job backtest và hiển thị: rỗng (kèm lý do) / lỗi / dashboard. */
export default function DashboardLoader({ jobId, period, onLoaded, openLink, compact = false }) {
  const [st, setSt] = useState({ loading: true, data: null, error: null })
  const [tick, setTick] = useState(0)      // đổi để buộc tải lại

  useEffect(() => {
    if (!jobId) { setSt({ loading: false, data: null, error: null }); return undefined }
    let dead = false
    setSt((s) => ({ ...s, loading: true, error: null }))
    getDashboard({ jobId, period }).then(
      (data) => { if (!dead) { setSt({ loading: false, data, error: null }); onLoaded && data.available && onLoaded(data) } },
      (e) => { if (!dead) setSt({ loading: false, data: null, error: e.message }) },
    )
    return () => { dead = true }
  }, [jobId, period, tick]) // eslint-disable-line react-hooks/exhaustive-deps

  const retry = useCallback(() => setTick((n) => n + 1), [])

  if (st.error && !st.data) return <ErrorState title="Không tải được dữ liệu danh mục" error={st.error} onRetry={retry} />
  if (st.loading && !st.data) return <Loading what="danh mục" />
  if (!jobId) return <Empty title="Chưa chọn lần backtest">Chọn một backtest đã chạy xong ở trên, hoặc chạy mới tại <Link to="/backtest">Backtest</Link>.</Empty>
  if (!st.data?.available) {
    return <Empty title="Chưa có dữ liệu backtest">{st.data?.reason || 'Backtest chưa khả dụng.'}</Empty>
  }
  return (
    <div style={{ opacity: st.loading ? 0.6 : 1, transition: 'opacity .15s' }}>
      {openLink}
      <DashboardView data={st.data} ctx={{ jobId }} compact={compact} />
    </div>
  )
}
