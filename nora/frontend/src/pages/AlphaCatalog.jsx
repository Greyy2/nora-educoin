import React, { useEffect, useMemo, useRef, useState } from 'react'
import { PageHead, Panel, Status, Loading, ErrorState, Empty } from '../components/ui'
import MathBlock from '../components/MathBlock'
import Term from '../components/Term'
import useAsync from '../hooks/useAsync'
import { getAlphaCatalog } from '../api'
import { fmtNum, fmtPct, fmtSPct, signClass, isNum } from '../lib/format'
import { legLabel } from '../lib/strategyLabel'
import { stageName, stageShort } from '../lib/funnel'
import '../styles/alphadoc.css'

const TF_TEXT = { '1m': '1 phút', '5m': '5 phút', '15m': '15 phút', '1h': '1 giờ', '4h': '4 giờ', '24h': '24 giờ' }
const SIDE_CLS = { LONG: 'long', SHORT: 'short' }
const statusTone = (a) => (a.book === 'main' ? 'ok' : 'warn')

/** Dòng "Triển khai": nhãn theo sổ + chế độ bot đang chạy thật (nếu đọc được). */
function Deploy({ d }) {
  const run = d?.running_modes || []
  return (
    <span className="deploy">
      {d?.label || '—'}
      {run.length > 0 && <span className="muted"> · đang chạy: {run.join(', ')}</span>}
    </span>
  )
}

/** Thẻ số liệu nhỏ. */
function Tile({ label, children }) {
  return <div className="n-tile"><div className="l">{label}</div><div className="v">{children}</div></div>
}

function StatGrid({ s }) {
  return (
    <div className="n-ad-statgrid">
      <Tile label="Lãi"><span className={signClass(s.ret_pct)}>{fmtSPct(s.ret_pct, 1)}</span></Tile>
      <Tile label={<Term k="mdd">MDD</Term>}>{fmtPct(s.mdd_pct, 1)}</Tile>
      <Tile label={<Term k="sharpe">Sharpe</Term>}>{fmtNum(s.sharpe, 2)}</Tile>
      <Tile label={<Term k="sortino">Sortino</Term>}>{fmtNum(s.sortino, 2)}</Tile>
      <Tile label={<Term k="profit_factor">PF</Term>}>{fmtNum(s.profit_factor, 2)}</Tile>
      <Tile label="Thắng">{fmtPct(s.win_rate, 1)}</Tile>
      <Tile label="Số lệnh">{fmtNum(s.trades, 0)}</Tile>
      <Tile label="Tài sản có lãi">{isNum(s.symbols_positive) ? s.symbols_positive : '—'}</Tile>
      <Tile label="Lãi · giá xấu nhất"><span className={signClass(s.extreme_ret_pct)}>{fmtSPct(s.extreme_ret_pct, 1)}</span></Tile>
      <Tile label="MDD · giá xấu nhất">{fmtPct(s.extreme_mdd_pct, 1)}</Tile>
    </div>
  )
}

function BookLine({ b }) {
  const w = b.wfa
  const hold = b.holdout?.extreme
  return (
    <div className="n-ad-books">
      <span><b>{b.kind === 'main' ? 'Sổ chính' : 'Sổ thử nghiệm'}</b> · {b.status_label}</span>
      <span>Khung {TF_TEXT[b.timeframe] || b.timeframe} · {b.universe?.length || 0} tài sản · rủi ro/lệnh {fmtNum(b.risk_per_trade_pct, 2)}%</span>
      {w?.compounded_oos_ret_pct && <span>Lãi kép OOS (walk-forward) <b className="pos">{fmtSPct(w.compounded_oos_ret_pct.extreme, 1)}</b> giá xấu nhất · MDD fold xấu nhất {fmtPct(w.worst_fold_mdd_pct?.extreme, 2)} · {w.positive_folds}/{w.n_folds} fold lãi</span>}
      {hold && <span>Holdout giá xấu nhất {fmtSPct(hold.ret_pct, 1)} · MDD {fmtPct(hold.mdd_pct, 1)}</span>}
      <span>Holdout: {b.holdout_pass == null ? '—' : b.holdout_pass ? <b className="pos">đạt</b> : <b className="neg">không đạt</b>}</span>
    </div>
  )
}

