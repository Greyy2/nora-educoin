import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { getMe, login as apiLogin, logout as apiLogout, createUser as apiCreateUser, enterByName } from '../api'

const UserCtx = createContext({
  me: null,
  loading: true,
  refresh: async () => {},
  login: async () => {},
  logout: async () => {},
  create: async () => {},
  enter: async () => {},
})

/** Hook dùng thông tin và thao tác phiên người dùng hiện tại */
export const useUser = () => useContext(UserCtx)

export function UserProvider({ children }) {
  const [me, setMe] = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const res = await getMe()
      setMe(res?.user || null)
      return res?.user || null
    } catch {
      setMe(null)
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const login = useCallback(async (handle, password) => {
    const res = await apiLogin(handle, password)
    if (res?.user) {
      setMe(res.user)
    }
    return res?.user
  }, [])

  const logout = useCallback(async () => {
    await apiLogout()
    setMe(null)
  }, [])

  const create = useCallback(async (body) => {
    const user = await apiCreateUser(body)
    if (user) {
      setMe(user)
    }
    return user
  }, [])

  const enter = useCallback(async (name) => {
    const res = await enterByName(name)
    if (res?.user) setMe(res.user)
    return res?.user
  }, [])

  return (
    <UserCtx.Provider value={{ me, loading, refresh, login, logout, create, enter }}>
      {children}
    </UserCtx.Provider>
  )
}
