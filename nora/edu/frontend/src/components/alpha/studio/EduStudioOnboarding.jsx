import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const PAD = 8
const POP_W = 460

export const ONBOARDING_DSL_SAMPLES = [
  {
    id: 'quick_rsi_edu',
    name: 'Quick RSI Momentum (Chuẩn EDU)',
    timeframe: '1h',
    desc: 'Bắt sóng hồi RSI kết hợp quản trị vốn & cắt lỗ 2%, chốt lời 4% tự thân trong code',
    code: `class QuickRsiEdu(SimpleAlgorithm):
    id = "quick_rsi_edu"
    timeframe = "1h"

    # ==========================================
    # QUẢN TRỊ RỦI RO & BẢO VỆ VỐN (Khuyên dùng trong EDU)
    # Phí giao dịch tính theo mặc định CEX perp (Taker 0.05%, Maker 0.02%)
    # ==========================================
    leverage = 1                # Đòn bẩy 1x (an toàn cho học tập)
    exit_unit = "pct"           # Đơn vị phần trăm
    stop_loss_rate = 2.0        # Cắt lỗ cứng 2% từ điểm vào
    take_profit_rate = 4.0      # Chốt lời mục tiêu 4% (R:R = 1:2)
    risk_per_trade_pct = 0.5    # Rủi ro 0.5% vốn mỗi lệnh

    def __algorithm__(self):
        close = self.data.pv_close
        rsi = self.feat.rsi(close, timeperiod=14)
        # Mua khi RSI chạm vùng quá bán (< 35)
        self.set_positions(rsi < 35, position=1)
        # Đóng vị thế khi RSI chạm vùng quá mua (> 65)
        self.set_positions(rsi > 65, position=0)`,
  },
  {
    id: 'dual_ema_trend',
    name: 'Dual EMA Trend Following',
    timeframe: '4h',
    desc: 'Đi theo xu hướng trung hạn với giao cắt đường EMA nhanh (9) và EMA chậm (21)',
    code: `class DualEmaTrend(SimpleAlgorithm):
    id = "dual_ema_trend"
    timeframe = "4h"

    def __algorithm__(self):
        close = self.data.pv_close
        fast = self.feat.ema(close, timeperiod=9)
        slow = self.feat.ema(close, timeperiod=21)
        # Vị thế Long khi đường nhanh vượt trên đường chậm
        self.set_positions(fast > slow, position=1)
        self.set_positions(fast < slow, position=0)`,
  },
  {
    id: 'sma_atr_breakout',
    name: 'SMA + ATR Volatility Breakout',
    timeframe: '1d',
    desc: 'Đột phá biến động khi giá vượt dải biên độ SMA 50 cộng ATR 14',
    code: `class SmaAtrBreakout(SimpleAlgorithm):
    id = "sma_atr_breakout"
    timeframe = "1d"

    def __algorithm__(self):
        close = self.data.pv_close
        sma = self.feat.sma(close, timeperiod=50)
        atr = self.feat.atr(self.data.pv_high, self.data.pv_low, close, timeperiod=14)
        # Vào vị thế khi giá vượt biên trên biến động SMA + ATR
        self.set_positions(close > (sma + atr), position=1)
        self.set_positions(close < sma, position=0)`,
  },
]

