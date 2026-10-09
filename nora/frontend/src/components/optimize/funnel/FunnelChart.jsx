import React, { useMemo, useState } from 'react'
import { Segmented } from '../../ui'
import { useMeta } from '../../../meta/MetaProvider'
import { stageName, stageShort, stageRule, fmtCount } from '../../../lib/funnel'
import { isNum, fmtPct } from '../../../lib/format'

/**
 * Biểu đồ phễu: mỗi tầng một hàng. Vạch xám nhạt = số alpha vào tầng, vạch xanh = số alpha qua tầng (cùng thang), nên phần xám
 * lòi ra chính là số bị loại. Chọn một tầng bằng click / Enter. `tops`: { [stage]: {code,label,count} } lý do loại chính.
 */
export default function FunnelChart({ counts, selected, onSelect, tops = {}, running = false, deadAt = null, legacy = [] }) {
  const { meta: metaGlobal } = useMeta()
  const m = metaGlobal
  const [scale, setScale] = useState('linear')
  const [showLegacy, setShowLegacy] = useState(false)
  const max = useMemo(() => Math.max(1, ...[...counts, ...legacy].map((c) => c.input ?? c.passed ?? 0)), [counts])
  const w = (n) => {
    if (!isNum(n) || n <= 0) return 0
    const v = scale === 'log' ? Math.log10(1 + n) / Math.log10(1 + max) : n / max
    return Math.max(0.6, v * 100)
  }
  const renderRow = (c, i, isLegacy = false) => {
          const sName = stageName(c.stage, m)
          const sShort = stageShort(c.stage, m)
          const sRule = stageRule(c.stage, m)
          const known = isNum(c.passed)
          const input = c.input ?? c.passed
          const rate = isNum(c.passed) && isNum(c.input) && c.input > 0 && (i > 0 || isLegacy) ? (c.passed / c.input) * 100 : null
          const top = c.top_reject || tops[c.stage]
          const final = c.stage === 'FINAL'
          const afterDead = !!deadAt && i > counts.findIndex((x) => x.stage === deadAt)
          const on = selected === c.stage
          return (
            <li key={c.stage} className={isLegacy ? 'legacy' : ''}>
              <button type="button" className={`n-fn-row ${isLegacy ? 'legacy' : ''} ${on ? 'on' : ''} ${known ? '' : 'idle'} ${afterDead ? 'dead' : ''}`} aria-pressed={on} onClick={() => onSelect(c.stage)}
                title={`${sName}. ${sRule ? `Điều kiện qua: ${sRule}` : ''}`}>
                <span className="st"><span className="code">{sShort}</span><span className="nm">{sName}</span>{isLegacy && <span className="n-badge">(cũ)</span>}</span>
                <span className="fbar" role="img" aria-label={known ? `${fmtCount(c.passed)} qua trên ${fmtCount(input)} vào` : 'chưa có số liệu'}>
                  <i className="track" style={{ width: `${w(input)}%` }} />
                  <i className={`fill ${final ? 'final' : ''}`} style={{ width: `${w(c.passed)}%` }} />
                </span>
                <span className="cnt r"><b>{afterDead && !known ? '0' : fmtCount(c.passed)}</b>{(i > 0 || isLegacy) && isNum(input) ? <span className="muted"> / {fmtCount(input)}</span> : null}</span>
                <span className="pct r">{rate != null ? fmtPct(rate, rate < 10 ? 1 : 0) : '—'}</span>
                <span className="why">
                  {top ? <><span className="lb">{top.label || top.code}</span> <span className="mono muted">{fmtCount(top.count)}</span></>
                    : <span className="muted">{afterDead && !known ? `Không có alpha vào (0 qua ${stageShort(deadAt, m)})` : i === 0 ? '—' : known && !running ? (rate === 100 ? 'Không loại alpha nào' : '…') : '—'}</span>}
                </span>
              </button>
            </li>
          )
  }
  return (
    <div className="n-fn">
      <div className="n-fn-tools">
        <span className="n-note">Vạch xanh: qua tầng · vạch xám: vào tầng. Bấm một tầng để xem thống kê, alpha và lệnh của tầng đó.</span>
        <Segmented label="Thang vạch" value={scale} onChange={setScale} options={[{ value: 'linear', label: 'Tuyến tính' }, { value: 'log', label: 'Log' }]} />
      </div>
      <div className="n-fn-head" aria-hidden="true">
        <span>Tầng</span><span /><span className="r">Qua / vào</span><span className="r">Tỉ lệ qua</span><span>Lý do loại chính</span>
      </div>
      <ol className="n-fn-list" aria-label="Các tầng của phễu">
        {counts.map((c, i) => renderRow(c, i))}
        {legacy.length > 0 && (
          <li className="n-fn-legacy-head">
            <button type="button" className="n-fn-legacy-toggle" aria-expanded={showLegacy} onClick={() => setShowLegacy((v) => !v)}>
              {showLegacy ? '▾' : '▸'} Tầng cũ ({legacy.length}) · ngoài luồng chuyển đổi chính
            </button>
          </li>
        )}
        {showLegacy && legacy.map((c) => renderRow(c, -1, true))}
      </ol>
    </div>
  )
}