/** Ngăn bên phải: ý tưởng + từng phần công thức của một alpha. */
function AlphaDoc({ a, book, onClose }) {
  const opener = useRef(null)
  const box = useRef(null)
  useEffect(() => {
    opener.current = document.activeElement
    box.current?.focus()
    const key = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); try { opener.current?.focus?.() } catch (e) { /* bỏ qua */ } }
  }, [onClose])
  const s = a.stats
  return (
    <div className="n-drawer-wrap">
      <div className="n-drawer-bg" onClick={onClose} aria-hidden="true" />
      <aside className="n-drawer" role="dialog" aria-modal="true" aria-label={`Chi tiết alpha ${a.label}`} tabIndex={-1} ref={box}>
        <header className="n-drawer-h">
          <div style={{ minWidth: 0 }}>
            <div className="kick muted">Alpha · {a.book === 'main' ? 'sổ chính' : 'sổ thử nghiệm'}</div>
            <h2 title={a.alpha_id || a.id}>{legLabel(a.id)}{a.alpha_id ? <span className="mono muted"> · {a.alpha_id.slice(0, 8)}</span> : null}</h2>
          </div>
          <button type="button" className="n-btn" onClick={onClose} aria-label="Đóng chi tiết">Đóng ✕</button>
        </header>
        <div className="n-drawer-b">
          <div style={{ display: 'grid', gap: 14, paddingBottom: 18 }}>
            <div className="n-ad-tags">
              <span className={`n-badge ${SIDE_CLS[a.side] || ''}`}>{a.side}</span>
              <span className="n-badge">{TF_TEXT[a.timeframe] || a.timeframe}</span>
              <Status tone={statusTone(a)}>{a.status_label}</Status>
              <span className="n-note"><Deploy d={a.deploy} /></span>
              <span className="n-note">Vũ trụ: {(a.universe || []).map((u) => u.replace('@perp', '')).join(' · ') || '—'}</span>
            </div>
            <section className="n-ad-sec" aria-label="Ý tưởng">
              <h3>Ý tưởng</h3>
              <p className="n-ad-idea">{a.idea}</p>
              {a.description && <p className="n-note">{a.description}</p>}
            </section>
            <section className="n-ad-sec" aria-label="Thống kê">
              <h3>Thống kê · {stageName(s.stage)} ({stageShort(s.stage)})</h3>
              <StatGrid s={s} />
              {book?.wfa && <p className="n-note">Cả sổ: lãi kép OOS {fmtSPct(book.wfa.compounded_oos_ret_pct?.level, 1)} (đúng mức) / {fmtSPct(book.wfa.compounded_oos_ret_pct?.extreme, 1)} (giá xấu nhất), MDD fold xấu nhất {fmtPct(book.wfa.worst_fold_mdd_pct?.extreme, 2)}, {book.wfa.positive_folds}/{book.wfa.n_folds} fold OOS có lãi.</p>}
            </section>
            {(a.formulas || []).map((f, i) => (
              <section className="n-ad-sec" key={f.key} aria-label={f.title}>
                <h3>{i + 1}. {f.title}</h3>
                <MathBlock latex={f.latex} label={f.title} />
                {f.note && <p className="n-note">{f.note}</p>}
              </section>
            ))}
            <p className="n-note">Công thức dựng tự động từ đúng cấu trúc và tham số mà engine đang chạy; mô phỏng lịch sử không bảo đảm kết quả tương lai.</p>
          </div>
        </div>
      </aside>
    </div>
  )
}

