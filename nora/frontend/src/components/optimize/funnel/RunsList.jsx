import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Panel, Status, Spinner, Loading, ErrorState, Empty } from '../../ui'
import { useMeta } from '../../../meta/MetaProvider'
import { RUN_STATUS, fmtCount, fmtEta, stageShort, splitLegacy } from '../../../lib/funnel'
import { fmtDateTime, fmtPct, isNum } from '../../../lib/format'
import { legLabel } from '../../../lib/strategyLabel'

/** Phễu thu nhỏ: 8 cột (S0 → FINAL), chiều cao theo log số alpha còn lại. */
export function MiniFunnel({ counts }) {
  const { meta } = useMeta()
  const max = Math.max(1, ...counts.map((c) => c.input ?? c.passed ?? 0))
  const h = (n) => (isNum(n) && n > 0 ? Math.max(2, (Math.log10(1 + n) / Math.log10(1 + max)) * 22) : 0)
  const label = counts.map((c) => `${stageShort(c.stage, meta)}: ${fmtCount(c.passed)}`).join(' → ')
  return (
    <svg className="n-minif" viewBox="0 0 108 24" width="108" height="24" role="img" aria-label={`Số alpha còn lại qua các tầng. ${label}`}>
      <title>{label}</title>
      {counts.map((c, i) => {
        const bh = h(c.passed)
        return <rect key={c.stage} x={i * 13.5} y={23 - bh} width="11" height={bh} rx="2" className={c.stage === 'FINAL' ? 'fin' : ''} />
      })}
      <line x1="0" x2="108" y1="23.5" y2="23.5" className="base" />
    </svg>
  )
}

const lastCount = (counts) => { for (let i = counts.length - 1; i >= 0; i--) if (isNum(counts[i].passed)) return counts[i] ; return null }

export default function RunsList({ q, onCreate }) {
  const nav = useNavigate()
  const { meta } = useMeta()
  if (q.error && !q.data) return <ErrorState title="Không tải được danh sách lượt chạy" error={q.error} onRetry={q.reload} />
  if (!q.data) return <Loading what="danh sách lượt chạy" />
  const runs = q.data.map((r) => splitLegacy(r, meta))   // luồng chính S0 → FINAL: tầng cũ (cờ legacy) không vào hàng thu nhỏ
  if (!runs.length) return <Empty title="Chưa có lượt phễu nào"><p>Tạo lượt đầu tiên để chạy hàng loạt alpha qua các tầng kiểm duyệt.</p><div className="n-sticky-actions" style={{ justifyContent: 'center' }}><button type="button" className="n-btn primary" onClick={onCreate}>Tạo lượt mới</button></div></Empty>
  return (
    <Panel title="Các lượt chạy" meta={<span className="mono">{runs.length} lượt{q.error ? ' · lỗi làm mới' : ''}</span>}>
      <div className="n-tblwrap long">
        <table className="n-tbl n-fn-tbl">
          <thead><tr><th>Lượt</th><th>Trạng thái</th><th>Tạo lúc</th><th>Chiến lược</th><th className="r">Alpha</th><th>Phễu S0 → FINAL</th><th className="r">FINAL</th><th>Tiến độ / ETA</th></tr></thead>
          <tbody>
            {runs.map((r) => {
              const st = RUN_STATUS[r.status] || { text: r.status, cls: '' }
              const live = r.status === 'running' || r.status === 'queued'
              const fin = r.counts.find((c) => c.stage === 'FINAL')
              const p = r.progress
              const pct = p?.total > 0 ? (p.done / p.total) * 100 : null
              return (
                <tr key={r.run_id} className="click" tabIndex={0} onClick={() => nav(`/alpha/funnel/${encodeURIComponent(r.run_id)}`)}
                  onKeyDown={(e) => { if (e.key === 'Enter') nav(`/alpha/funnel/${encodeURIComponent(r.run_id)}`) }}>
                  <td className="mono"><a href={`/alpha/funnel/${encodeURIComponent(r.run_id)}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); nav(`/alpha/funnel/${encodeURIComponent(r.run_id)}`) }}>{r.run_id}</a></td>
                  <td><Status tone={st.cls}>{live && <Spinner />}{st.text}</Status></td>
                  <td className="num">{fmtDateTime(r.created)}</td>
                  <td className="wrap"><span className="n-plist-inline">{r.strategies.map(legLabel).join(', ') || '—'}</span>{r.n_per_strategy ? <span className="muted mono"> · {fmtCount(r.n_per_strategy)}/cl</span> : null}</td>
                  <td className="r">{fmtCount(r.total_alphas)}</td>
                  <td><MiniFunnel counts={r.counts} /></td>
                  <td className="r">{fin && isNum(fin.passed) ? <b className={fin.passed ? 'pos' : ''}>{fmtCount(fin.passed)}</b> : <span className="muted">—</span>}</td>
                  <td>{live ? (
                    <span className="n-wbar"><span className="tr"><i style={{ width: `${pct ?? 0}%` }} /></span><span className="mono">{pct != null ? fmtPct(pct, 0) : '…'}</span><span className="muted mono">còn {fmtEta(p?.eta_s)}</span></span>
                  ) : <span className="muted">{r.status === 'done' ? 'xong' : r.status === 'failed' ? 'lỗi' : '—'}</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
