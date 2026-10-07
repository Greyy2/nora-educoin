import React from 'react'
import { fmtNum, fmtPct, fmtSPct, fmtMoney, fmtSigned, signClass, isNum } from '../../lib/format'
import '../../styles/diagnostics.css'

// Khối chẩn đoán dùng chung cho Education ("Thực tế chạy ra sao") và CreateAlpha ("Phân tích").
// Nguồn: result.diagnostics.{signal_activity, pnl_structure, market_comparison, regime_analysis, binding_condition, train_vs_test} + result.insights.
// Mọi số lấy thẳng từ JSON (đơn vị *_pct đã là phần trăm); khối thiếu / available=false thì ẩn hoặc ghi "không có dữ liệu", không bao giờ điền số giả.

export const EXIT_LABEL = {
  signal: 'Tín hiệu thoát',
  stop_loss: 'Cắt lỗ (stop-loss)',
  take_profit: 'Chốt lời (take-profit)',
  trailing: 'Trailing stop',
  timeout: 'Hết thời gian giữ',
  kill_switch: 'Kill switch danh mục',
  open_at_end: 'Còn mở cuối kỳ',
  liquidation: 'Thanh lý',
  other: 'Lý do khác',
  unknown: 'Không rõ',
}
const EXIT_TONE = { stop_loss: 'neg', liquidation: 'neg', kill_switch: 'neg', take_profit: 'pos', trailing: 'warn', timeout: 'warn' }

const REGIME_LABEL = { bull: 'Trên SMA200 (bull)', bear: 'Dưới SMA200 (bear)', unknown: 'Chưa đủ dữ liệu SMA' }

const INSIGHT_TITLE = {
  tail_dependent: 'Phụ thuộc vài lệnh lớn',
  concentrated_coin: 'Tập trung vào một tài sản',
  binding_condition: 'Điều kiện chặn tín hiệu',
  high_win_rate: 'Tỷ lệ thắng cao',
  bear_loss: 'Thua lỗ khi thị trường xấu',
  overfit_gap: 'Chênh lệch train / test lớn',
  negative_excess: 'Kém nắm giữ thụ động',
  robust_oos: 'Vững ngoài mẫu',
  only_long_bias: 'Chỉ giao dịch chiều Long',
  always_in: 'Gần như luôn có vị thế',
  fee_drag: 'Phí ăn mòn lợi nhuận',
  high_consecutive_losses: 'Chuỗi thua dài',
  rarely_in_market: 'Hiếm khi có vị thế',
  drawdown_heavy: 'Sụt giảm sâu',
  low_win_rate_trend: 'Thắng ít, payoff cao',
  beta_driven: 'Lợi nhuận chủ yếu là beta',
}
const SEV = { warning: 'Cảnh báo rủi ro', good: 'Điểm sáng', info: 'Thông tin' }

const EVIDENCE_LABEL = {
  top5_profit_pct: 'Top-5 lệnh % lãi gộp', closed_trades: 'Lệnh đã đóng', bear_pnl_usd: 'PnL bear (USD)', bear_days: 'Ngày bear', bull_pnl_usd: 'PnL bull (USD)',
  bull_days: 'Ngày bull', initial_capital: 'Vốn đầu', benchmark_bear_pnl_usd: 'Benchmark bear (USD)', market: 'Thị trường', max_drawdown_pct: 'MDD %', market_mdd_pct: 'MDD benchmark %',
  max_consecutive_losses: 'Chuỗi thua tối đa', excess_cagr: 'Chênh CAGR (điểm %)', strategy_cagr: 'CAGR chiến lược %', market_cagr: 'CAGR benchmark %', train_sharpe: 'Sharpe train',
  test_sharpe: 'Sharpe test', sharpe_decay: 'Test/Train', win_rate: 'Tỷ lệ thắng %', payoff: 'Payoff', long_trades: 'Lệnh long', short_trades: 'Lệnh short',
}
const fmtEv = (v) => (isNum(v) ? fmtNum(v, Number.isInteger(v) ? 0 : 2) : v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v))

