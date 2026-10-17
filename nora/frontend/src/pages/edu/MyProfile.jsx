import React, { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getUser, getUserStrategies, updateMe } from '../../api'
import { useUser } from '../../meta/UserProvider'
import UserPicker from '../../components/user/UserPicker'
import { Spinner } from '../../components/ui'

export default function MyProfile() {
  const { me, refresh } = useUser()
  const [searchParams] = useSearchParams()
  const queryUser = searchParams.get('user')

  const [targetUser, setTargetUser] = useState(null)
  const [strategies, setStrategies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Edit profile state
  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editBio, setEditBio] = useState('')
  const [editSaving, setEditSaving] = useState(false)
  const [editErr, setEditErr] = useState(null)

  const [pickerOpen, setPickerOpen] = useState(false)

  const isMe = !queryUser || (me && me.handle === queryUser)
  const activeHandle = queryUser || me?.handle

  useEffect(() => {
    let active = true
    if (!activeHandle) {
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)

    const fetchProfile = async () => {
      try {
        let uData = null
        if (queryUser && (!me || me.handle !== queryUser)) {
          uData = await getUser(queryUser)
        } else {
          uData = me
        }

        const stratsRes = await getUserStrategies(activeHandle)
        if (active) {
          setTargetUser(uData)
          setStrategies(Array.isArray(stratsRes) ? stratsRes : (Array.isArray(stratsRes?.strategies) ? stratsRes.strategies : []))
          if (uData) {
            setEditName(uData.display_name || '')
            setEditBio(uData.bio || '')
          }
        }
      } catch (err) {
        if (active) {
          setError(err.message || 'Không tải được hồ sơ')
        }
      } finally {
        if (active) setLoading(false)
      }
    }

    fetchProfile()
    return () => {
      active = false
    }
  }, [activeHandle, queryUser, me])

  const handleSaveProfile = async (e) => {
    e.preventDefault()
    setEditErr(null)
    const cleanName = editName.trim()
    if (!cleanName) {
      setEditErr('Tên hiển thị không được để trống.')
      return
    }

    setEditSaving(true)
    try {
      await updateMe({
        display_name: cleanName,
        bio: editBio.trim(),
      })
      await refresh()
      setEditing(false)
    } catch (err) {
      setEditErr(err.message || 'Lỗi cập nhật hồ sơ.')
    } finally {
      setEditSaving(false)
    }
  }

  const stats = React.useMemo(() => {
    if (!strategies || strategies.length === 0) return null

    let totalRet = 0
    let validRetCount = 0
    let maxRet = -Infinity
    let minRet = Infinity
    let bestStrat = null

    let totalMdd = 0
    let validMddCount = 0
    let minMdd = Infinity
    let maxMdd = -Infinity

    let totalSharpe = 0
    let validSharpeCount = 0
    let maxSharpe = -Infinity
    let highSharpeCount = 0

    let totalTrades = 0
    let totalWinRate = 0
    let winRateCount = 0
    let safeMddCount = 0

    let profitableStrats = 0

    strategies.forEach((s) => {
      const m = s.metrics?.simulate || s.metrics || {}
      const ret = m.ret_pct !== undefined ? m.ret_pct : (m.pnl_pct !== undefined ? m.pnl_pct : null)
      const mdd = m.mdd_pct !== undefined ? m.mdd_pct : (m.max_drawdown_pct !== undefined ? m.max_drawdown_pct : null)
      const sharpe = m.sharpe !== undefined ? m.sharpe : (m.sharpe_ratio !== undefined ? m.sharpe_ratio : null)
      const trades = m.trades !== undefined ? m.trades : 0
      const wr = m.win_rate_trades !== undefined ? m.win_rate_trades : (m.win_rate !== undefined ? m.win_rate : null)

      if (ret !== null && !isNaN(ret)) {
        totalRet += ret
        validRetCount += 1
        if (ret > maxRet) {
          maxRet = ret
          bestStrat = s
        }
        if (ret < minRet) minRet = ret
        if (ret > 0) profitableStrats += 1
      }

      if (mdd !== null && !isNaN(mdd)) {
        totalMdd += mdd
        validMddCount += 1
        if (mdd < minMdd) minMdd = mdd
        if (mdd > maxMdd) maxMdd = mdd
        if (mdd <= 20) safeMddCount += 1
      }

      if (sharpe !== null && !isNaN(sharpe)) {
        totalSharpe += sharpe
        validSharpeCount += 1
        if (sharpe > maxSharpe) maxSharpe = sharpe
        if (sharpe >= 1.0) highSharpeCount += 1
      }

      if (trades) totalTrades += trades
      if (wr !== null && !isNaN(wr)) {
        totalWinRate += wr
        winRateCount += 1
      }
    })

    const n = strategies.length
    return {
      count: n,
      avgReturn: validRetCount > 0 ? totalRet / validRetCount : 0,
      maxReturn: maxRet !== -Infinity ? maxRet : null,
      minReturn: minRet !== Infinity ? minRet : null,
      bestStrat,
      avgMdd: validMddCount > 0 ? totalMdd / validMddCount : 0,
      minMdd: minMdd !== Infinity ? minMdd : null,
      maxMdd: maxMdd !== -Infinity ? maxMdd : null,
      avgSharpe: validSharpeCount > 0 ? totalSharpe / validSharpeCount : 0,
      maxSharpe: maxSharpe !== -Infinity ? maxSharpe : null,
      highSharpeCount,
      safeMddCount,
      totalTrades,
      avgWinRate: winRateCount > 0 ? totalWinRate / winRateCount : null,
      profitableRatio: validRetCount > 0 ? (profitableStrats / validRetCount) * 100 : 0,
      profitableCount: profitableStrats,
    }
  }, [strategies])

  if (!activeHandle && !me) {
    return (
      <div style={{ maxWidth: 600, margin: '60px auto', textAlign: 'center', padding: '0 24px' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>👤</div>
        <h2 style={{ fontSize: 24, fontWeight: 700, margin: '0 0 10px 0' }}>Chưa đăng nhập</h2>
        <p style={{ color: 'var(--n-ink-2)', fontSize: 14, marginBottom: 24, lineHeight: 1.5 }}>
          Vui lòng chọn hoặc tạo người dùng để xem hồ sơ và quản lý các chiến lược của riêng bạn.
        </p>
        <button
          type="button"
          className="n-btn primary"
          onClick={() => setPickerOpen(true)}
          style={{ background: '#7c3aed', borderColor: '#7c3aed', padding: '10px 24px', fontSize: 14 }}
        >
          Chọn người dùng
        </button>
        <UserPicker open={pickerOpen} onClose={() => setPickerOpen(false)} />
      </div>
    )
  }

  const user = targetUser || me
  const bg = user?.avatar?.color || '#3b82f6'
  const emoji = user?.avatar?.emoji || '👤'

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto', padding: '32px 24px' }}>
      {/* Profile Card */}
      <div style={{
        background: 'var(--n-surface)',
        border: '1px solid var(--n-line)',
        borderRadius: 16,
        padding: 28,
        marginBottom: 36,
        boxShadow: '0 8px 24px rgba(0,0,0,0.2)',
      }}>
        {loading && !user ? (
          <div style={{ textAlign: 'center', padding: '24px 0', color: 'var(--n-ink-2)' }}>
            <Spinner /> Đang tải thông tin...
          </div>
        ) : (
          <div>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
                <span
                  style={{
                    width: 72,
                    height: 72,
                    borderRadius: '50%',
                    background: bg,
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 36,
                    boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
                    flexShrink: 0,
                  }}
                >
                  {emoji}
                </span>

                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0, color: 'var(--n-ink)' }}>
                      {user?.display_name || user?.handle}
                    </h1>
                    {isMe && (
                      <span style={{
                        fontSize: 11,
                        padding: '2px 8px',
                        background: 'var(--n-accent-wash)',
                        color: 'var(--n-accent)',
                        borderRadius: 12,
                        fontWeight: 600,
                      }}>
                        Tài khoản của bạn
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 14, color: 'var(--n-ink-2)', margin: '4px 0 0 0' }}>
                    @{user?.handle} {user?.role ? `· Vai trò: ${user.role}` : ''}
                  </div>
                </div>
              </div>

              {isMe && !editing && (
                <button
                  type="button"
                  className="n-btn sm"
                  onClick={() => setEditing(true)}
                  style={{ fontSize: 13 }}
                >
                  ✎ Chỉnh sửa hồ sơ
                </button>
              )}
            </div>

            {/* Bio / Edit section */}
            <div style={{ marginTop: 20, paddingTop: 18, borderTop: '1px solid var(--n-line-soft)' }}>
              {editing ? (
                <form onSubmit={handleSaveProfile} style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 520 }}>
                  {editErr && <div className="n-err" style={{ fontSize: 12 }}>{editErr}</div>}
                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--n-ink-2)', marginBottom: 4 }}>
                      Tên hiển thị:
                    </label>
                    <input
                      type="text"
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      maxLength={40}
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        borderRadius: 6,
                        background: 'var(--n-surface-2)',
                        border: '1px solid var(--n-line)',
                        color: 'inherit',
                        fontSize: 13,
                      }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: 12, color: 'var(--n-ink-2)', marginBottom: 4 }}>
                      Giới thiệu ngắn (bio):
                    </label>
                    <textarea
                      value={editBio}
                      onChange={(e) => setEditBio(e.target.value)}
                      maxLength={200}
                      rows={2}
                      style={{
                        width: '100%',
                        padding: '8px 10px',
                        borderRadius: 6,
                        background: 'var(--n-surface-2)',
                        border: '1px solid var(--n-line)',
                        color: 'inherit',
                        fontSize: 13,
                        resize: 'none',
                      }}
                    />
                  </div>

                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      type="submit"
                      className="n-btn primary sm"
                      disabled={editSaving}
                      style={{ background: '#7c3aed', borderColor: '#7c3aed' }}
                    >
                      {editSaving ? 'Đang lưu...' : 'Lưu thay đổi'}
                    </button>
                    <button
                      type="button"
                      className="n-btn sm"
                      onClick={() => setEditing(false)}
                      disabled={editSaving}
                    >
                      Huỷ
                    </button>
                  </div>
                </form>
              ) : (
                <div style={{ fontSize: 14, color: user?.bio ? 'var(--n-ink)' : 'var(--n-ink-2)', fontStyle: user?.bio ? 'normal' : 'italic' }}>
                  {user?.bio || 'Chưa cập nhật giới thiệu cá nhân.'}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Strategies Overview section */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 700, margin: 0, color: 'var(--n-ink)' }}>
              Thống kê danh mục ({strategies.length} chiến lược đã lưu)
            </h2>
            <p style={{ margin: '4px 0 0 0', fontSize: 13, color: 'var(--n-ink-2)' }}>
              {isMe ? 'Chỉ số tổng quan và phân bổ hiệu suất từ toàn bộ các chiến lược trong không gian cá nhân.' : `Chỉ số tổng hợp các chiến lược của @${user?.handle || ''}`}
            </p>
          </div>

          <Link
            to="/edu/studio"
            className="n-btn primary sm"
            style={{ background: '#7c3aed', borderColor: '#7c3aed', fontSize: 13, textDecoration: 'none' }}
          >
            + Viết chiến lược mới
          </Link>
        </div>

        {error && <div className="n-err" style={{ marginBottom: 16 }}>{error}</div>}

        {loading ? (
          <div style={{ textAlign: 'center', padding: '48px 0', color: 'var(--n-ink-2)' }}>
            <Spinner /> Đang tải dữ liệu tổng quan...
          </div>
        ) : strategies.length === 0 ? (
          <div style={{
            textAlign: 'center',
            padding: '48px 24px',
            background: 'var(--n-surface-2)',
            border: '1px dashed var(--n-line)',
            borderRadius: 12,
            color: 'var(--n-ink-2)',
          }}>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⚡</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--n-ink)', marginBottom: 6 }}>
              Chưa có chiến lược nào
            </div>
            <p style={{ fontSize: 13, maxWidth: 440, margin: '0 auto 16px auto', color: 'var(--n-ink-2)' }}>
              {isMe ? 'Bạn chưa lưu chiến lược nào. Hãy bắt đầu viết và chạy backtest thử nghiệm trong Studio!' : 'Người dùng này chưa xuất bản chiến lược nào.'}
            </p>
            {isMe && (
              <Link
                to="/edu/studio"
                className="n-btn primary sm"
                style={{ background: '#7c3aed', borderColor: '#7c3aed', textDecoration: 'none' }}
              >
                Mở Studio →
              </Link>
            )}
          </div>
        ) : stats && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            {/* KPI Cards Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
              {/* 1. Lợi nhuận trung bình */}
              <div style={{
                background: 'var(--n-surface-2)',
                border: '1px solid var(--n-line)',
                borderRadius: 14,
                padding: '20px 18px',
                boxShadow: '0 4px 14px rgba(0,0,0,0.1)',
              }}>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)', marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Lợi Nhuận Trung Bình</span>
                  <span style={{ fontSize: 16 }}>📈</span>
                </div>
                <div style={{
                  fontSize: 24,
                  fontWeight: 700,
                  color: stats.avgReturn >= 0 ? 'var(--n-pos)' : 'var(--n-neg)',
                  marginBottom: 6,
                }}>
                  {stats.avgReturn >= 0 ? '+' : ''}{stats.avgReturn.toFixed(1)}%
                </div>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>
                  Cao nhất: <span style={{ color: 'var(--n-pos)', fontWeight: 600 }}>{stats.maxReturn !== null ? `${stats.maxReturn >= 0 ? '+' : ''}${stats.maxReturn.toFixed(1)}%` : '—'}</span>
                </div>
              </div>

              {/* 2. MDD Trung bình */}
              <div style={{
                background: 'var(--n-surface-2)',
                border: '1px solid var(--n-line)',
                borderRadius: 14,
                padding: '20px 18px',
                boxShadow: '0 4px 14px rgba(0,0,0,0.1)',
              }}>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)', marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Sụt Giảm Tối Đa (TB)</span>
                  <span style={{ fontSize: 16 }}>🛡️</span>
                </div>
                <div style={{
                  fontSize: 24,
                  fontWeight: 700,
                  color: 'var(--n-warn)',
                  marginBottom: 6,
                }}>
                  {stats.avgMdd.toFixed(1)}%
                </div>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>
                  Thấp nhất: <span style={{ color: 'var(--n-ink)', fontWeight: 600 }}>{stats.minMdd !== null ? `${stats.minMdd.toFixed(1)}%` : '—'}</span>
                </div>
              </div>

              {/* 3. Sharpe Ratio TB */}
              <div style={{
                background: 'var(--n-surface-2)',
                border: '1px solid var(--n-line)',
                borderRadius: 14,
                padding: '20px 18px',
                boxShadow: '0 4px 14px rgba(0,0,0,0.1)',
              }}>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)', marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Chỉ Số Sharpe (TB)</span>
                  <span style={{ fontSize: 16 }}>⭐</span>
                </div>
                <div style={{
                  fontSize: 24,
                  fontWeight: 700,
                  color: 'var(--n-ink)',
                  marginBottom: 6,
                }}>
                  {stats.avgSharpe.toFixed(2)}
                </div>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>
                  Tốt nhất: <span style={{ color: 'var(--n-ink)', fontWeight: 600 }}>{stats.maxSharpe !== null ? stats.maxSharpe.toFixed(2) : '—'}</span>
                </div>
              </div>

              {/* 4. Tỷ lệ chiến lược có lãi */}
              <div style={{
                background: 'var(--n-surface-2)',
                border: '1px solid var(--n-line)',
                borderRadius: 14,
                padding: '20px 18px',
                boxShadow: '0 4px 14px rgba(0,0,0,0.1)',
              }}>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)', marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Tỷ Lệ Sinh Lời</span>
                  <span style={{ fontSize: 16 }}>🎯</span>
                </div>
                <div style={{
                  fontSize: 24,
                  fontWeight: 700,
                  color: stats.profitableRatio >= 50 ? 'var(--n-pos)' : 'var(--n-warn)',
                  marginBottom: 6,
                }}>
                  {stats.profitableRatio.toFixed(0)}%
                </div>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>
                  {stats.profitableCount}/{stats.count} chiến lược có lãi
                </div>
              </div>

              {/* 5. Tổng số lệnh & Win rate TB */}
              <div style={{
                background: 'var(--n-surface-2)',
                border: '1px solid var(--n-line)',
                borderRadius: 14,
                padding: '20px 18px',
                boxShadow: '0 4px 14px rgba(0,0,0,0.1)',
              }}>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)', marginBottom: 8, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span>Tổng Lệnh Khớp</span>
                  <span style={{ fontSize: 16 }}>⚡</span>
                </div>
                <div style={{
                  fontSize: 24,
                  fontWeight: 700,
                  color: 'var(--n-ink)',
                  marginBottom: 6,
                }}>
                  {stats.totalTrades.toLocaleString('vi-VN')}
                </div>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>
                  Win rate lệnh: <span style={{ color: 'var(--n-ink)', fontWeight: 600 }}>{stats.avgWinRate !== null ? `${stats.avgWinRate.toFixed(1)}%` : '—'}</span>
                </div>
              </div>
            </div>

            {/* Detailed Portfolio Breakdown / Health Matrix */}
            <div style={{
              background: 'var(--n-surface-2)',
              border: '1px solid var(--n-line)',
              borderRadius: 14,
              padding: 24,
              boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
            }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 16px 0', color: 'var(--n-ink)' }}>
                Phân Bổ & Tiêu Chuẩn Chất Lượng Danh Mục
              </h3>

              {/* Progress Bar: Profitable vs Loss strategies */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 6 }}>
                  <span style={{ color: 'var(--n-pos)', fontWeight: 600 }}>
                    Sinh lời: {stats.profitableCount} chiến lược ({stats.profitableRatio.toFixed(0)}%)
                  </span>
                  <span style={{ color: 'var(--n-neg)', fontWeight: 600 }}>
                    Thua lỗ: {stats.count - stats.profitableCount} chiến lược ({(100 - stats.profitableRatio).toFixed(0)}%)
                  </span>
                </div>
                <div style={{ width: '100%', height: 8, background: 'var(--n-surface)', borderRadius: 4, overflow: 'hidden', display: 'flex' }}>
                  <div style={{ width: `${stats.profitableRatio}%`, background: 'var(--n-pos)', transition: 'width 0.3s ease' }} />
                  <div style={{ width: `${100 - stats.profitableRatio}%`, background: 'var(--n-neg)', transition: 'width 0.3s ease' }} />
                </div>
              </div>

              {/* Parameter Distribution Table / 2 columns */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20, paddingTop: 16, borderTop: '1px solid var(--n-line-soft)' }}>
                {/* Cột 1: Thông số hiệu suất */}
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--n-ink)', marginBottom: 12 }}>
                    Hiệu Suất Tổng Thể
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-ink-2)' }}>Tổng số chiến lược đã lưu:</span>
                      <span style={{ fontWeight: 600, color: 'var(--n-ink)' }}>{stats.count}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-ink-2)' }}>Biên độ lợi nhuận:</span>
                      <span style={{ fontWeight: 600, color: 'var(--n-ink)' }}>
                        {stats.minReturn !== null ? `${stats.minReturn.toFixed(1)}%` : '—'} → {stats.maxReturn !== null ? `+${stats.maxReturn.toFixed(1)}%` : '—'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-ink-2)' }}>Tổng số lệnh mô phỏng:</span>
                      <span style={{ fontWeight: 600, color: 'var(--n-ink)' }}>{stats.totalTrades.toLocaleString('vi-VN')} lệnh</span>
                    </div>
                    {stats.bestStrat && (
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ color: 'var(--n-ink-2)' }}>Chiến lược dẫn đầu:</span>
                        <Link
                          to={`/edu/studio?alpha=${encodeURIComponent(stats.bestStrat.id || stats.bestStrat.alpha_id)}`}
                          style={{ color: '#8b5cf6', fontWeight: 600, textDecoration: 'none', maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          title={stats.bestStrat.name}
                        >
                          {stats.bestStrat.name} →
                        </Link>
                      </div>
                    )}
                  </div>
                </div>

                {/* Cột 2: Tiêu chuẩn rủi ro */}
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--n-ink)', marginBottom: 12 }}>
                    Tiêu Chuẩn Rủi Ro & Ổn Định
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-ink-2)' }}>Biên độ sụt giảm (MDD):</span>
                      <span style={{ fontWeight: 600, color: 'var(--n-warn)' }}>
                        {stats.minMdd !== null ? `${stats.minMdd.toFixed(1)}%` : '—'} → {stats.maxMdd !== null ? `${stats.maxMdd.toFixed(1)}%` : '—'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-ink-2)' }}>Chiến lược đạt chuẩn Sharpe ≥ 1.0:</span>
                      <span style={{ fontWeight: 600, color: 'var(--n-ink)' }}>
                        {stats.highSharpeCount}/{stats.count} ({((stats.highSharpeCount / stats.count) * 100).toFixed(0)}%)
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-ink-2)' }}>Chiến lược kiềm chế MDD ≤ 20%:</span>
                      <span style={{ fontWeight: 600, color: 'var(--n-ink)' }}>
                        {stats.safeMddCount}/{stats.count} ({((stats.safeMddCount / stats.count) * 100).toFixed(0)}%)
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'var(--n-ink-2)' }}>Tỷ lệ thắng lệnh trung bình:</span>
                      <span style={{ fontWeight: 600, color: 'var(--n-ink)' }}>
                        {stats.avgWinRate !== null ? `${stats.avgWinRate.toFixed(1)}%` : '—'}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      <UserPicker open={pickerOpen} onClose={() => setPickerOpen(false)} />
    </div>
  )
}
