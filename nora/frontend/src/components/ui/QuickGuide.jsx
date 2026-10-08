import React from 'react'
import { Link } from 'react-router-dom'


const STEPS = [
  { to: '/alpha/tune', title: 'Alpha', text: 'Chọn một chiến lược, thử nhiều bộ tham số trên vùng dev1 và xếp hạng theo điểm. Danh mục ý tưởng + công thức của các alpha đang chạy nằm ở tab Alpha.' },
  { to: '/backtest', title: 'Backtest', text: 'Chạy danh mục với bộ tham số đã chọn trên khoảng ngày và các tài sản bạn muốn.' },
  { to: '/backtest', title: 'Walk-forward (WFA)', text: 'Bước 2 trong trang Backtest: kiểm tra out-of-sample cuốn chiếu để biết có bị khớp quá mức không.' },
  { to: '/backtest', title: 'Monte Carlo', text: 'Bước 3: mô phỏng hàng nghìn kịch bản để đo xác suất sụt giảm vượt ngưỡng phá sản.' },
  { to: '/portfolio', title: 'Danh mục', text: 'Xem kết quả một lần Backtest: NAV, rủi ro, hiệu suất từng chiến thuật và danh sách lệnh.' },
]

/** Nội dung hướng dẫn: vòng Alpha → Backtest → WFA → Monte Carlo → Danh mục. */
export function GuideSteps({ onNavigate }) {
  return (
    <>
      <ol className="n-guide-steps">
        {STEPS.map((s, i) => (
          <li key={s.title}>
            <span className="no" aria-hidden="true">{i + 1}</span>
            <span><Link to={s.to} onClick={onNavigate}>{s.title}</Link><span className="tx">{s.text}</span></span>
          </li>
        ))}
      </ol>
      <p className="n-note n-guide-note">
        Danh mục và Backtest chỉ là <b>kết quả mô phỏng</b> trên dữ liệu lịch sử. Bot đang chạy thật (OKX paper/demo) xem ở trang <b>Live</b>.
      </p>
    </>
  )
}

export default GuideSteps
