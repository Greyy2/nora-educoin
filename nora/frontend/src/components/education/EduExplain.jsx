import React, { useState, useEffect, useMemo } from 'react'
import { postExplainStrategy } from '../../api'
import Diagnostics, { InsightList } from '../studio/Diagnostics'
import { fmtNum, fmtPct, fmtSigned, signClass, isNum } from '../../lib/format'
import { EDU_SAMPLES } from './educationSamples'
import '../../styles/education.css'

export default function EduExplain({ draft, result, profile = 'xno', position = null, note = null, staleNote = false, precomputedExplain = null }) {
  const posKey = JSON.stringify(position || {})
  const code = draft?.code || ''
  const [explainData, setExplainData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [explainErr, setExplainErr] = useState(null)

  // Khớp với metadata của mẫu nếu trùng mã
  const sampleMeta = useMemo(() => {
    return EDU_SAMPLES.find((s) => s.name === draft?.name || s.code.trim() === code.trim())
  }, [draft, code])

  // Gọi API /explain khi code hoặc profile thay đổi
  useEffect(() => {
    if (!code) {
      setExplainData(null)
      return
    }
    // Bản chạy sẵn (hash khớp) đã kèm khối explain: dùng luôn, không gọi API
    if (precomputedExplain) {
      setExplainData({ ok: true, profile, ...precomputedExplain })
      setExplainErr(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setExplainErr(null)

    postExplainStrategy(code, profile, position)
      .then((res) => {
        if (cancelled) return
        if (res.ok) {
          setExplainData(res)
          setExplainErr(null)
        } else {
          setExplainErr(res.error?.message || 'Không thể giải thích cấu trúc mã')
        }
      })
      .catch((err) => {
        if (cancelled) return
        setExplainErr(err.message || 'Lỗi kết nối API giải thích')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [code, profile, posKey, precomputedExplain])

  const diag = result?.diagnostics || {}
  const sigAct = diag.signal_activity || {}
  const pnlStruct = diag.pnl_structure || {}
  const mktComp = diag.market_comparison || {}
  const insights = Array.isArray(result?.insights) ? result.insights : []
  const dash = (v, f) => (isNum(v) ? f(v) : '—')

  return (
    <div className="edu-explain-container" style={{ padding: '8px 0', display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* ─── HEADER ─── */}
      <div className="edu-explain-card">
        <div className="edu-explain-header">
          <div className="edu-explain-title-badge">
            {sampleMeta?.category || 'Định lượng thuật toán'} · {sampleMeta?.difficulty || 'Tiêu chuẩn'}
          </div>
          <h2 className="edu-explain-title">{draft?.name || sampleMeta?.name || 'Chiến lược định lượng'}</h2>
          <div className="edu-explain-meta">
            <span className="n-badge">Khung nến: {result?.config?.timeframe || explainData?.indicators?.[0]?.timeframe || 'không có dữ liệu'}</span>
            <span className="n-badge brand">Hồ sơ: {profile === 'xno' ? 'XNO (Chuẩn xnoquant)' : 'Nora Portfolio Engine'}</span>
          </div>
        </div>

        {/* ─── KHỐI 1: Ý TƯỞNG CỐT LÕI ─── */}
        <div className="edu-explain-section">
          <div className="edu-explain-sec-title">
            <span className="edu-icon">💡</span> Khối 1 — Ý tưởng cốt lõi & Cơ sở định lượng
          </div>
          <p className="edu-explain-p">
            {sampleMeta?.summary ||
              'Mô hình định lượng này tự động hóa việc ra quyết định dựa trên các tín hiệu toán học khách quan, loại bỏ hoàn toàn yếu tố cảm xúc. Mục tiêu cốt lõi là khai thác các lợi thế thống kê (xu hướng động lượng, hồi quy về trung bình hoặc mở rộng biến động) để đạt tỷ suất sinh lời vượt trội trên rủi ro.'}
          </p>
        </div>
      </div>

      {/* ─── KHỐI 2: CHIẾN LƯỢC LÀM GÌ (AST API /explain) ─── */}
      <div className="edu-explain-card">
        <div className="edu-explain-section">
          <div className="edu-explain-sec-title">
            <span className="edu-icon">⚙️</span> Khối 2 — Chiến lược làm gì (Giải mã thuật toán từ AST)
          </div>

          {loading && <p className="n-note"><span className="spinner-border spinner-border-sm" /> Đang phân tích cây biểu thức thuật toán…</p>}
          {explainErr && <div className="push-alpha-err">⚠ {explainErr}</div>}

          {explainData && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {/* Cảnh báo cấu trúc nếu có */}
              {explainData.warnings && explainData.warnings.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {explainData.warnings.map((w, idx) => (
                    <div key={idx} className="edu-tip-item" style={{ borderLeftColor: '#f59e0b', color: '#fbbf24', background: 'rgba(245,158,11,.08)' }}>
                      ⚠ {typeof w === 'string' ? w : <><b>{w.title}:</b> {w.desc}</>}
                    </div>
                  ))}
                </div>
              )}

              {/* Danh sách chỉ báo kỹ thuật thực tế */}
              <div>
                <b style={{ fontSize: 13, color: 'var(--n-ink)' }}>Các chỉ báo kỹ thuật đang tính toán:</b>
                {(!explainData.indicators || explainData.indicators.length === 0) ? (
                  <p className="n-note">Không sử dụng chỉ báo kỹ thuật (chỉ giao dịch theo giá đóng cửa/mở cửa trực tiếp).</p>
                ) : (
                  <div className="edu-explain-grid" style={{ marginTop: 6 }}>
                    {explainData.indicators.map((ind, i) => (
                      <div key={i} className="edu-explain-feat-box">
                        <div className="edu-feat-name">{ind.signature}</div>
                        <div style={{ fontSize: 11, color: '#6366f1', fontWeight: 600, marginBottom: 2 }}>{ind.label_vi}</div>
                        <div className="edu-feat-desc">{ind.read_vi || ind.meaning_vi}</div>
                        <div style={{ fontSize: 10.5, color: '#94a3b8', marginTop: 4 }}>
                          Khởi động: {ind.warmup} nến · Nhóm: {ind.category}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Danh sách quy tắc ra quyết định */}
              <div>
                <b style={{ fontSize: 13, color: 'var(--n-ink)' }}>Quy tắc vào / thoát lệnh thực thi:</b>
                {(!explainData.rules || explainData.rules.length === 0) ? (
                  <p className="n-note">Chưa thiết lập quy tắc vị thế qua self.set_positions.</p>
                ) : (
                  <ul className="edu-explain-rules" style={{ marginTop: 6 }}>
                    {explainData.rules.map((r, i) => (
                      <li key={i} style={{ marginBottom: 4 }}>
                        <b>Quy tắc #{i + 1}:</b> {r.action_vi} khi <i>{r.condition_vi}</i>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {/* Cơ chế thực thi theo hồ sơ */}
              <div>
                <b style={{ fontSize: 13, color: 'var(--n-ink)' }}>Cơ chế thực thi & Khớp lệnh ({explainData.profile?.toUpperCase()}):</b>
                <div className="edu-explain-tips" style={{ marginTop: 6 }}>
                  {(explainData.execution || []).map((ex, i) => (
                    <div key={i} className="edu-tip-item">
                      <b>{ex.title}:</b> {ex.desc}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ─── KHỐI 3: THỰC TẾ CHẠY RA SAO (DIAGNOSTICS & INSIGHTS) ─── */}
      <div className="edu-explain-card">
        <div className="edu-explain-section">
          <div className="edu-explain-sec-title">
            <span className="edu-icon">📊</span> Khối 3 — Thực tế chạy ra sao (Đối chiếu số đo & Nhận xét)
          </div>

          {staleNote && !result && <p className="n-note" style={{ color: 'var(--n-warn)' }}>Mã đã khác bản gốc của mẫu nên kết quả chạy sẵn không còn khớp. Bấm “Chạy thử nghiệm” để có kết quả mới.</p>}
          {!result ? (
            <p className="n-note" style={{ margin: '4px 0' }}>
              Chưa có kết quả chạy backtest. Bấm <b>“Chạy backtest”</b> ở thanh bên trái để xem đối chiếu thực tế với thị trường và hệ thống nhận xét tự động.
            </p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {note}
              {/* Thẻ chẩn đoán hiệu suất */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8 }}>
                <div className="metric-box" style={{ background: 'rgba(15,23,42,0.4)', padding: 10, borderRadius: 6, border: '1px solid var(--n-line)' }}>
                  <span className="lbl">Số lệnh giao dịch</span>
                  <span className="val">{dash(sigAct.total_trades, (v) => `${fmtNum(v, 0)} lệnh`)}</span>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>
                    Có vị thế {dash(sigAct.days_in_market_pct, (v) => fmtPct(v, 1))} số ngày · phơi nhiễm TB {dash(sigAct.avg_exposure_pct, (v) => fmtPct(v, 1))}
                  </span>
                </div>
                <div className="metric-box" style={{ background: 'rgba(15,23,42,0.4)', padding: 10, borderRadius: 6, border: '1px solid var(--n-line)' }}>
                  <span className="lbl">Thời gian giữ lệnh TB</span>
                  <span className="val">{dash(sigAct.avg_holding_days, (v) => `${fmtNum(v, 1)} ngày`)}</span>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>Trung vị: {dash(sigAct.median_holding_days, (v) => `${fmtNum(v, 1)} ngày`)}</span>
                </div>
                <div className="metric-box" style={{ background: 'rgba(15,23,42,0.4)', padding: 10, borderRadius: 6, border: '1px solid var(--n-line)' }}>
                  <span className="lbl">Tỷ lệ thắng (theo lệnh)</span>
                  <span className="val">{dash(pnlStruct.win_rate, (v) => fmtPct(v, 1))}</span>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>Payoff: {dash(pnlStruct.payoff, (v) => fmtNum(v, 2))}</span>
                </div>
                <div className="metric-box" style={{ background: 'rgba(15,23,42,0.4)', padding: 10, borderRadius: 6, border: '1px solid var(--n-line)' }}>
                  <span className="lbl">Chênh CAGR so với luôn long</span>
                  <span className={`val ${signClass(mktComp.excess_cagr)}`}>{mktComp.available ? dash(mktComp.excess_cagr, (v) => `${fmtSigned(v, 1)} điểm %/năm`) : '—'}</span>
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>Beta: {mktComp.available ? dash(mktComp.beta, (v) => fmtNum(v, 2)) : '—'}</span>
                </div>
              </div>

              {/* Nhận xét tự động (Insights) */}
              <div>
                <b style={{ fontSize: 13, color: 'var(--n-ink)', display: 'block', marginBottom: 8 }}>
                  Nhận xét định lượng tự động ({insights.length} phát hiện):
                </b>
                {insights.length === 0 ? (
                  <p className="n-note">Không có nhận xét nào được sinh ra cho kết quả này.</p>
                ) : <InsightList insights={insights} />}
              </div>

              <Diagnostics result={result} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
