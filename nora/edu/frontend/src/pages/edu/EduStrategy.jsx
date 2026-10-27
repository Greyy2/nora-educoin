import React, { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { getEduStrategy } from '../../api'
import { Spinner } from '../../components/ui'
import CodeEditor from '../../components/alpha/studio/CodeEditor'
import CustomResult from '../../components/alpha/studio/CustomResult'
import UserPicker from '../../components/user/UserPicker'
import { useUser } from '../../meta/UserProvider'
import { Avatar } from './eduUi'

export default function EduStrategy() {
  const { id } = useParams()
  const nav = useNavigate()
  const { me } = useUser()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [pickerOpen, setPickerOpen] = useState(false)

  useEffect(() => {
    setData(null); setError(null)
    getEduStrategy(id).then(setData, (e) => setError(e.message || 'Không tải được chiến lược'))
  }, [id])

  if (error) return <div style={{ maxWidth: 1160, margin: '0 auto', padding: 24 }}><div className="n-err">{error}</div></div>
  if (!data) return <div style={{ textAlign: 'center', padding: 48 }}><Spinner /></div>
  const owner = data.owner
  const mine = me && owner && me.id === owner.id
  const copy = () => (me ? nav(`/studio?fork=${encodeURIComponent(data.id)}`) : setPickerOpen(true))

  return (
    <div style={{ maxWidth: 1160, margin: '0 auto', padding: '32px 24px', fontFamily: 'inherit' }}>
      <div style={{ marginBottom: 16 }}>
        <Link to={owner ? `/u/${encodeURIComponent(owner.handle)}` : '/market'} style={{ fontSize: 13, color: 'var(--n-accent)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
          ← {owner ? `Hồ sơ ${owner.display_name}` : 'Quay lại Market'}
        </Link>
      </div>

      <div style={{
        background: 'var(--n-surface)',
        border: '1px solid var(--n-line)',
        borderRadius: 16,
        padding: '20px 24px',
        boxShadow: 'var(--n-shadow)',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        marginBottom: 24,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          {owner && <Avatar avatar={owner.avatar} size={46} />}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, color: 'var(--n-ink)' }}>⚡ {data.name}</h1>
              {data.card?.category && (
                <span style={{ fontSize: 11.5, fontWeight: 600, padding: '3px 8px', borderRadius: 6, background: 'var(--n-surface-2)', border: '1px solid var(--n-line)', color: 'var(--n-ink-2)' }}>
                  {data.card.category}
                </span>
              )}
            </div>
            {owner && (
              <div style={{ fontSize: 12.5, color: 'var(--n-ink-2)', marginTop: 3 }}>
                Tác giả: <Link to={`/u/${encodeURIComponent(owner.handle)}`} style={{ color: 'var(--n-accent)', fontWeight: 500 }}>@{owner.handle}</Link> ({owner.display_name})
              </div>
            )}
          </div>
        </div>

        {!mine && (
          <button
            type="button"
            className="n-btn primary sm"
            onClick={copy}
            style={{ borderRadius: 8, padding: '8px 18px', fontWeight: 600, fontSize: 13, display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <span>✨</span> Sao chép về Studio để chỉnh sửa
          </button>
        )}
      </div>

      <div style={{
        background: 'var(--n-surface)',
        border: '1px solid var(--n-line)',
        borderRadius: 16,
        overflow: 'hidden',
        boxShadow: 'var(--n-shadow)',
        marginBottom: 24,
      }}>
        <div style={{
          padding: '10px 16px',
          background: 'var(--n-surface-2)',
          borderBottom: '1px solid var(--n-line)',
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--n-ink-2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <span>Mã nguồn thuật toán chiến lược (Python / Backtest Engine)</span>
          <span style={{ fontFamily: 'var(--n-mono)', fontSize: 11 }}>Read-Only</span>
        </div>
        <div style={{ height: 320 }}>
          <CodeEditor value={data.code || ''} readOnly assist={false} height="100%" label="Code chiến lược" />
        </div>
      </div>

      {data.result ? (
        <div style={{ background: 'var(--n-surface)', border: '1px solid var(--n-line)', borderRadius: 16, padding: 20, boxShadow: 'var(--n-shadow)' }}>
          <CustomResult result={data.result} explain={false} tourKey="" />
        </div>
      ) : (
        <div style={{ textAlign: 'center', padding: 40, background: 'var(--n-surface)', border: '1px dashed var(--n-line)', borderRadius: 16, color: 'var(--n-ink-2)' }}>
          Chưa có báo cáo kết quả kiểm định cho chiến lược này.
        </div>
      )}

      <UserPicker open={pickerOpen} onClose={() => setPickerOpen(false)} />
    </div>
  )
}
