import React, { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate, useLocation } from 'react-router-dom'
import { useNotifications, addBacktestNotification } from '../../lib/notifications'
import useJobList from '../../hooks/useJobList'
import { getJob } from '../../api'
import { fmtSPct, fmtPct, signClass } from '../../lib/format'

const BELL_ICON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" style={{ width: 17, height: 17 }} aria-hidden="true">
    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
  </svg>
)

function timeAgo(ts) {
  if (!ts) return ''
  const diffSec = Math.floor((Date.now() - ts) / 1000)
  if (diffSec < 45) return 'Vừa xong'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} phút trước`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} giờ trước`
  return `${Math.floor(diffSec / 86400)} ngày trước`
}

export default function NotificationBell() {
  const { notifications, unreadCount, markAsRead, markAllAsRead } = useNotifications()
  const { jobs } = useJobList(25)
  const [open, setOpen] = useState(false)
  const [toast, setToast] = useState(null)
  const box = useRef(null)
  const navigate = useNavigate()
  const loc = useLocation()
  const seenJobs = useRef(new Set())

  // Tự động đóng dropdown khi chuyển trang
  useEffect(() => {
    setOpen(false)
  }, [loc.pathname, loc.search])

  // Đóng dropdown khi click ra ngoài hoặc nhấn phím Escape
  useEffect(() => {
    if (!open) return undefined
    const click = (e) => {
      const pop = document.getElementById('n-notification-pop')
      if (box.current && !box.current.contains(e.target) && (!pop || !pop.contains(e.target))) {
        setOpen(false)
      }
    }
    const key = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', click)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('mousedown', click)
      document.removeEventListener('keydown', key)
    }
  }, [open])

  // Theo dõi danh sách jobs từ hệ thống để tự động nạp các job backtest hoàn thành
  useEffect(() => {
    if (!jobs || !jobs.length) return
    const isFirstScan = seenJobs.current.size === 0

    jobs.forEach((j) => {
      const jId = j.id || j.job_id
      if (!jId) return

      if (j.status === 'done' && !seenJobs.current.has(jId)) {
        seenJobs.current.add(jId)

        const isBacktest =
          j.kind === 'book_backtest' ||
          j.kind === 'custom_backtest' ||
          String(j.kind || '').includes('backtest') ||
          j.kind === 'wfa' ||
          j.kind === 'mc'

        if (isBacktest) {
          const st = j.params?.strategies?.[0]
          const stratKey = st?.id || j.params?.strategy || 'dca_short'
          const title = j.label || j.detail || stratKey
          const rawSym = Array.isArray(j.params?.symbols)
            ? j.params.symbols[0]
            : typeof j.params?.symbols === 'string'
              ? j.params.symbols
              : 'BTC@perp'
          const symbol = String(rawSym).replace('@perp', '') + '@perp'
          const sum = j.result?.summary || j.result?.out_of_sample || j.result?.in_sample || j.result || {}

          addBacktestNotification({
            job_id: jId,
            alpha_id: stratKey,
            title,
            symbol,
            time: j.finished
              ? typeof j.finished === 'number'
                ? j.finished * 1000
                : new Date(j.finished).getTime()
              : j.created
                ? j.created * 1000
                : Date.now(),
            ret_pct: sum.ret_pct,
            mdd_pct: sum.mdd_pct,
            win_rate: sum.win_rate ?? sum.win_pct,
            trades: sum.trades,
            status: 'done',
            read: isFirstScan, // Nếu là các job cũ trong lịch sử thì đánh dấu đã đọc
          })

          // Nếu job chưa có kết quả chi tiết kèm theo, fetch ngầm để cập nhật đầy đủ PnL & Win Rate
          if (!j.result || sum.ret_pct == null) {
            getJob(jId).then((fullJob) => {
              if (fullJob?.result) {
                const res = fullJob.result
                const s = res.summary || res.out_of_sample || res.in_sample || res
                addBacktestNotification({
                  job_id: jId,
                  alpha_id: stratKey,
                  title,
                  symbol,
                  time: fullJob.finished
                    ? typeof fullJob.finished === 'number'
                      ? fullJob.finished * 1000
                      : new Date(fullJob.finished).getTime()
                    : Date.now(),
                  ret_pct: s.ret_pct,
                  mdd_pct: s.mdd_pct,
                  win_rate: s.win_rate ?? s.win_pct,
                  trades: s.trades,
                  status: 'done',
                  read: true,
                })
              }
            }).catch(() => {})
          }
        }
      }
    })
  }, [jobs])

  // Lắng nghe thông báo mới để hiển thị toast ngắn trên header
  useEffect(() => {
    const onNotif = (e) => {
      if (e.detail?.type === 'add' && e.detail.item) {
        setToast(e.detail.item)
        const t = setTimeout(() => setToast(null), 6000)
        return () => clearTimeout(t)
      }
    }
    window.addEventListener('nora_notification_change', onNotif)
    return () => window.removeEventListener('nora_notification_change', onNotif)
  }, [])

  const handleOpenResult = (item) => {
    markAsRead(item.job_id)
    setOpen(false)
    setToast(null)
    const targetAlpha = item.alpha_id || item.title

    // Lưu vào sessionStorage để trang đích đảm bảo luôn nạp và mở Drawer kết quả ngay cả khi reload/chuyển route
    try {
      sessionStorage.setItem(
        'nora_view_alpha_detail',
        JSON.stringify({ alphaId: targetAlpha, jobId: item.job_id, item })
      )
    } catch (e) { /* ignore */ }

    // Phát sự kiện mở drawer tức thì (nếu đang ở trang backtest)
    window.dispatchEvent(
      new CustomEvent('nora_open_alpha_result', {
        detail: { alphaId: targetAlpha, jobId: item.job_id, item, notificationItem: item },
      })
    )

    navigate(`/coin/backtest?view_alpha=${encodeURIComponent(targetAlpha)}&step=1`)
  }

  return (
    <div className="n-tray" ref={box} style={{ position: 'relative', zIndex: open ? 120 : undefined }}>
      {/* Nút Chuông Icon Đơn Giản - Không text, bo góc tròn 32x32px */}
      <button
        type="button"
        className={`n-pill n-tray-btn ${unreadCount > 0 ? 'live' : ''}`}
        aria-expanded={open}
        aria-haspopup="true"
        title={unreadCount > 0 ? `${unreadCount} kết quả backtest mới` : 'Thông báo kết quả backtest'}
        onClick={() => setOpen((o) => !o)}
        style={{
          position: 'relative',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 32,
          height: 32,
          padding: 0,
          borderRadius: 8,
          cursor: 'pointer',
          background: open ? 'var(--n-surface-2)' : undefined,
          borderColor: open ? 'var(--n-accent)' : undefined,
          transition: 'all 0.15s ease',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: unreadCount > 0 ? 'var(--n-accent)' : 'var(--n-ink-2)' }}>
          {BELL_ICON}
        </span>
        {unreadCount > 0 && (
          <span
            style={{
              position: 'absolute',
              top: -2,
              right: -2,
              background: '#ef4444',
              color: '#ffffff',
              fontSize: 9.5,
              fontWeight: 700,
              minWidth: 16,
              height: 16,
              borderRadius: 8,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '0 3px',
              lineHeight: 1,
              border: '2px solid var(--n-bg, #09090b)',
              boxShadow: '0 2px 5px rgba(239, 68, 68, 0.4)',
              animation: 'pulse 2s infinite',
            }}
          >
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {/* Popover danh sách thông báo: Nhỏ gọn, hiển thị ngay từ nút thông báo thả xuống */}
      {open && (
        <div
          id="n-notification-pop"
          className="n-pop"
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            right: 0,
            width: 320,
            maxWidth: 'calc(100vw - 20px)',
            background: 'var(--n-surface)',
            border: '1px solid var(--n-line)',
            borderRadius: 10,
            boxShadow: '0 12px 36px rgba(0, 0, 0, 0.45), 0 0 0 1px var(--n-line)',
            zIndex: 120,
            overflow: 'hidden',
          }}
        >
          {/* Header nhỏ gọn */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '8px 12px',
              borderBottom: '1px solid var(--n-line)',
              background: 'var(--n-surface-2)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <b style={{ fontSize: 12.5, color: 'var(--n-ink)' }}>Thông báo</b>
              {unreadCount > 0 && (
                <span className="n-badge brand sm" style={{ fontSize: 10, padding: '0 5px', lineHeight: '15px' }}>
                  {unreadCount} mới
                </span>
              )}
            </div>
            {unreadCount > 0 && (
              <button
                type="button"
                className="n-btn xs"
                onClick={markAllAsRead}
                style={{ fontSize: 10.5, padding: '1px 6px', height: 20 }}
              >
                Đã đọc tất cả
              </button>
            )}
          </div>

          {/* Danh sách thông báo */}
          <div style={{ maxHeight: 310, overflowY: 'auto', padding: '6px' }}>
            {notifications.length === 0 ? (
              <div style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--n-ink-3)' }}>
                <div style={{ fontSize: 18, marginBottom: 4, opacity: 0.6 }}>🔔</div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>Chưa có thông báo kiểm định</div>
                <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
                  Kết quả backtest chạy xong sẽ hiển thị ở đây.
                </div>
              </div>
            ) : (
              notifications.map((item) => (
                <div
                  key={item.job_id}
                  onClick={() => handleOpenResult(item)}
                  style={{
                    padding: '8px 10px',
                    borderRadius: 7,
                    marginBottom: 4,
                    background: item.read ? 'transparent' : 'rgba(56, 189, 248, 0.08)',
                    border: '1px solid',
                    borderColor: item.read ? 'var(--n-line-soft, rgba(255,255,255,0.08))' : 'rgba(56, 189, 248, 0.35)',
                    cursor: 'pointer',
                    transition: 'all 0.12s ease',
                  }}
                  className="hover-row"
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      {!item.read && (
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-accent, #38bdf8)' }} />
                      )}
                      <span className="n-badge ok sm" style={{ fontSize: 9.5, padding: '0 4px', lineHeight: '14px', fontWeight: 600 }}>
                        ✓ Xong
                      </span>
                      <span className="mono" style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>
                        {String(item.symbol || '').replace('@perp', '')}
                      </span>
                    </div>
                    <span className="muted" style={{ fontSize: 10 }}>
                      {timeAgo(item.time)}
                    </span>
                  </div>

                  <div
                    style={{
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--n-ink)',
                      marginBottom: 4,
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                    title={item.title}
                  >
                    {item.title}
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11 }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      {item.ret_pct != null && (
                        <span className={`mono ${signClass(item.ret_pct)}`} style={{ fontWeight: 600 }}>
                          PnL: {fmtSPct(item.ret_pct, 1)}
                        </span>
                      )}
                      {item.mdd_pct != null && (
                        <span className="mono neg" style={{ fontWeight: 500 }}>
                          MDD: −{fmtPct(item.mdd_pct, 1)}
                        </span>
                      )}
                      {item.win_rate != null && (
                        <span className="mono muted">
                          Win: {fmtPct(item.win_rate, 1)}
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--n-accent, #38bdf8)', fontWeight: 600 }}>➔</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Toast thông báo nổi nhanh khi vừa hoàn thành */}
      {toast &&
        createPortal(
          <div
            className="v2"
            onClick={() => handleOpenResult(toast)}
            style={{
              position: 'fixed',
              top: 56,
              right: 16,
              width: 300,
              maxWidth: 'calc(100vw - 32px)',
              padding: '10px 14px',
              background: 'var(--n-surface, #18181b)',
              border: '1.5px solid var(--n-accent, #38bdf8)',
              borderRadius: 8,
              boxShadow: '0 12px 32px rgba(0,0,0,0.6)',
              zIndex: 100000,
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
              <span style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--n-accent, #38bdf8)' }}>
                ✓ BACKTEST HOÀN TẤT
              </span>
              <span className="muted" style={{ fontSize: 10 }}>Vừa xong</span>
            </div>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--n-ink)', marginBottom: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {toast.title}
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11 }}>
              <div style={{ display: 'flex', gap: 8 }}>
                {toast.ret_pct != null && (
                  <span className={`mono ${signClass(toast.ret_pct)}`} style={{ fontWeight: 600 }}>
                    PnL: {fmtSPct(toast.ret_pct, 1)}
                  </span>
                )}
                {toast.win_rate != null && (
                  <span className="mono muted">
                    Win: {fmtPct(toast.win_rate, 1)}
                  </span>
                )}
              </div>
              <span style={{ fontSize: 10.5, color: 'var(--n-accent, #38bdf8)', fontWeight: 600 }}>Xem ➔</span>
            </div>
          </div>,
          document.body
        )}
    </div>
  )
}
