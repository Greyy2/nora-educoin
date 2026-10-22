import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { eduUserCached, getEduUser } from '../../api'
import { Spinner } from '../../components/ui'
import { fmtNum, isNum } from '../../lib/format'
import { Avatar, Stat, cardStyle, usd, pct, spct, tone } from './eduUi'

export default function EduUser() {
  const { handle } = useParams()
  const nav = useNavigate()
  const [data, setData] = useState(() => eduUserCached(handle) || null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setData(eduUserCached(handle) || null); setError(null)
    getEduUser(handle).then(setData, (e) => setError(e.message || 'Không tải được hồ sơ'))
  }, [handle])

  if (error) return <div style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}><div className="n-err">{error}</div></div>
  if (!data) return <div style={{ textAlign: 'center', padding: 48 }}><Spinner /></div>
  const { user, summary, strategies } = data
  const th = { textAlign: 'right', padding: '8px 10px', fontSize: 12, color: 'var(--n-ink-2)', fontWeight: 500 }
  const td = { textAlign: 'right', padding: '10px', fontSize: 13, whiteSpace: 'nowrap' }

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>
      <Link to="/edu" style={{ fontSize: 13, color: 'var(--n-ink-2)', textDecoration: 'none' }}>← Market</Link>
      <div style={{ ...cardStyle, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 20, margin: '12px 0 24px' }}>
        <Avatar avatar={user.avatar} size={56} />
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontSize: 20, fontWeight: 700 }}>{user.display_name}</div>
          <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>@{user.handle}</div>
          {user.bio && <div style={{ fontSize: 13, color: 'var(--n-ink-2)', marginTop: 4 }}>{user.bio}</div>}
        </div>
        <div style={{ display: 'flex', gap: 28 }}>
          <Stat label="Chiến lược" value={summary.n_strategies} />
          <Stat label="Tổng PnL" value={usd(summary.total_pnl_usd)} color={tone(summary.total_pnl_usd)} />
          <Stat label="MDD lớn nhất" value={pct(summary.max_mdd_pct)} />
        </div>
      </div>

      {strategies.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, border: '1px dashed var(--n-line)', borderRadius: 12, color: 'var(--n-ink-2)' }}>Chưa có chiến lược nào.</div>
      ) : (
        <div style={{ overflowX: 'auto', ...cardStyle, padding: 4 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: 'left' }}>Chiến lược</th>
                <th style={{ ...th, textAlign: 'left' }}>Nhóm</th>
                <th style={th}>Lãi</th><th style={th}>MDD</th><th style={th}>Sharpe</th><th style={th}>Win</th><th style={th}>Số lệnh</th>
              </tr>
            </thead>
            <tbody>
              {strategies.map((s) => (
                <tr key={s.id} onClick={() => nav(`/edu/s/${encodeURIComponent(s.id)}`)} style={{ cursor: 'pointer', borderTop: '1px solid var(--n-line-soft)' }}>
                  <td style={{ ...td, textAlign: 'left', fontWeight: 600 }}><Link to={`/edu/s/${encodeURIComponent(s.id)}`} style={{ color: 'inherit', textDecoration: 'none' }}>{s.name}</Link></td>
                  <td style={{ ...td, textAlign: 'left', color: 'var(--n-ink-2)' }}>{s.category || '—'}</td>
                  <td style={{ ...td, color: tone(s.ret_pct) }}>{spct(s.ret_pct)}</td>
                  <td style={td}>{pct(s.mdd_pct)}</td>
                  <td style={td}>{isNum(s.sharpe) ? fmtNum(s.sharpe, 2) : '—'}</td>
                  <td style={td}>{pct(s.win_rate, 1)}</td>
                  <td style={td}>{s.trades ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