/** Nhận xét tự động: message_vi + evidence dạng chip khoá: giá trị. */
export function InsightList({ insights, empty }) {
  const list = Array.isArray(insights) ? insights : []
  if (!list.length) return empty ? <p className="dg-empty">{empty}</p> : null
  return (
    <div className="dg-ins">
      {list.map((ins, i) => {
        const sev = ['warning', 'good', 'info'].includes(ins.severity) ? ins.severity : 'info'
        const ev = ins.evidence && typeof ins.evidence === 'object' ? Object.entries(ins.evidence) : []
        return (
          <div key={ins.id || i} className={`dg-in ${sev}`}>
            <div className="dg-in-h">
              <b>{INSIGHT_TITLE[ins.id] || ins.id}</b>
              <span>{SEV[sev]}</span>
            </div>
            <p>{ins.message_vi}</p>
            {ev.length > 0 && (
              <div className="dg-chips">
                {ev.map(([k, v]) => <span key={k} className="dg-chip" title={k}>{EVIDENCE_LABEL[k] || k}: <b>{fmtEv(v)}</b></span>)}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function Sec({ title, hint, children }) {
  return (
    <section className="dg-sec">
      <div className="dg-h"><b>{title}</b>{hint && <span className="muted">{hint}</span>}</div>
      <div className="dg-b">{children}</div>
    </section>
  )
}

function Tile({ label, children, sub, cls = '', title }) {
  return <div className="n-tile" title={title}><div className="l">{label}</div><div className={`v ${cls}`}>{children}</div>{sub != null && <div className="s">{sub}</div>}</div>
}

function Bar({ label, pct, value, extra, tone = '' }) {
  const w = isNum(pct) ? Math.max(0, Math.min(100, pct)) : 0
  return (
    <div className="dg-bar">
      <span className="nm">{label}</span>
      <span className="tr"><i className={tone} style={{ width: `${w}%` }} /></span>
      <span className="vl">{value}{extra != null && <em> {extra}</em>}</span>
    </div>
  )
}

const usd = (v) => (isNum(v) ? fmtSigned(v, 0) : '—')

function Benchmark({ mc }) {
  if (!mc) return null
  if (!mc.available) return <Sec title="So với benchmark luôn long"><p className="dg-empty">Không có dữ liệu so sánh benchmark{mc.reason ? ` (${mc.reason})` : ''}.</p></Sec>
  const ex = mc.excess_cagr
  return (
    <Sec title="So với benchmark luôn long" hint={isNum(mc.days) ? `${fmtNum(mc.days, 0)} ngày` : null}>
      <div className="n-tilegrid">
        <Tile label="Beta" sub="độ nhạy với benchmark" title="Hệ số hồi quy lợi suất ngày chiến lược theo lợi suất ngày benchmark luôn long">{fmtNum(mc.beta, 2)}</Tile>
        <Tile label="Tương quan" sub="với lợi suất ngày benchmark">{fmtNum(mc.correlation, 2)}</Tile>
        <Tile label="CAGR chiến lược" cls={signClass(mc.strategy_cagr)} sub={isNum(mc.strategy_total_return_pct) ? `tổng ${fmtSPct(mc.strategy_total_return_pct, 0)}` : null}>{fmtSPct(mc.strategy_cagr, 1)}</Tile>
        <Tile label="CAGR benchmark" cls={signClass(mc.market_cagr)} sub={isNum(mc.market_total_return_pct) ? `tổng ${fmtSPct(mc.market_total_return_pct, 0)}` : null}>{fmtSPct(mc.market_cagr, 1)}</Tile>
        <Tile label="Chênh CAGR" cls={signClass(ex)} sub="chiến lược − benchmark (điểm %/năm)">{isNum(ex) ? fmtSigned(ex, 1) : '—'}</Tile>
        <Tile label="MDD chiến lược" cls="neg">{isNum(mc.strategy_mdd) ? fmtSPct(-Math.abs(mc.strategy_mdd), 1) : '—'}</Tile>
        <Tile label="MDD benchmark" cls="neg">{isNum(mc.market_mdd) ? fmtSPct(-Math.abs(mc.market_mdd), 1) : '—'}</Tile>
      </div>
      {mc.benchmark && <p className="dg-note">Benchmark: {mc.benchmark}.</p>}
    </Sec>
  )
}

function Regimes({ ra }) {
  if (!ra) return null
  if (!ra.available) return <Sec title="Chế độ thị trường"><p className="dg-empty">Không có dữ liệu chế độ thị trường{ra.reason ? ` (${ra.reason})` : ''}.</p></Sec>
  const rows = ['bull', 'bear', 'unknown'].filter((k) => ra[k] && typeof ra[k] === 'object')
  if (!rows.length) return null
  return (
    <Sec title="Chế độ thị trường" hint={`${ra.market != null ? `giá ${ra.market} ` : ''}so với SMA${ra.sma_days ?? ''}${isNum(ra.total_days) ? ` · ${fmtNum(ra.total_days, 0)} ngày` : ''}`}>
      <div className="n-tblwrap">
        <table className="n-tbl">
          <thead>
            <tr>
              <th>Chế độ</th><th className="r">Số ngày</th><th className="r">PnL chiến lược (USD)</th><th className="r">% tổng PnL</th>
              <th className="r">Lệnh vào</th><th className="r">Ngày có vị thế</th><th className="r">Thị trường</th><th className="r">PnL benchmark (USD)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((k) => {
              const r = ra[k]
              return (
                <tr key={k}>
                  <td>{REGIME_LABEL[k]}</td>
                  <td className="r">{isNum(r.days) ? fmtNum(r.days, 0) : '—'}{isNum(r.pct_days) && <span className="muted"> ({fmtPct(r.pct_days, 0)})</span>}</td>
                  <td className={`r ${signClass(r.pnl_usd)}`}>{usd(r.pnl_usd)}</td>
                  <td className={`r ${signClass(r.pnl_share_pct)}`}>{isNum(r.pnl_share_pct) ? fmtSPct(r.pnl_share_pct, 1) : '—'}</td>
                  <td className="r">{isNum(r.trades_entered) ? fmtNum(r.trades_entered, 0) : '—'}</td>
                  <td className="r">{fmtPct(r.days_in_market_pct, 1)}</td>
                  <td className={`r ${signClass(r.market_return_pct)}`}>{isNum(r.market_return_pct) ? fmtSPct(r.market_return_pct, 1) : '—'}</td>
                  <td className={`r ${signClass(r.benchmark_pnl_usd)}`}>{usd(r.benchmark_pnl_usd)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="dg-note">
        Phân loại theo từng ngày: giá {ra.market ?? 'thị trường'} trên SMA{ra.sma_days ?? ''} là bull, dưới là bear, chưa đủ nến để tính SMA là unknown.
        {isNum(ra.total_pnl_usd) && <> Tổng PnL chiến lược <b className={signClass(ra.total_pnl_usd)}>{usd(ra.total_pnl_usd)} USD</b>.</>}
      </p>
    </Sec>
  )
}

function ExitReasons({ sa }) {
  const pcts = sa?.exit_reasons
  if (!pcts || typeof pcts !== 'object' || !Object.keys(pcts).length) return null
  const counts = sa.exit_reason_counts || {}
  const rows = Object.entries(pcts).filter(([, v]) => isNum(v)).sort((a, b) => b[1] - a[1])
  if (!rows.length) return null
  return (
    <Sec title="Lý do thoát lệnh" hint={isNum(sa.total_trades) ? `${fmtNum(sa.total_trades, 0)} lệnh (đã đóng ${isNum(sa.closed_trades) ? fmtNum(sa.closed_trades, 0) : '—'}, đang mở ${isNum(sa.open_trades) ? fmtNum(sa.open_trades, 0) : '—'})` : null}>
      <div className="dg-bars">
        {rows.map(([k, v]) => (
          <Bar key={k} label={EXIT_LABEL[k] || k} pct={v} tone={EXIT_TONE[k] || ''} value={fmtPct(v, 1)} extra={isNum(counts[k]) ? `· ${fmtNum(counts[k], 0)} lệnh` : null} />
        ))}
      </div>
    </Sec>
  )
}

function Holding({ sa }) {
  if (!sa || typeof sa !== 'object' || !Object.keys(sa).length) return null
  const coins = sa.time_in_market_by_coin && typeof sa.time_in_market_by_coin === 'object' ? Object.entries(sa.time_in_market_by_coin).filter(([, v]) => isNum(v)).sort((a, b) => b[1] - a[1]) : []
  return (
    <Sec title="Thời gian nắm giữ">
      <div className="n-tilegrid">
        <Tile label="Ngày có vị thế" sub="% số ngày có ít nhất một vị thế mở">{fmtPct(sa.days_in_market_pct, 1)}</Tile>
        <Tile label="Mức phơi nhiễm TB" sub={isNum(sa.max_exposure_pct) ? `cao nhất ${fmtPct(sa.max_exposure_pct, 1)}` : 'trung bình theo ngày'}>{fmtPct(sa.avg_exposure_pct, 1)}</Tile>
        <Tile label="Giữ lệnh TB" sub={isNum(sa.median_holding_days) ? `trung vị ${fmtNum(sa.median_holding_days, 1)} ngày` : null}>{isNum(sa.avg_holding_days) ? `${fmtNum(sa.avg_holding_days, 1)} ngày` : '—'}</Tile>
        <Tile label="Long / Short" sub="số lệnh">{isNum(sa.long_trades) && isNum(sa.short_trades) ? `${fmtNum(sa.long_trades, 0)} / ${fmtNum(sa.short_trades, 0)}` : '—'}</Tile>
      </div>
      {coins.length > 0 && (
        <>
          <div className="dg-note">Thời gian có vị thế theo từng tài sản (% số ngày)</div>
          <div className="dg-coins">
            {coins.map(([c, v]) => <Bar key={c} label={c} pct={v} value={fmtPct(v, 0)} />)}
          </div>
        </>
      )}
      {(sa.exposure_basis || sa.holding_basis) && <p className="dg-note">{[sa.exposure_basis && `Phơi nhiễm: ${sa.exposure_basis}`, sa.holding_basis && `Giữ lệnh: ${sa.holding_basis}`].filter(Boolean).join(' · ')}.</p>}
    </Sec>
  )
}

function PnlStructure({ ps }) {
  if (!ps || typeof ps !== 'object' || !Object.keys(ps).length) return null
  return (
    <Sec title="Cấu trúc lãi lỗ" hint={isNum(ps.closed_trades) ? `${fmtNum(ps.closed_trades, 0)} lệnh đã đóng` : null}>
      <div className="n-tilegrid">
        <Tile label="Tỷ lệ thắng (lệnh)">{fmtPct(ps.win_rate, 1)}</Tile>
        <Tile label="Payoff (lãi TB / lỗ TB)">{fmtNum(ps.payoff, 2)}</Tile>
        <Tile label="Lãi TB / lệnh thắng" sub={isNum(ps.winning_trades) ? `${fmtNum(ps.winning_trades, 0)} lệnh thắng` : null}>{isNum(ps.avg_win) ? `${fmtMoney(ps.avg_win)} USD` : '—'}</Tile>
        <Tile label="Lỗ TB / lệnh thua" sub={isNum(ps.losing_trades) ? `${fmtNum(ps.losing_trades, 0)} lệnh thua` : null}>{isNum(ps.avg_loss) ? `${fmtMoney(ps.avg_loss)} USD` : '—'}</Tile>
        <Tile label="Lệnh thắng lớn nhất">{isNum(ps.max_win) ? `${fmtMoney(ps.max_win)} USD` : '—'}</Tile>
        <Tile label="Lệnh thua lớn nhất">{isNum(ps.max_loss) ? `${fmtMoney(ps.max_loss)} USD` : '—'}</Tile>
        <Tile label="Top-5 lệnh thắng" sub="% tổng lãi gộp">{fmtPct(ps.top5_profit_pct, 1)}</Tile>
        <Tile label="Chuỗi thua dài nhất" sub="lệnh liên tiếp">{isNum(ps.max_consecutive_losses) ? fmtNum(ps.max_consecutive_losses, 0) : '—'}</Tile>
        <Tile label="Phí" sub={isNum(ps.fees_pct_of_capital) ? `${fmtPct(ps.fees_pct_of_capital, 1)} vốn đầu` : null}>{isNum(ps.fees_usd) ? `${fmtMoney(ps.fees_usd)} USD` : '—'}</Tile>
        <Tile label="Phí / lãi gộp" sub="mức phí ăn vào lãi trước phí">{fmtPct(ps.fee_drag_pct, 1)}</Tile>
      </div>
    </Sec>
  )
}

function Binding({ bc }) {
  if (!bc) return null
  if (!bc.available) return <Sec title="Điều kiện chặn vào lệnh"><p className="dg-empty">Không có dữ liệu điều kiện chặn{bc.reason ? ` (${bc.reason})` : ''}.</p></Sec>
  const rules = (Array.isArray(bc.rules) ? bc.rules : []).filter((r) => Array.isArray(r.conjuncts) && r.conjuncts.length)
  if (!rules.length) return null
  return (
    <Sec title="Điều kiện chặn vào lệnh" hint={`${bc.timeframe ? `khung ${bc.timeframe}` : ''}${Array.isArray(bc.symbols) ? ` · ${bc.symbols.length} tài sản` : ''}`}>
      {rules.map((r, ri) => (
        <div key={ri} className="dg-rule">
          <div className="dg-rule-h">
            <b>Quy tắc vào {r.side || ''} #{r.index}{isNum(r.line) ? ` (dòng ${r.line})` : ''}</b>
            {isNum(r.level) && <span>mức vị thế {fmtNum(r.level, 2)}</span>}
            {isNum(r.bars) && <span>{fmtNum(r.bars, 0)} thanh nến đã xét</span>}
            {isNum(r.all_true_bars) && <span>đủ điều kiện: <b>{fmtNum(r.all_true_bars, 0)}</b></span>}
            {isNum(r.near_miss_bars) && <span>suýt đạt (chỉ thiếu 1 điều kiện): <b>{fmtNum(r.near_miss_bars, 0)}</b></span>}
          </div>
          {r.n_conjuncts <= 1 ? (
            <div className="dg-note" style={{ color: 'var(--n-ink-2)' }}>
              Điều kiện: {r.conjuncts[0].text_vi}
              {isNum(r.conjuncts[0].pct_true) && <> — đúng ở <b>{fmtPct(r.conjuncts[0].pct_true, 1)}</b> số thanh nến đã xét</>}
            </div>
          ) : (
          <div className="n-tblwrap">
            <table className="n-tbl">
              <thead>
                <tr>
                  <th>Điều kiện</th>
                  <th className="r" title="Tỷ lệ thanh nến điều kiện này đúng">% đúng</th>
                  <th className="r" title="Trong các thanh nến suýt đạt, tỷ lệ chỉ riêng điều kiện này sai">% suýt đạt do điều kiện này</th>
                  <th className="r" title="Số thanh nến chỉ riêng điều kiện này sai, trên tổng thanh nến đã xét">% thanh nến chỉ bị chặn bởi nó</th>
                </tr>
              </thead>
              <tbody>
                {r.conjuncts.map((c, ci) => {
                  const bind = r.binding && r.binding.index === c.index && r.n_conjuncts > 1
                  return (
                    <tr key={ci} className={bind ? 'bind' : ''}>
                      <td className="txt">{c.text_vi}{bind && <span className="dg-tag">chặn nhiều nhất</span>}</td>
                      <td className="r">{fmtPct(c.pct_true, 1)}</td>
                      <td className="r">{fmtPct(c.share_of_near_miss_pct, 1)}</td>
                      <td className="r">{fmtPct(c.pct_only_false_of_bars, 1)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          )}
          {r.n_conjuncts <= 1 && <p className="dg-note">Quy tắc chỉ có một điều kiện nên không có thống kê điều kiện nào chặn nó.</p>}
        </div>
      ))}
    </Sec>
  )
}

function TrainTest({ tv }) {
  if (!tv || typeof tv !== 'object' || !Object.keys(tv).length) return null
  const has = ['train_sharpe', 'test_sharpe', 'train_cagr', 'test_cagr', 'train_mdd', 'test_mdd'].some((k) => isNum(tv[k]))
  if (!has) return null
  const mdd = (v) => (isNum(v) ? fmtSPct(-Math.abs(v), 1) : '—')
  return (
    <Sec title="Train so với Test">
      <div className="n-tblwrap">
        <table className="n-tbl">
          <thead><tr><th>Chỉ số</th><th className="r">Train</th><th className="r">Test</th></tr></thead>
          <tbody>
            <tr><td>Sharpe</td><td className="r">{fmtNum(tv.train_sharpe, 2)}</td><td className="r">{fmtNum(tv.test_sharpe, 2)}</td></tr>
            <tr><td>CAGR</td><td className={`r ${signClass(tv.train_cagr)}`}>{fmtSPct(tv.train_cagr, 1)}</td><td className={`r ${signClass(tv.test_cagr)}`}>{fmtSPct(tv.test_cagr, 1)}</td></tr>
            <tr><td>Max drawdown</td><td className="r neg">{mdd(tv.train_mdd)}</td><td className="r neg">{mdd(tv.test_mdd)}</td></tr>
          </tbody>
        </table>
      </div>
      {isNum(tv.sharpe_decay) && <p className="dg-note">Sharpe test bằng <b>{fmtNum(tv.sharpe_decay, 2)}</b> lần Sharpe train (1.00 = không suy giảm).</p>}
    </Sec>
  )
}

/** result = result.json của custom_backtest hoặc bản ghi Education chạy sẵn. withInsights: thêm danh sách nhận xét ở đầu. */
export default function Diagnostics({ result, withInsights = false }) {
  const d = result?.diagnostics
  const insights = Array.isArray(result?.insights) ? result.insights : []
  if (!d || typeof d !== 'object') return <p className="dg-empty">Kết quả này không có khối chẩn đoán (diagnostics).</p>
  return (
    <div className="dg">
      {withInsights && insights.length > 0 && (
        <Sec title="Nhận xét định lượng tự động" hint={`${insights.length} phát hiện`}><InsightList insights={insights} /></Sec>
      )}
      <Benchmark mc={d.market_comparison} />
      <Regimes ra={d.regime_analysis} />
      <ExitReasons sa={d.signal_activity} />
      <Holding sa={d.signal_activity} />
      <PnlStructure ps={d.pnl_structure} />
      <Binding bc={d.binding_condition} />
      <TrainTest tv={d.train_vs_test} />
    </div>
  )
}
