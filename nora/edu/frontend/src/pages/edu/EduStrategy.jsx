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
  const [authorHover, setAuthorHover] = useState(false)

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
    <div style={{ maxWidth: 1160, margin: '0 auto', padding: '24px 20px 48px', fontFamily: 'inherit' }}>
      <style>{`
        .edu-strategy-back-wrap {
          margin-bottom: 14px;
          margin-left: -28px;
        }
        @media (max-width: 1240px) {
          .edu-strategy-back-wrap {
            margin-left: 0;
          }
        }
        .edu-strategy-back-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-size: 13px;
          font-weight: 600;
          color: var(--n-ink-2);
          text-decoration: none;
          padding: 6px 14px;
          border-radius: 8px;
          border: 1px solid var(--n-line);
          background: var(--n-surface);
          transition: all 0.18s cubic-bezier(0.4, 0, 0.2, 1);
          cursor: pointer;
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
        }
        .edu-strategy-back-btn:hover {
          background: var(--n-accent);
          color: #ffffff;
          border-color: var(--n-accent);
          transform: translateX(-3px);
          box-shadow: 0 4px 14px rgba(99, 102, 241, 0.3);
        }
        .edu-strategy-back-btn svg {
          transition: transform 0.18s ease;
        }
        .edu-strategy-back-btn:hover svg {
          transform: translateX(-2px);
        }
        .edu-author-trigger {
          position: relative;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 3px 8px;
          border-radius: 6px;
          text-decoration: none;
          color: var(--n-ink-2);
          transition: all 0.15s ease;
          border: 1px solid transparent;
        }
        .edu-author-trigger:hover {
          background: var(--n-surface-2);
          border-color: var(--n-line);
          color: var(--n-ink);
        }
        .edu-author-trigger:hover .author-name {
          color: var(--n-accent);
        }
        .edu-author-hover-card {
          position: absolute;
          top: calc(100% + 8px);
          left: 0;
          width: 270px;
          background: var(--n-surface);
          border: 1px solid var(--n-line);
          border-radius: 12px;
          padding: 12px 14px;
          box-shadow: 0 12px 32px rgba(0, 0, 0, 0.22), 0 0 0 1px var(--n-line);
          z-index: 50;
          pointer-events: none;
          animation: eduFadeIn 0.18s ease-out;
        }
        @keyframes eduFadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .edu-copy-alpha-btn {
          height: 32px;
          padding: 0 14px;
          font-size: 12.5px;
          font-weight: 600;
          border-radius: 7px;
          display: inline-flex;
          align-items: center;
          gap: 6px;
          cursor: pointer;
          transition: all 0.15s ease;
          box-shadow: 0 2px 8px rgba(99, 102, 241, 0.25);
          white-space: nowrap;
        }
        .edu-copy-alpha-btn:hover {
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
        }
      `}</style>

      {/* Nút Back lệch nhẹ sang bên trái của khối card một chút */}
      <div className="edu-strategy-back-wrap">
        <Link to="/market" className="edu-strategy-back-btn" title="Quay lại Market">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
          <span>Back</span>
        </Link>
      </div>

      {/* Card Header chiến lược */}
      <div style={{
          background: 'var(--n-surface)',
          border: '1px solid var(--n-line)',
          borderRadius: 14,
          padding: '16px 20px',
          boxShadow: 'var(--n-shadow)',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 16,
          marginBottom: 20,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            {owner && (
              <Link
                to={`/u/${encodeURIComponent(owner.handle)}`}
                title={`Hồ sơ tác giả ${owner.display_name}`}
                style={{
                  display: 'inline-block',
                  borderRadius: '50%',
                  transition: 'transform 0.18s ease',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.06)' }}
                onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)' }}
              >
                <Avatar avatar={owner.avatar} size={48} />
              </Link>
            )}
            <div>
              {/* Dòng 1: Tên Alpha nổi bật vừa vặn */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 16, color: '#eab308' }}>⚡</span>
                <h1 style={{
                  fontSize: 18,
                  fontWeight: 700,
                  letterSpacing: '-0.01em',
                  margin: 0,
                  color: 'var(--n-ink)',
                  lineHeight: 1.25,
                }}>
                  {data.name}
                </h1>
                {data.card?.category && (
                  <span style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: '2px 7px',
                    borderRadius: 5,
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink-2)',
                  }}>
                    {data.card.category}
                  </span>
                )}
              </div>

              {/* Dòng 2: Tên tác giả to hơn, rõ ràng, kèm tương tác Hover Card */}
              {owner && (
                <div style={{ marginTop: 6, position: 'relative', display: 'inline-flex', alignItems: 'center' }}>
                  <span style={{ fontSize: 13, color: 'var(--n-ink-3)', marginRight: 4 }}>Tác giả:</span>
                  <Link
                    to={`/u/${encodeURIComponent(owner.handle)}`}
                    className="edu-author-trigger"
                    onMouseEnter={() => setAuthorHover(true)}
                    onMouseLeave={() => setAuthorHover(false)}
                  >
                    <span className="author-name" style={{ fontSize: 14.5, fontWeight: 700 }}>
                      {owner.display_name}
                    </span>
                    <span style={{ fontSize: 13, color: 'var(--n-ink-3)' }}>
                      (@{owner.handle})
                    </span>
                    <span style={{ fontSize: 12, opacity: 0.7, marginLeft: 2 }}>↗</span>
                  </Link>

                  {/* Hover Card nổi bật khi di chuột vào User */}
                  {authorHover && (
                    <div className="edu-author-hover-card">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                        <Avatar avatar={owner.avatar} size={38} />
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div style={{ fontSize: 13.5, fontWeight: 700, color: 'var(--n-ink)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {owner.display_name}
                          </div>
                          <div style={{ fontSize: 11.5, color: 'var(--n-accent)', fontWeight: 500 }}>
                            @{owner.handle}
                          </div>
                        </div>
                      </div>
                      {owner.bio && (
                        <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)', marginBottom: 8, lineHeight: 1.4, maxHeight: 42, overflow: 'hidden' }}>
                          {owner.bio}
                        </div>
                      )}
                      <div style={{
                        paddingTop: 8,
                        borderTop: '1px solid var(--n-line)',
                        fontSize: 11.5,
                        fontWeight: 600,
                        color: 'var(--n-accent)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                      }}>
                        <span>Xem toàn bộ chiến lược</span>
                        <span>→</span>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Nút Copy Alpha nhỏ gọn */}
          {!mine && (
            <button
              type="button"
              className="n-btn primary edu-copy-alpha-btn"
              onClick={copy}
              title="Sao chép thuật toán chiến lược này về Studio"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              <span>Copy Alpha</span>
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

      {data.is_historical_result && data.result && (
        <div style={{
          background: 'rgba(234, 179, 8, 0.08)',
          border: '1px solid rgba(234, 179, 8, 0.3)',
          borderRadius: 14,
          padding: '14px 18px',
          marginBottom: 20,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 12,
          fontSize: 13,
          color: 'var(--n-ink)',
        }}>
          <span style={{ fontSize: 20, lineHeight: 1 }}>ℹ️</span>
          <div>
            <div style={{ fontWeight: 700, color: 'var(--n-warn)' }}>
              Bản ghi kiểm định từ phiên bản lịch sử ({data.metrics_status || 'STALE_SOURCE_CHANGED'})
            </div>
            <div style={{ fontSize: 12, color: 'var(--n-ink-2)', marginTop: 3, lineHeight: 1.5 }}>
              Mã nguồn hiển thị bên trên là bản hiện tại (v{data.current_version ?? 1}).
              Báo cáo kiểm định bên dưới phản ánh kết quả của phiên bản lịch sử
              {data.result_version != null ? ` (v${data.result_version})` : ' (lịch sử không lưu số version)'}
              {data.program_hash ? ` [mã băm: ${data.program_hash.slice(0, 10)}]` : ''}
              {data.run_id ? ` [run: ${data.run_id}]` : ' [run: không xác định]'}.
              Bạn có thể bấm <strong>Copy Alpha</strong> để nạp mã nguồn vào Studio và chạy kiểm định lại với phiên bản mới nhất.
            </div>
          </div>
        </div>
      )}

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