export const EDU_STUDIO_STEPS = [
  {
    id: 'welcome',
    sel: '.se-ws',
    title: '1. Chào mừng bạn đến Nora EDU Studio',
    body: [
      { label: 'Không gian nghiên cứu định lượng', text: 'Nora Studio giúp bạn học tập và thực hành xây dựng chiến lược giao dịch tự động bằng Python theo chuẩn Nora DSL đơn giản, an toàn.' },
      { label: 'Bố cục làm việc', text: 'Bên trái là trình soạn thảo Code & thanh điều khiển chạy; bên phải là kết quả Backtest, biểu đồ nến và thư viện chiến lược mẫu.' },
    ],
  },
  {
    id: 'dsl_structure',
    sel: '.se-code',
    title: '2. Cấu trúc chiến lược Nora DSL',
    body: [
      { label: 'Kế thừa SimpleAlgorithm', text: 'Mọi chiến lược định lượng kế thừa từ class SimpleAlgorithm. Bạn định nghĩa tham số (timeframe) và hàm logic __algorithm__(self).' },
      { label: '3 khối cốt lõi', text: 'Dữ liệu giá (self.data.pv_close), Chỉ báo kỹ thuật (self.feat.rsi, ema, sma, atr) và Quyết định vị thế (self.set_positions).' },
    ],
    sampleCode: ONBOARDING_DSL_SAMPLES[0].code,
  },
  {
    id: 'samples',
    sel: '.se-rtabs',
    title: '3. Kho mẫu chiến lược định lượng',
    body: [
      { label: 'Bộ 3 mẫu thực chiến', text: 'Hệ thống chuẩn bị sẵn 3 chiến lược tiêu biểu đã được biên dịch và kiểm định: Quick RSI, Dual EMA và SMA-ATR Breakout.' },
      { label: 'Nạp nhanh', text: 'Chọn một mẫu bên dưới để xem trước và nạp trực tiếp vào trình soạn thảo bằng 1 click.' },
    ],
    hasSamplePicker: true,
  },
  {
    id: 'settings',
    sel: '.se-chips',
    title: '4. Cài đặt tham số & Rổ tài sản',
    body: [
      { label: 'Khung thời gian & Vốn', text: 'Tuỳ chỉnh khung nến (1h, 4h, 1d), vốn ban đầu ($10,000) và rổ tiền mã hóa nghiên cứu (BTC, ETH).' },
      { label: 'Phân tách Train / Test', text: 'Tách dữ liệu trong mẫu (Train 80%) và ngoài mẫu (Test 20%) giúp kiểm định độ bền vững, chống hiện tượng học vẹt (overfitting).' },
    ],
  },
  {
    id: 'compile_validation',
    sel: '.se-strip-h',
    title: '5. Biên dịch thời gian thực & Bảo vệ nháp',
    body: [
      { label: 'Kiểm tra AST thời gian thực', text: 'Hệ thống tự động kiểm tra cú pháp Python AST và chỉ rõ dòng bị lỗi ngay khi bạn đang soạn thảo.' },
      { label: 'Bảo vệ bản nháp (Draft Safety)', text: 'Bản nháp được tự động lưu trữ định kỳ trong trình duyệt. Khi gặp lỗi cú pháp hay vô tình đóng tab, code của bạn luôn được bảo toàn.' },
    ],
  },
  {
    id: 'engine_sandbox',
    sel: '.se-run',
    title: '6. Động cơ Backtest độc lập (Sandbox 2 GB)',
    body: [
      { label: 'Môi trường an toàn', text: 'Tiến trình backtest EDU chạy trong sandbox cách ly với giới hạn 2 GB RAM (Nora EDU Backtest Engine), bảo vệ độ ổn định của máy chủ.' },
      { label: 'Khớp lệnh không nhìn trước', text: 'Mô phỏng khớp nến lịch sử tại Open nến kế tiếp với synthetic quote spread proxy đã kiểm định (không lookahead).' },
    ],
  },
  {
    id: 'quant_metrics',
    sel: '.se-right',
    title: '7. Bộ chỉ số định lượng & Ngưỡng tín nhiệm',
    body: [
      { label: 'Sharpe, CAGR & MDD', text: 'Tỷ suất Sharpe đo lường hiệu quả trên rủi ro, CAGR đo tăng trưởng hàng năm, và Max Drawdown đo độ sụt giảm tối đa từ đỉnh tài sản.' },
      { label: 'Ngưỡng xếp hạng N ≥ 20 & ≥ 30 ngày', text: 'Chiến lược cần đạt tối thiểu 20 lệnh giao dịch và thời gian kiểm thử 30 ngày (hoặc 500 nến khung ngắn) để đủ điều kiện xếp hạng trên Thị trường.' },
    ],
  },
  {
    id: 'versioning_fork',
    sel: '.se-save',
    title: '8. Quản lý phiên bản & Sao chép (Fork)',
    body: [
      { label: 'Lưu phiên bản (Versioning)', text: 'Mỗi lần cải tiến chiến lược, bạn lưu thành v1, v2, v3... kèm lịch sử thay đổi để theo dõi sự tiến bộ.' },
      { label: 'Sao chép có nguồn gốc (Fork)', text: 'Khi fork chiến lược từ cộng đồng, nguồn tác giả gốc (@user, mã alpha, version, code_hash) luôn được bảo toàn bất biến trên máy chủ.' },
    ],
  },
]

