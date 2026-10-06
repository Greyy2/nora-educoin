import React, { useEffect, useRef, useState } from 'react'
import { PageHead, Panel, Loading, ErrorState, Empty } from '../components/ui'
import MathBlock from '../components/MathBlock'
import useAsync from '../hooks/useAsync'
import { getAlphaCatalog } from '../api'
import { fmtNum, fmtPct, fmtSPct, signClass } from '../lib/format'
import '../styles/alphadoc.css'

// Thư viện chiến lược: mỗi CHIẾN LƯỢC (không phải mỗi alpha / khung giờ) = ý tưởng -> công thức bằng lời -> công thức toán -> thống kê alpha đã đạt.
const SIDE_CLS = { Long: 'ok', Short: 'bad' }
const BOOK = { main: 'sổ chính', explore: 'thử nghiệm' }

function best(stats) {
  return (stats || []).reduce((b, x) => (b == null || (x.ret_pct ?? -1e9) > (b.ret_pct ?? -1e9) ? x : b), null)
}

function StrategyDoc({ s, onClose }) {
  const box = useRef(null)
  useEffect(() => {
    const opener = document.activeElement
    box.current?.focus()
    const key = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); try { opener?.focus?.() } catch (e) { /* bỏ qua */ } }
  }, [onClose])
  return (
    <div className="n-drawer-wrap">
      <div className="n-drawer-bg" onClick={onClose} aria-hidden="true" />
      <aside className="n-drawer" role="dialog" aria-modal="true" aria-label={`Chiến lược ${s.name} ${s.side}`} tabIndex={-1} ref={box}>
        <header className="n-drawer-h">
          <div style={{ minWidth: 0 }}>
            <div className="kick muted">{s.kind}</div>
            <h2>{s.name} <span className={`n-badge ${SIDE_CLS[s.side] || ''}`}>{s.side}</span></h2>
          </div>
          <button type="button" className="n-btn" onClick={onClose} aria-label="Đóng">Đóng ✕</button>
        </header>
        <div className="n-drawer-b">
          <div className="n-ad-body">
            <section className="n-ad-sec"><h3>Ý tưởng</h3><p className="n-ad-idea">{s.idea}</p></section>
            <section className="n-ad-sec">
              <h3>Công thức</h3>
              <ul className="n-ad-plain">{s.plain.map((x, i) => <li key={i}>{x}</li>)}</ul>
            </section>
            <section className="n-ad-sec">
              <h3>Công thức toán học</h3>
              {s.math.map((m, i) => (
                <div key={i} className="n-ad-mathrow"><span className="t">{m.title}</span><MathBlock latex={m.latex} label={m.title} /></div>
              ))}
            </section>
            <section className="n-ad-sec">
              <h3>Thống kê</h3>
              {!s.stats.length ? <p className="n-note">Chưa có alpha nào của chiến lược này qua kiểm định.</p> : (
                <div className="n-tblwrap">
                  <table className="n-tbl">
                    <thead><tr><th>Alpha</th><th>Khung</th><th className="r">Lợi nhuận</th><th className="r">MDD</th><th className="r">Sharpe</th><th className="r">PF</th><th className="r">Thắng</th><th className="r">Lệnh</th></tr></thead>
                    <tbody>
                      {s.stats.map((a) => (
                        <tr key={`${a.book}:${a.leg}`}>
                          <td><span className="mono">{(a.alpha_id || a.leg).slice(0, 8)}</span> <span className="muted">· {a.side === 'LONG' ? 'Long' : 'Short'} · {BOOK[a.book] || a.book}</span></td>
                          <td className="mono">{a.timeframe}</td>
                          <td className={`r ${signClass(a.ret_pct)}`}>{fmtSPct(a.ret_pct, 1)}</td>
                          <td className="r">{fmtPct(a.mdd_pct, 2)}</td>
                          <td className="r">{fmtNum(a.sharpe, 2)}</td>
                          <td className="r">{fmtNum(a.profit_factor, 2)}</td>
                          <td className="r">{fmtPct(a.win_rate, 1)}</td>
                          <td className="r">{fmtNum(a.trades, 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </div>
        </div>
      </aside>
    </div>
  )
}

function Card({ s, onOpen }) {
  const b = best(s.stats)
  return (
    <button type="button" className="n-ad-card" onClick={onOpen}>
      <div className="h"><b>{s.name}</b> <span className={`n-badge ${SIDE_CLS[s.side] || ''}`}>{s.side}</span></div>
      <div className="k muted">{s.kind}</div>
      <p className="idea">{s.idea}</p>
      <div className="st">
        <span><span className="muted">Alpha đạt</span> <b>{s.stats.length}</b></span>
        {b && <span><span className="muted">Tốt nhất</span> <b className={signClass(b.ret_pct)}>{fmtSPct(b.ret_pct, 1)}</b> <span className="muted">MDD</span> <b>{fmtPct(b.mdd_pct, 1)}</b></span>}
      </div>
    </button>
  )
}

export default function AlphaCatalog() {
  const q = useAsync(() => getAlphaCatalog(), [])
  const [open, setOpen] = useState(null)
  const sources = q.data?.sources || []
  const picked = open && sources.flatMap((x) => x.strategies || []).find((x) => x.key === open)
  return (
    <>
      <PageHead kicker="Thư viện chiến lược" title="Alpha" subtitle="Mỗi chiến lược: ý tưởng → công thức → công thức toán → thống kê các alpha đã đạt. Bấm một thẻ để xem." />
      {q.error && <ErrorState title="Không tải được thư viện chiến lược" error={q.error} onRetry={q.reload} />}
      {q.loading && !q.data && <Loading what="thư viện chiến lược" />}
      {sources.map((src) => (
        <Panel key={src.key} title={src.label} meta={<span>{(src.strategies || []).length} chiến lược</span>}>
          {!(src.strategies || []).length ? <Empty title="Chưa có chiến lược" /> : (
            <div className="n-ad-grid">{src.strategies.map((s) => <Card key={s.key} s={s} onOpen={() => setOpen(s.key)} />)}</div>
          )}
        </Panel>
      ))}
      {picked && <StrategyDoc s={picked} onClose={() => setOpen(null)} />}
    </>
  )
}
