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

  if (error) return <div style={{ maxWidth: 1100, margin: '0 auto', padding: 24 }}><div className="n-err">{error}</div></div>
  if (!data) return <div style={{ textAlign: 'center', padding: 48 }}><Spinner /></div>
  const owner = data.owner
  const mine = me && owner && me.id === owner.id
  const copy = () => (me ? nav(`/edu/studio?fork=${encodeURIComponent(data.id)}`) : setPickerOpen(true))

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '32px 24px' }}>
      <Link to={owner ? `/edu/u/${encodeURIComponent(owner.handle)}` : '/edu'} style={{ fontSize: 13, color: 'var(--n-ink-2)', textDecoration: 'none' }}>← {owner ? owner.display_name : 'Market'}</Link>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12, margin: '12px 0 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {owner && <Avatar avatar={owner.avatar} size={40} />}
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>{data.name}</h1>
            {owner && <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>@{owner.handle}{data.card?.category ? ` · ${data.card.category}` : ''}</div>}
          </div>
        </div>
        {!mine && <button type="button" className="n-btn primary sm" onClick={copy}>Sao chép về của tôi</button>}
      </div>
      <div style={{ height: 320, border: '1px solid var(--n-line)', borderRadius: 10, overflow: 'hidden', marginBottom: 24 }}>
        <CodeEditor value={data.code || ''} readOnly assist={false} height="100%" label="Code chiến lược (chỉ đọc)" />
      </div>
      {data.result ? <CustomResult result={data.result} explain={false} tourKey="" /> : <div style={{ color: 'var(--n-ink-2)' }}>Chưa có kết quả.</div>}
      <UserPicker open={pickerOpen} onClose={() => setPickerOpen(false)} />
    </div>
  )
}
