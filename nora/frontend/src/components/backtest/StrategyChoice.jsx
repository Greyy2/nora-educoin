import React from 'react'
import { Segmented } from '../ui'
import { SIDE_OPTIONS } from '../../lib/strategyLabel'
import '../../styles/backtest.css'

/**
 * Ba chiến lược (KEMA, Sideway, DCA) dạng thẻ: tên, loại, mô tả; thẻ đang chọn hiện thêm ô chọn chiều Long / Short / Cả hai.
 * picks = { [mã chiến lược]: 'LONG' | 'SHORT' | 'BOTH' }. Mặc định chọn một (radio); multi=true cho phép chọn nhiều (danh mục).
 * Chiến lược có coming=true (DCA) chỉ hiển thị, không chọn được. extra(c) chèn thêm một dòng ghi chú dưới mô tả.
 */
export default function StrategyChoice({ catalog, picks, multi = false, onPick, onSide, extra = null, label = 'Chiến lược' }) {
  return (
    <div className="n-sc-list" role={multi ? 'group' : 'radiogroup'} aria-label={label}>
      <div className="n-sc-grid">
        {catalog.map((c) => {
          const off = !!c.coming || !Object.keys(c.legs || {}).length
          const side = picks[c.id]
          const on = !!side && !off
          return (
            <div key={c.id} className={`n-sc-card ${on ? 'on' : ''} ${off ? 'off' : ''}`}>
              <label className="n-sc-pick" title={c.description}>
                <input type={multi ? 'checkbox' : 'radio'} name="bt-strategy" checked={on} disabled={off} onChange={() => onPick(c)} />
                <span className="n-sc-body">
                  <span className="n-sc-top">
                    <span className="id">{c.name}</span>
                    <span className="n-badge">{c.kind}</span>
                    {off && <span className="n-status warn">đang xây dựng</span>}
                  </span>
                  <span className="ds">{c.description}</span>
                  {extra && !off && extra(c)}
                </span>
              </label>
              {on && (
                <div className="n-sc-side">
                  <span className="muted">Chiều giao dịch</span>
                  <Segmented label={`Chiều giao dịch của ${c.name}`} value={side} onChange={(v) => onSide(c, v)} options={SIDE_OPTIONS} />
                </div>
              )}
            </div>
          )
        })}
      </div>
      {!catalog.length && <p className="n-note">Chưa có danh sách chiến lược.</p>}
    </div>
  )
}
