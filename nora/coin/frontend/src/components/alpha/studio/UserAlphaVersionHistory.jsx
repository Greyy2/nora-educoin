import React, { useEffect, useState } from 'react'
import { getUserAlphaVersions, getUserAlphaVersionCode } from '../../../api'
import { Spinner, ErrorState } from '../../ui'
import { fmtDateTime, fmtNum, fmtPct, fmtSPct } from '../../../lib/format'

/**
 * Hiển thị lịch sử phiên bản của Alpha người dùng, xem & so sánh mã nguồn giữa các phiên bản,
 * (kiểm lại alpha đã gỡ cùng phễu).
 */
export default function UserAlphaVersionHistory({ alphaId, currentVersion, onSelectVersion }) {
  const [versions, setVersions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [selectedVer, setSelectedVer] = useState(null)
  const [verDetail, setVerDetail] = useState(null)
  const [verLoading, setVerLoading] = useState(false)


  async function loadVersions() {
    if (!alphaId) return
    setLoading(true)
    setError(null)
    try {
      const list = await getUserAlphaVersions(alphaId)
      const arr = Array.isArray(list) ? list : []
      // Sắp xếp phiên bản mới nhất lên đầu
      arr.sort((a, b) => (b.version || 1) - (a.version || 1))
      setVersions(arr)
      if (arr.length > 0 && selectedVer === null) {
        setSelectedVer(arr[0].version)
      }
    } catch (e) {
      setError(e.message || 'Không tải được danh sách phiên bản')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadVersions()
  }, [alphaId])

  useEffect(() => {
    if (!alphaId || selectedVer === null) return
    let active = true
    setVerLoading(true)
    getUserAlphaVersionCode(alphaId, selectedVer)
      .then((data) => {
        if (active) setVerDetail(data)
      })
      .catch((err) => {
        if (active) setVerDetail({ error: err.message })
      })
      .finally(() => {
        if (active) setVerLoading(false)
      })
    return () => {
      active = false
    }
  }, [alphaId, selectedVer])

  if (loading) return <div className="n-note"><Spinner /> Đang tải lịch sử phiên bản…</div>
  if (error) return <p className="n-note neg">{error} <button type="button" className="n-btn sm" onClick={loadVersions}>Thử lại</button></p>

  if (!versions.length) {
    return (
      <div className="n-note">
        Chưa có lịch sử phiên bản bổ sung.
      </div>
    )
  }

  const curRec = verDetail
  const testMetrics = curRec?.metrics?.test
  const simMetrics = curRec?.metrics?.simulate

  return (
    <div className="n-user-versions" style={{ marginTop: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
        <h4 style={{ margin: 0 }}>Lịch sử phiên bản ({versions.length})</h4>
      </div>


      {/* Tabs chọn phiên bản */}
      <div className="n-seg" style={{ marginBottom: 10, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {versions.map((v) => {
          const isSelected = selectedVer === v.version
          const isCur = currentVersion && v.version === currentVersion
          return (
            <button
              key={v.version}
              type="button"
              className={`n-btn xs ${isSelected ? 'primary' : ''}`}
              onClick={() => setSelectedVer(v.version)}
            >
              v{v.version} {isCur ? '(hiện tại)' : ''}
            </button>
          )
        })}
      </div>

      {verLoading && <div className="n-note"><Spinner /> Đang tải thông tin v{selectedVer}…</div>}

      {!verLoading && curRec && !curRec.error && (
        <div className="n-vdetail" style={{ background: 'var(--n-subtle, rgba(255,255,255,0.03))', padding: 10, borderRadius: 6, border: '1px solid var(--n-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
            <div>
              <b>{curRec.name || `Phiên bản ${selectedVer}`}</b>
              <div className="n-note mono" style={{ fontSize: 11 }}>
                Mã băm: {curRec.program_hash || '—'} · Lưu lúc: {curRec.saved_at || curRec.updated_at ? fmtDateTime(curRec.saved_at || curRec.updated_at) : '—'}
              </div>
            </div>
            {onSelectVersion && (
              <button
                type="button"
                className="n-btn sm brand"
                onClick={() => onSelectVersion(curRec)}
                title="Nạp code và cấu hình phiên bản này vào trình soạn thảo"
              >
                Nạp v{selectedVer} vào trình soạn
              </button>
            )}
          </div>

          {(testMetrics || simMetrics) && (
            <div style={{ display: 'flex', gap: 12, marginBottom: 8, fontSize: 12 }}>
              {testMetrics?.sharpe != null && <span>Sharpe Test: <b>{fmtNum(testMetrics.sharpe, 2)}</b></span>}
              {simMetrics?.cagr_pct != null && <span>CAGR: <b>{fmtSPct(simMetrics.cagr_pct, 1)}</b></span>}
              {simMetrics?.mdd_pct != null && <span>MDD: <b>{fmtPct(simMetrics.mdd_pct, 1)}</b></span>}
              {simMetrics?.trades != null && <span>Số lệnh: <b>{simMetrics.trades}</b></span>}
            </div>
          )}

          {curRec.code && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--n-muted)', marginBottom: 4 }}>Mã nguồn Python (v{selectedVer}):</div>
              <pre className="mono" style={{ maxHeight: 220, overflow: 'auto', background: 'var(--n-bg-dark, #0d1117)', padding: 8, borderRadius: 4, fontSize: 12, margin: 0 }}>
                <code>{curRec.code}</code>
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
