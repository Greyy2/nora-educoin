import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiPost, apiGet } from '../../../api'

const SAMPLE_PROMPTS = [
  {
    title: 'EMA 50 & RSI 55 Trend Following',
    text: 'Mua khi giá vượt EMA 50 và RSI > 55, thoát khi cắt xuống',
    symbol: 'BTC-USDT',
    timeframe: '1h',
  },
  {
    title: 'RSI Mean Reversion (Bắt đáy 4h)',
    text: 'Bắt đáy khi RSI < 30 trên khung 4h, chốt lời 3%',
    symbol: 'BTC-USDT',
    timeframe: '4h',
  },
  {
    title: 'Donchian Channel Breakout lọc ATR',
    text: 'Breakout kênh Donchian 20 có lọc ATR',
    symbol: 'BTC-USDT',
    timeframe: '1h',
  },
]

export default function PromptResearchView({ onOpenCode, onSaved }) {
  const navigate = useNavigate()
  const [prompt, setPrompt] = useState(SAMPLE_PROMPTS[0].text)
  const [symbol, setSymbol] = useState('BTC-USDT')
  const [timeframe, setTimeframe] = useState('1h')
  const [side, setSide] = useState('both')

  const [job, setJob] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingStep, setLoadingStep] = useState('')
  const [error, setError] = useState(null)
  const [saveSuccess, setSaveSuccess] = useState(null)
  const [engineInfo, setEngineInfo] = useState(null)

  useEffect(() => {
    let alive = true
    apiGet('/api/studio/research/engine/status')
      .then((res) => {
        if (alive && res) setEngineInfo(res)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // Chỉnh sửa trực tiếp
  const [editFormula, setEditFormula] = useState(false)
  const [formulaJson, setFormulaJson] = useState('')
  const [editCode, setEditCode] = useState(false)
  const [codeText, setCodeText] = useState('')

  // Bước 1: Khởi tạo và sinh ý tưởng
  const handleStartResearch = async () => {
    if (!prompt.trim() || prompt.trim().length < 20) {
      setError('Độ dài prompt phải từ 20 đến 2000 ký tự.')
      return
    }
    setError(null)
    setSaveSuccess(null)
    setLoading(true)
    setLoadingStep('Đang thẩm định prompt & sinh ý tưởng...')
    try {
      const res = await apiPost('/api/studio/research', {
        prompt: prompt.trim(),
        opts: { symbol, timeframe, side },
      })
      setJob(res)
      if (res.state === 'failed') {
        setError(res.error || 'Thẩm định prompt không thành công.')
      }
    } catch (err) {
      setError(err?.message || 'Lỗi khi khởi tạo phiên nghiên cứu.')
    } finally {
      setLoading(false)
      setLoadingStep('')
    }
  }

  // Bước 2 -> 3, 4, 5, 6: Chọn ý tưởng
  const handlePickIdea = async (ideaIndex) => {
    if (!job?.job_id) return
    setError(null)
    setLoading(true)
    setLoadingStep('Đang chuyển ý tưởng thành công thức, sinh code & chạy backtest thật...')
    try {
      const res = await apiPost(`/api/studio/research/${job.job_id}/pick`, {
        idea_index: ideaIndex,
      })
      setJob(res)
      if (res.state === 'failed') {
        setError(res.error || 'Lỗi trong quá trình thực thi.')
      }
    } catch (err) {
      setError(err?.message || 'Lỗi khi chọn ý tưởng.')
    } finally {
      setLoading(false)
      setLoadingStep('')
    }
  }

  // Chạy lại từ bước bất kỳ
  const handleRerun = async (fromStep, edits = {}) => {
    if (!job?.job_id) return
    setError(null)
    setLoading(true)
    setLoadingStep(`Đang chạy lại từ bước ${fromStep}...`)
    try {
      const res = await apiPost(`/api/studio/research/${job.job_id}/rerun`, {
        from_step: fromStep,
        edits,
      })
      setJob(res)
      setEditFormula(false)
      setEditCode(false)
      if (res.state === 'failed') {
        setError(res.error || 'Lỗi khi chạy lại bước.')
      }
    } catch (err) {
      setError(err?.message || 'Lỗi khi chạy lại.')
    } finally {
      setLoading(false)
      setLoadingStep('')
    }
  }

  // Lưu chiến lược
  const handleSave = async () => {
    if (!job?.job_id) return
    setError(null)
    try {
      const res = await apiPost(`/api/studio/research/${job.job_id}/save`, {})
      setSaveSuccess(`Đã lưu chiến lược thành công (ID: ${res.alpha_id})`)
      if (onSaved) onSaved(res)
    } catch (err) {
      setError(err?.message || 'Lỗi lưu chiến lược.')
    }
  }

  // Chuyển sang mode Code
  const handleSwitchToCode = () => {
    const code = job?.steps?.step4?.code
    if (code && onOpenCode) {
      onOpenCode({
        code,
        name: pickedIdea?.name || 'Alpha Prompt Strategy',
        symbol,
        timeframe,
        metrics: job?.steps?.step5?.metrics || null,
        jobId: job?.job_id || null,
      })
    }
  }

  // Chạy Paper/Testnet
  const handleDeployLive = () => {
    const code = job?.steps?.step4?.code
    if (code) {
      navigate('/live/bots?source=custom', { state: { code, symbol, base_frame: timeframe } })
    }
  }

  const s1 = job?.steps?.step1
  const s2 = job?.steps?.step2
  const s3 = job?.steps?.step3
  const s4 = job?.steps?.step4
  const s5 = job?.steps?.step5
  const s6 = job?.steps?.step6
  const pickedIdea = job?.steps?.picked_idea

  const currentStep = job ? job.current_step : 0

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '16px 20px', color: 'var(--n-ink)' }}>
      {/* Tiêu đề & Giới thiệu */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 22, fontWeight: 700, color: 'var(--n-ink)' }}>
            Nora Alpha Research
          </span>
          <span style={{
            fontSize: 11,
            fontWeight: 600,
            padding: '2px 8px',
            borderRadius: 12,
            background: 'var(--n-accent-wash)',
            color: 'var(--n-accent)',
            border: '1px solid var(--n-accent)'
          }}>
            Mô hình Man Group AlphaTrend
          </span>
          {engineInfo?.model && (
            <span style={{
              fontSize: 11,
              fontWeight: 500,
              padding: '2px 9px',
              borderRadius: 12,
              background: 'var(--n-surface-2)',
              color: 'var(--n-ink)',
              border: '1px solid var(--n-line)',
              display: 'inline-flex',
              alignItems: 'center',
              gap: 6
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--n-pos)' }} />
              AI Engine: {engineInfo.model}
            </span>
          )}
        </div>
        <div style={{ fontSize: 13, color: 'var(--n-ink-2)', marginTop: 4 }}>
          Quy trình 6 bước tự động: Ý tưởng tài chính → Công thức toán học → Mã nguồn Nora DSL → Backtest Nautilus thật → Tổng hợp kết luận không bịa số.
        </div>
      </div>

      {/* Thông báo lỗi / Thành công */}
      {error && (
        <div style={{
          padding: '10px 14px',
          marginBottom: 16,
          background: 'var(--n-neg-wash)',
          border: '1px solid var(--n-neg)',
          borderRadius: 8,
          color: 'var(--n-neg)',
          fontSize: 13
        }}>
          ⚠️ {error}
        </div>
      )}
      {saveSuccess && (
        <div style={{
          padding: '10px 14px',
          marginBottom: 16,
          background: 'var(--n-pos-wash)',
          border: '1px solid var(--n-pos)',
          borderRadius: 8,
          color: 'var(--n-pos)',
          fontSize: 13
        }}>
          ✅ {saveSuccess}
        </div>
      )}

      {/* Trạng thái đang tải */}
      {loading && (
        <div style={{
          padding: '12px 16px',
          marginBottom: 16,
          background: 'var(--n-accent-wash)',
          border: '1px solid var(--n-accent)',
          borderRadius: 8,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          color: 'var(--n-accent)',
          fontSize: 13
        }}>
          <span className="n-spin" style={{ display: 'inline-block', width: 14, height: 14, border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%' }} />
          <span>{loadingStep || 'Đang xử lý pipeline...'}</span>
        </div>
      )}

      {/* Danh sách 6 bước dọc */}
      <div style={{ display: 'grid', gap: 18 }}>

        {/* BƯỚC 1: Input Prompt */}
        <div style={{
          background: 'var(--n-surface)',
          border: '1px solid var(--n-line)',
          borderRadius: 12,
          padding: 18,
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                background: currentStep >= 1 ? 'var(--n-accent)' : 'var(--n-surface-2)',
                color: currentStep >= 1 ? 'var(--n-accent-ink)' : 'var(--n-ink-2)',
                width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700
              }}>1</span>
              <span style={{ fontWeight: 600, fontSize: 15 }}>Ý tưởng giao dịch & Thẩm định (Prompt Validation)</span>
            </div>
            {s1 && (
              <span style={{
                fontSize: 11,
                padding: '2px 8px',
                borderRadius: 4,
                background: s1.valid ? 'var(--n-pos-wash)' : 'var(--n-neg-wash)',
                color: s1.valid ? 'var(--n-pos)' : 'var(--n-neg)'
              }}>
                {s1.valid ? 'Hợp lệ' : 'Chưa hợp lệ'}
              </span>
            )}
          </div>

          {/* Ô nhập prompt */}
          <div style={{ display: 'grid', gap: 10 }}>
            <div>
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Nhập ý tưởng chiến lược giao dịch bằng tiếng Việt (20 đến 2000 ký tự)..."
                rows={3}
                style={{
                  width: '100%',
                  background: 'var(--n-surface-2)',
                  border: '1px solid var(--n-line)',
                  borderRadius: 8,
                  padding: '10px 12px',
                  color: 'var(--n-ink)',
                  fontSize: 13.5,
                  fontFamily: 'inherit',
                  resize: 'vertical'
                }}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: prompt.length < 20 ? 'var(--n-neg)' : 'var(--n-ink-3)', marginTop: 4 }}>
                <span>{prompt.length < 20 ? 'Tối thiểu 20 ký tự' : 'Độ dài hợp lệ'}</span>
                <span>{prompt.length} / 2000 ký tự</span>
              </div>
            </div>

            {/* Prompt gợi ý mẫu */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 11.5, color: 'var(--n-ink-2)' }}>Mẫu thử:</span>
              {SAMPLE_PROMPTS.map((p, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => {
                    setPrompt(p.text)
                    setSymbol(p.symbol)
                    setTimeframe(p.timeframe)
                  }}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    borderRadius: 6,
                    padding: '3px 8px',
                    fontSize: 11.5,
                    color: 'var(--n-ink-2)',
                    cursor: 'pointer'
                  }}
                >
                  💡 {p.title}
                </button>
              ))}
            </div>

            {/* Tùy chọn tài sản & khung */}
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 4, flexWrap: 'wrap' }}>
              <label style={{ fontSize: 12, color: 'var(--n-ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                Tài sản:
                <select
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink)',
                    borderRadius: 6,
                    padding: '4px 8px',
                    fontSize: 12
                  }}
                >
                  <option value="BTC-USDT">BTC-USDT</option>
                  <option value="ETH-USDT">ETH-USDT</option>
                  <option value="SOL-USDT">SOL-USDT</option>
                </select>
              </label>

              <label style={{ fontSize: 12, color: 'var(--n-ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                Khung nến:
                <select
                  value={timeframe}
                  onChange={(e) => setTimeframe(e.target.value)}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink)',
                    borderRadius: 6,
                    padding: '4px 8px',
                    fontSize: 12
                  }}
                >
                  <option value="15m">15m</option>
                  <option value="1h">1h</option>
                  <option value="4h">4h</option>
                </select>
              </label>

              <label style={{ fontSize: 12, color: 'var(--n-ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
                Hướng:
                <select
                  value={side}
                  onChange={(e) => setSide(e.target.value)}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink)',
                    borderRadius: 6,
                    padding: '4px 8px',
                    fontSize: 12
                  }}
                >
                  <option value="both">Both (Long & Short)</option>
                  <option value="long">Chỉ Long</option>
                  <option value="short">Chỉ Short</option>
                </select>
              </label>

              <button
                type="button"
                onClick={handleStartResearch}
                disabled={loading || prompt.length < 20}
                style={{
                  marginLeft: 'auto',
                  background: 'var(--n-accent)',
                  color: 'var(--n-accent-ink)',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: 6,
                  padding: '6px 16px',
                  fontSize: 13,
                  cursor: loading || prompt.length < 20 ? 'not-allowed' : 'pointer',
                  opacity: loading || prompt.length < 20 ? 0.6 : 1
                }}
              >
                {loading && !job ? 'Đang khởi chạy...' : '🚀 Bắt đầu nghiên cứu'}
              </button>
            </div>
          </div>
        </div>

        {/* BƯỚC 2: Ý tưởng giao dịch (Idea Generation) */}
        {s2 && (
          <div style={{
            background: 'var(--n-surface)',
            border: '1px solid var(--n-line)',
            borderRadius: 12,
            padding: 18,
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  background: currentStep >= 2 ? 'var(--n-accent)' : 'var(--n-surface-2)',
                  color: currentStep >= 2 ? 'var(--n-accent-ink)' : 'var(--n-ink-2)',
                  width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700
                }}>2</span>
                <span style={{ fontWeight: 600, fontSize: 15 }}>Ý tưởng giao dịch đề xuất ({s2.length} ý tưởng)</span>
              </div>
              <button
                type="button"
                onClick={() => handleRerun(1)}
                disabled={loading}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--n-line)',
                  borderRadius: 6,
                  padding: '3px 10px',
                  fontSize: 11.5,
                  color: 'var(--n-ink-2)',
                  cursor: 'pointer'
                }}
              >
                🔄 Chạy lại bước này
              </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
              {s2.map((idea, idx) => {
                const isSelected = pickedIdea?.name === idea.name
                return (
                  <div
                    key={idx}
                    style={{
                      background: isSelected ? 'var(--n-accent-wash)' : 'var(--n-surface-2)',
                      border: `1px solid ${isSelected ? 'var(--n-accent)' : 'var(--n-line)'}`,
                      borderRadius: 10,
                      padding: 14,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8
                    }}
                  >
                    <div style={{ fontWeight: 600, fontSize: 14, color: isSelected ? 'var(--n-accent)' : 'var(--n-ink)' }}>
                      #{idea.id || idx + 1}: {idea.name}
                    </div>
                    <div style={{ fontSize: 12.5, color: 'var(--n-ink-2)', lineHeight: 1.45 }}>
                      <b>Lý do tài chính:</b> {idea.rationale}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--n-ink-2)', lineHeight: 1.4 }}>
                      <b>Vào lệnh:</b> {idea.entry}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--n-ink-2)', lineHeight: 1.4 }}>
                      <b>Thoát lệnh:</b> {idea.exit}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--n-ink-2)', lineHeight: 1.4 }}>
                      <b>Rủi ro:</b> {idea.risk}
                    </div>

                    <button
                      type="button"
                      onClick={() => handlePickIdea(idx)}
                      disabled={loading}
                      style={{
                        marginTop: 'auto',
                        background: isSelected ? 'var(--n-accent-wash)' : 'var(--n-surface)',
                        border: `1px solid ${isSelected ? 'var(--n-accent)' : 'var(--n-line)'}`,
                        borderRadius: 6,
                        padding: '6px 12px',
                        fontSize: 12.5,
                        fontWeight: 600,
                        color: isSelected ? 'var(--n-accent)' : 'var(--n-ink)',
                        cursor: loading ? 'not-allowed' : 'pointer'
                      }}
                    >
                      {isSelected ? '✓ Đang chọn ý tưởng này' : 'Chọn ý tưởng này →'}
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* BƯỚC 3: Công thức chỉ báo (Formula) */}
        {s3 && (
          <div style={{
            background: 'var(--n-surface)',
            border: '1px solid var(--n-line)',
            borderRadius: 12,
            padding: 18,
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  background: currentStep >= 3 ? 'var(--n-accent)' : 'var(--n-surface-2)',
                  color: currentStep >= 3 ? 'var(--n-accent-ink)' : 'var(--n-ink-2)',
                  width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700
                }}>3</span>
                <span style={{ fontWeight: 600, fontSize: 15 }}>Công thức chỉ báo (Nora Catalog Formula)</span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  onClick={() => {
                    setEditFormula(!editFormula)
                    setFormulaJson(JSON.stringify(s3, null, 2))
                  }}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--n-line)',
                    borderRadius: 6,
                    padding: '3px 10px',
                    fontSize: 11.5,
                    color: 'var(--n-ink-2)',
                    cursor: 'pointer'
                  }}
                >
                  {editFormula ? 'Hủy sửa' : '✏️ Sửa công thức'}
                </button>
                <button
                  type="button"
                  onClick={() => handleRerun(3)}
                  disabled={loading}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--n-line)',
                    borderRadius: 6,
                    padding: '3px 10px',
                    fontSize: 11.5,
                    color: 'var(--n-ink-2)',
                    cursor: 'pointer'
                  }}
                >
                  🔄 Chạy lại bước này
                </button>
              </div>
            </div>

            {editFormula ? (
              <div style={{ display: 'grid', gap: 10 }}>
                <textarea
                  value={formulaJson}
                  onChange={(e) => setFormulaJson(e.target.value)}
                  rows={8}
                  style={{
                    width: '100%',
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    borderRadius: 6,
                    padding: 10,
                    color: 'var(--n-ink)',
                    fontFamily: 'monospace',
                    fontSize: 12
                  }}
                />
                <button
                  type="button"
                  onClick={() => {
                    try {
                      const parsed = JSON.parse(formulaJson)
                      handleRerun(3, { formula: parsed })
                    } catch (e) {
                      alert('JSON không hợp lệ: ' + e.message)
                    }
                  }}
                  style={{
                    background: 'var(--n-accent)',
                    color: 'var(--n-accent-ink)',
                    fontWeight: 600,
                    border: 'none',
                    borderRadius: 6,
                    padding: '6px 14px',
                    fontSize: 12.5,
                    cursor: 'pointer',
                    justifySelf: 'start'
                  }}
                >
                  Lưu & Chạy lại từ công thức này
                </button>
              </div>
            ) : (
              <div style={{ display: 'grid', gap: 10 }}>
                <div style={{ fontSize: 13, color: 'var(--n-ink)', lineHeight: 1.5 }}>
                  {s3.description_vi}
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span style={{ fontSize: 11.5, color: 'var(--n-ink-2)' }}>Chỉ báo danh mục:</span>
                  {(s3.indicators || []).map((ind, i) => (
                    <span
                      key={i}
                      style={{
                        background: 'var(--n-accent-wash)',
                        border: '1px solid var(--n-accent)',
                        borderRadius: 6,
                        padding: '2px 8px',
                        fontSize: 11.5,
                        color: 'var(--n-accent)',
                        fontFamily: 'monospace'
                      }}
                    >
                      {ind.name}({Object.entries(ind.params || {}).map(([k, v]) => `${k}=${v}`).join(', ')})
                    </span>
                  ))}
                </div>
                <div style={{
                  background: 'var(--n-surface-2)',
                  border: '1px solid var(--n-line)',
                  borderRadius: 6,
                  padding: '8px 12px',
                  fontSize: 12,
                  fontFamily: 'monospace'
                }}>
                  <div><b>Entry:</b> {s3.entry_rule}</div>
                  <div><b>Exit:</b> {s3.exit_rule}</div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* BƯỚC 4: Mã nguồn chiến lược (Code Nora DSL) */}
        {s4 && (
          <div style={{
            background: 'var(--n-surface)',
            border: '1px solid var(--n-line)',
            borderRadius: 12,
            padding: 18,
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  background: currentStep >= 4 ? 'var(--n-accent)' : 'var(--n-surface-2)',
                  color: currentStep >= 4 ? 'var(--n-accent-ink)' : 'var(--n-ink-2)',
                  width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700
                }}>4</span>
                <span style={{ fontWeight: 600, fontSize: 15 }}>Mã nguồn chiến lược (Nora DSL Code)</span>
                <span style={{
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 4,
                  background: 'var(--n-accent-wash)',
                  color: 'var(--n-accent)'
                }}>
                  Biên dịch: {s4.route?.engine === 'native' ? 'Nautilus native' : 'Nora DSL'}
                </span>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  onClick={() => {
                    setEditCode(!editCode)
                    setCodeText(s4.code)
                  }}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--n-line)',
                    borderRadius: 6,
                    padding: '3px 10px',
                    fontSize: 11.5,
                    color: 'var(--n-ink-2)',
                    cursor: 'pointer'
                  }}
                >
                  {editCode ? 'Hủy sửa' : '✏️ Sửa mã nguồn'}
                </button>
                <button
                  type="button"
                  onClick={handleSwitchToCode}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-accent)',
                    borderRadius: 6,
                    padding: '3px 10px',
                    fontSize: 11.5,
                    color: 'var(--n-accent)',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  📝 Mở trong mode Code
                </button>
                <button
                  type="button"
                  onClick={() => handleRerun(4)}
                  disabled={loading}
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--n-line)',
                    borderRadius: 6,
                    padding: '3px 10px',
                    fontSize: 11.5,
                    color: 'var(--n-ink-2)',
                    cursor: 'pointer'
                  }}
                >
                  🔄 Chạy lại bước này
                </button>
              </div>
            </div>

            {editCode ? (
              <div style={{ display: 'grid', gap: 10 }}>
                <textarea
                  value={codeText}
                  onChange={(e) => setCodeText(e.target.value)}
                  rows={14}
                  style={{
                    width: '100%',
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    borderRadius: 6,
                    padding: 10,
                    color: 'var(--n-ink)',
                    fontFamily: 'monospace',
                    fontSize: 12
                  }}
                />
                <button
                  type="button"
                  onClick={() => handleRerun(4, { code: codeText })}
                  style={{
                    background: 'var(--n-accent)',
                    color: 'var(--n-accent-ink)',
                    fontWeight: 600,
                    border: 'none',
                    borderRadius: 6,
                    padding: '6px 14px',
                    fontSize: 12.5,
                    cursor: 'pointer',
                    justifySelf: 'start'
                  }}
                >
                  Biên dịch & Chạy lại với mã này
                </button>
              </div>
            ) : (
              <pre style={{
                background: 'var(--n-surface-2)',
                border: '1px solid var(--n-line)',
                borderRadius: 8,
                padding: '12px 14px',
                fontSize: 12,
                fontFamily: 'monospace',
                overflowX: 'auto',
                color: 'var(--n-ink)',
                maxHeight: 280
              }}>
                {s4.code}
              </pre>
            )}
          </div>
        )}

        {/* BƯỚC 5: Kết quả Backtest thật (Nautilus Trader) */}
        {s5 && (
          <div style={{
            background: 'var(--n-surface)',
            border: '1px solid var(--n-line)',
            borderRadius: 12,
            padding: 18,
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{
                  background: currentStep >= 5 ? 'var(--n-accent)' : 'var(--n-surface-2)',
                  color: currentStep >= 5 ? 'var(--n-accent-ink)' : 'var(--n-ink-2)',
                  width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700
                }}>5</span>
                <span style={{ fontWeight: 600, fontSize: 15 }}>Kết quả Backtest Nautilus Trader ({symbol} · {timeframe})</span>
              </div>
              <button
                type="button"
                onClick={() => handleRerun(5)}
                disabled={loading}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--n-line)',
                  borderRadius: 6,
                  padding: '3px 10px',
                  fontSize: 11.5,
                  color: 'var(--n-ink-2)',
                  cursor: 'pointer'
                }}
              >
                🔄 Chạy lại Backtest
              </button>
            </div>

            {/* Bảng chỉ số metrics */}
            {s5.metrics ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10 }}>
                <div style={{ background: 'var(--n-surface-2)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--n-line)' }}>
                  <div style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>Tổng Lãi (Return)</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: (s5.metrics.total_return || 0) >= 0 ? 'var(--n-pos)' : 'var(--n-neg)' }}>
                    {((s5.metrics.total_return || 0) * 100).toFixed(2)}%
                  </div>
                </div>

                <div style={{ background: 'var(--n-surface-2)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--n-line)' }}>
                  <div style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>Max Drawdown</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--n-neg)' }}>
                    {(Math.abs(s5.metrics.max_drawdown || 0) * (Math.abs(s5.metrics.max_drawdown || 0) > 1 ? 1 : 100)).toFixed(2)}%
                  </div>
                </div>

                <div style={{ background: 'var(--n-surface-2)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--n-line)' }}>
                  <div style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>Sharpe Ratio</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: (s5.metrics.sharpe_ratio || 0) >= 0.5 ? 'var(--n-pos)' : 'var(--n-ink)' }}>
                    {(s5.metrics.sharpe_ratio || 0).toFixed(2)}
                  </div>
                </div>

                <div style={{ background: 'var(--n-surface-2)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--n-line)' }}>
                  <div style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>Win Rate</div>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>
                    {((s5.metrics.win_rate || 0) * 100).toFixed(1)}%
                  </div>
                </div>

                <div style={{ background: 'var(--n-surface-2)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--n-line)' }}>
                  <div style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>Số lệnh (Trades)</div>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>
                    {s5.metrics.total_trades || 0}
                  </div>
                </div>

                <div style={{ background: 'var(--n-surface-2)', padding: '10px 12px', borderRadius: 8, border: '1px solid var(--n-line)' }}>
                  <div style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>So với Buy & Hold</div>
                  <div style={{
                    fontSize: 16,
                    fontWeight: 700,
                    color: (s5.metrics.total_return || 0) > ((s5.benchmark?.total_return) || 0) ? 'var(--n-pos)' : 'var(--n-neg)'
                  }}>
                    {((s5.metrics.total_return || 0) - ((s5.benchmark?.total_return) || 0) >= 0 ? '+' : '')}
                    {(((s5.metrics.total_return || 0) - ((s5.benchmark?.total_return) || 0)) * 100).toFixed(2)}%
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 13, color: 'var(--n-ink-2)' }}>Đang cập nhật chỉ số...</div>
            )}
          </div>
        )}

        {/* BƯỚC 6: Tổng hợp & Kết luận (Synthesis & Actions) */}
        {s6 && (
          <div style={{
            background: 'var(--n-surface)',
            border: `2px solid ${s6.verdict === 'đạt' ? 'var(--n-pos)' : 'var(--n-neg)'}`,
            borderRadius: 12,
            padding: 20,
            boxShadow: '0 4px 16px rgba(0,0,0,0.15)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{
                  background: 'var(--n-accent)',
                  color: 'var(--n-accent-ink)',
                  width: 24, height: 24, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700
                }}>6</span>
                <span style={{ fontWeight: 700, fontSize: 16 }}>Đánh giá & Kết luận Alpha (Synthesis)</span>
              </div>
              <span style={{
                fontSize: 13,
                fontWeight: 700,
                padding: '4px 12px',
                borderRadius: 20,
                background: s6.verdict === 'đạt' ? 'var(--n-pos-wash)' : 'var(--n-neg-wash)',
                color: s6.verdict === 'đạt' ? 'var(--n-pos)' : 'var(--n-neg)',
                border: `1px solid ${s6.verdict === 'đạt' ? 'var(--n-pos)' : 'var(--n-neg)'}`
              }}>
                {s6.verdict === 'đạt' ? '✓ ĐẠT TIÊU CHUẨN' : '✗ CHƯA ĐẠT TIÊU CHUẨN'}
              </span>
            </div>

            {/* Tiêu chí kiểm định code-calculated */}
            {s6.criteria && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
                {Object.entries(s6.criteria).map(([k, c], i) => (
                  <span
                    key={i}
                    style={{
                      fontSize: 11.5,
                      padding: '3px 8px',
                      borderRadius: 6,
                      background: c.passed ? 'var(--n-pos-wash)' : 'var(--n-neg-wash)',
                      color: c.passed ? 'var(--n-pos)' : 'var(--n-neg)',
                      border: `1px solid ${c.passed ? 'var(--n-pos)' : 'var(--n-neg)'}`
                    }}
                  >
                    {c.passed ? '✓' : '✗'} {k}: {c.val?.toFixed ? c.val.toFixed(2) : c.val} ({c.threshold})
                  </span>
                ))}
              </div>
            )}

            {/* Văn bản tổng hợp */}
            <div style={{
              fontSize: 13.5,
              lineHeight: 1.65,
              color: 'var(--n-ink)',
              background: 'var(--n-surface-2)',
              padding: '12px 16px',
              borderRadius: 8,
              marginBottom: 16
            }}>
              {s6.summary}
            </div>

            {/* Bộ 3 nút hành động */}
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={handleSave}
                style={{
                  background: 'var(--n-accent)',
                  color: 'var(--n-accent-ink)',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: 8,
                  padding: '8px 18px',
                  fontSize: 13,
                  cursor: 'pointer'
                }}
              >
                💾 Lưu chiến lược
              </button>

              <button
                type="button"
                onClick={handleSwitchToCode}
                style={{
                  background: 'var(--n-surface-2)',
                  color: 'var(--n-ink)',
                  border: '1px solid var(--n-line)',
                  fontWeight: 600,
                  borderRadius: 8,
                  padding: '8px 18px',
                  fontSize: 13,
                  cursor: 'pointer'
                }}
              >
                📝 Mở trong mode Code
              </button>

              <button
                type="button"
                onClick={handleDeployLive}
                style={{
                  background: 'var(--n-pos-wash)',
                  color: 'var(--n-pos)',
                  border: '1px solid var(--n-pos)',
                  fontWeight: 600,
                  borderRadius: 8,
                  padding: '8px 18px',
                  fontSize: 13,
                  cursor: 'pointer'
                }}
              >
                ⚡ Chạy Paper / Testnet
              </button>
            </div>
          </div>
        )}

      </div>
    </div>
  )
}
