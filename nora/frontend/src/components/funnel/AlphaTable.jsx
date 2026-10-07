import React, { useState } from 'react'
import { Panel, Segmented, Loading, ErrorState, Empty, NA } from '../ui'
import Term from '../Term'
import Pager from './Pager'
import { AlphaLink, ParamList, AlphaStatus, StrategyName } from './parts'
import useAsync from '../../hooks/useAsync'
import { getFunnelAlphas } from '../../api'
import { stageShort, fmtMetric } from '../../lib/funnel'
import { signClass, fmtSPct } from '../../lib/format'
import { legLabel } from '../../lib/strategyLabel'

const COLS = [
  { k: 'ret_pct', label: 'Lãi' }, { k: 'mdd_pct', label: 'MDD', term: 'mdd' }, { k: 'sharpe', label: 'Sharpe', term: 'sharpe' },
  { k: 'trades', label: 'Lệnh' }, { k: 'win_rate', label: 'Tỉ lệ thắng' }, { k: 'profit_factor', label: 'PF', term: 'profit_factor' },
]

/** Bảng alpha của một tầng: lọc qua/loại + chiến lược, sắp xếp theo chỉ số, phân trang; tiêu đề bảng dính. */
export default function AlphaTable({ runId, stage, strategies, selected, onSelect, onOpen, onTrades }) {
  const [status, setStatus] = useState('all')
  const [strategy, setStrategy] = useState('')
  const [sort, setSort] = useState({ k: 'sharpe', desc: true })
  const [pg, setPg] = useState({ offset: 0, limit: 50 })
  const sortParam = `${sort.desc ? '-' : ''}${sort.k}`
  const q = useAsync(() => getFunnelAlphas(runId, { stage, status: status === 'all' ? '' : status, strategy, sort: sortParam, offset: pg.offset, limit: pg.limit }),
    [runId, stage, status, strategy, sortParam, pg.offset, pg.limit])
  const reset = (fn) => (v) => { fn(v); setPg((p) => ({ ...p, offset: 0 })) }
  const toggleSort = (k) => { setSort((s) => (s.k === k ? { k, desc: !s.desc } : { k, desc: true })); setPg((p) => ({ ...p, offset: 0 })) }
  const showS = ['S5_sizing', 'S6_holdout', 'FINAL'].includes(stage)
  const d = q.data
  return (
    <Panel title="Alpha ở tầng này" meta={
      <>
        <Segmented label="Lọc theo kết quả" value={status} onChange={reset(setStatus)} options={[{ value: 'all', label: 'Tất cả' }, { value: 'passed', label: '✓ Qua' }, { value: 'rejected', label: '✗ Bị loại' }]} />
        <select className="n-sel" style={{ width: 200 }} aria-label="Lọc theo chiến lược" value={strategy} onChange={(e) => reset(setStrategy)(e.target.value)}>
          <option value="">Mọi chiến lược</option>
          {strategies.map((s) => <option key={s} value={s}>{legLabel(s)}</option>)}
        </select>
      </>
    }>
      {q.error && <ErrorState title="Không tải được bảng alpha" error={q.error} onRetry={q.reload} />}
      {!q.error && !d && <Loading what="bảng alpha" />}
      {d && (
        <>
          <div className={`n-tblwrap long ${q.loading ? 'busy' : ''}`}>
            <table className="n-tbl n-fn-tbl">
              <thead>
                <tr>
                  <th>Mã</th><th>Chiến lược</th><th>Tham số</th><th>Kết quả</th>
                  {COLS.map((c) => (
                    <th key={c.k} className="r" aria-sort={sort.k === c.k ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
                      <button type="button" className="n-th-sort" onClick={() => toggleSort(c.k)} title="Bấm để sắp xếp">
                        {c.label}<span aria-hidden="true">{sort.k === c.k ? (sort.desc ? ' ▼' : ' ▲') : ''}</span>
                      </button>
                      {c.term && <Term k={c.term}>{''}</Term>}
                    </th>
                  ))}
                  {showS && <th className="r"><Term k="scale_s">s</Term></th>}
                  <th>Lý do loại</th><th />
                </tr>
              </thead>
              <tbody>
                {d.items.map((a) => (
                  <tr key={a.alpha_id} className={selected === a.alpha_id ? 'sel' : ''} onClick={() => onSelect(a.alpha_id)}>
                    <td><AlphaLink id={a.alpha_id} onOpen={onOpen} active={selected === a.alpha_id} /></td>
                    <td><StrategyName id={a.strategy} /></td>
                    <td className="wrap"><ParamList params={a.params} /></td>
                    <td><AlphaStatus a={a} /></td>
                    {COLS.map((c) => <td key={c.k} className={`r ${c.k === 'ret_pct' ? signClass(a.metrics?.[c.k]) : ''}`}>{c.k === 'ret_pct' ? fmtSPct(a.metrics?.ret_pct, 1) : (a.metrics?.[c.k] == null && a.metrics?.[`${c.k}_note`]) ? <NA note={a.metrics[`${c.k}_note`]} /> : fmtMetric(c.k, a.metrics?.[c.k])}</td>)}
                    {showS && <td className="r">{fmtMetric('final_scale', a.final_scale)}</td>}
                    <td className="wrap why">{a.rejected_stage ? <span title={a.reject_msg}>{stageShort(a.rejected_stage)} · {a.reject_msg || a.reject_code}</span> : <span className="muted">—</span>}</td>
                    <td><button type="button" className="n-btn sm" onClick={(e) => { e.stopPropagation(); onTrades(a.alpha_id) }}>Lệnh →</button></td>
                  </tr>
                ))}
                {!d.items.length && <tr><td colSpan={showS ? 13 : 12}><Empty title="Không có alpha khớp bộ lọc" /></td></tr>}
              </tbody>
            </table>
          </div>
          <Pager total={d.total} offset={pg.offset} limit={pg.limit} onChange={setPg} />
        </>
      )}
    </Panel>
  )
}
