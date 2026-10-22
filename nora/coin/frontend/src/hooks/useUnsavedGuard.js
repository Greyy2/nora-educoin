import { useEffect } from 'react'
import { useBlocker } from 'react-router-dom'

/**
 * Cảnh báo rời trang khi còn thay đổi chưa lưu:
 *  - đóng tab / tải lại: sự kiện beforeunload (trình duyệt tự hiện hộp thoại chuẩn);
 *  - chuyển trang trong ứng dụng: useBlocker của react-router (cần data router: createBrowserRouter + RouterProvider, xem App.jsx);
 *    đổi mỗi query string (?job=...) cùng đường dẫn thì không chặn.
 * Trả `blocker` ({ state: 'unblocked' | 'blocked' | 'proceeding', proceed(), reset() }) cho LeaveGuardDialog.
 */
export default function useUnsavedGuard(dirty) {
  useEffect(() => {
    if (!dirty) return undefined
    const onUnload = (e) => { e.preventDefault(); e.returnValue = ''; return '' }
    window.addEventListener('beforeunload', onUnload)
    return () => window.removeEventListener('beforeunload', onUnload)
  }, [dirty])
  return useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname)
}
