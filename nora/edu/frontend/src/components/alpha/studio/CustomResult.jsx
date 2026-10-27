import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Segmented, Empty } from '../../ui'
import Term from '../../ui/Term'
import Pager from '../../ui/Pager'
import RangeBrush from './RangeBrush'
import AreaLine from '../../charts/AreaLine'
import UnderwaterStrip from '../../charts/UnderwaterStrip'
import { fmtNum, fmtSPct, fmtPct, fmtMoney, signClass, isNum, toMs, fmtSigned } from '../../../lib/format'
import Diagnostics, { InsightList } from './Diagnostics'
import ResultExplain from './ResultExplain'
import ResultTour from './ResultTour'
import ProvenanceBadge from '../../common/ProvenanceBadge'
import WarningsPanel from '../../common/WarningsPanel'
import { useMeta } from '../../../meta/MetaProvider'
import { normMetrics, normYearly, stagePlot, resolveCols, runConfigDiff as getRunConfigDiff, TRADE_COLS, SYMBOL_COLS, POSITION_COLS } from '../../../lib/customResult'
import TestingStatusCard from './TestingStatusCard'

const STAGES = [
  { value: 'train', label: 'Train', block: 'train' },
  { value: 'test', label: 'Test', block: 'test' },
  { value: 'all', label: 'Toàn kỳ', block: 'simulate' },
]
const BENCH_LABEL = 'Luôn long (benchmark)'
// MỘT định nghĩa cho mỗi chỉ số; cơ sở nêu một lần (BASIS_NOTE): năm = 365 ngày, lợi suất ngày = vốn mark-to-market cuối ngày UTC, win rate / profit factor theo lệnh đã đóng.
const BASIS_NOTE = 'Cơ sở: năm = 365 ngày; Sharpe, Sortino, CAGR, Calmar tính trên lợi suất ngày (vốn cuối ngày UTC); Max drawdown tính trên mức sụt giảm sâu nhất (bao gồm râu nến intrabar worst equity); tỉ lệ thắng và Profit factor tính theo từng lệnh đã đóng.'
const SEEN_TOURS = new Set() // mỗi lần chạy chỉ tự mở hướng dẫn một lần; nút "Xem giải thích" mở lại
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
  const unavailable = (value, reason) => value == null ? <span title={reason || 'Chưa đủ dữ liệu để tính'}>N/A</span> : fmtNum(value)
  return (
    <div className="n-tilegrid se-tiles" title={BASIS_NOTE}>
      <Tile label="Lãi toàn kỳ" title="Tổng lãi kép của toàn bộ giai đoạn, không annualize" cls={signClass(m.ret)}>{fmtSPct(m.ret)}</Tile>
      <Tile label={<Term k="cagr">CAGR (%/năm)</Term>} title={isNum(m.cagr) && isNum(m.days) ? `Tốc độ tăng trưởng quy đổi theo năm từ ${fmtNum(m.days, 0)} ngày dữ liệu: (1 + lãi toàn kỳ)^(365 / số ngày) - 1` : 'Tốc độ tăng trưởng quy đổi theo năm; cần đủ số ngày dữ liệu'} cls={signClass(m.cagr)}>{fmtSPct(m.cagr)}</Tile>
      <Tile label={<Term k="sharpe">Sharpe</Term>}>{fmtNum(m.sharpe)}</Tile>
      <Tile label={<Term k="sortino">Sortino</Term>} title={m.sortino == null ? 'Không xác định: chuỗi lợi suất ngày không có đủ biến động giảm để tính Sortino.' : undefined}>{unavailable(m.sortino, 'Không xác định: chuỗi lợi suất ngày không có đủ biến động giảm.')}</Tile>
      <Tile label={<Term k="mdd">Max drawdown</Term>} cls={isNum(m.mdd) && m.mdd !== 0 ? 'neg' : ''}>{fmtSPct(m.mdd)}</Tile>
      <Tile label={<Term k="calmar">Calmar</Term>}>{unavailable(m.calmar, 'Không xác định khi Max Drawdown bằng 0 hoặc chưa có đủ chuỗi vốn.')}</Tile>
      <Tile label="Tỉ lệ thắng" title="Số lệnh lãi chia tổng số lệnh đã đóng">{win(m.winTrades)}</Tile>
      <Tile label="Profit factor" title={m.pfNote || 'Tổng lãi chia tổng lỗ của các lệnh đã đóng'}>{unavailable(m.pfTrades, m.pfNote === 'không có lệnh thua' ? 'N/A: chưa có lệnh thua để làm mẫu số.' : m.pfNote)}</Tile>
      <Tile label="Số lệnh">{isNum(m.trades) ? fmtNum(m.trades, 0) : '—'}</Tile>
      <Tile label="Phí (USDT)">{isNum(m.fees) ? fmtMoney(m.fees) : '—'}</Tile>
      <Tile label="Số ngày">{isNum(m.days) ? fmtNum(m.days, 0) : '—'}</Tile>
      <Tile label="Biến động năm">{fmtSPct(m.volAnn)}</Tile>
      <Tile label="VaR 95% ngày">{fmtSPct(m.var95)}</Tile>
      <Tile label="CVaR 95% ngày">{fmtSPct(m.cvar95)}</Tile>
      <Tile label="Tỉ lệ ngày lãi">{fmtPct(m.winDays, 1)}</Tile>
      <Tile label="Ngày tốt nhất" cls={signClass(m.bestDay)}>{fmtSPct(m.bestDay)}</Tile>
      <Tile label="Ngày xấu nhất" cls={signClass(m.worstDay)}>{fmtSPct(m.worstDay)}</Tile>
      <Tile label="Payoff" title={m.payoff == null ? 'Không xác định: cần ít nhất một lệnh thắng và một lệnh thua đã đóng.' : undefined}>{unavailable(m.payoff, m.payoffNote || 'Cần ít nhất một lệnh thắng và một lệnh thua đã đóng.')}</Tile>
      <Tile label="Expectancy / lệnh">{fmtSPct(m.expectancyPct)}</Tile>
      <Tile label="Phí ăn mòn">{fmtPct(m.feeDrag, 1)}</Tile>
      <Tile label="Ngày dưới đỉnh">{isNum(m.maxDdDays) ? fmtNum(m.maxDdDays, 0) : '—'}</Tile>
      <Tile label="Chuỗi thua dài nhất">{isNum(m.maxConsecLosses) ? fmtNum(m.maxConsecLosses, 0) : '—'}</Tile>
      <Tile label="Top-5 lệnh / lãi">{fmtPct(m.top5Share, 1)}</Tile>
      <Tile label="MAE xấu nhất">{fmtSPct(m.maeWorst)}</Tile>
      <Tile label="Gần thanh lý nhất">{fmtPct(m.liqProximity, 1)}</Tile>
      <Tile label="Số lần thanh lý">{isNum(m.liquidations) ? fmtNum(m.liquidations, 0) : '—'}</Tile>
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
  const [filterSym, setFilterSym] = useState('ALL')
  const [filterSide, setFilterSide] = useState('ALL')
  const [filterOutcome, setFilterOutcome] = useState('ALL')

  const symbols = useMemo(() => {
    const set = new Set()
    trades.forEach((t) => {
      const s = (t.symbol || t.sym || '').replace('@perp', '')
      if (s) set.add(s)
    })
    return Array.from(set).sort()
  }, [trades])

  const filtered = useMemo(() => {
    return trades.filter((t) => {
      const sym = (t.symbol || t.sym || '').replace('@perp', '')
      if (filterSym !== 'ALL' && sym !== filterSym) return false
      const side = String(t.side || '').toUpperCase()
      if (filterSide !== 'ALL' && side !== filterSide) return false
      const pnl = Number(t.pnl_usd ?? t.pnl ?? t.net_pnl ?? 0)
      if (filterOutcome === 'WIN' && pnl <= 0) return false
      if (filterOutcome === 'LOSS' && pnl >= 0) return false
      return true
    })
  }, [trades, filterSym, filterSide, filterOutcome])

  const enriched = useMemo(() => {
    let runningPnl = 0
    return filtered.map((t, idx) => {
      const pnl = Number(t.pnl_usd ?? t.pnl ?? t.net_pnl ?? 0)
      runningPnl += pnl
      return {
        ...t,
        trade_no: idx + 1,
        cum_pnl: Math.round(runningPnl * 100) / 100,
      }
    })
  }, [filtered])

  const stats = useMemo(() => {
    const total = enriched.length
    if (!total) return null
    let wins = 0
    let losses = 0
    let totalPnl = 0
    let totalFees = 0
    let grossWin = 0
    let grossLoss = 0

    enriched.forEach((t) => {
      const pnl = Number(t.pnl_usd ?? t.pnl ?? t.net_pnl ?? 0)
      const fee = Number(t.fees_usd ?? t.fee_usd ?? t.fee ?? t.fees ?? 0)
      totalPnl += pnl
      totalFees += fee
      if (pnl > 0) {
        wins++
        grossWin += pnl
      } else if (pnl < 0) {
        losses++
        grossLoss += Math.abs(pnl)
      }
    })

    const winRate = (wins / total) * 100
    const profitFactor = grossLoss > 0 ? grossWin / grossLoss : (wins > 0 ? null : 0)
    const avgTrade = totalPnl / total

    return {
      total,
      wins,
      losses,
      totalPnl,
      totalFees,
      winRate,
      profitFactor,
      avgTrade,
    }
  }, [enriched])

  const slice = enriched.slice(pg.offset, pg.offset + pg.limit)

  return (
    <div className="tv-trades-container">
      {/* TradingView Asset Filter & Quick Stats Toolbar */}
      <div
        className="tv-trades-toolbar"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '10px 14px',
          background: 'rgba(255, 255, 255, 0.03)',
          border: '1px solid var(--n-border, #334155)',
          borderRadius: 8,
          marginBottom: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--n-muted, #94a3b8)' }}>Tài sản:</span>
          <select
            className="n-sel"
            style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4, height: 28 }}
            value={filterSym}
            onChange={(e) => { setFilterSym(e.target.value); setPg({ offset: 0, limit: 50 }) }}
          >
            <option value="ALL">Tất cả tài sản ({symbols.length})</option>
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>

          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--n-muted, #94a3b8)', marginLeft: 6 }}>Chiều:</span>
          <select
            className="n-sel"
            style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4, height: 28 }}
            value={filterSide}
            onChange={(e) => { setFilterSide(e.target.value); setPg({ offset: 0, limit: 50 }) }}
          >
            <option value="ALL">Tất cả chiều</option>
            <option value="LONG">LONG</option>
            <option value="SHORT">SHORT</option>
          </select>

          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--n-muted, #94a3b8)', marginLeft: 6 }}>Kết quả:</span>
          <select
            className="n-sel"
            style={{ fontSize: 12, padding: '4px 8px', borderRadius: 4, height: 28 }}
            value={filterOutcome}
            onChange={(e) => { setFilterOutcome(e.target.value); setPg({ offset: 0, limit: 50 }) }}
          >
            <option value="ALL">Tất cả kết quả</option>
            <option value="WIN">Lệnh thắng</option>
            <option value="LOSS">Lệnh thua</option>
          </select>
        </div>

        {stats && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', fontSize: 12 }}>
            <div>
              <span className="muted">Số lệnh: </span>
              <b>{stats.total}</b> <span style={{ opacity: 0.7 }}>({stats.wins}W / {stats.losses}L)</span>
            </div>
            <div>
              <span className="muted">Tỉ lệ thắng: </span>
              <b className={stats.winRate >= 50 ? 'pos' : 'neg'}>{fmtPct(stats.winRate, 1)}</b>
            </div>
            <div>
              <span className="muted">Tổng Lãi/Lỗ: </span>
              <b className={signClass(stats.totalPnl)}>{fmtSigned(stats.totalPnl, 2)} USDT</b>
            </div>
            <div>
              <span className="muted">Lãi TB: </span>
              <b className={signClass(stats.avgTrade)}>{fmtSigned(stats.avgTrade, 2)} USDT</b>
            </div>
            <div>
              <span className="muted">Tổng phí: </span>
              <span>{fmtMoney(stats.totalFees)} USDT</span>
            </div>
          </div>
        )}
      </div>

      <Rows rows={slice} spec={TRADE_COLS} empty="Không có lệnh nào thỏa mãn bộ lọc." />
      {enriched.length > 50 && <Pager total={enriched.length} offset={pg.offset} limit={pg.limit} onChange={setPg} />}
    </div>
  )
}


