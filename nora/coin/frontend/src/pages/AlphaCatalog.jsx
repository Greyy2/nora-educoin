import React, { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { PageHead, Panel, Loading, ErrorState, Empty, Segmented } from '../components/ui'
import MathBlock from '../components/ui/MathBlock'
import useAsync, { useResource } from '../hooks/useAsync'
import SystemStrategyEditor from '../components/alpha/studio/SystemStrategyEditor'
import { getAlphaCatalog, getTopAgents, postArchiveUserAlpha, postUpdateUserAlphaStatus, deleteUserAlpha } from '../api'
import { fmtNum, fmtPct, fmtSPct, signClass, isNum } from '../lib/format'
import useResizableDrawer from '../hooks/useResizableDrawer'
import '../styles/alpha.css'

// Thư viện chiến lược: mỗi CHIẾN LƯỢC = ý tưởng -> công thức bằng lời -> công thức toán -> thống kê alpha đã đạt.
const SIDE_CLS = { Long: 'ok', Short: 'bad', 'Long + Short': 'ok' }
const BOOK = { main: 'sổ chính', explore: 'thử nghiệm' }

function best(stats) {
  return (stats || []).reduce((b, x) => (b == null || (x.ret_pct ?? -1e9) > (b.ret_pct ?? -1e9) ? x : b), null)
}

/** Câu có ký hiệu toán trong $…$ -> chữ + KaTeX nội dòng. */
function Rich({ text }) {
  return String(text).split(/(\$[^$]+\$)/).map((x, i) => (x.startsWith('$') && x.endsWith('$') && x.length > 2
    ? <MathBlock key={i} latex={x.slice(1, -1)} inline /> : <React.Fragment key={i}>{x}</React.Fragment>))
}

const aHead = (a) => `${a.timeframe} · ${a.side === 'LONG' ? 'L' : 'S'}`
const aTitle = (a) => `${a.alpha_id || a.leg} · ${BOOK[a.book] || a.book}`

function Results({ stats }) {
  return (
    <div className="n-tblwrap">
      <table className="n-tbl n-ad-res">
        <thead><tr><th>Alpha</th><th className="r">Lợi nhuận</th><th className="r">Bi quan</th><th className="r">MDD</th><th className="r">Thắng</th><th className="r">PF</th><th className="r">Sharpe</th><th className="r">Sortino</th><th className="r">Lệnh</th><th className="r">TS có lãi</th></tr></thead>
        <tbody>
          {stats.map((a) => (
            <tr key={`${a.book}:${a.leg}`}>
              <td title={aTitle(a)}><b>{aHead(a)}</b> <span className="mono muted">{(a.alpha_id || a.leg).slice(0, 8)}</span> <span className="n-badge">{BOOK[a.book] || a.book}</span></td>
              <td className={`r ${signClass(a.ret_pct)}`}>{fmtSPct(a.ret_pct, 1)}</td>
              <td className={`r ${signClass(a.extreme_ret_pct)}`}>{fmtSPct(a.extreme_ret_pct, 1)}</td>
              <td className="r">{fmtPct(a.mdd_pct, 2)}</td>
              <td className="r">{fmtPct(a.win_rate, 1)}</td>
              <td className="r">{fmtNum(a.profit_factor, 2)}</td>
              <td className="r">{fmtNum(a.sharpe, 2)}</td>
              <td className="r">{fmtNum(a.sortino, 2)}</td>
              <td className="r">{fmtNum(a.trades, 0)}</td>
              <td className="r">{a.symbols_positive != null ? `${a.symbols_positive}/${a.universe || '?'}` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Tile({ label, value, cls = '', sub }) {
  return <div className="n-tile"><div className="l">{label}</div><div className={`v ${cls}`}>{value}</div>{sub && <div className="s muted">{sub}</div>}</div>
}

function Summary({ m }) {
  const avg = m.n > 1 ? `TB ${m.n} alpha` : null
  return (
    <div className="n-ad-sum">
      <Tile label="Lợi nhuận" value={fmtSPct(m.ret_pct, 1)} cls={signClass(m.ret_pct)} sub={avg} />
      <Tile label="Lợi nhuận (bi quan)" value={fmtSPct(m.extreme_ret_pct, 1)} cls={signClass(m.extreme_ret_pct)} sub="SL khớp giá xấu nhất nến" />
      <Tile label="MDD" value={fmtPct(m.mdd_pct, 2)} sub={m.n > 1 ? 'xấu nhất' : null} />
      <Tile label="MDD (bi quan)" value={fmtPct(m.extreme_mdd_pct, 2)} />
      <Tile label="Tỉ lệ thắng" value={fmtPct(m.win_rate, 1)} sub={avg} />
      <Tile label="Profit factor" value={fmtNum(m.profit_factor, 2)} sub={avg} />
      <Tile label="Sharpe" value={fmtNum(m.sharpe, 2)} sub={avg} />
      <Tile label="Sortino" value={fmtNum(m.sortino, 2)} sub={avg} />
      <Tile label="Số lệnh" value={fmtNum(m.trades, 0)} sub={m.n > 1 ? 'tổng' : null} />
    </div>
  )
}

function TopAgentSummary({ m }) {
  return (
    <div className="n-ad-sum">
      <Tile label="Lợi nhuận chốt" value={m.realized != null ? `${m.realized >= 0 ? '+' : ''}${fmtNum(m.realized, 0)} USDT` : '—'} cls={signClass(m.realized)} />
      <Tile label="Tỉ lệ thắng" value={fmtPct(m.win_rate, 1)} />
      <Tile label="Profit factor" value={fmtNum(m.profit_factor, 2)} />
      <Tile label="Số lệnh" value={fmtNum(m.trades, 0)} sub="lệnh thực tế (báo cáo)" />
      <Tile label="Số basket" value={fmtNum(m.baskets, 0)} sub="nhóm lệnh theo vị thế" />
      <Tile label="Tần suất" value={m.per_day != null ? `${fmtNum(m.per_day, 1)} lệnh/ngày` : '—'} />
      <Tile label="Đòn bẩy" value={m.leverage != null ? `${m.leverage}x` : '—'} />
      <Tile label="Thời gian giữ" value={m.hold_med != null ? `${fmtNum(m.hold_med, 1)} giờ` : '—'} sub="trung vị" />
      <Tile label="Tỉ lệ Long" value={m.long_pct != null ? fmtPct(m.long_pct, 1) : '—'} sub={m.long_pct != null ? `Short ${fmtPct(100 - m.long_pct, 1)}` : null} />
      <Tile label="Lãi lớn nhất" value={m.max_win != null ? `+${fmtNum(m.max_win, 0)} $` : '—'} cls="ok" />
      <Tile label="Lỗ lớn nhất" value={m.max_loss != null ? `${fmtNum(m.max_loss, 0)} $` : '—'} cls="bad" />
      <Tile label="Tỉ lệ nhồi (DCA)" value={m.add_pct != null ? fmtPct(m.add_pct, 1) : '—'} />
      <Tile label="Tầng DCA tối đa" value={m.max_layers != null ? `${m.max_layers} tầng` : '—'} />
    </div>
  )
}

function fmtFrozen(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? String(iso) : `${d.toISOString().slice(0, 16).replace('T', ' ')} UTC`
}

/** Dòng nguồn gốc số liệu Top Agent (file đã đóng băng) + cảnh báo OOS lệch bản fit. */
function TopAgentProvenance({ prov, mixed, caveat }) {
  return (
    <div style={{ marginTop: 6 }}>
      {prov && (
        <div className="muted" style={{ fontSize: 12 }}>
          Số liệu đóng băng lúc {fmtFrozen(prov.frozen_at)}{prov.git_commit ? ` · commit ${String(prov.git_commit).slice(0, 7)}` : ''}{prov.source ? ` · nguồn: ${prov.source}` : ''}
        </div>
      )}
      {mixed && (
        <div className="warn" style={{ fontSize: 12, marginTop: 4 }}>⚠ OOS tính trên bản fit cũ hơn</div>
      )}
      {caveat && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{caveat}</div>}
    </div>
  )
}

function TopAgentBreakdown({ rows }) {
  if (!rows || rows.length === 0) return null
  return (
    <div style={{ marginTop: 14 }}>
      <div className="muted" style={{ fontSize: 13, marginBottom: 6, fontWeight: 500 }}>
        Cơ cấu phân bổ các loại lệnh thoát thực tế:
      </div>
      <div className="n-tblwrap">
        <table className="n-tbl n-ad-res">
          <thead>
            <tr>
              <th>Phương thức thoát lệnh</th>
              <th className="r">Tỷ trọng lệnh</th>
              <th>Mô tả xử lý</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, idx) => (
              <tr key={idx}>
                <td><b>{r.label}</b></td>
                <td className="r"><b>{fmtPct(r.pct, 1)}</b></td>
                <td className="muted" style={{ fontSize: 12.5 }}>{r.desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function StrategyDoc({ s, onClose, onReload }) {
  const navigate = useNavigate()
  const [acting, setActing] = useState(false)
  const [editSrc, setEditSrc] = useState(false)
  const box = useRef(null)
  const { width, onMouseDown } = useResizableDrawer(980)

  useEffect(() => {
    const opener = document.activeElement
    box.current?.focus()
    const key = (e) => { if (e.key === 'Escape' && !document.querySelector('.sse-box')) onClose() }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); try { opener?.focus?.() } catch (e) { /* bỏ qua */ } }
  }, [onClose])

  const handleArchive = async () => {
    if (!window.confirm(`Bạn có chắc muốn lưu trữ Alpha "${s.name}"?`)) return
    setActing(true)
    try {
      await postArchiveUserAlpha(s.alpha_id)
      onClose()
      if (onReload) onReload()
    } catch (e) {
      alert(e.message || 'Lỗi lưu trữ Alpha')
    } finally {
      setActing(false)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(`Bạn có chắc chắn muốn xoá vĩnh viễn chiến lược "${s.name}"? Dữ liệu và các phiên bản sẽ bị xoá hoàn toàn khỏi hệ thống.`)) return
    setActing(true)
    try {
      await deleteUserAlpha(s.alpha_id)
      onClose()
      if (onReload) onReload()
    } catch (e) {
      alert(e.message || 'Lỗi xoá Alpha')
    } finally {
      setActing(false)
    }
  }

  const handleToggleCandidate = async () => {
    const current = s.stats?.[0]?.stage || 'SAVED'
    const next = current === 'CANDIDATE' ? 'SAVED' : 'CANDIDATE'
    setActing(true)
    try {
      await postUpdateUserAlphaStatus(s.alpha_id, next)
      if (onReload) onReload()
    } catch (e) {
      alert(e.message || 'Lỗi cập nhật trạng thái')
    } finally {
      setActing(false)
    }
  }

  const handleOpenEditor = () => {
    navigate(`/coin/alpha/create?alpha=${encodeURIComponent(s.alpha_id || s.strategy)}`)
  }

  return createPortal(
    <div className="v2 n-drawer-wrap">
      <div className="n-drawer-bg" onClick={onClose} aria-hidden="true" />
      <aside
        className="n-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`Chiến lược ${s.name} ${s.side}`}
        style={{ width: `${width}px`, maxWidth: '100vw' }}
        tabIndex={-1}
        ref={box}
      >
        {/* Thanh kéo co giãn cạnh trái */}
        <div
          className="n-drawer-resize-handle"
          onMouseDown={onMouseDown}
          title="Kéo sang trái/phải để thay đổi kích thước ngăn chi tiết"
        />

        <header className="n-drawer-h" style={{ paddingBottom: 10 }}>
          <div style={{ minWidth: 0 }}>
            <div className="kick muted">{s.isTopAgent ? 'Top Agent Trade · OKX Copy-Trade' : s.kind}</div>
            <h2>
              {s.name}{' '}
              <span className={`n-badge ${SIDE_CLS[s.side] || ''}`}>{s.side}</span>
            </h2>
            {s.isTopAgent && <TopAgentProvenance prov={s.provenance} mixed={s.mixed_runs} caveat={s.caveat} />}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
              {!s.is_user_alpha && !s.isTopAgent && s.strategy && (
                <button type="button" className="n-btn sm" onClick={() => setEditSrc(true)} title="Xem / sửa file chiến lược hệ thống">
                  {'</>'} Mã nguồn
                </button>
              )}
              {s.is_user_alpha && (
                <>
                  <button type="button" className="n-btn sm brand" onClick={handleOpenEditor}>
                    Mở để sửa ➔
                  </button>
                  <button type="button" className="n-btn sm" onClick={handleToggleCandidate} disabled={acting}>
                    {s.stats?.[0]?.stage === 'CANDIDATE' ? 'Bỏ đánh dấu ứng viên' : '★ Đánh dấu ứng viên'}
                  </button>
                  <button type="button" className="n-btn sm" style={{ color: 'var(--n-neg)' }} onClick={handleArchive} disabled={acting}>
                    Lưu trữ (Archive)
                  </button>
                  <button type="button" className="n-btn sm danger" onClick={handleDelete} disabled={acting} title="Xoá vĩnh viễn khỏi hệ thống">
                    🗑 Xoá vĩnh viễn
                  </button>
                </>
              )}
            </div>
          </div>
          <button type="button" className="n-btn" onClick={onClose} aria-label="Đóng">Đóng ✕</button>
        </header>

        <div className="n-drawer-b" style={{ padding: '20px 24px' }}>
          <div className="n-ad-body">
            <section className="n-ad-sec">
              <h3>Ý tưởng giao dịch</h3>
              <p className="n-ad-idea">{s.idea}</p>
            </section>

            {/* Bảng tham số cấu hình */}
            {s.params_list && s.params_list.length > 0 && (
              <section className="n-ad-sec">
                <h3>Bộ tham số cấu hình</h3>
                <div className="n-tblwrap" style={{ marginTop: 8 }}>
                  <table className="n-tbl">
                    <thead>
                      <tr>
                        <th>Tham số</th>
                        <th>Giá trị</th>
                        <th>Khóa tham số</th>
                      </tr>
                    </thead>
                    <tbody>
                      {s.params_list.map((p) => (
                        <tr key={p.key}>
                          <td><b>{p.label}</b></td>
                          <td><b className="mono ok" style={{ fontSize: 13.5 }}>{p.value}</b></td>
                          <td className="mono muted">{p.key}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            <section className="n-ad-sec">
              <h3>Quy tắc thực thi & Diễn giải logic</h3>
              <ul className="n-ad-plain">
                {s.plain.map((x, i) => <li key={i}><Rich text={x} /></li>)}
              </ul>
            </section>

            {s.math && s.math.length > 0 && (
              <section className="n-ad-sec">
                <h3>Công thức toán học định lượng</h3>
                {s.isTopAgent && <p className="n-note">Dạng tổng quát của loại bot (minh hoạ ký hiệu), không phải tham số đã fit của bot này; tham số cụ thể xem mục Công thức.</p>}
                {s.math.map((m, i) => (
                  <div key={i} className="n-ad-mathrow">
                    <span className="t">{m.title}</span>
                    <MathBlock latex={m.latex} label={m.title} />
                  </div>
                ))}
              </section>
            )}

          </div>
        </div>
      </aside>
      {editSrc && <SystemStrategyEditor id={s.strategy} name={s.name} onClose={() => setEditSrc(false)} onSaved={onReload} />}
    </div>,
    document.body
  )
}

function extractParamsText(s) {
  if (s.isTopAgent) {
    const f = s.formula_summary || {}
    const p = []
    if (f.tp) {
      const tpClean = String(f.tp).replace(/^TP\s*=\s*/i, '').trim()
      p.push(`TP: ${tpClean}`)
    }
    if (f.sl) {
      const slClean = String(f.sl).replace(/^SL\s*=\s*/i, '').trim()
      p.push(`SL: ${slClean.length > 25 ? slClean.slice(0, 25) + '…' : slClean}`)
    }
    if (f.act) {
      const actClean = String(f.act).replace(/^kích hoạt trailing\s*=\s*/i, '').trim()
      p.push(`Trail: ${actClean.length > 20 ? actClean.slice(0, 20) + '…' : actClean}`)
    }
    if (s.summary?.leverage) p.push(`Đòn bẩy: ${s.summary.leverage}x`)
    if (p.length > 0) return p.slice(0, 3).join(' · ')
    return s.plain?.[0] || 'Chiến lược copy-trade OKX'
  }
  if (s.params_list && s.params_list.length > 0) {
    return s.params_list.map((p) => `${p.label || p.key}: ${p.value}`).slice(0, 4).join(' · ')
  }
  if (s.config?.params && Object.keys(s.config.params).length > 0) {
    return Object.entries(s.config.params).map(([k, v]) => `${k}: ${v}`).slice(0, 4).join(' · ')
  }
  if (s.params && Object.keys(s.params).length > 0) {
    return Object.entries(s.params).map(([k, v]) => `${k}: ${v}`).slice(0, 4).join(' · ')
  }
  if (s.config?.position) {
    return `Đòn bẩy: ${s.config.position.leverage || 1}x · Vốn: ${s.config.position.size_pct || 100}%`
  }
  return null
}

function extractCardStats(s) {
  const m = s.summary || s.metrics || s.stats?.[0] || best(s.stats) || {}
  const ret = m.ret_pct ?? (s.isTopAgent && m.realized != null ? m.realized : null)
  let mdd = m.mdd_pct ?? m.extreme_mdd_pct
  let isMddUsdt = false
  if (mdd == null && s.isTopAgent && m.max_loss != null) {
    mdd = m.max_loss
    isMddUsdt = true
  }
  const sharpe = m.sharpe
  const winRate = m.win_rate ?? m.win
  return { ret, mdd, sharpe, winRate, isRealizedUsdt: s.isTopAgent && m.ret_pct == null && m.realized != null, isMddUsdt }
}

function CardStats({ s }) {
  const { ret, mdd, sharpe, winRate, isRealizedUsdt, isMddUsdt } = extractCardStats(s)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginTop: 8, padding: '8px 10px', background: 'var(--n-card, rgba(255,255,255,0.03))', borderRadius: 6, border: '1px solid var(--n-line, rgba(255,255,255,0.06))', fontSize: 12 }}>
      <div>
        <span className="muted" style={{ display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>PnL</span>
        <b className={signClass(ret)} style={{ fontSize: 13 }}>
          {ret == null ? '—' : isRealizedUsdt ? `${ret >= 0 ? '+' : ''}${fmtNum(ret, 0)} $` : fmtSPct(ret, 1)}
        </b>
      </div>
      <div>
        <span className="muted" style={{ display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>MDD</span>
        <b className="neg" style={{ fontSize: 13 }}>
          {mdd == null ? '—' : isMddUsdt ? `${fmtNum(mdd, 0)} $` : fmtPct(mdd, 1)}
        </b>
      </div>
      <div>
        <span className="muted" style={{ display: 'block', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {isNum(sharpe) ? 'Sharpe' : 'Win rate'}
        </span>
        <b style={{ fontSize: 13 }}>
          {isNum(sharpe) ? fmtNum(sharpe, 2) : winRate != null ? `${fmtNum(winRate, 1)}%` : '—'}
        </b>
      </div>
    </div>
  )
}

function Card({ s, onOpen }) {
  const paramsText = extractParamsText(s)

  return (
    <button type="button" className="n-ad-card" onClick={onOpen}>
      <div className="h">
        <b>{s.name}</b>
        <span className={`n-badge ${SIDE_CLS[s.side] || ''}`}>{s.side}</span>
      </div>
      <div className="k muted" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span>{s.kind}</span>
        {s.is_user_alpha && (
          <span className="n-badge" style={{ background: 'var(--n-accent-wash)', color: 'var(--n-accent)', fontWeight: 700 }}>
            Alpha người dùng
          </span>
        )}
        {s.isTopAgent && (
          <span className="n-badge" style={{ background: 'rgba(234, 179, 8, 0.15)', color: 'var(--n-warn, #eab308)', fontWeight: 600 }}>
            Tham khảo OKX
          </span>
        )}
        {s.isTopAgent && s.summary?.leverage && (
          <span className="n-badge">{s.summary.leverage}x</span>
        )}
      </div>
      {paramsText && (
        <div
          style={{
            fontSize: 11,
            color: 'var(--n-ink-2, #94a3b8)',
            marginTop: 6,
            lineHeight: 1.35,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            textAlign: 'left',
          }}
          title={paramsText}
        >
          <span style={{ color: 'var(--n-ink-3, #64748b)', fontWeight: 600 }}>Tham số: </span>
          {paramsText}
        </div>
      )}
      <CardStats s={s} />
    </button>
  )
}

const BOT_TYPE_GENERAL = {
  cutter: { kind: 'Loại bot: cutter', text: 'Mô tả chung của loại bot "cutter" (không phải tham số riêng của bot này): thoát vị thế bằng các luật chốt/cắt như TP, SL, trailing, hoà vốn. Tham số đã fit xem mục Công thức.' },
  hold: { kind: 'Loại bot: hold', text: 'Mô tả chung của loại bot "hold" (không phải tham số riêng của bot này): giữ vị thế và thoát theo các luật trong mục Công thức. Tham số đã fit xem mục Công thức.' },
  runner: { kind: 'Loại bot: runner', text: 'Mô tả chung của loại bot "runner" (không phải tham số riêng của bot này): thoát vị thế theo các luật trong mục Công thức. Tham số đã fit xem mục Công thức.' },
}
const FORMULA_LABELS = [
  ['tp', 'Chốt lời (TP)'],
  ['sl', 'Cắt lỗ (SL)'],
  ['act', 'Kích hoạt trailing'],
  ['gb', 'Giveback trailing'],
  ['bes', 'Kích hoạt hoà vốn'],
  ['brd', 'Độ sâu hoà vốn'],
]

function mapTopAgentBot(b, prov) {
  const r = b.report_stats?.real || {}
  const realized = r.realized ?? b.in_sample_metrics?.real_pnl_sum
  const win = r.win
  const general = BOT_TYPE_GENERAL[b.bot_type] || { kind: b.bot_type ? `Loại bot: ${b.bot_type}` : 'OKX copy-trade', text: 'Bot copy-trade OKX; các luật thoát đã fit xem mục Công thức.' }

  const longPct = r.longPct
  const side = longPct == null ? '—' : longPct >= 70 ? 'Long' : longPct <= 30 ? 'Short' : 'Long + Short'
  const kind = general.kind
  const idea = general.text

  const plain = []
  for (const [key, label] of FORMULA_LABELS) {
    if (b.formula_summary?.[key]) plain.push(`${label}: ${b.formula_summary[key]}`)
  }
  if (r.addPct != null && r.stepMed != null) {
    plain.push(`Nhồi lệnh (số liệu thực tế): ${fmtNum(r.addPct, 1)}% lệnh có nhồi, bước nhồi trung vị ${fmtNum(r.stepMed, 2)}%${r.maxLayers != null ? `, tối đa ${r.maxLayers} tầng` : ''}.`)
  }
  if (b.exit_structure && b.exit_structure.length > 0) {
    plain.push(`Cấu trúc luật thoát (theo fit): ${b.exit_structure.join(' → ')}.`)
  }
  if (plain.length === 0) plain.push('Chưa có công thức thoát đã fit trong dữ liệu.')

  const math = [
    {
      title: 'Dạng tổng quát · Chốt lời & Cắt lỗ',
      latex: String.raw`P_{\mathrm{TP}} = P_{\mathrm{avg}} \cdot (1 \pm k_{\mathrm{TP}}) \quad \Big| \quad \mathrm{ROI}_{\mathrm{SL}} = \alpha + \beta \cdot \mathrm{ATR}_{1\mathrm{h}} \cdot L`,
    },
    {
      title: 'Dạng tổng quát · Cơ chế Trailing Stop',
      latex: String.raw`P_{\mathrm{exit}} \le P_{\max} \cdot (1 - \delta_{\mathrm{giveback}}) \quad \text{khi} \quad \frac{P_{\max} - P_{\mathrm{avg}}}{P_{\mathrm{avg}}} \ge \Delta_{\mathrm{act}}`,
    },
    {
      title: 'Dạng tổng quát · Hoà vốn & Quản trị DCA',
      latex: String.raw`P_{\mathrm{BE}} = P_{\mathrm{avg}} \pm \Delta_{\mathrm{lock}} \quad \Big| \quad P_{\mathrm{add}, i} = P_{i-1} \cdot (1 - d_{\mathrm{step}}), \; i \le N_{\max}`,
    },
  ]

  const summary = {
    realized,
    win_rate: win,
    profit_factor: r.pf,
    trades: r.n,
    baskets: b.n_baskets,
    per_day: r.perDay,
    leverage: r.levMed,
    hold_med: r.holdMed,
    long_pct: r.longPct,
    max_win: r.maxWin,
    max_loss: r.maxLoss,
    add_pct: r.addPct,
    max_layers: r.maxLayers,
  }

  const breakdownDesc = {
    'TP-limit': 'Khớp giá chốt lời giới hạn đặt sẵn tại sàn',
    'trailing/pullback': 'Chốt lời động khi giá tạo đỉnh và quay đầu hồi',
    SL: 'Cắt lỗ bảo vệ tài khoản khi chạm ngưỡng rủi ro',
    'hoà vốn (hồi về)': 'Thoát lệnh tại giá hoà vốn khi đà tăng suy yếu',
    'hoà vốn (stop)': 'Stop bảo toàn vốn kích hoạt',
    'khác': 'Đóng vị thế theo điều kiện cấu trúc khác',
  }
  const breakdown = Object.entries(b.class_mix_pct || {}).map(([cls, pct]) => ({
    label: cls,
    pct,
    desc: breakdownDesc[cls] || 'Điều kiện thoát vị thế',
  }))

  return {
    key: `topagent_${b.slug}`,
    name: b.name,
    kind,
    side,
    idea,
    plain,
    math,
    summary,
    formula_summary: b.formula_summary || {},
    breakdown,
    isTopAgent: true,
    provenance: prov,
    mixed_runs: !!b.mixed_runs,
    caveat: b.caveat,
  }
}

export default function AlphaCatalog() {
  const [sp, setSp] = useSearchParams()
  const filter = sp.get('filter') || 'all'
  const setFilter = (f) => setSp({ filter: f })

  const q = useResource('alphas', () => getAlphaCatalog())
  const qAgents = useAsync(() => getTopAgents(), [])
  const [open, setOpen] = useState(null)

  const sources = q.data?.sources || []
  const noraStrategies = sources.flatMap((x) => x.strategies || [])
  const topAgentStrategies = (qAgents.data?.bots || []).map((b) => mapTopAgentBot(b, qAgents.data?.provenance))
  const allStrategies = [...noraStrategies, ...topAgentStrategies]
  const picked = open && allStrategies.find((x) => x.key === open)

  const nCore = allStrategies.filter((s) => !s.is_user_alpha && !s.isTopAgent).length
  const nUser = allStrategies.filter((s) => s.is_user_alpha).length
  const nRef = allStrategies.filter((s) => s.isTopAgent).length

  const filteredList = allStrategies.filter((s) => {
    if (filter === 'core') return !s.is_user_alpha && !s.isTopAgent
    if (filter === 'user') return !!s.is_user_alpha
    if (filter === 'reference') return !!s.isTopAgent
    return true
  })

  return (
    <>
      <PageHead
        kicker="Thư viện chiến lược"
        title="Alpha"
        subtitle="Danh mục toàn bộ Alpha: mô tả ý tưởng, bộ tham số cấu hình, quy tắc thực thi và công thức toán học định lượng."
      />
      {q.error && <ErrorState title="Không tải được thư viện chiến lược" error={q.error} onRetry={q.reload} />}
      {qAgents.error && <ErrorState title="Không tải được dữ liệu Top agent" error={qAgents.error} onRetry={qAgents.reload} />}
      {(q.loading && !q.data) || (qAgents.loading && !qAgents.data) ? (
        <Loading what="thư viện chiến lược" />
      ) : null}

      <Panel
        title="Danh mục chiến lược & Alpha"
        meta={
          <Segmented
            label="Lọc nhóm"
            value={filter === 'verified' ? 'all' : filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: `Tất cả (${allStrategies.length})` },
              { value: 'core', label: `Chiến lược hệ thống (${nCore})` },
              { value: 'user', label: `Alpha người dùng (${nUser})` },
              { value: 'reference', label: `Bot tham khảo OKX (${nRef})` },
            ]}
          />
        }
      >
        {filter === 'reference' && (
          <p className="muted" style={{ margin: '0 0 12px 0', fontSize: '13px', lineHeight: '1.5' }}>
            Chiến lược giao dịch của các bot copy-trade hàng đầu trên sàn OKX (dùng cho tham khảo & đối sánh mô hình).
          </p>
        )}
        {(filter === 'reference' || (filter === 'all' && topAgentStrategies.length > 0)) && (
          <div style={{ marginBottom: 12 }}>
            <TopAgentProvenance prov={qAgents.data?.provenance} />
          </div>
        )}
        {!filteredList.length ? (
          <Empty
            title={
              filter === 'user'
                ? 'Chưa có Alpha người dùng nào được lưu'
                : filter === 'reference'
                ? (qAgents.data?.reason || 'Chưa có dữ liệu bot tham khảo')
                : 'Chưa có chiến lược phù hợp bộ lọc'
            }
          />
        ) : (
          <div className="n-ad-grid">
            {filteredList.map((s) => (
              <Card key={s.key} s={s} onOpen={() => setOpen(s.key)} />
            ))}
          </div>
        )}
      </Panel>

      {picked && <StrategyDoc s={picked} onClose={() => setOpen(null)} onReload={() => { q.reload(); qAgents.reload() }} />}
    </>
  )
}

