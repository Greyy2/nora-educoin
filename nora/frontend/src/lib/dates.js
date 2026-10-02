// Ngày hiển thị / nhập dạng dd/mm/yyyy (không phụ thuộc locale trình duyệt); nội bộ luôn là 'YYYY-MM-DD' (UTC).
const pad = (n) => String(n).padStart(2, '0')

export const isoToVn = (iso) => (typeof iso === 'string' && /^\d{4}-\d{2}-\d{2}/.test(iso) ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '')

/** 'dd/mm/yyyy' (cũng nhận d/m/yyyy, dấu - hoặc .) -> 'YYYY-MM-DD', hoặc null nếu sai / ngày không tồn tại. */
export function vnToIso(text) {
  const m = /^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\s*$/.exec(String(text ?? ''))
  if (!m) return null
  const d = Number(m[1]); const mo = Number(m[2]); const y = Number(m[3])
  if (y < 1990 || y > 2100 || mo < 1 || mo > 12 || d < 1) return null
  const dt = new Date(Date.UTC(y, mo - 1, d))
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) return null
  return `${y}-${pad(mo)}-${pad(d)}`
}

export function addDaysIso(iso, n) {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

/** Số ngày gồm cả hai đầu. */
export function daysInclusive(a, b) {
  if (!a || !b) return null
  const n = Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000) + 1
  return Number.isFinite(n) ? n : null
}

/** Các khoảng chọn nhanh từ `windows` của danh mục (start, dev1_end, dev2_end, end).
 *  Mốc dev1_end / dev2_end là ranh giới đầu ngày (ngày đầu của vùng kế tiếp), nên ngày cuối gồm cả hai đầu của dev1/dev2 lùi một ngày. */
export function datePresets(w) {
  if (!w?.start || !w?.end) return []
  const out = []
  if (w.dev1_end) out.push({ key: 'dev1', label: 'dev1', start: w.start, end: addDaysIso(w.dev1_end, -1) })
  if (w.dev1_end && w.dev2_end) out.push({ key: 'dev2', label: 'dev2', start: w.dev1_end, end: addDaysIso(w.dev2_end, -1) })
  if (w.dev2_end) out.push({ key: 'holdout', label: 'Holdout', start: w.dev2_end, end: w.end })
  out.push({ key: 'all', label: 'Toàn bộ', start: w.start, end: w.end })
  out.push({ key: 'last90', label: '90 ngày gần nhất', start: addDaysIso(w.end, -89), end: w.end })
  return out
}
