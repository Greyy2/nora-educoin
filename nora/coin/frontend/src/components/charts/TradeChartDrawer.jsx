import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loading, ErrorState } from '../ui'
import SignalChart from './SignalChart'
import SignalExplainPanel from './SignalExplainPanel'
import useAsync from '../../hooks/useAsync'
import { explainChart } from '../../api'
import { tradeWindow, signalForTrade } from './chartFormat'

/** Ngăn kéo bên phải: biểu đồ giải thích tín hiệu của một lệnh. request = thân yêu cầu explain không có start/end. */
export default function TradeChartDrawer({ open, onClose, request, trade, title }) {
  const opener = useRef(null)
  const box = useRef(null)
  const [selT, setSelT] = useState(null)
  const reqKey = JSON.stringify(request)
  const win = useMemo(() => (trade ? tradeWindow(trade.enter_ms, trade.close_ms) : null), [trade])
  const q = useAsync(open && trade ? () => explainChart({ ...request, ...win }) : null, [open, reqKey, win?.start, win?.end])
  const d = q.data

  useEffect(() => {
    if (!open) return undefined
    opener.current = document.activeElement
    box.current?.focus()
    // pha capture + chặn lan để Esc chỉ đóng ngăn kéo biểu đồ, không đóng luôn ngăn kéo alpha bên dưới
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    window.addEventListener('keydown', key, true)
    return () => { window.removeEventListener('keydown', key, true); try { opener.current?.focus?.() } catch (e) { /* bỏ qua */ } }
  }, [open, onClose])

  // chọn sẵn tín hiệu đã gây ra lệnh
  useEffect(() => { setSelT(d && trade ? signalForTrade(d.signals, trade.enter_ms)?.t ?? null : null) }, [d, trade])
  const trades = useMemo(() => (trade ? [trade] : []), [trade])
  const selected = useMemo(() => d?.signals?.find((s) => s.t === selT) || null, [d, selT])

  if (!open || !trade) return null
  return createPortal(
    <div className="v2 n-drawer-wrap">
      <div className="n-drawer-bg" onClick={onClose} aria-hidden="true" />
      <aside className="n-drawer" role="dialog" aria-modal="true" aria-label={title || 'Biểu đồ tín hiệu'} tabIndex={-1} ref={box}>
        <header className="n-drawer-h">
          <div style={{ minWidth: 0 }}>
            <div className="kick muted">Biểu đồ tín hiệu</div>
            <h2 title={title}>{title || 'Biểu đồ lệnh'}</h2>
          </div>
          <button type="button" className="n-btn" onClick={onClose} aria-label="Đóng biểu đồ">Đóng ✕</button>
        </header>
        <div className="n-drawer-b">
          {q.error && <ErrorState title="Không dựng được biểu đồ" error={q.error} onRetry={q.reload} />}
          {!q.error && !d && <Loading what="biểu đồ" />}
          {d && (
            <div style={{ display: 'grid', gap: 12, paddingBottom: 18 }}>
              <SignalChart data={d} trades={trades} selectedT={selT} onSelectSignal={(s) => setSelT(s.t)} />
              {!selected && d.signals.length === 0 && <p className="n-note">Không có tín hiệu nào trong khoảng này.</p>}
              <SignalExplainPanel data={d} selected={selected} />
            </div>
          )}
        </div>
      </aside>
    </div>,
    document.body
  )
}
