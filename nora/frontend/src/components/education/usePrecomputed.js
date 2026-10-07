import { useEffect, useMemo, useState } from 'react'
import useAsync from '../../hooks/useAsync'
import { getEducationResults, getEducationResult, postCompileStrategy } from '../../api'

// Kết quả backtest tính trước của mẫu Education (data/education/results). Khớp theo program_hash của code đang mở:
//   fresh  = hash của code (biên dịch qua /strategies/compile) trùng hash bản ghi chạy sẵn và cùng hồ sơ -> dùng ngay, không cần chạy lại;
//   stale  = code xuất phát từ một mẫu có bản ghi nhưng hash đã khác (người dùng sửa code) -> bản ghi chạy sẵn không còn khớp;
//   none   = không có bản ghi cho code này; loading = đang tra cứu.
const hashCache = new Map()

export default function usePrecomputed({ code, profile, sampleKey }) {
  const idx = useAsync(getEducationResults, [])
  const items = Array.isArray(idx.data?.items) ? idx.data.items : []
  const [hash, setHash] = useState(null) // { code, hash } | { code, error }
  const trimmed = (code || '').trim()

  useEffect(() => {
    if (!trimmed) { setHash(null); return undefined }
    if (hashCache.has(trimmed)) { setHash({ code: trimmed, hash: hashCache.get(trimmed) }); return undefined }
    let dead = false
    const t = setTimeout(() => {
      postCompileStrategy(code).then(
        (r) => { if (dead) return; const h = r?.ok ? r.program_hash || null : null; if (h) hashCache.set(trimmed, h); setHash({ code: trimmed, hash: h }) },
        () => { if (!dead) setHash({ code: trimmed, hash: null }) },
      )
    }, 500)
    return () => { dead = true; clearTimeout(t) }
  }, [trimmed]) // eslint-disable-line react-hooks/exhaustive-deps

  const hashReady = hash && hash.code === trimmed
  const cur = hashReady ? hash.hash : null
  const item = useMemo(() => (cur ? items.find((i) => i.status === 'ok' && i.program_hash === cur && (!i.profile || i.profile === profile)) : null), [items, cur, profile])
  const origin = useMemo(() => (sampleKey ? items.find((i) => i.key === sampleKey) : null), [items, sampleKey])
  const rec = useAsync(item ? () => getEducationResult(item.key) : null, [item?.key])

  let state = 'none'
  if (item) state = rec.data && rec.data.program_hash === cur ? 'fresh' : rec.error ? 'none' : 'loading'
  else if (!idx.loading && !idx.error && trimmed && !hashReady) state = 'loading'
  else if (origin && hashReady) state = 'stale'
  return { state, record: state === 'fresh' ? rec.data : null, item: item || origin || null, origin, error: idx.error || rec.error || null }
}