function useRect(sel, nonce) {
  const [rect, setRect] = useState(null)
  const last = useRef('')
  useEffect(() => {
    let raf = 0
    let tries = 0
    let scrolled = false
    setRect(null)
    last.current = ''
    const tick = () => {
      const el = sel ? document.querySelector(sel) : null
      if (el) {
        if (!scrolled) {
          scrolled = true
          el.scrollIntoView({ block: 'center', behavior: 'instant' in document.documentElement.style ? 'instant' : 'auto' })
        }
        const r = el.getBoundingClientRect()
        const key = [r.left, r.top, r.width, r.height].map(Math.round).join()
        if (key !== last.current) {
          last.current = key
          setRect({ left: r.left, top: r.top, width: r.width, height: r.height })
        }
      } else if (++tries > 40 && last.current !== 'none') {
        last.current = 'none'
        setRect(null)
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [sel, nonce])
  return rect
}

export default function EduStudioOnboarding({ isOpen, onClose, onLoadSample }) {
  const [index, setIndex] = useState(0)
  const [selectedSampleIndex, setSelectedSampleIndex] = useState(0)
  const popRef = useRef(null)
  const [pos, setPos] = useState({ left: 0, top: 0 })

  // Phục hồi bước đang dở dang theo DEC-04
  useEffect(() => {
    if (isOpen) {
      try {
        const raw = localStorage.getItem('nora_edu_onboarding')
        if (raw) {
          const parsed = JSON.parse(raw)
          if (typeof parsed?.current_step === 'number' && parsed.current_step >= 0 && parsed.current_step < EDU_STUDIO_STEPS.length) {
            setIndex(parsed.current_step)
          }
        }
      } catch (e) { /* ignore */ }
    }
  }, [isOpen])

  // Lưu tiến trình current_step theo DEC-04
  const persistStep = useCallback((stepIdx, isCompleted = false, isDismissed = false) => {
    try {
      localStorage.setItem('nora_edu_onboarding', JSON.stringify({
        completed: isCompleted,
        dismissed: isDismissed,
        current_step: stepIdx,
        last_active: Date.now(),
      }))
    } catch (e) { /* ignore */ }
  }, [])

  const step = EDU_STUDIO_STEPS[index]
  const rect = useRect(step?.sel, step?.id)
  const isLast = index === EDU_STUDIO_STEPS.length - 1

  const handleNext = useCallback(() => {
    if (index < EDU_STUDIO_STEPS.length - 1) {
      const nextIdx = index + 1
      setIndex(nextIdx)
      persistStep(nextIdx, false, false)
    } else {
      persistStep(index, true, false)
      onClose(true)
    }
  }, [index, onClose, persistStep])

  const handlePrev = useCallback(() => {
    if (index > 0) {
      const prevIdx = index - 1
      setIndex(prevIdx)
      persistStep(prevIdx, false, false)
    }
  }, [index, persistStep])

  const handleDismiss = useCallback(() => {
    persistStep(index, false, true)
    onClose(false)
  }, [index, onClose, persistStep])

  useEffect(() => {
    if (!isOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        onClose(false)
        return
      }
      const t = e.target
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.closest?.('.cm-editor'))) return
      if (e.key === 'ArrowRight') {
        e.preventDefault()
        handleNext()
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        handlePrev()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [isOpen, handleNext, handlePrev, onClose])

  useLayoutEffect(() => {
    if (!isOpen) return
    const pop = popRef.current
    if (!pop) return
    const vw = window.innerWidth
    const vh = window.innerHeight
    const h = pop.offsetHeight
    const w = Math.min(POP_W, vw - 24)
    if (!rect) {
      setPos({ left: (vw - w) / 2, top: Math.max(16, (vh - h) / 2) })
      return
    }
    const below = vh - (rect.top + rect.height) - PAD
    const above = rect.top - PAD
    let top
    if (rect.height > vh * 0.55) {
      top = Math.max(20, (vh - h) / 2)
    } else if (below >= h + 12) {
      top = rect.top + rect.height + PAD + 8
    } else if (above >= h + 12) {
      top = rect.top - PAD - 8 - h
    } else {
      top = Math.min(vh - h - 12, Math.max(16, vh - h - 24))
    }
    const left = Math.min(vw - w - 12, Math.max(12, rect.left + Math.min(rect.width, 600) / 2 - w / 2))
    setPos({ left, top })
  }, [isOpen, rect, index, step])

  if (!isOpen || !step) return null

  const sp = rect ? {
    left: rect.left - PAD,
    top: rect.top - PAD,
    width: rect.width + 2 * PAD,
    height: rect.height + 2 * PAD,
  } : null

  return createPortal(
    <div className="rt-root edu-onboarding-overlay" role="dialog" aria-modal="true" aria-label="Hướng dẫn Studio">
      {sp ? <div className="rt-spot" style={sp} /> : <div className="rt-dim" />}
      <div
        ref={popRef}
        className="rt-pop edu-onboarding-pop"
        style={{ left: pos.left, top: pos.top, width: Math.min(POP_W, window.innerWidth - 24), maxWidth: '94vw' }}
      >
        <div className="rt-hd" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <span className="rt-step" style={{ background: 'var(--n-brand, #38bdf8)', color: '#0f172a', fontWeight: 700, padding: '2px 8px', borderRadius: 4, fontSize: 11 }}>
            Bước {index + 1}/{EDU_STUDIO_STEPS.length}
          </span>
          <span className="rt-title" style={{ fontSize: 13, fontWeight: 700, flex: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {step.title}
          </span>
          <button
            type="button"
            className="n-btn sm ghost"
            onClick={handleDismiss}
            aria-label="Đóng hướng dẫn"
            style={{ padding: '0 4px', fontSize: 14, minWidth: 24, height: 24 }}
          >
            ✕
          </button>
        </div>

        <div className="rt-body" style={{ maxHeight: '45vh', overflowY: 'auto' }}>
          {step.body.map((b, i) => (
            <p key={i} style={{ margin: '0 0 8px', lineHeight: 1.5, fontSize: 13 }}>
              {b.label && <b style={{ color: 'var(--n-ink-0, #f8fafc)' }}>{b.label}: </b>}
              <span style={{ color: 'var(--n-ink-1, #94a3b8)' }}>{b.text}</span>
            </p>
          ))}

          {step.hasSamplePicker && (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
                {ONBOARDING_DSL_SAMPLES.map((s, idx) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`n-btn sm ${selectedSampleIndex === idx ? 'primary brand' : 'ghost'}`}
                    style={{ fontSize: 11, padding: '2px 8px' }}
                    onClick={() => setSelectedSampleIndex(idx)}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 12, color: 'var(--n-ink-1, #94a3b8)', marginBottom: 6 }}>
                💡 <b>{ONBOARDING_DSL_SAMPLES[selectedSampleIndex].name} ({ONBOARDING_DSL_SAMPLES[selectedSampleIndex].timeframe}):</b> {ONBOARDING_DSL_SAMPLES[selectedSampleIndex].desc}
              </div>
              <pre
                style={{
                  background: 'rgba(15, 23, 42, 0.85)',
                  border: '1px solid var(--n-border, #334155)',
                  borderRadius: 6,
                  padding: '8px 10px',
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: '#e2e8f0',
                  overflowX: 'auto',
                  maxHeight: 140,
                }}
              >
                {ONBOARDING_DSL_SAMPLES[selectedSampleIndex].code}
              </pre>
              {onLoadSample && (
                <button
                  type="button"
                  className="n-btn sm"
                  style={{ marginTop: 6, width: '100%', fontSize: 12 }}
                  onClick={() => {
                    onLoadSample(ONBOARDING_DSL_SAMPLES[selectedSampleIndex].code)
                  }}
                >
                  ⚡ Nạp mẫu [{ONBOARDING_DSL_SAMPLES[selectedSampleIndex].name}] vào Editor
                </button>
              )}
            </div>
          )}

          {step.sampleCode && !step.hasSamplePicker && (
            <div style={{ marginTop: 8 }}>
              <pre
                style={{
                  background: 'rgba(15, 23, 42, 0.85)',
                  border: '1px solid var(--n-border, #334155)',
                  borderRadius: 6,
                  padding: '8px 10px',
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: '#e2e8f0',
                  overflowX: 'auto',
                  maxHeight: 140,
                }}
              >
                {step.sampleCode}
              </pre>
              {onLoadSample && (
                <button
                  type="button"
                  className="n-btn sm"
                  style={{ marginTop: 6, width: '100%', fontSize: 12 }}
                  onClick={() => {
                    onLoadSample(step.sampleCode)
                  }}
                >
                  ⚡ Nạp mã mẫu này vào Editor
                </button>
              )}
            </div>
          )}
        </div>

        <div className="rt-dots" aria-hidden="true" style={{ display: 'flex', gap: 5, justifyContent: 'center', margin: '8px 0' }}>
          {EDU_STUDIO_STEPS.map((s, i) => (
            <button
              key={s.id}
              type="button"
              className={i === index ? 'on' : i < index ? 'done' : ''}
              onClick={() => {
                setIndex(i)
                persistStep(i, false, false)
              }}
              aria-label={`Đến bước ${i + 1}`}
              style={{
                width: i === index ? 18 : 6,
                height: 6,
                borderRadius: 3,
                background: i === index ? 'var(--n-brand, #38bdf8)' : i < index ? 'var(--n-ink-3, #475569)' : 'rgba(255, 255, 255, 0.2)',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
                transition: 'all 0.2s',
              }}
            />
          ))}
        </div>

        <div className="rt-ft" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginTop: 8 }}>
          <button type="button" className="n-btn sm ghost" onClick={handleDismiss} title="Đóng (Esc)">
            Bỏ qua
          </button>
          <div style={{ display: 'flex', gap: 6 }}>
            <button type="button" className="n-btn sm" onClick={handlePrev} disabled={index === 0} title="Quay lại (←)">
              Trước
            </button>
            <button type="button" className="n-btn sm primary brand" onClick={handleNext} title={isLast ? 'Hoàn tất' : 'Tiếp theo (→)'} autoFocus>
              {isLast ? 'Hoàn tất ✓' : 'Tiếp ➔'}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.querySelector('.v2') || document.body,
  )
}
