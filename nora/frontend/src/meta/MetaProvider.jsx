import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { getStudioMeta, getCatalog, getStrategies } from '../api'

import { registerFunnelMeta } from '../lib/funnel'
import { subscribeResource, invalidateResource } from '../lib/bus'

export { invalidateResource, subscribeResource }

const MetaCtx = createContext({
  meta: null,
  catalog: null,
  loading: true,
  error: null,
  reload: () => {},
  invalidate: () => {},
})

/** Hook đọc metadata duy nhất từ backend. */
export const useMeta = () => useContext(MetaCtx)

/** Hook đọc catalog chiến lược (tương thích ngược hoàn toàn với CatalogContext cũ). */
export function useCatalog() {
  const { catalog, loading, error, invalidate } = useContext(MetaCtx)
  return {
    data: catalog,
    loading,
    error,
    reload: () => invalidate('catalog'),
  }
}

export function MetaProvider({ children }) {
  const [meta, setMeta] = useState(null)
  const [catalog, setCatalog] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const metaVersion = useRef(null)

  const loadMeta = useCallback(async (silent = false) => {
    try {
      const data = await getStudioMeta()
      if (data && data.version) {
        metaVersion.current = data.version
      }
      registerFunnelMeta(data)
      setMeta(data)
      return data
    } catch (e) {
      if (!silent) setError(e.message || String(e))
    }
  }, [])

  const loadCatalog = useCallback(async (silent = false) => {
    try {
      const data = await getCatalog()
      setCatalog(data)
      return data
    } catch (e) {
      if (!silent) setError(e.message || String(e))
    }
  }, [])

  const loadAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      await Promise.all([loadMeta(silent), loadCatalog(silent), getStrategies(silent).catch(() => null)])
    } finally {
      if (!silent) setLoading(false)
    }
  }, [loadMeta, loadCatalog])

  const invalidate = useCallback((pattern = 'all') => {
    if (pattern === 'all' || pattern === 'meta') {
      loadMeta(true)
    }
    if (pattern === 'all' || pattern === 'catalog') {
      loadCatalog(true)
    }
    invalidateResource(pattern)
  }, [loadMeta, loadCatalog])

  useEffect(() => {
    loadAll(false)
  }, [loadAll])

  // Tự động làm mới meta khi tab chuyển sang active
  useEffect(() => {
    const onFocus = () => {
      if (!document.hidden) {
        loadMeta(true)
      }
    }
    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onFocus)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onFocus)
    }
  }, [loadMeta])

  // Lắng nghe lời gọi invalidate từ các hàm API hoặc hooks
  useEffect(() => {
    const handler = (pattern) => {
      if (pattern === 'all' || pattern === 'meta') loadMeta(true)
      if (pattern === 'all' || pattern === 'catalog') loadCatalog(true)
    }
    return subscribeResource(handler)
  }, [loadMeta, loadCatalog])

  return (
    <MetaCtx.Provider value={{ meta, catalog, loading, error, reload: loadAll, invalidate }}>
      {children}
    </MetaCtx.Provider>
  )
}

/** Tương thích ngược với component Root() trong App.jsx */
export const CatalogProvider = MetaProvider
export default MetaProvider
