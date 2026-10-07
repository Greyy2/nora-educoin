import React from 'react'
import { Spinner } from '../ui'
import { fmtNum, fmtSPct } from '../../lib/format'
import { normMetrics } from '../../lib/customResult'

/** Mục "Đã lưu": các alpha người dùng đã lưu (GET /api/studio/alphas/user). Mở một mục nạp code + cấu hình + KẾT QUẢ ĐÃ LƯU, không chạy lại.
 *  list = kết quả useAsync(getUserAlphas); onOpen(id); openingId = mục đang tải. Chỉ hiển thị số đo backend đã lưu (thiếu -> "—"). */
export default function SavedAlphaList({ list, onOpen, openingId = '', activeId = '' }) {
  const items = (Array.isArray(list.data) ? list.data : []).filter((s) => s.status !== 'ARCHIVED')
  return (
    <>
      <h3 className="se-h3">Đã lưu {items.length ? `(${items.length})` : ''}</h3>
      {list.error && <p className="n-note neg">Không tải được danh sách đã lưu: {list.error} <button type="button" className="n-btn sm" onClick={list.reload}>Thử lại</button></p>}
      {list.loading && !list.data && <p className="n-note"><Spinner /> Đang tải…</p>}
      {!list.loading && !items.length && !list.error && (
        <p className="n-note">Chưa có chiến lược nào được lưu. Chạy backtest cho code hiện tại rồi bấm “Lưu chiến lược”; bản nháp và kết quả chưa lưu sẽ mất khi đóng trang.</p>
      )}
      <div className="se-cards">
        {items.map((s) => {
          const sim = normMetrics(s.metrics?.simulate)
          const test = normMetrics(s.metrics?.test)
          const cfg = s.config || {}
          return (
            <div key={s.id} className={`n-card-sel se-saved ${activeId === s.id ? 'on' : ''}`} role="button" tabIndex={0} aria-busy={openingId === s.id}
              onClick={() => onOpen(s.id)} onKeyDown={(e) => { if (e.key === 'Enter') onOpen(s.id) }}>
              <b>{s.name || s.id}</b>
              <span className="n-note mono">{s.id}{s.updated_at ? ` · ${String(s.updated_at).slice(0, 10)}` : ''}</span>
              <span className="n-note">{cfg.start && cfg.end ? `${cfg.start} → ${cfg.end}` : 'không có dữ liệu cấu hình'}</span>
              <span className="n-note">Sharpe Test {fmtNum(test?.sharpe, 2)} · CAGR {fmtSPct(sim?.cagr, 1)}</span>
              {s.has_result === false && <span className="n-note neg" title="Bản ghi lưu từ phiên bản cũ, không kèm ảnh chụp kết quả; mở lên chỉ có code và cấu hình, cần chạy lại">Bản cũ: không có kết quả đã lưu</span>}
              {openingId === s.id && <Spinner />}
            </div>
          )
        })}
      </div>
    </>
  )
}
