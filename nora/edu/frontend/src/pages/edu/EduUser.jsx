import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { eduUserCached, getEduUser } from '../../api'
import { Spinner } from '../../components/ui'
import { fmtNum, isNum } from '../../lib/format'
import { useUser } from '../../meta/UserProvider'
import { Avatar, Stat, cardStyle, usd, pct, spct, tone } from './eduUi'

export default function EduUser() {
  const { handle } = useParams()
  const nav = useNavigate()
  const { me } = useUser()
  const [data, setData] = useState(() => eduUserCached(handle) || null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setData(eduUserCached(handle) || null); setError(null)
    getEduUser(handle).then(setData, (e) => setError(e.message || 'Không tải được hồ sơ'))
  }, [handle])

  if (error) return <div style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}><div className="n-err">{error}</div></div>
  if (!data) return <div style={{ textAlign: 'center', padding: 48 }}><Spinner /></div>
  const { user, summary, strategies } = data
  const isOwner = Boolean(data.is_owner ?? (me && (me.id === user.id || me.handle === user.handle)))

  return (
    <div style={{ maxWidth: 1160, margin: '0 auto', padding: '32px 24px', fontFamily: 'inherit' }}>
      <div style={{ marginBottom: 16 }}>
        <Link to="/market" style={{ fontSize: 13, color: 'var(--n-accent)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
          ← Quay lại Market
        </Link>
      </div>

      {/* Thẻ thông tin Tác giả */}
      <div style={{ ...cardStyle, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 24, marginBottom: 28 }}>
        <Avatar avatar={user.avatar} size={64} />
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--n-ink)', letterSpacing: '-0.01em' }}>{user.display_name}</div>
          <div style={{ fontSize: 13, color: 'var(--n-ink-2)', marginTop: 2 }}>@{user.handle}</div>
          {user.bio && <div style={{ fontSize: 13.5, color: 'var(--n-ink-2)', marginTop: 8, lineHeight: 1.5 }}>{user.bio}</div>}
        </div>
        <div style={{ display: 'flex', gap: 24, background: 'var(--n-surface-2)', padding: '14px 20px', borderRadius: 12, border: '1px solid var(--n-line)' }}>
          <Stat label={isOwner ? "Chiến lược" : "Chiến lược công khai"} value={strategies.length} />
          <div style={{ width: 1, background: 'var(--n-line)' }} />
          <Stat label={isOwner ? "Tổng PnL" : "Lợi nhuận nổi bật"} value={isOwner ? usd(summary.total_pnl_usd) : spct(strategies[0]?.ret_pct)} color={isOwner ? tone(summary.total_pnl_usd) : tone(strategies[0]?.ret_pct)} />
          <div style={{ width: 1, background: 'var(--n-line)' }} />
          <Stat label="Max Drawdown" value={pct(summary.max_mdd_pct)} color={summary.max_mdd_pct != null ? 'var(--n-neg)' : undefined} />
        </div>
      </div>

      {/* Bảng danh sách chiến lược */}
      <div style={{ marginBottom: 16, display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: 'var(--n-ink)' }}>
          {isOwner
            ? `Danh sách thuật toán & chiến lược (${strategies.length})`
            : `Chiến lược nổi bật nhất (${strategies.length})`}
        </h2>
        {!isOwner && (
          <span style={{ fontSize: 12, color: 'var(--n-ink-2)', background: 'var(--n-surface-2)', padding: '4px 10px', borderRadius: 6, border: '1px solid var(--n-line)' }}>
            🔒 Theo quy tắc Market: Người xem chỉ thấy 1 alpha tốt nhất của tác giả khác
          </span>
        )}
      </div>

      {strategies.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 48, background: 'var(--n-surface)', border: '1px dashed var(--n-line)', borderRadius: 16, color: 'var(--n-ink-2)' }}>
          Chưa có chiến lược nào được xuất bản.
        </div>
      ) : (
        <div style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
              <thead>
                <tr style={{ background: 'var(--n-surface-2)', borderBottom: '1px solid var(--n-line)' }}>
                  <th style={{ padding: '12px 18px', fontWeight: 600, color: 'var(--n-ink-2)', fontSize: 12 }}>Chiến lược</th>
                  <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--n-ink-2)', fontSize: 12 }}>Nhóm</th>
                  <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--n-ink-2)', fontSize: 12, textAlign: 'right' }}>Lợi nhuận</th>
                  <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--n-ink-2)', fontSize: 12, textAlign: 'right' }}>Max Drawdown</th>
                  <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--n-ink-2)', fontSize: 12, textAlign: 'right' }}>Sharpe</th>
                  <th style={{ padding: '12px 16px', fontWeight: 600, color: 'var(--n-ink-2)', fontSize: 12, textAlign: 'right' }}>Win Rate</th>
                  <th style={{ padding: '12px 18px', fontWeight: 600, color: 'var(--n-ink-2)', fontSize: 12, textAlign: 'right' }}>Số lệnh</th>
                </tr>
              </thead>
              <tbody>
                {strategies.map((s) => (
                  <tr
                    key={s.id}
                    onClick={() => nav(`/s/${encodeURIComponent(s.id)}`)}
                    style={{
                      cursor: 'pointer',
                      borderBottom: '1px solid var(--n-line-soft)',
                      transition: 'background-color 0.15s ease',
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--n-surface-2)' }}
                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent' }}
                  >
                    <td style={{ padding: '14px 18px', fontWeight: 600, color: 'var(--n-ink)' }}>
                      <Link to={`/s/${encodeURIComponent(s.id)}`} style={{ color: 'inherit', textDecoration: 'none' }}>
                        ⚡ {s.name}
                      </Link>
                    </td>
                    <td style={{ padding: '14px 16px' }}>
                      <span style={{ fontSize: 11.5, padding: '3px 8px', borderRadius: 6, background: 'var(--n-surface-2)', border: '1px solid var(--n-line)', color: 'var(--n-ink-2)' }}>
                        {s.category || 'Mặc định'}
                      </span>
                    </td>
                    <td style={{ padding: '14px 16px', textAlign: 'right', fontWeight: 600, color: tone(s.ret_pct) }}>
                      {spct(s.ret_pct)}
                    </td>
                    <td style={{ padding: '14px 16px', textAlign: 'right', color: s.mdd_pct != null ? 'var(--n-neg)' : 'inherit' }}>
                      {pct(s.mdd_pct)}
                    </td>
                    <td style={{ padding: '14px 16px', textAlign: 'right', fontWeight: 600, color: isNum(s.sharpe) && s.sharpe > 1 ? 'var(--n-accent)' : 'inherit' }}>
                      {isNum(s.sharpe) ? fmtNum(s.sharpe, 2) : '—'}
                    </td>
                    <td style={{ padding: '14px 16px', textAlign: 'right' }}>
                      {pct(s.win_rate, 1)}
                    </td>
                    <td style={{ padding: '14px 18px', textAlign: 'right', color: 'var(--n-ink-2)' }}>
                      {s.trades ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
