import React from 'react'
import { fmtNum } from '../../../lib/format'

/**
 * Giải thích kết quả (chỉ /education): KHÔNG có ngưỡng hay nhận xét nào ở trình duyệt. Mọi chữ do backend sinh tất định và nằm trong result.explain:
 *  - result.explain.{rules, indicators, execution, warnings}: logic mã (alpha/compile.explain_program trên IR đã biên dịch, vị thế đúng lần chạy);
 *  - result.explain.notes.<mục>: ghi chú từng mục kết quả (metrics/notes.build_notes) ghép từ logic + số đo của chính lần chạy.
 * Hướng dẫn từng bước dùng result.explain.notes: xem ResultTour / CustomResult. Mặc định export là thẻ "Chiến lược làm gì".
 */
export default function ResultExplain({ result }) {
  const ex = result?.explain
  if (!ex) return <p className="n-note">Kết quả này được lưu trước khi có khối giải thích; chạy lại để có phần giải thích.</p>
  const { rules = [], indicators = [], execution = [], warnings = [] } = ex
  return (
    <div className="re-logic">
      <div className="re-sec">
        <div className="re-t">Quy tắc vào / thoát</div>
        {rules.length === 0 ? <p className="n-note">Mã không có quy tắc set_positions.</p> : (
          <ol>{rules.map((r) => <li key={r.index}>{r.action_vi}{r.line ? <span className="muted"> (dòng {r.line})</span> : null}</li>)}</ol>
        )}
      </div>
      <div className="re-sec">
        <div className="re-t">Chỉ báo sử dụng</div>
        {indicators.length === 0 ? <p className="n-note">Không dùng chỉ báo (chỉ giá / khối lượng trực tiếp).</p> : (
          <div className="re-ind">
            {indicators.map((ind) => (
              <div key={ind.call} className="re-ind-i">
                <div className="mono">{ind.call}</div>
                <b>{ind.label_vi}</b>
                <div className="muted">{ind.meaning_vi}</div>
                <div className="muted">Khởi động {fmtNum(ind.warmup, 0)} nến · khung {ind.timeframe}</div>
              </div>
            ))}
          </div>
        )}
      </div>
      <div className="re-sec">
        <div className="re-t">Cơ chế thực thi</div>
        <ul>{execution.map((e) => <li key={e.title}><b>{e.title}:</b> {e.desc}</li>)}</ul>
      </div>
      {warnings.length > 0 && (
        <div className="re-sec">
          <div className="re-t">Lưu ý cấu trúc</div>
          <ul>{warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
        </div>
      )}
    </div>
  )
}
