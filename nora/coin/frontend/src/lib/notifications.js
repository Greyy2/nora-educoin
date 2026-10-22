import { useState, useEffect, useCallback } from 'react'

const STORAGE_KEY = 'nora_backtest_notifications'
const MAX_NOTIFS = 40

export function getStoredNotifications() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    return JSON.parse(raw)
  } catch (e) {
    return []
  }
}

export function saveNotifications(list) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_NOTIFS)))
  } catch (e) {
    /* ignore */
  }
}

export function addBacktestNotification(notif) {
  if (!notif || !notif.job_id) return
  const current = getStoredNotifications()
  // Tránh trùng lặp theo job_id
  const exists = current.some((n) => n.job_id === notif.job_id)
  if (exists) return

  const item = {
    id: notif.job_id,
    job_id: notif.job_id,
    alpha_id: notif.alpha_id || '',
    title: notif.title || 'Chiến lược Backtest',
    symbol: notif.symbol || 'BTC@perp',
    time: notif.time || Date.now(),
    ret_pct: notif.ret_pct != null ? notif.ret_pct : null,
    mdd_pct: notif.mdd_pct != null ? notif.mdd_pct : null,
    win_rate: notif.win_rate != null ? notif.win_rate : null,
    trades: notif.trades != null ? notif.trades : null,
    status: notif.status || 'done',
    read: false,
  }

  const updated = [item, ...current]
  saveNotifications(updated)
  window.dispatchEvent(new CustomEvent('nora_notification_change', { detail: { type: 'add', item } }))
}

export function markAsRead(jobId) {
  const current = getStoredNotifications()
  const updated = current.map((n) => (n.job_id === jobId ? { ...n, read: true } : n))
  saveNotifications(updated)
  window.dispatchEvent(new CustomEvent('nora_notification_change', { detail: { type: 'read', jobId } }))
}

export function markAllAsRead() {
  const current = getStoredNotifications()
  const updated = current.map((n) => ({ ...n, read: true }))
  saveNotifications(updated)
  window.dispatchEvent(new CustomEvent('nora_notification_change', { detail: { type: 'read_all' } }))
}

export function clearAllNotifications() {
  localStorage.removeItem(STORAGE_KEY)
  window.dispatchEvent(new CustomEvent('nora_notification_change', { detail: { type: 'clear' } }))
}

/**
 * Hook quản lý danh sách thông báo hoàn thành kiểm định
 */
export function useNotifications() {
  const [notifications, setNotifications] = useState(getStoredNotifications)

  useEffect(() => {
    const handler = () => {
      setNotifications(getStoredNotifications())
    }
    window.addEventListener('nora_notification_change', handler)
    window.addEventListener('storage', handler)
    return () => {
      window.removeEventListener('nora_notification_change', handler)
      window.removeEventListener('storage', handler)
    }
  }, [])

  const unreadCount = notifications.filter((n) => !n.read).length

  return {
    notifications,
    unreadCount,
    markAsRead,
    markAllAsRead,
    clearAllNotifications,
    addBacktestNotification,
  }
}
