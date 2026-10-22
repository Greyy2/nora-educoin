import React, { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { eduMarketCached, getEduMarket, prefetchEduUser } from '../../api'
import UserPicker from '../../components/user/UserPicker'
import { useUser } from '../../meta/UserProvider'
import { Avatar, Stat, cardStyle, usd, pct, tone } from './eduUi'

const SORTS = [['pnl', 'Tổng PnL'], ['new', 'Mới nhất'], ['name', 'Tên']]

export default function EduMarket() {
  const { me } = useUser()
  const [rows, setRows] = useState(() => eduMarketCached('pnl')?.users || [])
  const [sort, setSort] = useState('pnl')
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(() => !eduMarketCached('pnl'))
  const [error, setError] = useState(null)
  const [pickerOpen, setPickerOpen] = useState(false)

  const load = async () => {
    const c = eduMarketCached(sort)
    if (c) setRows(c.users || []); else setLoading(true)
    setError(null)
    try { setRows((await getEduMarket(sort))?.users || []) } catch (e) { setError(e.message || 'Không tải được danh sách') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [sort]) // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(() => {
    let list = rows
    if (me?.handle || me?.id) {
      list = list.filter((u) => u.handle !== me.handle && u.id !== me.id)
    }
    const t = q.trim().toLowerCase()
    return t ? list.filter((u) => `${u.display_name} ${u.handle}`.toLowerCase().includes(t)) : list
  }, [rows, q, me])

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 28, fontWeight: 700, margin: 0 }}>Market</h1>
          <p style={{ margin: '6px 0 0', fontSize: 14, color: 'var(--n-ink-2)' }}>Chiến lược của các tác giả, số liệu từ kết quả backtest đã lưu.</p>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <input className="n-input" placeholder="Tìm theo tên" value={q} onChange={(e) => setQ(e.target.value)} style={{ fontSize: 13, width: 160 }} />
          <select className="n-input" value={sort} onChange={(e) => setSort(e.target.value)} style={{ fontSize: 13 }} aria-label="Sắp xếp">
            {SORTS.map(([k, l]) => <option key={k} value={k}>Sắp xếp: {l}</option>)}
          </select>
          {!me && <button type="button" className="n-btn sm" onClick={() => setPickerOpen(true)} style={{ fontSize: 13 }}>Đăng nhập</button>}
          <Link to="/edu/studio" className="n-btn primary sm" style={{ fontSize: 13, textDecoration: 'none' }}>Studio</Link>
        </div>
      </div>

      {error && <div className="n-err" style={{ marginBottom: 16 }}>{error}</div>}
      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
          {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} style={{ ...cardStyle, height: 150, opacity: 0.45, animation: 'pulse 1.2s ease-in-out infinite' }} />)}
          <style>{'@keyframes pulse{50%{opacity:.2}}'}</style>
        </div>
      ) : shown.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '48px 24px', border: '1px dashed var(--n-line)', borderRadius: 12, color: 'var(--n-ink-2)' }}>Chưa có tác giả phù hợp.</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
          {shown.map((u) => (
            <Link key={u.handle} to={`/edu/u/${encodeURIComponent(u.handle)}`} onMouseEnter={() => prefetchEduUser(u.handle)} style={{ ...cardStyle, display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Avatar avatar={u.avatar} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 15, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{u.display_name}</div>
                  <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>@{u.handle}</div>
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
                <Stat label="Chiến lược" value={u.n_strategies} />
                <Stat label="Tổng PnL" value={usd(u.total_pnl_usd)} color={tone(u.total_pnl_usd)} />
                <Stat label="MDD lớn nhất" value={pct(u.max_mdd_pct)} color={u.max_mdd_pct != null ? tone(-1) : undefined} />
              </div>
              <div style={{ fontSize: 12, color: 'var(--n-ink-2)', borderTop: '1px solid var(--n-line-soft)', paddingTop: 10, minHeight: 32, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {u.best ? <>Tốt nhất: <span style={{ color: 'var(--n-ink)' }}>{u.best.name}</span></> : 'Chưa có chiến lược'}
              </div>
            </Link>
          ))}
        </div>
      )}
      <UserPicker open={pickerOpen} onClose={() => { setPickerOpen(false); load() }} />
    </div>
  )
}