function SourceTable({ source, onOpen, openId }) {
  const rows = source.alphas || []
  if (!rows.length) return <Empty title="Chưa có alpha nào trong nguồn này">Dựng sổ chiến lược hoặc xuất bản từ Phễu kiểm duyệt alpha để có danh mục.</Empty>
  return (
    <div className="n-tblwrap">
      <table className="n-tbl n-ad-tbl">
        <thead>
          <tr>
            <th>Alpha</th><th>Chiến lược</th><th>Trạng thái / Triển khai</th>
            <th className="r">Lợi nhuận</th><th className="r"><Term k="mdd">MDD</Term></th><th className="r"><Term k="sharpe">Sharpe</Term></th>
            <th className="r"><Term k="profit_factor">PF</Term></th><th className="r">Thắng</th><th className="r">Số lệnh</th><th title="Giai đoạn phễu của số liệu">Giai đoạn</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => {
            const key = `${a.book}:${a.id}`
            const s = a.stats
            return (
              <tr key={key} className={openId === key ? 'sel' : ''} onClick={() => onOpen(key)}>
                <td className="name">
                  <button type="button" className="n-ad-open" onClick={(e) => { e.stopPropagation(); onOpen(key) }} title="Xem ý tưởng và công thức">{legLabel(a.id)}</button>
                  {' '}<span className={`n-badge ${SIDE_CLS[a.side] || ''}`}>{a.side}</span> <span className="n-badge">{a.timeframe}</span>
                  {a.alpha_id && <span className="sub mono">{a.alpha_id.slice(0, 8)}</span>}
                </td>
                <td>{a.strategy_label}</td>
                <td className="deploy"><Status tone={statusTone(a)}>{a.status_label}</Status><div style={{ marginTop: 3 }}><Deploy d={a.deploy} /></div></td>
                <td className={`r ${signClass(s.ret_pct)}`}>{fmtSPct(s.ret_pct, 1)}</td>
                <td className="r">{fmtPct(s.mdd_pct, 1)}</td>
                <td className="r">{fmtNum(s.sharpe, 2)}</td>
                <td className="r">{fmtNum(s.profit_factor, 2)}</td>
                <td className="r">{fmtPct(s.win_rate, 1)}</td>
                <td className="r">{fmtNum(s.trades, 0)}</td>
                <td title={stageName(s.stage)}>{stageShort(s.stage)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function AlphaCatalog() {
  const q = useAsync(() => getAlphaCatalog(), [])
  const [open, setOpen] = useState(null)   // "<sổ>:<id>"
  const sources = q.data?.sources || []
  const picked = useMemo(() => {
    if (!open) return null
    for (const src of sources) {
      const a = (src.alphas || []).find((x) => `${x.book}:${x.id}` === open)
      if (a) return { a, book: src.books?.[a.book] }
    }
    return null
  }, [open, sources])
  return (
    <>
      <PageHead kicker="Danh mục alpha" title="Alpha · Ý tưởng và công thức"
        subtitle="Mỗi alpha mô tả bằng ý tưởng kinh tế và công thức toán tài chính của chính cấu trúc đang chạy, kèm bảng thống kê. Bấm một dòng để xem chi tiết." />
      {q.error && <ErrorState title="Không tải được danh mục alpha" error={q.error} onRetry={q.reload} />}
      {q.loading && !q.data && <Loading what="danh mục alpha" />}
      {sources.map((src) => (
        <Panel key={src.key} title={src.label} meta={<span>{(src.alphas || []).length} alpha</span>} className="n-ad-src">
          {Object.values(src.books || {}).map((b) => <BookLine key={b.kind} b={b} />)}
          <SourceTable source={src} onOpen={setOpen} openId={open} />
        </Panel>
      ))}
      {q.data && !sources.length && <Empty title="Chưa có nguồn alpha nào" />}
      {picked && <AlphaDoc a={picked.a} book={picked.book} onClose={() => setOpen(null)} />}
    </>
  )
}
