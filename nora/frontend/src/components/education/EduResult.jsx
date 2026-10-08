import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import CustomResult from '../studio/CustomResult'
import { normMetrics } from '../../lib/customResult'
import { fmtNum, fmtPct, fmtSPct, fmtMoney, isNum } from '../../lib/format'
import '../../styles/education.css'

/**
 * EduResult:
 * - 100% giao diện CustomResult nguyên bản.
 * - Spotlight Walkthrough (chỉ mở khi bấm nút giải thích; không tự bật), định vị thông minh:
 *   + Popover không bao giờ bị tràn đáy màn hình, footer luôn cố định trong viewport.
 *   + Cuộn mượt (smooth scroll) căn giữa element mục tiêu.
 *   + Nền tối mờ xung quanh, khoanh viền đỏ nổi bật.
 */
const TOUR_SEEN_KEY = 'nora-edu-result-tour-seen'
const readSeen = () => { try { return localStorage.getItem(TOUR_SEEN_KEY) === '1' } catch (e) { return false } }

export default function EduResult({ result, jobLine }) {
  const containerRef = useRef(null)
  const [tourActive, setTourActive] = useState(false)
  const [tourStep, setTourStep] = useState(0)
  const [highlightRect, setHighlightRect] = useState(null)
  const [seen, setSeen] = useState(readSeen)

  // Trích xuất số liệu thực tế từ kết quả
  const mSim = normMetrics(result?.metrics?.simulate || result?.metrics?.all)
  const mTrain = normMetrics(result?.metrics?.train)
  const mTest = normMetrics(result?.metrics?.test)
  const m = mSim || mTrain || {}

  // Mọi số lãi/lỗ lấy từ backend (diagnostics.pnl_structure, config, final_equity); thiếu thì null -> hiện "không có dữ liệu", không dùng hằng số thay thế.
  const ps = result?.diagnostics?.pnl_structure
  const initialCap = isNum(result?.config?.initial_capital) ? result.config.initial_capital : null
  const finalEquity = isNum(result?.final_equity) ? result.final_equity : null
  const netProfitUsd = isNum(ps?.net_pnl_usd) ? ps.net_pnl_usd : null
  const hasPnl = ps && [ps.avg_win, ps.avg_loss, ps.max_win, ps.max_loss, ps.payoff].some(isNum)
  const NA = <span className="muted">không có dữ liệu</span>
  const usd = (v) => (isNum(v) ? <b>{fmtMoney(v)}</b> : NA)

  const notes = useMemo(() => (Array.isArray(result?.insights) ? result.insights.filter((i) => i && i.message_vi).slice(0, 4) : []), [result])
  const holdDays = result?.diagnostics?.signal_activity?.avg_holding_days

  // 4 Bước giải thích lần lượt
  const STEPS = useMemo(() => [
    {
      key: 'metrics',
      title: '1. Các Tham Số Hiệu Suất (Performance Metrics)',
      tab: 'overview',
      selector: '.se-agg, .se-yr',
      fallbackSelector: '.se-agg',
      content: (
        <div className="edu-tour-body">
          <p className="edu-tour-lead">
            Các chỉ số này tóm tắt lợi nhuận và rủi ro của đường vốn trong lần chạy này. Công thức dưới đây khớp đúng với mã tính (backend/metrics):
          </p>
          <div className="edu-tour-section">
            <b>Ý nghĩa & Cách tính toán:</b>
            <ul>
              <li>
                <b>Sharpe</b> (<code>trung bình(r) / độ lệch chuẩn(r) × √365</code>, r = lợi suất NGÀY của vốn mark-to-market đóng ngày UTC, độ lệch chuẩn mẫu ddof=1,
                KHÔNG trừ lãi suất phi rủi ro): lợi suất trung bình ngày trên mỗi đơn vị biến động ngày, quy năm theo 365 ngày (crypto giao dịch cả tuần). Sortino dùng độ lệch xuống so với 0.
              </li>
              <li>
                <b>CAGR</b> (<code>(Π(1 + r))^(365 / N) − 1</code>, N = số ngày lợi suất, không tính mốc vốn đầu): tăng trưởng vốn kép quy năm theo 365 ngày. Cùng định nghĩa ở ô tổng hợp, bảng theo năm và Chẩn đoán.
              </li>
              <li>
                <b>Max Drawdown</b> (<code>min(vốn / đỉnh vốn trước đó − 1)</code> trên vốn ĐÓNG NGÀY): mức sụt giảm sâu nhất từ một đỉnh. Đây là MDD theo ngày; MDD trong nến
                (tính cả giá xấu nhất trong nến, khắt khe hơn) của engine không được dùng ở trang này.
              </li>
              <li>
                <b>Profit Factor</b> (<code>Σ PnL các lệnh lãi / |Σ PnL các lệnh lỗ|</code> trên lệnh đã đóng, tối đa 99 khi không có lệnh lỗ): &gt; 1 nghĩa là tổng lãi lớn hơn tổng lỗ.
              </li>
              <li>
                <b>Calmar</b> (<code>CAGR / |MDD|</code>, MDD theo ngày): lợi suất năm trên mỗi đơn vị sụt giảm sâu nhất.
              </li>
            </ul>
            <p className="n-note" style={{ marginTop: 6 }}>
              Ngưỡng tham khảo thường dùng (quy tắc kinh nghiệm, không phải tiêu chuẩn): Sharpe trên 1 thường được xem là khá; Profit Factor trên 1 là có lãi gộp lớn hơn lỗ gộp.
              Các chỉ số trong mẫu không chứng minh lợi thế ngoài mẫu — hãy xem thêm Train / Test và phần Chẩn đoán.
            </p>
          </div>
          <div className="edu-tour-verdict">
            <b>Số liệu thực tế của lần chạy này:</b>
            <p>
              CAGR <b>{fmtSPct(m.cagr)}</b>/năm, Sharpe <b>{fmtNum(m.sharpe)}</b>, Max Drawdown theo ngày <b>{fmtSPct(m.mdd)}</b>, Profit Factor <b>{fmtNum(m.pfTrades)}</b>,
              Calmar <b>{fmtNum(m.calmar)}</b>.{' '}
              {isNum(m.sharpe) && m.sharpe >= 1.0
                ? 'Sharpe từ 1 trở lên (mức khá theo quy tắc kinh nghiệm) nhưng đây vẫn là kết quả trong dữ liệu quá khứ; kiểm tra Train / Test trước khi kết luận.'
                : 'Sharpe dưới 1: lợi suất chưa bù tương xứng cho mức biến động trong dữ liệu này.'}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: 'chart',
      title: '2. Đọc Biểu Đồ Đường Vốn & Phát Hiện Overfitting',
      tab: 'overview',
      selector: '.se-cc:first-of-type',
      fallbackSelector: '.se-cc',
      content: (
        <div className="edu-tour-body">
          <p className="edu-tour-lead">
            Nhìn vào biểu đồ đường vốn (Equity Curve), bạn có thể đọc được hành vi của thuật toán qua các chu kỳ thị trường:
          </p>
          <div className="edu-tour-section">
            <b>Nhìn vào biểu đồ này thì thấy gì:</b>
            <ul>
              <li>
                <b>Đoạn dốc đứng (Surge):</b> Vốn tăng nhanh — thường là lúc chiến lược đang giữ vị thế đúng chiều trong một nhịp thị trường mạnh.
              </li>
              <li>
                <b>Đoạn nằm ngang phẳng lì (Plateau):</b> Vốn gần như không đổi — thường là lúc chiến lược không có vị thế (đứng ngoài thị trường). Đối chiếu với "% ngày có vị thế" ở phần Chẩn đoán.
              </li>
              <li>
                <b>Đoạn tụt bậc thang:</b> Chuỗi lệnh lỗ liên tiếp hoặc vị thế đang giữ đi ngược chiều; xem bảng lệnh và "Chuỗi thua dài nhất" để biết nguyên nhân.
              </li>
            </ul>
          </div>
          <div className="edu-tour-verdict">
            <b>Vạch phân cách Train | Test (Kiểm tra Overfitting):</b>
            <p>
              Đường đứt nét màu xanh đánh dấu ranh giới giữa tập Train (In-sample) và Test (Out-of-sample). Nếu đường vốn sang đoạn Test vẫn tăng với tốc độ tương đương thì đó là dấu hiệu tốt về độ bền (không phải bảo chứng). Nếu đoạn Test gãy dốc hoặc đi ngang, chiến lược có thể đã khớp quá mức với dữ liệu train (overfitting). Đoạn Test được chạy lại từ vốn đầu tại mốc chia.
            </p>
          </div>
        </div>
      ),
    },
    {
      key: 'trades',
      title: '3. Giải Phẫu Danh Sách Lệnh (Trade List & Execution)',
      tab: 'analysis',
      selector: '.se-cc',
      fallbackSelector: '.n-tblwrap',
      content: (
        <div className="edu-tour-body">
          <p className="edu-tour-lead">
            Từng dòng lệnh cho thấy điểm vào / ra, lý do thoát và tỷ lệ bất đối xứng lãi / lỗ:
          </p>
          <div className="edu-tour-section">
            <b>Nhìn vào danh sách lệnh thì thấy gì:</b>
            <ul>
              <li>
                <b>Điểm vào / Điểm ra:</b> Giá vào, giá ra và lý do thoát (tín hiệu thoát, stop-loss, take-profit, …) ghi ở từng dòng; điều kiện vào / ra cụ thể nằm trong tab "Giải thích thuật toán".
              </li>
              <li>
                <b>Tỷ lệ Payoff (Lãi TB / Lỗ TB):</b> {hasPnl ? (
                  <>Lãi TB {usd(ps.avg_win)} / lỗ TB {usd(ps.avg_loss)} USDT → payoff {isNum(ps.payoff) ? <b>{fmtNum(ps.payoff)}</b> : NA}; tỷ lệ thắng {isNum(ps.win_rate) ? <b>{fmtPct(ps.win_rate, 1)}</b> : NA}; lệnh thắng lớn nhất {isNum(ps.max_win) ? <b>+{fmtMoney(ps.max_win)}</b> : NA}, lệnh thua lớn nhất {isNum(ps.max_loss) ? <b>-{fmtMoney(ps.max_loss)}</b> : NA} USDT.</>
                ) : 'Không có dữ liệu lệnh đã đóng trong bản ghi này (payoff, lãi/lỗ trung bình, lệnh lớn nhất do backend tính ở diagnostics.pnl_structure).'}
              </li>
              <li>
                <b>Thời gian giữ lệnh:</b> {isNum(holdDays) ? <>Trung bình <b>{fmtNum(holdDays, 1)}</b> ngày/lệnh (lệnh đang mở tính tới cuối kỳ).</> : 'Xem "Thời gian nắm giữ" ở phần Chẩn đoán.'}
              </li>
              <li>
                <b>Phí giao dịch:</b> {isNum(m.fees) ? <>Tổng phí mô phỏng <b>{fmtMoney(m.fees)} USDT</b> (đã tính trong đường vốn).</> : 'Không có số phí trong bản ghi này.'}
              </li>
            </ul>
          </div>
        </div>
      ),
    },
    {
      key: 'verdict',
      title: '4. Tổng Quan Đánh Giá: Lãi Lỗ Ra Sao & Khả Năng Thực Chiến',
      tab: 'overview',
      selector: '.se-res',
      fallbackSelector: '.edu-result-wrapper',
      content: (
        <div className="edu-tour-body">
          <div className="edu-tour-finbox">
            <div>
              <span className="lbl">Vốn khởi điểm:</span>
              {isNum(initialCap) ? <b>{fmtMoney(initialCap)} USDT</b> : NA}
            </div>
            <div className="arr">➔</div>
            <div>
              <span className="lbl">Vốn kết thúc:</span>
              {isNum(finalEquity) ? <b className={isNum(initialCap) ? (finalEquity >= initialCap ? 'pos' : 'neg') : ''}>{fmtMoney(finalEquity)} USDT</b> : NA}
            </div>
            <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
              <span className="lbl">Lợi nhuận ròng:</span>
              {isNum(netProfitUsd) ? (
                <b className={`large ${netProfitUsd >= 0 ? 'pos' : 'neg'}`}>
                  {netProfitUsd >= 0 ? '+' : ''}{fmtMoney(netProfitUsd)} USDT ({fmtSPct(m.ret)})
                </b>
              ) : NA}
            </div>
          </div>
          <div className="edu-tour-section" style={{ marginTop: 10 }}>
            <b>Nhận xét từ chính số liệu của lần chạy:</b>
            {notes.length ? (
              <ul>
                {notes.map((n, i) => <li key={i}>{n.message_vi}</li>)}
              </ul>
            ) : <p>Không có nhận xét tự động nào được kích hoạt (hoặc bản ghi này không kèm chẩn đoán).</p>}
            <p className="n-note" style={{ marginTop: 6 }}>
              Các nhận xét trên được sinh bằng quy tắc cố định từ số đo thật (không dùng LLM). Backtest chỉ mô phỏng dữ liệu quá khứ với giả định phí / khớp lệnh của engine, không đảm bảo kết quả tương lai.
            </p>
          </div>
        </div>
      ),
    },
  ], [m, ps, hasPnl, initialCap, finalEquity, netProfitUsd, notes, holdDays])

  // Hàm chuyển tab trong CustomResult
  const switchSubTab = useCallback((targetTab) => {
    if (!containerRef.current) return
    const tabButtons = containerRef.current.querySelectorAll('.se-row2 button[role="tab"], .se-row2 button')
    if (!tabButtons || !tabButtons.length) return

    for (const btn of tabButtons) {
      const txt = (btn.textContent || '').trim().toLowerCase()
      if (targetTab === 'overview' && (txt.includes('tổng quan') || txt.includes('overview'))) {
        btn.click()
        break
      } else if (targetTab === 'analysis' && (txt.includes('phân tích') || txt.includes('analysis'))) {
        btn.click()
        break
      } else if (targetTab === 'perf' && (txt.includes('hiệu suất') || txt.includes('perf'))) {
        btn.click()
        break
      }
    }
  }, [])

  // Cập nhật vị trí Highlight rect & scroll mượt mà
  const updateRect = useCallback((shouldScroll = false) => {
    if (!tourActive || !containerRef.current) return
    const step = STEPS[tourStep]
    if (!step) return

    let el = null
    const sels = [step.selector, step.fallbackSelector]
    for (const s of sels) {
      try {
        const found = containerRef.current.querySelectorAll(s)
        if (found && found.length) {
          if (found.length > 1 && step.key === 'metrics') {
            const r1 = found[0].getBoundingClientRect()
            const r2 = found[found.length - 1].getBoundingClientRect()
            const top = Math.min(r1.top, r2.top)
            const left = Math.min(r1.left, r2.left)
            const right = Math.max(r1.right, r2.right)
            const bottom = Math.max(r1.bottom, r2.bottom)
            setHighlightRect({ top, left, width: right - left, height: bottom - top })
            if (shouldScroll) {
              found[0].scrollIntoView({ behavior: 'smooth', block: 'center' })
            }
            return
          }
          el = found[0]
          break
        }
      } catch (_) {}
    }

    if (el) {
      if (shouldScroll) {
        // Cuộn mượt mà vào giữa khung nhìn
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        setTimeout(() => {
          const r = el.getBoundingClientRect()
          setHighlightRect({ top: r.top, left: r.left, width: r.width, height: r.height })
        }, 250)
      } else {
        const r = el.getBoundingClientRect()
        setHighlightRect({ top: r.top, left: r.left, width: r.width, height: r.height })
      }
    } else {
      setHighlightRect(null)
    }
  }, [tourActive, tourStep, STEPS])

  // Khi chuyển bước: chuyển tab phù hợp rồi cuộn và update rect
  useEffect(() => {
    if (!tourActive) return
    const step = STEPS[tourStep]
    if (step && step.tab) {
      switchSubTab(step.tab)
    }

    const timer = setTimeout(() => {
      updateRect(true)
    }, 140)

    const onScrollOrResize = () => {
      updateRect(false)
    }

    window.addEventListener('resize', onScrollOrResize)
    window.addEventListener('scroll', onScrollOrResize, true)

    return () => {
      clearTimeout(timer)
      window.removeEventListener('resize', onScrollOrResize)
      window.removeEventListener('scroll', onScrollOrResize, true)
    }
  }, [tourActive, tourStep, switchSubTab, updateRect, STEPS])

  // Giải thích chỉ mở khi người dùng bấm nút "Xem giải thích từng phần" (không tự bật đè lên biểu đồ); ghi nhớ đã đóng để bỏ nhãn "mới".
  const closeTour = useCallback(() => {
    setTourActive(false)
    try { localStorage.setItem(TOUR_SEEN_KEY, '1') } catch (e) { /* trình duyệt chặn lưu trữ: bỏ qua */ }
    setSeen(true)
  }, [])

  useEffect(() => {
    if (!tourActive) return undefined
    const onKey = (e) => { if (e.key === 'Escape') closeTour() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [tourActive, closeTour])

  const curStep = STEPS[tourStep]

  // Định vị thông minh cho Popover (tránh khuất đáy, footer luôn cố định)
  const popoverStyle = useMemo(() => {
    const popWidth = Math.min(520, window.innerWidth - 32)
    const maxPopHeight = 460

    // Bước 4 (tổng quan) hoặc khi vùng highlight chiếm gần hết màn hình
    if (!highlightRect || curStep.key === 'verdict' || highlightRect.height > window.innerHeight * 0.72) {
      return {
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: `${popWidth}px`,
        maxHeight: `min(${maxPopHeight}px, calc(100vh - 48px))`,
      }
    }

    const pad = 12
    const spaceBelow = window.innerHeight - (highlightRect.top + highlightRect.height)
    const spaceAbove = highlightRect.top
    const leftPos = Math.max(16, Math.min(highlightRect.left, window.innerWidth - popWidth - 16))

    // Ưu tiên 1: Đặt bên dưới nếu còn đủ khoảng trống (ít nhất 280px)
    if (spaceBelow >= 280) {
      return {
        top: `${highlightRect.top + highlightRect.height + pad}px`,
        left: `${leftPos}px`,
        width: `${popWidth}px`,
        maxHeight: `min(${maxPopHeight}px, calc(${spaceBelow - pad - 16}px))`,
      }
    }

    // Ưu tiên 2: Đặt bên trên nếu khoảng trống trên đủ rộng
    if (spaceAbove >= 280) {
      return {
        bottom: `${window.innerHeight - highlightRect.top + pad}px`,
        left: `${leftPos}px`,
        width: `${popWidth}px`,
        maxHeight: `min(${maxPopHeight}px, calc(${spaceAbove - pad - 16}px))`,
      }
    }

    // Ưu tiên 3: Neo góc dưới bên phải màn hình (không bao giờ che mất nút bấm)
    return {
      bottom: '24px',
      right: '24px',
      width: `${popWidth}px`,
      maxHeight: `min(${maxPopHeight}px, calc(100vh - 48px))`,
    }
  }, [highlightRect, curStep])

  const enrichedJobLine = (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
      <button
        type="button"
        className="edu-tour-btn-start"
        onClick={() => {
          setTourActive(true)
          setTourStep(0)
        }}
        title="Bật giải thích tương tác highlight từng phần"
      >
        💡 Xem giải thích từng phần{seen ? '' : ' (mới)'}
      </button>
      {jobLine}
    </div>
  )

  return (
    <div ref={containerRef} className="edu-result-wrapper" style={{ position: 'relative', height: '100%' }}>
      {/* Kết quả nguyên bản 100% của CustomResult với nút giải thích tích hợp trong hàng tiêu đề */}
      <CustomResult result={result} jobLine={enrichedJobLine} />

      {/* Lớp Spotlight Onboarding Walkthrough */}
      {tourActive && (
        <div className="edu-spotlight-portal">
          {/* Khung highlight khoanh đỏ với viền và shadow mờ toàn màn hình xung quanh */}
          {highlightRect && curStep.key !== 'verdict' && (
            <div
              className="edu-spotlight-highlight-box"
              style={{
                top: `${Math.max(0, highlightRect.top - 6)}px`,
                left: `${Math.max(0, highlightRect.left - 6)}px`,
                width: `${highlightRect.width + 12}px`,
                height: `${highlightRect.height + 12}px`,
              }}
            />
          )}

          {/* Nếu là bước tổng quan, phủ bóng mờ đều toàn màn hình */}
          {curStep.key === 'verdict' && (
            <div className="edu-spotlight-full-dark" onClick={closeTour} />
          )}

          {/* Hộp Popover giải thích nổi phía trên */}
          <div className="edu-tour-popover" style={popoverStyle} role="dialog" aria-modal="true">
            <div className="edu-tour-header">
              <span className="edu-tour-title">{curStep.title}</span>
              <span className="edu-tour-step-badge">
                {tourStep + 1} / {STEPS.length}
              </span>
            </div>

            <div className="edu-tour-content-scroll">
              {curStep.content}
            </div>

            <div className="edu-tour-footer">
              <button
                type="button"
                className="edu-tour-skip-btn"
                onClick={closeTour}
              >
                Bỏ qua (Skip)
              </button>

              <div className="edu-tour-nav-btns">
                {tourStep > 0 && (
                  <button
                    type="button"
                    className="edu-tour-prev-btn"
                    onClick={() => setTourStep((s) => Math.max(0, s - 1))}
                  >
                    ← Trước
                  </button>
                )}

                {tourStep < STEPS.length - 1 ? (
                  <button
                    type="button"
                    className="edu-tour-next-btn"
                    onClick={() => setTourStep((s) => Math.min(STEPS.length - 1, s + 1))}
                  >
                    Tiếp (Next) ➔
                  </button>
                ) : (
                  <button
                    type="button"
                    className="edu-tour-next-btn finish"
                    onClick={closeTour}
                  >
                    Hoàn tất ✓
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
