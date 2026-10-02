import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { getCatalog } from '../api'

const Ctx = createContext({ data: null, loading: true, error: null, reload: () => {} })
export const useCatalog = () => useContext(Ctx)

export function CatalogProvider({ children }) {
  const [st, setSt] = useState({ data: null, loading: true, error: null })
  const load = useCallback(() => {
    setSt((s) => ({ ...s, loading: true }))
    getCatalog().then((data) => setSt({ data, loading: false, error: null }), (e) => setSt({ data: null, loading: false, error: e.message }))
  }, [])
  useEffect(() => { load() }, [load])
  return <Ctx.Provider value={{ ...st, reload: load }}>{children}</Ctx.Provider>
}