function EffectiveConfigTable({ cfg }) {
  const prov = cfg?.param_provenance || {}
  const pos = cfg?.position || {}
  const hasProvenance = Object.keys(prov).length > 0
  const hasPos = Object.keys(pos).length > 0

  if (!hasPos && !hasProvenance) return null

  const keyDisplay = [
    { key: 'leverage', label: 'Đòn bẩy', fmt: (v) => `${v}x` },
    { key: 'market', label: 'Thị trường', fmt: (v) => String(v).toUpperCase() },
    { key: 'stop_loss_rate', label: 'Cắt lỗ (Stop Loss)', fmt: (v, u) => u === 'atr' ? `${v}×ATR` : `${(v * (v <= 1 ? 100 : 1)).toFixed(1)}%` },
    { key: 'take_profit_rate', label: 'Chốt lời (Take Profit)', fmt: (v, u) => u === 'atr' ? `${v}×ATR` : `${(v * (v <= 1 ? 100 : 1)).toFixed(1)}%` },
    { key: 'exit_unit', label: 'Đơn vị thoát lệnh', fmt: (v) => v === 'atr' ? 'ATR (Biến động)' : '% (Phần trăm)' },
    { key: 'risk_per_trade_pct', label: 'Rủi ro mỗi lệnh', fmt: (v) => `${v}% vốn` },
    { key: 'max_open_trades', label: 'Lệnh mở tối đa', fmt: (v) => `${v}` },
    { key: 'fee_rate', label: 'Phí Taker', fmt: (v) => `${(v * 100).toFixed(3)}%` },
    { key: 'slippage_rate', label: 'Trượt giá', fmt: (v) => `${(v * 100).toFixed(3)}%` },
  ]

  const sourceBadge = (src) => {
    switch (src) {
      case 'code':
        return <span style={{ background: 'rgba(34, 197, 94, 0.15)', color: '#4ade80', padding: '1px 6px', borderRadius: 4, fontSize: 11, border: '1px solid rgba(34, 197, 94, 0.3)' }}>📄 Từ Code</span>
      case 'ui':
        return <span style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#60a5fa', padding: '1px 6px', borderRadius: 4, fontSize: 11, border: '1px solid rgba(59, 130, 246, 0.3)' }}>⚙️ Từ Giao diện</span>
      case 'nora_default':
      case 'system_default':
        return <span style={{ background: 'rgba(148, 163, 184, 0.1)', color: '#94a3b8', padding: '1px 6px', borderRadius: 4, fontSize: 11 }}>Mặc định</span>
      default:
        return <span style={{ background: 'rgba(148, 163, 184, 0.08)', color: '#94a3b8', padding: '1px 6px', borderRadius: 4, fontSize: 11, fontStyle: 'italic' }}>Không có dữ liệu nguồn (run cũ)</span>
    }
  }

  return (
    <section className="se-cc">
      <div className="se-cc-h">
        <b>Cấu hình hiệu lực & Nguồn tham số</b>
        <span className="sp" />
        <span className="muted" style={{ fontSize: 11 }}>Minh bạch các giá trị Engine thực thi</span>
      </div>
      <div className="se-cc-b">
        {!hasProvenance && (
          <div className="n-note" style={{ marginBottom: 10, padding: '6px 10px', background: 'rgba(255, 255, 255, 0.04)', borderRadius: 4 }}>
            ℹ️ <b>Không có dữ liệu nguồn (run cũ):</b> Bản ghi này được tạo trước khi hệ thống bổ sung tracking nguồn gốc tham số. Chạy lại backtest để xem phân định rõ nguồn từ Code hay Giao diện.
          </div>
        )}
        <table className="n-tbl" style={{ width: '100%', fontSize: 12 }}>
          <thead>
            <tr>
              <th>Tham số</th>
              <th>Giá trị áp dụng</th>
              <th>Đơn vị</th>
              <th>Nguồn gốc</th>
            </tr>
          </thead>
          <tbody>
            {keyDisplay.map(({ key, label, fmt }) => {
              const item = prov[key]
              const val = item ? item.value : pos[key]
              if (val == null) return null
              const unit = item?.unit || (key.includes('pct') ? '%' : '')
              const src = item?.source || (hasProvenance ? 'system_default' : 'legacy')
              return (
                <tr key={key}>
                  <td><b>{label}</b> <code style={{ fontSize: 10, color: 'var(--n-muted)' }}>({key})</code></td>
                  <td><b>{fmt ? fmt(val, unit) : val}</b></td>
                  <td>{unit || '—'}</td>
                  <td>{sourceBadge(src)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

const SUBS = [{ value: 'overview', label: 'Overview' }, { value: 'perf', label: 'Performance' }, { value: 'analysis', label: 'Analysis' }]
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
  const unavailable = (value, reason) => value == null
    ? <span title={reason || 'Chưa đủ dữ liệu để tính'}>N/A</span>
    : fmtNum(value)
  return (
    <div className="se-agg" data-tour="summary">
      <div className="se-agg-t">Dữ liệu tổng hợp</div>
      <div className="se-agg-c"><span className="l">Lãi toàn kỳ</span><b className={c(m?.ret)}>{fmtSPct(m?.ret)}</b></div>
      <div className="se-agg-c"><span className="l">Sharpe</span><b>{fmtNum(m?.sharpe)}</b></div>
      <div className="se-agg-c" title={isNum(m?.cagr) && isNum(m?.days) ? `Quy đổi theo năm từ ${fmtNum(m.days, 0)} ngày dữ liệu, dùng năm 365 ngày` : undefined}><span className="l">CAGR (%/năm)</span><b className={c(m?.cagr)}>{fmtSPct(m?.cagr)}</b></div>
      <div className="se-agg-c"><span className="l">Max drawdown</span><b className={isNum(m?.mdd) && m.mdd !== 0 ? 'neg' : ''}>{fmtSPct(m?.mdd)}</b></div>
      <div className="se-agg-c"><span className="l">Profit Factor</span><b>{unavailable(m?.pfTrades, 'N/A: chưa có lệnh thua để làm mẫu số.')}</b></div>
      <div className="se-agg-c" title={m?.calmar == null ? 'Không xác định khi Max drawdown bằng 0 hoặc chưa đủ dữ liệu' : undefined}><span className="l">Calmar</span><b>{unavailable(m?.calmar, 'Không xác định khi Max drawdown bằng 0 hoặc chưa đủ dữ liệu')}</b></div>
    </div>
  )
}

function NoTradeNotice({ result }) {
  const binding = result?.diagnostics?.binding_condition
  const rules = Array.isArray(binding?.rules) ? binding.rules : []
  const noEntrySignals = rules.length > 0 && rules.every((rule) => isNum(rule?.all_true_bars) && rule.all_true_bars === 0)
  return (
    <div className="n-banner" role="status" style={{ borderLeftColor: 'var(--n-warn)', marginBottom: 12 }}>
      <span>
        <b>Không có lệnh đóng hoặc vị thế mở trong kỳ.</b>{' '}
        {noEntrySignals
          ? `Chẩn đoán backend xác nhận cả ${rules.length} quy tắc vào lệnh đều có 0 nến thỏa điều kiện.`
          : 'Các chỉ số lợi nhuận bằng 0 phản ánh không phát sinh giao dịch; chưa đủ chẩn đoán để kết luận vì sao.'}
        {' '}Mở tab Analysis để xem điều kiện vào lệnh và cảnh báo dữ liệu/thực thi.
      </span>
    </div>
  )
}

function YearlyTable({ rows }) {
  if (!rows.length) return <p className="n-note se-pad">Không có số liệu theo năm cho giai đoạn này.</p>
  return (
    <div className="se-yr n-tblwrap" data-tour="yearly">
      <table className="n-tbl">
        <thead><tr><th>Năm</th><th>Sharpe</th><th>CAGR</th><th>Max Drawdown</th><th>Profit Factor</th><th>Calmar</th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.year}-${r.stage}-${i}`}>
              <td className="mono">{r.year}</td><td className="mono">{fmtNum(r.sharpe)}</td>
              <td className={`mono ${signClass(r.cagr)}`}>{fmtSPct(r.cagr)}</td><td className="mono neg">{fmtSPct(r.mdd)}</td>
              <td className="mono">{r.pf == null ? 'N/A' : fmtNum(r.pf)}</td><td className="mono">{r.calmar == null ? 'N/A' : fmtNum(r.calmar)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ChartCard({ title, children, tall = 1, tour, isZoomed, onResetZoom }) {
  const [min, setMin] = useState(false)
  const [big, setBig] = useState(false)
  return (
    <section className="se-cc" data-tour={tour}>
      <div className="se-cc-h"><b>{title}</b><span className="sp" />
        {isZoomed && (
          <button
            type="button"
            className="n-btn xs ghost"
            style={{ fontSize: 11, padding: '2px 8px', marginRight: 6, borderRadius: 6, color: 'var(--n-accent)' }}
            onClick={onResetZoom}
            title="Đặt lại về toàn kỳ 100% (Phím 0)"
          >
            ↺ Đặt lại zoom
          </button>
        )}
        <button type="button" className="n-icon-btn" aria-label={min ? 'Mở rộng' : 'Thu nhỏ'} title={min ? 'Mở rộng' : 'Thu nhỏ'} onClick={() => setMin(!min)}>{I.min}</button>
        <button type="button" className="n-icon-btn" aria-label="Phóng to" title="Phóng to / thu về" onClick={() => { setBig(!big); setMin(false) }}>{I.max}</button>
      </div>
      {!min && <div className="se-cc-b">{children(big ? 1.7 : tall)}</div>}
    </section>
  )
}

/** Kết quả một lần chạy: result = result.json của job custom_backtest. Bố cục: hàng Giai đoạn, Tổng quan / Hiệu suất / Phân tích, Biểu đồ. */
/** `explain` (chỉ /education): thêm khối "Chiến lược làm gì" và hướng dẫn từng bước (ResultTour) dùng ghi chú backend result.explain.notes; giao diện còn lại giống hệt /alpha/create. */
export default function CustomResult({ result, jobLine, explain = false, tourKey = '', editorCode = '', runCode = '', currentForm = null, defaultMode = 'fast' }) {
  const [stage, setStage] = useState('all')
  const [sub, setSub] = useState('overview')
  const [shown, setShown] = useState({ equity: true, pnl: true, dd: true, ret: false })
  const [pick, setPick] = useState(false)
  const [chartRanges, setChartRanges] = useState({ equity: [0, 1], pnl: [0, 1], dd: [0, 1], ret: [0, 1] })
  useEffect(() => {
    setChartRanges({ equity: [0, 1], pnl: [0, 1], dd: [0, 1], ret: [0, 1] })
  }, [stage])
  const [hi, setHi] = useState(null)
  const metrics = useMemo(() => Object.fromEntries(STAGES.map((s) => [s.value, normMetrics(result?.metrics?.[s.block])])), [result])
  const ser = useMemo(() => stagePlot(result?.series, stage), [result, stage])      // chuỗi do backend tính (series.stages); trình duyệt chỉ vẽ
  const bench = ser?.bench || null
  const yearlyAll = useMemo(() => normYearly(result?.yearly), [result])
  const hasM = (r) => [r.sharpe, r.cagr, r.mdd, r.pf, r.calmar].some(isNum)
  const yearly = (stage === 'all' ? yearlyAll : yearlyAll.filter((r) => r.stage === stage)).filter(hasM)
  const trades = Array.isArray(result?.trades) ? result.trades : []
  const notes = explain ? result?.explain?.notes || {} : {}
  const bySym = Array.isArray(result?.by_symbol) ? result.by_symbol : []
  const open = Array.isArray(result?.positions_open) ? result.positions_open : []

  // ---- hướng dẫn từng bước (chỉ education): 3 bước đầu code/chạy + 5 bước giải thích kết quả ----
  const { meta } = useMeta()
  const [tour, setTour] = useState(null) // null | chỉ số bước
  const steps = useMemo(() => {
    if (!explain) return []

    // 3 bước chính đầu tiên: Hướng dẫn cách viết code chiến lược và chạy
    const codeSteps = [
      {
        id: 'code_editor',
        title: 'Soạn thảo chiến lược Python',
        sub: 'overview',
        sel: '[data-tour="code-editor"], .se-code',
        body: [
          { text: 'Viết chiến lược bằng ngôn ngữ Python kế thừa lớp SimpleAlgorithm. Bạn định nghĩa các quy tắc vào lệnh, thoát lệnh và quản lý vị thế dựa trên dữ liệu nến & chỉ báo kỹ thuật.' },
        ],
      },
      {
        id: 'code_settings',
        title: 'Cài đặt tham số & Rổ coin',
        sub: 'overview',
        sel: '[data-tour="code-settings"], .se-chips',
        body: [
          { text: 'Chọn các cặp tiền mã hoá (BTC, ETH,...), khung thời gian nến và mức vốn khởi điểm tại thanh cấu hình trước khi tiến hành chạy kiểm thử.' },
        ],
      },
      {
        id: 'code_run',
        title: 'Chạy kiểm thử trên dữ liệu thật',
        sub: 'overview',
        sel: '[data-tour="code-run"], .se-run',
        body: [
          { text: 'Bấm nút "Chạy backtest" (hoặc phím tắt Ctrl/⌘ + Enter) để hệ thống tự động mô phỏng khớp lệnh trên toàn bộ dữ liệu lịch sử chuẩn xác.' },
        ],
      },
    ]

    // 5 bước tiếp theo: Giải thích các thành phần cốt lõi của kết quả (Result)
    const place = {
      summary: {
        sub: 'overview',
        sel: '[data-tour="summary"]',
        ok: true,
        title: 'Kết quả tổng quan',
        fallback: 'Tổng hợp các chỉ số trọng yếu: Tổng lãi lỗ (PnL), tỷ lệ thắng (Win Rate), chỉ số Sharpe và độ sụt giảm tối đa (Max Drawdown).',
      },
      equity: {
        sub: 'overview',
        show: 'equity',
        sel: '[data-tour="equity"]',
        ok: !!ser,
        title: 'Đường cong tăng trưởng vốn',
        fallback: 'Đường vốn biểu thị giá trị tài sản qua thời gian so với thị trường mua & giữ (Buy & Hold). Đường vốn tăng đều, ít gián đoạn là minh chứng cho chiến lược ổn định.',
      },
      yearly: {
        sub: 'overview',
        sel: '[data-tour="yearly"]',
        ok: yearlyAll.length > 0,
        title: 'Lãi lỗ theo từng năm',
        fallback: 'Bảng thống kê hiệu suất qua từng năm, giúp đánh giá chiến lược có sinh lời bền vững qua các chu kỳ thị trường (bull, bear, sideway) hay không.',
      },
      by_symbol: {
        sub: 'perf',
        sel: '[data-tour="by_symbol"]',
        ok: bySym.length > 0,
        title: 'Hiệu suất theo tài sản',
        fallback: 'Phân tích chi tiết trên từng đồng coin trong danh mục để nhận biết tài sản nào mang lại lợi nhuận chính và tài sản nào kém hiệu quả.',
      },
      testing_status: {
        sub: 'analysis',
        sel: '[data-tour="testing_status"]',
        ok: true,
        title: 'Bộ tiêu chí kiểm định (IS Testing Status)',
        fallback: 'Bộ tiêu chí định lượng chuẩn XNO: kiểm tra Sharpe Ratio (≥ 1.2), CAGR (≥ 25%), Max Drawdown (≥ -40%), Profit Factor (≥ 1.7) và Calmar (≥ 0.9) để đánh giá chiến lược có đạt chuẩn vượt qua bài kiểm định hay chưa.',
      },
      train_test: {
        sub: 'analysis',
        sel: '[data-tour="train_test"]',
        ok: true,
        title: 'Kiểm định Train và Test',
        fallback: 'Kiểm định ngoài mẫu (Out-of-sample): so sánh kết quả giữa tập huấn luyện (Train) và kiểm thử (Test) để bảo đảm chiến lược không bị học vẹt (overfit).',
      },
    }

    const defaultSections = [
      { key: 'summary', label_vi: 'Kết quả tổng quan' },
      { key: 'testing_status', label_vi: 'Bộ tiêu chí kiểm định (IS Testing Status)' },
      { key: 'equity', label_vi: 'Đường cong tăng trưởng vốn' },
      { key: 'yearly', label_vi: 'Lãi lỗ theo từng năm' },
      { key: 'by_symbol', label_vi: 'Hiệu suất theo tài sản' },
      { key: 'train_test', label_vi: 'Kiểm định Train và Test' },
    ]
    const tourList = (meta?.explain_tour && meta.explain_tour.length > 0) ? meta.explain_tour : defaultSections

    const resultSteps = tourList.map((item) => {
      const pl = place[item.key]
      if (!pl || !pl.ok) return null
      const noteText = notes[item.notes_key || item.key] || pl.fallback
      return {
        id: item.key,
        title: item.label_vi || pl.title || item.key,
        sub: pl.sub,
        show: pl.show,
        sel: pl.sel,
        body: [{ text: noteText }],
      }
    }).filter(Boolean)

    return [...codeSteps, ...resultSteps]
  }, [explain, notes, ser, yearlyAll.length, bySym.length, meta?.explain_tour])

  const gotoStep = useCallback((i) => {
    const d = steps[i]
    if (!d) return
    if (d.sub) {
      setStage('all')
      setSub(d.sub)
    }
    if (d.show) setShown((p) => (p[d.show] ? p : { ...p, [d.show]: true }))
    setTour(i)
  }, [steps])

  const closeTour = useCallback(() => setTour(null), [])

  useEffect(() => {
    if (!tourKey || !steps.length || SEEN_TOURS.has(tourKey)) return undefined
    SEEN_TOURS.add(tourKey)
    const t = setTimeout(() => gotoStep(0), 450)
    return () => clearTimeout(t)
  }, [tourKey, steps.length]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!result || typeof result !== 'object') return <Empty title="Chưa có kết quả">Job đã xong nhưng máy chủ không trả <code>result</code>.</Empty>

  const cfg = result.config || {}
  const m = metrics[stage] || metrics.all
  const opts = STAGES.map((s) => ({ ...s, disabled: !metrics[s.value], title: metrics[s.value] ? undefined : 'Không có số liệu cho giai đoạn này' }))
  const sl = (arr, r) => {
    const n = arr.length
    const a = Math.floor((r ? r[0] : 0) * n)
    const b = Math.max(a + 2, Math.ceil((r ? r[1] : 1) * n))
    return arr.slice(a, b)
  }
  const getMarks = (r) => {
    const a0 = ser ? Math.floor((r ? r[0] : 0) * ser.dates.length) : 0
    return ser && ser.splitIdx - a0 > 0 && stage === 'all' ? [{ i: ser.splitIdx - a0, label: 'Train | Test' }] : []
  }
  const updateRange = (k, newR) => {
    setChartRanges((prev) => ({
      ...prev,
      [k]: typeof newR === 'function' ? newR(prev[k] || [0, 1]) : newR,
    }))
  }
  const body = (k) => {
    if (!ser) return null
    const r = chartRanges[k] || [0, 1]
    const marks = getMarks(r)
    const onZoom = (newR) => updateRange(k, newR)
    return {
      equity: (f) => <AreaLine dates={sl(ser.dates, r)} height={Math.round(260 * f)} hover={hi} onHover={setHi} marks={marks} label="Đường vốn" zoomRange={r} onZoom={onZoom} series={[{ key: 'e', label: 'Vốn (USDT)', values: sl(ser.equity, r), color: 'var(--n-brand, #3b82f6)', area: true }, ...(bench ? [{ key: 'b', label: BENCH_LABEL, values: sl(bench.equity, r), color: 'var(--n-bench)', dashed: true }] : [])]} />,
      pnl: (f) => <AreaLine dates={sl(ser.dates, r)} height={Math.round(260 * f)} hover={hi} onHover={setHi} marks={marks} label="Lãi lỗ" zoomRange={r} onZoom={onZoom} series={[{ key: 'p', label: 'PnL (USDT)', values: sl(ser.pnl, r), color: 'var(--n-pos)', area: true }, ...(bench ? [{ key: 'b', label: BENCH_LABEL, values: sl(bench.pnl, r), color: 'var(--n-bench)', dashed: true }] : [])]} />,
      dd: (f) => <UnderwaterStrip dates={sl(ser.dates, r)} values={sl(ser.dd, r)} height={Math.round(180 * f)} hover={hi} onHover={setHi} marks={marks} zoomRange={r} onZoom={onZoom} />,
      ret: (f) => <AreaLine dates={sl(ser.dates, r)} height={Math.round(180 * f)} hover={hi} onHover={setHi} label="Lợi suất ngày" zoomRange={r} onZoom={onZoom} valueFormat={(v) => `${fmtNum(v, 1)}%`} series={[{ key: 'r', label: 'Lợi suất ngày (%)', values: sl(ser.ret, r), color: 'var(--n-info)' }]} />,
    }[k]
  }

  const manifest = result?.manifest || null

  return (
    <div className="se-res">
      {tour != null && steps[tour] && <ResultTour steps={steps} index={tour} onIndex={gotoStep} onClose={closeTour} />}

      <div className="se-row1">
        <span className="se-lbl">Giai đoạn:</span>
        <Segmented label="Giai đoạn" value={stage} onChange={setStage} options={opts} />
        <span className="se-sp" />
        {steps.length > 0 && <button type="button" className="n-btn sm se-tourbtn" onClick={() => gotoStep(0)} title="Hướng dẫn từng bước từ Code đến Kết quả (←/→, Esc)">✨ Xem hướng dẫn ({steps.length} bước)</button>}
        {jobLine}
        {result.program_hash && <span className="mono muted" title="Mã băm chương trình đã biên dịch">{String(result.program_hash).slice(0, 12)}</span>}
        {manifest && (
          <span
            className="mono muted edu-manifest-badge"
            style={{
              fontSize: 11,
              background: 'rgba(255, 255, 255, 0.06)',
              border: '1px solid var(--n-border, #334155)',
              padding: '2px 6px',
              borderRadius: 4,
            }}
            title={`Run Manifest ID: ${manifest.job_id}\nEngine: ${manifest.engine?.name} v${manifest.engine?.version}\nRAM Cap: ${Math.round((manifest.engine?.memory_cap_bytes || 0) / (1024 * 1024 * 1024))} GB\nDataset: ${manifest.dataset?.symbol} ${manifest.dataset?.timeframe}\nDigest: ${manifest.dataset?.data_digest}`}
          >
            📋 manifest: {manifest.code_hash?.slice(0, 8)} ({manifest.dataset?.timeframe || '1h'})
          </span>
        )}
        <ProvenanceBadge provenance={result?.provenance} />
      </div>

      {(() => {
        const effSlip = Number(cfg?.position?.slippage_rate ?? cfg?.param_provenance?.slippage_rate?.value ?? 0)
        return (
          <div className="edu-slippage-notice" style={{
            margin: '6px 0 10px',
            padding: '8px 12px',
            background: effSlip > 0 ? 'rgba(59, 130, 246, 0.08)' : 'rgba(234, 179, 8, 0.08)',
            border: effSlip > 0 ? '1px solid rgba(59, 130, 246, 0.25)' : '1px solid rgba(234, 179, 8, 0.25)',
            borderRadius: 6,
            fontSize: 12,
            color: effSlip > 0 ? '#93c5fd' : '#fef08a',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}>
            <span>{effSlip > 0 ? 'ℹ️' : '⚠️'}</span>
            {effSlip > 0 ? (
              <span><b>Lưu ý giáo dục:</b> Backtest EDU đang mô phỏng trượt giá {(effSlip * 100).toFixed(2)}% mỗi chiều.</span>
            ) : (
              <span><b>Lưu ý giáo dục:</b> Backtest EDU hiện giả định trượt giá bằng 0 (slippage = 0), kết quả giao dịch thực tế trên sàn có thể chênh lệch do độ sâu thanh khoản thị trường.</span>
            )}
          </div>
        )
      })()}

      {Array.isArray(cfg?.conflicts) && cfg.conflicts.length > 0 && (
        <div className="edu-conflict-notice" style={{
          margin: '0 0 10px',
          padding: '8px 12px',
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.35)',
          borderRadius: 6,
          fontSize: 12,
          color: '#fca5a5',
        }}>
          <div style={{ fontWeight: 600, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>⚠️</span> <span>Cảnh báo: Cấu hình giao diện đang ghi đè tham số khai báo trong code</span>
          </div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {cfg.conflicts.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}

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
          {stage === 'all' && isNum(m?.trades) && m.trades === 0 && trades.length === 0 && open.length === 0 && <NoTradeNotice result={result} />}
          {explain && <section className="se-cc"><div className="se-cc-h"><b>Chiến lược làm gì</b></div><div className="se-cc-b"><ResultExplain result={result} /></div></section>}
          <YearlyTable rows={yearly} />
          {yearly.length > 0 && <p className="n-note se-pad">{BASIS_NOTE}</p>}
          {!ser && <p className="n-note se-pad">Không có chuỗi vốn cho giai đoạn này.</p>}
          {ser && bench && (shown.equity || shown.pnl) && <p className="n-note se-pad">Đường nét đứt: benchmark luôn long (cùng rổ, vốn và khoảng ngày){stage === 'test' ? ', được backend chạy lại trên chính cửa sổ Test từ vốn đầu' : ''}.</p>}
          {ser && !bench && (shown.equity || shown.pnl) && <p className="n-note se-pad">Không có benchmark cho giai đoạn này.</p>}
          {ser?.downsample?.step > 1 && <p className="n-note se-pad">Biểu đồ đã hạ mẫu ở backend: mỗi điểm gộp {ser.downsample.step} ngày ({fmtNum(ser.downsample.source_points, 0)} → {fmtNum(ser.downsample.points, 0)} điểm); equity lấy cuối nhóm, drawdown lấy đáy nhóm, lợi suất là lãi kép của nhóm.</p>}
          {ser && CHARTS.filter((c) => shown[c.key]).map((c) => {
            const r = chartRanges[c.key] || [0, 1]
            const isZoomed = r[0] > 0.001 || r[1] < 0.999
            return (
              <ChartCard
                key={c.key}
                title={c.label}
                tour={c.key}
                isZoomed={isZoomed}
                onResetZoom={() => updateRange(c.key, [0, 1])}
              >
                {(f) => <>
                  {body(c.key)(f)}
                  {c.key === 'equity' && (
                    <RangeBrush
                      values={ser.equity}
                      range={chartRanges.equity || [0, 1]}
                      onChange={(newR) => updateRange('equity', newR)}
                    />
                  )}
                </>}
              </ChartCard>
            )
          })}
        </>
      )}

      {sub === 'perf' && (
        <>
          {m ? <section className="se-cc"><div className="se-cc-h"><b>Chỉ số</b></div><div className="se-cc-b"><MetricTiles m={m} />
            <p className="n-note" style={{ marginTop: 8 }}>{BASIS_NOTE}</p>
</div></section>
            : <p className="n-note se-pad">Không có số liệu cho giai đoạn này.</p>}
          {bySym.length > 0 && <section className="se-cc" data-tour="by_symbol"><div className="se-cc-h"><b>Theo tài sản</b><span className="sp" /><span className="muted">{bySym.length} tài sản</span></div><div className="se-cc-b"><Rows rows={bySym} spec={SYMBOL_COLS} empty="" /></div></section>}
        </>
      )}

      {sub === 'analysis' && (
        <>
          <div data-tour="testing_status">
            <TestingStatusCard metrics={m} stage={stage} capital={cfg?.initial_capital} />
          </div>
          <EffectiveConfigTable cfg={cfg} />
          <Diagnostics result={result} isEducation={explain} />
          {Array.isArray(result?.trades) ? <section className="se-cc" data-tour="trades"><div className="se-cc-h"><b>Danh sách lệnh</b><span className="sp" /><span className="muted">{fmtNum(trades.length, 0)} lệnh</span></div><div className="se-cc-b"><TradesTable trades={trades} /></div></section>
            : <p className="n-note se-pad">Kết quả không kèm danh sách lệnh.</p>}
          {open.length > 0 && <section className="se-cc"><div className="se-cc-h"><b>Vị thế còn mở cuối kỳ</b><span className="sp" /><span className="muted">{open.length}</span></div><div className="se-cc-b"><Rows rows={open} spec={POSITION_COLS} empty="" /></div></section>}
          <WarningsPanel warnings={result?.warnings} />
        </>
      )}
    </div>
  )
}
