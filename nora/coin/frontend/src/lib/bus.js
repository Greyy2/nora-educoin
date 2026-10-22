// Bộ phân phối sự kiện tài nguyên độc lập, tránh phụ thuộc vòng tròn giữa api và React context.
const listeners = new Set()

export function subscribeResource(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

export function invalidateResource(pattern = 'all') {
  listeners.forEach((fn) => {
    try {
      fn(pattern)
    } catch (e) {
      console.error('Lỗi khi thông báo invalidate:', e)
    }
  })
}
