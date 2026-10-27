import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiPost, apiGet, apiDelete } from '../../../api'

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
  const [activeTab, setActiveTab] = useState('research') // 'research' | 'registry' | 'config'

  // Pipeline state
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

  // Direct edit states in pipeline
  const [editFormula, setEditFormula] = useState(false)
  const [formulaJson, setFormulaJson] = useState('')
  const [editCode, setEditCode] = useState(false)
  const [codeText, setCodeText] = useState('')

  // Registry state
  const [registryAlphas, setRegistryAlphas] = useState([])
  const [loadingRegistry, setLoadingRegistry] = useState(false)
  const [registryFilter, setRegistryFilter] = useState('all') // 'all' | 'tested' | 'validated' | 'rejected' | 'archived'
  const [reviewModalAlpha, setReviewModalAlpha] = useState(null)
  const [reviewDecision, setReviewDecision] = useState('validated')
  const [reviewerName, setReviewerName] = useState('')
  const [reviewNotes, setReviewNotes] = useState('')
  const [submittingReview, setSubmittingReview] = useState(false)
  const [reviewError, setReviewError] = useState(null)
  const [verifyingCitationId, setVerifyingCitationId] = useState(null)
  const [citationErrors, setCitationErrors] = useState({})

  // Config tab state
  const [cfgProvider, setCfgProvider] = useState('heuristics')
  const [cfgModel, setCfgModel] = useState('')
  const [cfgSymbol, setCfgSymbol] = useState('BTC-USDT')
  const [cfgTf, setCfgTf] = useState('1h')
  const [cfgSide, setCfgSide] = useState('both')
  const [validatingCfg, setValidatingCfg] = useState(false)
  const [cfgValidationResult, setCfgValidationResult] = useState(null)
  const [cfgError, setCfgError] = useState(null)

  // Fetch engine status on mount
  useEffect(() => {
    let alive = true
    apiGet('/api/studio/research/engine/status')
      .then((res) => {
        if (alive && res) {
          setEngineInfo(res)
          if (res.active_provider) setCfgProvider(res.active_provider)
          if (res.model) setCfgModel(res.model)
        }
      })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // Load registry when tab switches to 'registry'
  const loadRegistry = async () => {
    setLoadingRegistry(true)
    try {
      const res = await apiGet('/api/studio/research/registry')
      setRegistryAlphas(Array.isArray(res) ? res : res?.prompt_alphas || [])
    } catch (err) {
      setError(err?.message || 'Không thể tải kho Prompt Alpha.')
    } finally {
      setLoadingRegistry(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'registry') {
      loadRegistry()
    }
  }, [activeTab])

  // Sources & Inbox state
  const [sourcesList, setSourcesList] = useState([])
  const [loadingSources, setLoadingSources] = useState(false)
  const [collectingSources, setCollectingSources] = useState(false)
  const [sourcesTypeFilter, setSourcesTypeFilter] = useState('all') // 'all' | 'auto_api' | 'auto_rss' | 'manual'

  const [inboxItems, setInboxItems] = useState([])
  const [inboxStats, setInboxStats] = useState({ new: 0, interesting: 0, promoted: 0, has_card: 0, dismissed: 0, total: 0 })
  const [loadingInbox, setLoadingInbox] = useState(false)
  const [inboxFilterStatus, setInboxFilterStatus] = useState('all')
  const [inboxFilterSource, setInboxFilterSource] = useState('all')
  const [inboxFilterTier, setInboxFilterTier] = useState('all')
  const [inboxFilterMinScore, setInboxFilterMinScore] = useState(0)
  const [inboxSearchQuery, setInboxSearchQuery] = useState('')
  const [promotingItemId, setPromotingItemId] = useState(null)
  const [dismissingFiltered, setDismissingFiltered] = useState(false)

  const loadSources = async () => {
    setLoadingSources(true)
    try {
      const res = await apiGet('/api/studio/research/sources')
      setSourcesList(Array.isArray(res) ? res : [])
    } catch (err) {
      setError(err?.message || 'Không thể tải danh sách nguồn nghiên cứu.')
    } finally {
      setLoadingSources(false)
    }
  }

  const loadInbox = async () => {
    setLoadingInbox(true)
    try {
      const res = await apiGet('/api/studio/research/inbox')
      setInboxItems(res?.items || [])
      if (res?.stats) setInboxStats(res.stats)
    } catch (err) {
      setError(err?.message || 'Không thể tải hộp thư ý tưởng.')
    } finally {
      setLoadingInbox(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'sources') {
      loadSources()
    } else if (activeTab === 'inbox') {
      loadInbox()
    }
  }, [activeTab])

  // Initial load of inbox counts for badges
  useEffect(() => {
    apiGet('/api/studio/research/inbox')
      .then((res) => {
        if (res?.stats) setInboxStats(res.stats)
      })
      .catch(() => {})
  }, [])

  const handleRunCollection = async () => {
    setCollectingSources(true)
    setError(null)
    setSaveSuccess(null)
    try {
      const res = await apiPost('/api/studio/research/sources/collect')
      setSaveSuccess(`✓ Đã hoàn tất chu kỳ thu thập tự động: quét ${res.sources_scanned} nguồn khả dụng lúc ${res.timestamp}.`)
      await loadSources()
      await loadInbox()
    } catch (err) {
      setError(err?.message || 'Lỗi khi kích hoạt thu thập tự động.')
    } finally {
      setCollectingSources(false)
    }
  }

  const handleUpdateInboxStatus = async (itemId, status) => {
    try {
      const res = await apiPost(`/api/studio/research/inbox/${itemId}/status`, { status })
      if (res?.ok) {
        setInboxItems((prev) => prev.map((it) => (it.id === itemId ? { ...it, status } : it)))
        loadInbox()
      }
    } catch (err) {
      setError(err?.message || 'Lỗi khi cập nhật trạng thái mục trong hộp thư.')
    }
  }

  const handlePromoteInboxToCard = async (item) => {
    setPromotingItemId(item.id)
    setError(null)
    try {
      const res = await apiPost(`/api/studio/research/inbox/${item.id}/promote`)
      if (res?.ok && res.prompt_text) {
        setPrompt(res.prompt_text)
        if (res.symbol) setSymbol(res.symbol)
        if (res.timeframe) setTimeframe(res.timeframe)
        if (res.side) setSide(res.side)
        setActiveTab('research')
        setSaveSuccess(`✓ Đã chuẩn hóa Thẻ ý tưởng "${res.name}" theo SCHEMA.md và nạp vào Alpha Prompt! Bạn có thể nhấn "Bắt đầu nghiên cứu" để sinh mã và backtest.`)
        loadInbox()
      }
    } catch (err) {
      setError(err?.message || 'Lỗi khi chuyển đổi mục thành thẻ ý tưởng.')
    } finally {
      setPromotingItemId(null)
    }
  }

  const handleDismissFiltered = async () => {
    setDismissingFiltered(true)
    try {
      const payload = {}
      if (inboxSearchQuery.trim()) payload.q = inboxSearchQuery.trim()
      if (inboxFilterSource !== 'all') payload.source_id = inboxFilterSource
      if (inboxFilterTier !== 'all') payload.tier = inboxFilterTier
      if (inboxFilterMinScore > 0) payload.min_score = Number(inboxFilterMinScore)

      const res = await apiPost('/api/studio/research/inbox/dismiss_filtered', payload)
      setSaveSuccess(`✓ Đã bỏ qua ${res.dismissed_count} mục mới đang lọc.`)
      await loadInbox()
    } catch (err) {
      setError(err?.message || 'Lỗi khi bỏ qua các mục.')
    } finally {
      setDismissingFiltered(false)
    }
  }


  // Pipeline Handlers
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

  const handleSave = async () => {
    if (!job?.job_id) return
    setError(null)
    try {
      const res = await apiPost(`/api/studio/research/${job.job_id}/save`, {})
      setSaveSuccess(`Đã lưu chiến lược vào Kho Prompt Alpha thành công (ID: ${res.alpha_id})`)
      if (onSaved) onSaved(res)
    } catch (err) {
      setError(err?.message || 'Lỗi lưu chiến lược.')
    }
  }

  const handleSwitchToCode = (codeToOpen, meta = {}) => {
    const code = codeToOpen || job?.steps?.step4?.code
    if (code && onOpenCode) {
      onOpenCode({
        code,
        name: meta.name || pickedIdea?.name || 'Alpha Prompt Strategy',
        symbol: meta.symbol || symbol,
        timeframe: meta.timeframe || timeframe,
        metrics: meta.metrics || job?.steps?.step5?.metrics || null,
        jobId: job?.job_id || null,
      })
    }
  }

  const handleDeployLive = (codeToRun, sym, tf) => {
    const code = codeToRun || job?.steps?.step4?.code
    if (code) {
      navigate('/live/bots?source=custom', {
        state: {
          code,
          symbol: sym || symbol,
          base_frame: tf || timeframe,
        },
      })
    }
  }

  // Registry Actions
  const handleOpenReviewModal = (alpha) => {
    setReviewModalAlpha(alpha)
    setReviewDecision(alpha.metrics && (alpha.metrics.total_trades || 0) > 0 ? 'validated' : 'rejected')
    setReviewerName('')
    setReviewNotes('')
    setReviewError(null)
  }

  const handleSubmitReview = async () => {
    if (!reviewModalAlpha) return
    if (!reviewerName.trim()) {
      setReviewError('Vui lòng nhập tên người đánh giá (reviewer).')
      return
    }
    if (!reviewNotes.trim()) {
      setReviewError('Vui lòng nhập ghi chú đánh giá.')
      return
    }
    setSubmittingReview(true)
    setReviewError(null)
    try {
      await apiPost(`/api/studio/research/registry/${reviewModalAlpha.id}/review`, {
        status: reviewDecision,
        reviewer: reviewerName.trim(),
        review_notes: reviewNotes.trim(),
      })
      setReviewModalAlpha(null)
      loadRegistry()
    } catch (err) {
      setReviewError(err?.message || 'Lỗi khi cập nhật đánh giá.')
    } finally {
      setSubmittingReview(false)
    }
  }

  const handleArchiveAlpha = async (alphaId) => {
    try {
      await apiPost(`/api/studio/research/registry/${alphaId}/archive`, {})
      loadRegistry()
    } catch (err) {
      setError(err?.message || 'Lỗi khi lưu trữ alpha.')
    }
  }

  const handleVerifyCitations = async (alphaId) => {
    setVerifyingCitationId(alphaId)
    setCitationErrors((current) => ({ ...current, [alphaId]: null }))
    try {
      const res = await apiPost(`/api/studio/research/registry/${alphaId}/citations/verify`, {})
      setRegistryAlphas((current) => current.map((alpha) => alpha.id === alphaId ? res.record : alpha))
    } catch (err) {
      setCitationErrors((current) => ({ ...current, [alphaId]: err?.message || 'Không thể xác minh citation.' }))
    } finally {
      setVerifyingCitationId(null)
    }
  }

  const handleDeleteAlpha = async (alphaId) => {
    if (!window.confirm('Bạn có chắc muốn xoá Prompt Alpha này không?')) return
    try {
      await apiDelete(`/api/studio/research/registry/${alphaId}`)
      loadRegistry()
    } catch (err) {
      setError(err?.message || 'Lỗi khi xoá alpha.')
    }
  }

  // Config Validator Handler
  const handleValidateConfig = async () => {
    setValidatingCfg(true)
    setCfgError(null)
    setCfgValidationResult(null)
    try {
      const res = await apiPost('/api/studio/research/config/validate', {
        provider: cfgProvider,
        model: cfgModel,
        symbol: cfgSymbol,
        timeframe: cfgTf,
        side: cfgSide,
      })
      setCfgValidationResult(res)
    } catch (err) {
      setCfgError(err?.message || 'Lỗi khi kiểm tra cấu hình.')
    } finally {
      setValidatingCfg(false)
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

  const filteredRegistry = registryAlphas.filter((a) => {
    if (registryFilter === 'all') return true
    return a.status === registryFilter
  })

  return (
    <div style={{ maxWidth: 1040, margin: '0 auto', padding: '16px 20px', color: 'var(--n-ink)' }}>
      {/* Tiêu đề & Giới thiệu */}
      <div style={{ marginBottom: 16 }}>
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
          Quy trình 6 bước chuẩn mực: Ý tưởng tài chính → Công thức toán học → Mã nguồn Nora DSL → Backtest Nautilus thật → Tổng hợp & Cổng đánh giá con người.
        </div>
      </div>

      {/* Tab Switcher */}
      <div style={{
        display: 'flex',
        gap: 8,
        borderBottom: '1px solid var(--n-line)',
        marginBottom: 18,
        paddingBottom: 4
      }}>
        <button
          type="button"
          onClick={() => setActiveTab('research')}
          style={{
            background: activeTab === 'research' ? 'var(--n-surface-2)' : 'transparent',
            border: activeTab === 'research' ? '1px solid var(--n-line)' : 'none',
            borderBottom: activeTab === 'research' ? '2px solid var(--n-accent)' : 'none',
            borderRadius: '6px 6px 0 0',
            padding: '8px 16px',
            fontSize: 13,
            fontWeight: activeTab === 'research' ? 700 : 500,
            color: activeTab === 'research' ? 'var(--n-accent)' : 'var(--n-ink-2)',
            cursor: 'pointer'
          }}
        >
          🔬 Ý tưởng
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('inbox')}
          style={{
            background: activeTab === 'inbox' ? 'var(--n-surface-2)' : 'transparent',
            border: activeTab === 'inbox' ? '1px solid var(--n-line)' : 'none',
            borderBottom: activeTab === 'inbox' ? '2px solid var(--n-accent)' : 'none',
            borderRadius: '6px 6px 0 0',
            padding: '8px 16px',
            fontSize: 13,
            fontWeight: activeTab === 'inbox' ? 700 : 500,
            color: activeTab === 'inbox' ? 'var(--n-accent)' : 'var(--n-ink-2)',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6
          }}
        >
          📥 Hộp thư
          {inboxStats.new > 0 && (
            <span style={{
              background: 'var(--n-accent)',
              color: 'var(--n-accent-ink, #ffffff)',
              fontSize: 10,
              padding: '1px 6px',
              borderRadius: 10,
              fontWeight: 700
            }}>
              {inboxStats.new}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('sources')}
          style={{
            background: activeTab === 'sources' ? 'var(--n-surface-2)' : 'transparent',
            border: activeTab === 'sources' ? '1px solid var(--n-line)' : 'none',
            borderBottom: activeTab === 'sources' ? '2px solid var(--n-accent)' : 'none',
            borderRadius: '6px 6px 0 0',
            padding: '8px 16px',
            fontSize: 13,
            fontWeight: activeTab === 'sources' ? 700 : 500,
            color: activeTab === 'sources' ? 'var(--n-accent)' : 'var(--n-ink-2)',
            cursor: 'pointer'
          }}
        >
          🌐 Nguồn
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('registry')}
          style={{
            background: activeTab === 'registry' ? 'var(--n-surface-2)' : 'transparent',
            border: activeTab === 'registry' ? '1px solid var(--n-line)' : 'none',
            borderBottom: activeTab === 'registry' ? '2px solid var(--n-accent)' : 'none',
            borderRadius: '6px 6px 0 0',
            padding: '8px 16px',
            fontSize: 13,
            fontWeight: activeTab === 'registry' ? 700 : 500,
            color: activeTab === 'registry' ? 'var(--n-accent)' : 'var(--n-ink-2)',
            cursor: 'pointer',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6
          }}
        >
          📚 Kho ý tưởng (Registry)
          {registryAlphas.length > 0 && (
            <span style={{
              background: 'var(--n-surface-3, #334155)',
              color: 'var(--n-ink)',
              fontSize: 10,
              padding: '1px 6px',
              borderRadius: 10,
              fontWeight: 700
            }}>
              {registryAlphas.length}
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('config')}
          style={{
            background: activeTab === 'config' ? 'var(--n-surface-2)' : 'transparent',
            border: activeTab === 'config' ? '1px solid var(--n-line)' : 'none',
            borderBottom: activeTab === 'config' ? '2px solid var(--n-accent)' : 'none',
            borderRadius: '6px 6px 0 0',
            padding: '8px 16px',
            fontSize: 13,
            fontWeight: activeTab === 'config' ? 700 : 500,
            color: activeTab === 'config' ? 'var(--n-accent)' : 'var(--n-ink-2)',
            cursor: 'pointer'
          }}
        >
          ⚙️ Cấu hình
        </button>
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

      {/* ═══════════════════════════════════════════════════════════════════
          TAB 1: NGHIÊN CỨU & PIPELINE (6 BƯỚC)
          ═══════════════════════════════════════════════════════════════════ */}
      {activeTab === 'research' && (
        <>
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

            {/* BƯỚC 2: Ý tưởng giao dịch (Idea Generation & Hypothesis Structure) */}
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
                    <span style={{ fontWeight: 600, fontSize: 15 }}>Ý tưởng giao dịch đề xuất & Giả thuyết phản nghiệm ({s2.length} ý tưởng)</span>
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

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
                  {s2.map((idea, idx) => {
                    const isSelected = pickedIdea?.name === idea.name
                    const hyp = idea.hypothesis || {}
                    const cites = idea.citations || []
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
                        {hyp.economic_mechanism && (
                          <div style={{ fontSize: 12, color: 'var(--n-ink-2)', lineHeight: 1.4, background: 'var(--n-surface)', padding: 6, borderRadius: 6, border: '1px solid var(--n-line)' }}>
                            <b>Cơ chế kinh tế:</b> {hyp.economic_mechanism}
                          </div>
                        )}
                        {hyp.falsifiable_conditions && hyp.falsifiable_conditions.length > 0 && (
                          <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)' }}>
                            <b>Điều kiện phản nghiệm:</b>
                            <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                              {hyp.falsifiable_conditions.map((fc, fci) => (
                                <li key={fci}>{fc}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {hyp.rejection_rules && hyp.rejection_rules.length > 0 && (
                          <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)' }}>
                            <b>Quy tắc bác bỏ:</b>
                            <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                              {hyp.rejection_rules.map((rr, rri) => (
                                <li key={rri}>{rr}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {cites.length > 0 && (
                          <div style={{ fontSize: 11, color: 'var(--n-ink-3)', borderTop: '1px dashed var(--n-line)', paddingTop: 6 }}>
                            <b>Nguồn tham chiếu:</b>{' '}
                            {cites.map((c, ci) => (
                              <a
                                key={ci}
                                href={c.url}
                                target="_blank"
                                rel="noreferrer"
                                style={{ color: 'var(--n-accent)', textDecoration: 'underline', marginRight: 8 }}
                              >
                                {c.title || c.provider}
                              </a>
                            ))}
                          </div>
                        )}
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
                      onClick={() => handleSwitchToCode(s4.code, { name: pickedIdea?.name, symbol, timeframe })}
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
                    💾 Lưu vào Kho Prompt Alpha
                  </button>

                  <button
                    type="button"
                    onClick={() => handleSwitchToCode(s4?.code, { name: pickedIdea?.name, symbol, timeframe })}
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
                    onClick={() => handleDeployLive(s4?.code, symbol, timeframe)}
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
        </>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          TAB 2: KHO PROMPT ALPHA (REGISTRY & HUMAN REVIEW GATE)
          ═══════════════════════════════════════════════════════════════════ */}
      {activeTab === 'registry' && (
        <div style={{ display: 'grid', gap: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 13, color: 'var(--n-ink-2)' }}>Lọc trạng thái:</span>
              {['all', 'tested', 'validated', 'rejected', 'archived'].map((status) => (
                <button
                  key={status}
                  type="button"
                  onClick={() => setRegistryFilter(status)}
                  style={{
                    background: registryFilter === status ? 'var(--n-accent)' : 'var(--n-surface-2)',
                    color: registryFilter === status ? 'var(--n-accent-ink)' : 'var(--n-ink)',
                    border: '1px solid var(--n-line)',
                    borderRadius: 6,
                    padding: '3px 10px',
                    fontSize: 12,
                    fontWeight: registryFilter === status ? 700 : 500,
                    cursor: 'pointer',
                    textTransform: 'capitalize'
                  }}
                >
                  {status === 'all' ? 'Tất cả' : status}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={loadRegistry}
              disabled={loadingRegistry}
              style={{
                background: 'var(--n-surface-2)',
                border: '1px solid var(--n-line)',
                borderRadius: 6,
                padding: '4px 12px',
                fontSize: 12,
                color: 'var(--n-ink)',
                cursor: 'pointer'
              }}
            >
              🔄 Tải lại
            </button>
          </div>

          {loadingRegistry ? (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--n-ink-2)', fontSize: 13 }}>
              Đang tải danh sách Prompt Alpha...
            </div>
          ) : filteredRegistry.length === 0 ? (
            <div style={{
              padding: '36px 20px',
              textAlign: 'center',
              background: 'var(--n-surface-2)',
              borderRadius: 10,
              border: '1px dashed var(--n-line)',
              color: 'var(--n-ink-2)',
              fontSize: 13
            }}>
              Chưa có Prompt Alpha nào {registryFilter !== 'all' ? `với trạng thái "${registryFilter}"` : ''}.
              <br />
              Hãy chuyển sang tab "🔬 Nghiên cứu & Pipeline" để tạo và lưu chiến lược mới.
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 14 }}>
              {filteredRegistry.map((alpha) => {
                const hyp = alpha.hypothesis || {}
                const cites = alpha.citations || []
                const m = alpha.metrics || {}
                const isTested = alpha.status === 'tested'
                const isValidated = alpha.status === 'validated'
                const isRejected = alpha.status === 'rejected'
                const isArchived = alpha.status === 'archived'

                const statusBg = isValidated ? 'var(--n-pos-wash)' : isRejected ? 'var(--n-neg-wash)' : isTested ? 'var(--n-accent-wash)' : 'var(--n-surface-2)'
                const statusColor = isValidated ? 'var(--n-pos)' : isRejected ? 'var(--n-neg)' : isTested ? 'var(--n-accent)' : 'var(--n-ink-2)'

                return (
                  <div
                    key={alpha.id}
                    data-testid={`prompt-alpha-${alpha.id}`}
                    style={{
                      background: 'var(--n-surface)',
                      border: '1px solid var(--n-line)',
                      borderRadius: 10,
                      padding: 16,
                      display: 'grid',
                      gap: 10
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
                      <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                          <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--n-ink)' }}>
                            {alpha.name}
                          </span>
                          <span style={{
                            fontSize: 11,
                            fontWeight: 700,
                            padding: '2px 8px',
                            borderRadius: 12,
                            background: statusBg,
                            color: statusColor,
                            border: `1px solid ${statusColor}`,
                            textTransform: 'uppercase'
                          }}>
                            {alpha.status}
                          </span>
                        </div>
                        <div style={{ fontSize: 12, color: 'var(--n-ink-2)', marginTop: 2 }}>
                          ID: <span style={{ fontFamily: 'monospace' }}>{alpha.id}</span> · {alpha.symbol} · {alpha.timeframe} · {alpha.side} · Tạo: {new Date(alpha.created_at || Date.now()).toLocaleString('vi-VN')}
                        </div>
                      </div>

                      {/* Action buttons */}
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <button
                          type="button"
                          onClick={() => handleOpenReviewModal(alpha)}
                          style={{
                            background: 'var(--n-accent)',
                            color: 'var(--n-accent-ink)',
                            border: 'none',
                            borderRadius: 6,
                            padding: '4px 10px',
                            fontSize: 12,
                            fontWeight: 600,
                            cursor: 'pointer'
                          }}
                        >
                          ⚖️ Đánh giá (Review Gate)
                        </button>
                        <button
                          type="button"
                          onClick={() => handleSwitchToCode(alpha.code, alpha)}
                          style={{
                            background: 'var(--n-surface-2)',
                            border: '1px solid var(--n-line)',
                            borderRadius: 6,
                            padding: '4px 10px',
                            fontSize: 12,
                            color: 'var(--n-ink)',
                            cursor: 'pointer'
                          }}
                        >
                          📝 Sửa Code
                        </button>
                        {!isArchived && (
                          <button
                            type="button"
                            onClick={() => handleArchiveAlpha(alpha.id)}
                            style={{
                              background: 'var(--n-surface-2)',
                              border: '1px solid var(--n-line)',
                              borderRadius: 6,
                              padding: '4px 10px',
                              fontSize: 12,
                              color: 'var(--n-ink-2)',
                              cursor: 'pointer'
                            }}
                          >
                            📦 Lưu trữ
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => handleDeleteAlpha(alpha.id)}
                          style={{
                            background: 'var(--n-neg-wash)',
                            border: '1px solid var(--n-neg)',
                            borderRadius: 6,
                            padding: '4px 10px',
                            fontSize: 12,
                            color: 'var(--n-neg)',
                            cursor: 'pointer'
                          }}
                        >
                          🗑️ Xoá
                        </button>
                      </div>
                    </div>

                    {/* Hypothesis Details */}
                    {hyp.economic_mechanism && (
                      <div style={{ fontSize: 12.5, color: 'var(--n-ink)', background: 'var(--n-surface-2)', padding: 10, borderRadius: 6 }}>
                        <b>Cơ chế kinh tế:</b> {hyp.economic_mechanism}
                      </div>
                    )}

                    {/* Citations */}
                    {cites.length > 0 ? (
                      <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)' }}>
                        <b>Nguồn tham chiếu ({cites.length}):</b>{' '}
                        <button
                          type="button"
                          onClick={() => handleVerifyCitations(alpha.id)}
                          disabled={verifyingCitationId === alpha.id}
                          style={{
                            background: 'var(--n-surface-2)',
                            border: '1px solid var(--n-line)',
                            borderRadius: 6,
                            padding: '3px 8px',
                            color: 'var(--n-ink)',
                            cursor: verifyingCitationId === alpha.id ? 'wait' : 'pointer'
                          }}
                        >
                          {verifyingCitationId === alpha.id ? 'Đang xác minh DOI...' : 'Xác minh DOI với Crossref'}
                        </button>{' '}
                        {cites.map((c, ci) => (
                          <span key={ci} style={{ marginRight: 10 }}>
                            <a
                              href={c.url}
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: 'var(--n-accent)', textDecoration: 'underline' }}
                            >
                              {c.title || c.provider}
                            </a>
                            <span style={{ marginLeft: 4, color: c.verified ? 'var(--n-pos)' : 'var(--n-ink-2)' }}>
                              {c.verified ? '· DOI đã đối chiếu Crossref' : '· Chưa xác minh'}
                            </span>
                          </span>
                        ))}
                        <div style={{ marginTop: 5 }}>Crossref xác minh metadata DOI, không xác minh tính đúng của kết luận nghiên cứu.</div>
                        {citationErrors[alpha.id] && (
                          <div role="alert" style={{ marginTop: 5, color: 'var(--n-neg)' }}>
                            Không xác minh được nguồn: {citationErrors[alpha.id]}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)' }}>
                        Chưa có nguồn tham chiếu; cần citation DOI đã xác minh với Crossref trước khi reviewer có thể phê duyệt.
                      </div>
                    )}

                    {/* Backtest Metrics Banner */}
                    <div style={{
                      display: 'flex',
                      gap: 16,
                      flexWrap: 'wrap',
                      background: 'var(--n-surface-2)',
                      padding: '8px 12px',
                      borderRadius: 6,
                      fontSize: 12
                    }}>
                      <span><b>Lãi:</b> <span style={{ color: (m.total_return || 0) >= 0 ? 'var(--n-pos)' : 'var(--n-neg)', fontWeight: 600 }}>{((m.total_return || 0) * 100).toFixed(2)}%</span></span>
                      <span><b>MDD:</b> <span style={{ color: 'var(--n-neg)', fontWeight: 600 }}>{(Math.abs(m.max_drawdown || 0) * (Math.abs(m.max_drawdown || 0) > 1 ? 1 : 100)).toFixed(2)}%</span></span>
                      <span><b>Sharpe:</b> <span style={{ fontWeight: 600 }}>{(m.sharpe_ratio || 0).toFixed(2)}</span></span>
                      <span><b>Lệnh:</b> <span style={{ fontWeight: 600 }}>{m.total_trades || 0}</span></span>
                      <span><b>Win rate:</b> <span style={{ fontWeight: 600 }}>{((m.win_rate || 0) * 100).toFixed(1)}%</span></span>
                    </div>

                    {/* Review Info if reviewed */}
                    {alpha.reviewed_by && (
                      <div style={{
                        fontSize: 11.5,
                        color: 'var(--n-ink-2)',
                        borderTop: '1px dashed var(--n-line)',
                        paddingTop: 6,
                        display: 'flex',
                        gap: 12,
                        flexWrap: 'wrap'
                      }}>
                        <span><b>Đánh giá bởi:</b> {alpha.reviewed_by}</span>
                        <span><b>Thời gian:</b> {new Date(alpha.reviewed_at).toLocaleString('vi-VN')}</span>
                        {alpha.review_notes && <span><b>Ghi chú:</b> {alpha.review_notes}</span>}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Modal Human Review Gate */}
          {reviewModalAlpha && (
            <div style={{
              position: 'fixed',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              background: 'rgba(0,0,0,0.65)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              zIndex: 9999,
              padding: 16
            }}>
              <div style={{
                background: 'var(--n-surface)',
                border: '1px solid var(--n-line)',
                borderRadius: 12,
                maxWidth: 520,
                width: '100%',
                padding: 22,
                boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                display: 'grid',
                gap: 14
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 700, fontSize: 16 }}>
                    Đánh giá con người: {reviewModalAlpha.name}
                  </span>
                  <button
                    type="button"
                    onClick={() => setReviewModalAlpha(null)}
                    style={{ background: 'transparent', border: 'none', fontSize: 16, cursor: 'pointer', color: 'var(--n-ink)' }}
                  >
                    ✕
                  </button>
                </div>

                <div style={{ fontSize: 12.5, color: 'var(--n-ink-2)', lineHeight: 1.45 }}>
                  Cổng đánh giá con người (Human Review Gate): Alpha chỉ được chuyển sang trạng thái <b>validated</b> khi có citation DOI đã đối chiếu Crossref, backtest thật đủ mẫu và ghi chú OOS rõ ràng. Crossref chỉ xác minh metadata, không xác minh kết luận nghiên cứu.
                </div>

                {reviewError && (
                  <div style={{ padding: '8px 12px', background: 'var(--n-neg-wash)', color: 'var(--n-neg)', borderRadius: 6, fontSize: 12 }}>
                    ⚠️ {reviewError}
                  </div>
                )}

                <label style={{ fontSize: 13, display: 'grid', gap: 6 }}>
                  <b>Quyết định thẩm định:</b>
                  <select
                    value={reviewDecision}
                    onChange={(e) => setReviewDecision(e.target.value)}
                    style={{
                      background: 'var(--n-surface-2)',
                      border: '1px solid var(--n-line)',
                      color: 'var(--n-ink)',
                      padding: '6px 10px',
                      borderRadius: 6
                    }}
                  >
                    <option value="validated">Phê duyệt (Validated) — Đạt tiêu chuẩn đưa vào danh mục</option>
                    <option value="rejected">Bác bỏ (Rejected) — Không đạt hoặc rủi ro cao</option>
                  </select>
                </label>

                <label style={{ fontSize: 13, display: 'grid', gap: 6 }}>
                  <b>Tên người thẩm định (Reviewer):</b>
                  <input
                    type="text"
                    value={reviewerName}
                    onChange={(e) => setReviewerName(e.target.value)}
                    placeholder="VD: Quản lý rủi ro / Nguyễn Văn A"
                    style={{
                      background: 'var(--n-surface-2)',
                      border: '1px solid var(--n-line)',
                      color: 'var(--n-ink)',
                      padding: '6px 10px',
                      borderRadius: 6
                    }}
                  />
                </label>

                <label style={{ fontSize: 13, display: 'grid', gap: 6 }}>
                  <b>Ghi chú & Lý giải đánh giá:</b>
                  <textarea
                    rows={3}
                    value={reviewNotes}
                    onChange={(e) => setReviewNotes(e.target.value)}
                    placeholder="Ghi rõ lý do phê duyệt/bác bỏ, phân tích giả thuyết phản nghiệm..."
                    style={{
                      background: 'var(--n-surface-2)',
                      border: '1px solid var(--n-line)',
                      color: 'var(--n-ink)',
                      padding: '6px 10px',
                      borderRadius: 6,
                      resize: 'vertical'
                    }}
                  />
                </label>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 4 }}>
                  <button
                    type="button"
                    onClick={() => setReviewModalAlpha(null)}
                    style={{
                      background: 'transparent',
                      border: '1px solid var(--n-line)',
                      borderRadius: 6,
                      padding: '6px 14px',
                      fontSize: 13,
                      cursor: 'pointer',
                      color: 'var(--n-ink)'
                    }}
                  >
                    Hủy
                  </button>
                  <button
                    type="button"
                    onClick={handleSubmitReview}
                    disabled={submittingReview}
                    style={{
                      background: 'var(--n-accent)',
                      color: 'var(--n-accent-ink)',
                      fontWeight: 600,
                      border: 'none',
                      borderRadius: 6,
                      padding: '6px 16px',
                      fontSize: 13,
                      cursor: submittingReview ? 'not-allowed' : 'pointer'
                    }}
                  >
                    {submittingReview ? 'Đang lưu...' : 'Xác nhận Đánh giá'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          TAB 3: HỘP THƯ (INBOX METADATA TỰ ĐỘNG THU THẬP)
          ═══════════════════════════════════════════════════════════════════ */}
      {activeTab === 'inbox' && (
        <div style={{ display: 'grid', gap: 16 }}>
          {/* Thông báo hướng dẫn */}
          <div style={{
            background: 'var(--n-surface-2, #18191e)',
            border: '1px solid var(--n-line, #2d3139)',
            borderRadius: 10,
            padding: '12px 16px',
            fontSize: 12.5,
            color: 'var(--n-ink-2, #94a3b8)',
            lineHeight: 1.5
          }}>
            Hộp thư chứa metadata (tiêu đề, link, tóm tắt ngắn) do bộ thu thập lấy từ các nguồn tự động. Chưa phải thẻ ý tưởng. Đánh dấu <b>Chuyển thành thẻ</b> thì hệ thống sẽ đọc nguồn, viết thẻ theo <b>SCHEMA.md</b> (kèm nguồn lợi thế kinh tế) rồi đưa sang danh sách Alpha Prompt để sinh mã và backtest.
          </div>

          {/* 5 Thẻ đếm số liệu thống kê */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
            gap: 10
          }}>
            <div style={{
              background: 'var(--n-surface, #101216)',
              border: '1px solid var(--n-line, #2d3139)',
              borderRadius: 8,
              padding: '12px 14px',
              display: 'grid',
              gap: 4
            }}>
              <div style={{ fontSize: 11, color: 'var(--n-ink-2, #94a3b8)', fontWeight: 600 }}>MỚI</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--n-ink, #ffffff)' }}>
                {inboxStats.new}
              </div>
            </div>

            <div style={{
              background: 'var(--n-surface, #101216)',
              border: '1px solid var(--n-line, #2d3139)',
              borderRadius: 8,
              padding: '12px 14px',
              display: 'grid',
              gap: 4
            }}>
              <div style={{ fontSize: 11, color: 'var(--n-ink-2, #94a3b8)', fontWeight: 600 }}>ĐÁNG XEM</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--n-accent, #38bdf8)' }}>
                {inboxStats.interesting}
              </div>
            </div>

            <div style={{
              background: 'var(--n-surface, #101216)',
              border: '1px solid var(--n-line, #2d3139)',
              borderRadius: 8,
              padding: '12px 14px',
              display: 'grid',
              gap: 4
            }}>
              <div style={{ fontSize: 11, color: 'var(--n-ink-2, #94a3b8)', fontWeight: 600 }}>CHUYỂN THÀNH THẺ</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--n-pos, #10b981)' }}>
                {inboxStats.promoted}
              </div>
            </div>

            <div style={{
              background: 'var(--n-surface, #101216)',
              border: '1px solid var(--n-line, #2d3139)',
              borderRadius: 8,
              padding: '12px 14px',
              display: 'grid',
              gap: 4
            }}>
              <div style={{ fontSize: 11, color: 'var(--n-ink-2, #94a3b8)', fontWeight: 600 }}>ĐÃ CÓ THẺ</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--n-ink, #ffffff)' }}>
                {inboxStats.has_card}
              </div>
            </div>

            <div style={{
              background: 'var(--n-surface, #101216)',
              border: '1px solid var(--n-line, #2d3139)',
              borderRadius: 8,
              padding: '12px 14px',
              display: 'grid',
              gap: 4
            }}>
              <div style={{ fontSize: 11, color: 'var(--n-ink-2, #94a3b8)', fontWeight: 600 }}>BỎ QUA</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--n-ink-3, #64748b)' }}>
                {inboxStats.dismissed}
              </div>
            </div>
          </div>

          {/* Thanh lọc & tìm kiếm */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            flexWrap: 'wrap',
            background: 'var(--n-surface, #101216)',
            border: '1px solid var(--n-line, #2d3139)',
            borderRadius: 8,
            padding: '10px 14px'
          }}>
            <input
              type="text"
              value={inboxSearchQuery}
              onChange={(e) => setInboxSearchQuery(e.target.value)}
              placeholder="Tìm tiêu đề, tóm tắt..."
              style={{
                flex: '1 1 200px',
                background: 'var(--n-surface-2, #18191e)',
                border: '1px solid var(--n-line, #2d3139)',
                color: 'var(--n-ink, #ffffff)',
                padding: '6px 12px',
                borderRadius: 6,
                fontSize: 12.5
              }}
            />

            <select
              value={inboxFilterStatus}
              onChange={(e) => setInboxFilterStatus(e.target.value)}
              style={{
                background: 'var(--n-surface-2, #18191e)',
                border: '1px solid var(--n-line, #2d3139)',
                color: 'var(--n-ink, #ffffff)',
                padding: '6px 10px',
                borderRadius: 6,
                fontSize: 12.5
              }}
            >
              <option value="all">Mọi trạng thái</option>
              <option value="new">Mới</option>
              <option value="interesting">Đáng xem</option>
              <option value="promoted">Chuyển thành thẻ</option>
              <option value="has_card">Đã có thẻ</option>
              <option value="dismissed">Bỏ qua</option>
            </select>

            <select
              value={inboxFilterSource}
              onChange={(e) => setInboxFilterSource(e.target.value)}
              style={{
                background: 'var(--n-surface-2, #18191e)',
                border: '1px solid var(--n-line, #2d3139)',
                color: 'var(--n-ink, #ffffff)',
                padding: '6px 10px',
                borderRadius: 6,
                fontSize: 12.5
              }}
            >
              <option value="all">Mọi nguồn</option>
              {sourcesList.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>

            <select
              value={inboxFilterTier}
              onChange={(e) => setInboxFilterTier(e.target.value)}
              style={{
                background: 'var(--n-surface-2, #18191e)',
                border: '1px solid var(--n-line, #2d3139)',
                color: 'var(--n-ink, #ffffff)',
                padding: '6px 10px',
                borderRadius: 6,
                fontSize: 12.5
              }}
            >
              <option value="all">Mọi tầng</option>
              <option value="học thuật">Học thuật</option>
              <option value="thực chiến / open-source">Thực chiến / open-source</option>
            </select>

            <select
              value={inboxFilterMinScore}
              onChange={(e) => setInboxFilterMinScore(Number(e.target.value))}
              style={{
                background: 'var(--n-surface-2, #18191e)',
                border: '1px solid var(--n-line, #2d3139)',
                color: 'var(--n-ink, #ffffff)',
                padding: '6px 10px',
                borderRadius: 6,
                fontSize: 12.5
              }}
            >
              <option value={0}>Mọi điểm</option>
              <option value={2}>Điểm ≥ 2</option>
              <option value={3}>Điểm ≥ 3</option>
              <option value={4}>Điểm ≥ 4</option>
              <option value={5}>Điểm = 5</option>
            </select>

            <span style={{ fontSize: 12, color: 'var(--n-ink-2, #94a3b8)', whiteSpace: 'nowrap' }}>
              {inboxItems.filter((it) => {
                if (inboxFilterStatus !== 'all' && it.status !== inboxFilterStatus) return false
                if (inboxFilterSource !== 'all' && it.source_id !== inboxFilterSource) return false
                if (inboxFilterTier !== 'all' && it.tier !== inboxFilterTier) return false
                if (inboxFilterMinScore > 0 && (it.score || 0) < inboxFilterMinScore) return false
                if (inboxSearchQuery.trim()) {
                  const q = inboxSearchQuery.toLowerCase()
                  const txt = `${it.title || ''} ${it.summary || ''} ${(it.keywords || []).join(' ')}`.toLowerCase()
                  if (!txt.includes(q)) return false
                }
                return true
              }).length} mục khớp
            </span>

            <button
              type="button"
              onClick={handleDismissFiltered}
              disabled={dismissingFiltered}
              style={{
                background: 'var(--n-surface-2, #18191e)',
                color: 'var(--n-ink, #ffffff)',
                border: '1px solid var(--n-line, #2d3139)',
                borderRadius: 6,
                padding: '6px 12px',
                fontSize: 12,
                cursor: dismissingFiltered ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap',
                marginLeft: 'auto'
              }}
            >
              {dismissingFiltered ? 'Đang bỏ qua...' : 'Bỏ qua các mục mới đang lọc'}
            </button>
          </div>

          {/* Bảng danh sách Hộp thư */}
          <div style={{
            background: 'var(--n-surface, #101216)',
            border: '1px solid var(--n-line, #2d3139)',
            borderRadius: 10,
            overflow: 'hidden'
          }}>
            {loadingInbox ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--n-ink-2)' }}>
                Đang tải dữ liệu hộp thư...
              </div>
            ) : inboxItems.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--n-ink-2)' }}>
                Hộp thư trống. Bạn có thể nhấn <b>Chạy thu thập ngay</b> ở tab Nguồn để nạp ý tưởng mới.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                  <thead>
                    <tr style={{
                      background: 'var(--n-surface-2, #18191e)',
                      borderBottom: '1px solid var(--n-line, #2d3139)',
                      color: 'var(--n-ink-2, #94a3b8)',
                      fontSize: 12
                    }}>
                      <th style={{ padding: '10px 14px', width: 95 }}>Ngày</th>
                      <th style={{ padding: '10px 14px' }}>Tiêu đề & Tóm tắt</th>
                      <th style={{ padding: '10px 14px', width: 170 }}>Nguồn</th>
                      <th style={{ padding: '10px 14px', width: 150 }}>Từ khoá</th>
                      <th style={{ padding: '10px 14px', width: 60, textAlign: 'center' }}>Điểm</th>
                      <th style={{ padding: '10px 14px', width: 170, textAlign: 'right' }}>Thao tác</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inboxItems
                      .filter((it) => {
                        if (inboxFilterStatus !== 'all' && it.status !== inboxFilterStatus) return false
                        if (inboxFilterSource !== 'all' && it.source_id !== inboxFilterSource) return false
                        if (inboxFilterTier !== 'all' && it.tier !== inboxFilterTier) return false
                        if (inboxFilterMinScore > 0 && (it.score || 0) < inboxFilterMinScore) return false
                        if (inboxSearchQuery.trim()) {
                          const q = inboxSearchQuery.toLowerCase()
                          const txt = `${it.title || ''} ${it.summary || ''} ${(it.keywords || []).join(' ')}`.toLowerCase()
                          if (!txt.includes(q)) return false
                        }
                        return true
                      })
                      .map((item) => (
                        <tr
                          key={item.id}
                          style={{
                            borderBottom: '1px solid var(--n-line, #2d3139)',
                            opacity: item.status === 'dismissed' ? 0.45 : 1
                          }}
                        >
                          <td style={{ padding: '12px 14px', fontSize: 12, color: 'var(--n-ink-2, #94a3b8)', verticalAlign: 'top' }}>
                            {item.date}
                          </td>
                          <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                            <div style={{ display: 'grid', gap: 4 }}>
                              <a
                                href={item.url || '#'}
                                target="_blank"
                                rel="noreferrer"
                                style={{
                                  fontWeight: 600,
                                  color: 'var(--n-ink, #ffffff)',
                                  textDecoration: 'none',
                                  fontSize: 13.5
                                }}
                              >
                                {item.title}
                              </a>
                              {item.summary && (
                                <div style={{
                                  fontSize: 12,
                                  color: 'var(--n-ink-2, #94a3b8)',
                                  lineHeight: 1.45,
                                  display: '-webkit-box',
                                  WebkitLineClamp: 3,
                                  WebkitBoxOrient: 'vertical',
                                  overflow: 'hidden'
                                }}>
                                  {item.summary}
                                </div>
                              )}
                            </div>
                          </td>
                          <td style={{ padding: '12px 14px', fontSize: 12, color: 'var(--n-ink-2, #94a3b8)', verticalAlign: 'top' }}>
                            {item.source}
                          </td>
                          <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                              {(item.keywords || []).map((kw, i) => (
                                <span
                                  key={i}
                                  style={{
                                    fontSize: 10.5,
                                    padding: '1px 6px',
                                    borderRadius: 4,
                                    background: 'var(--n-surface-2, #18191e)',
                                    color: 'var(--n-ink-2, #94a3b8)',
                                    border: '1px solid var(--n-line, #2d3139)'
                                  }}
                                >
                                  {kw}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td style={{ padding: '12px 14px', textAlign: 'center', verticalAlign: 'top' }}>
                            <span style={{
                              fontWeight: 700,
                              fontSize: 12.5,
                              color: item.score >= 4 ? 'var(--n-pos, #10b981)' : item.score >= 3 ? 'var(--n-accent, #38bdf8)' : 'var(--n-ink, #ffffff)'
                            }}>
                              {item.score}
                            </span>
                          </td>
                          <td style={{ padding: '12px 14px', textAlign: 'right', verticalAlign: 'top' }}>
                            <div style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                              <button
                                type="button"
                                onClick={() => handleUpdateInboxStatus(item.id, item.status === 'interesting' ? 'new' : 'interesting')}
                                style={{
                                  background: item.status === 'interesting' ? 'var(--n-accent-wash, rgba(56,189,248,0.15))' : 'var(--n-surface-2, #18191e)',
                                  color: item.status === 'interesting' ? 'var(--n-accent, #38bdf8)' : 'var(--n-ink, #ffffff)',
                                  border: '1px solid var(--n-line, #2d3139)',
                                  borderRadius: 5,
                                  padding: '4px 8px',
                                  fontSize: 11.5,
                                  cursor: 'pointer',
                                  whiteSpace: 'nowrap'
                                }}
                              >
                                Đáng xem
                              </button>

                              <button
                                type="button"
                                onClick={() => handlePromoteInboxToCard(item)}
                                disabled={promotingItemId === item.id}
                                style={{
                                  background: 'var(--n-pos-wash, rgba(16,185,129,0.15))',
                                  color: 'var(--n-pos, #10b981)',
                                  border: '1px solid var(--n-pos, #10b981)',
                                  borderRadius: 5,
                                  padding: '4px 10px',
                                  fontSize: 11.5,
                                  fontWeight: 600,
                                  cursor: promotingItemId === item.id ? 'not-allowed' : 'pointer',
                                  whiteSpace: 'nowrap'
                                }}
                              >
                                {promotingItemId === item.id ? '...' : '→ Thẻ'}
                              </button>

                              <button
                                type="button"
                                onClick={() => handleUpdateInboxStatus(item.id, 'dismissed')}
                                style={{
                                  background: 'transparent',
                                  color: 'var(--n-ink-3, #64748b)',
                                  border: '1px solid transparent',
                                  borderRadius: 5,
                                  padding: '4px 6px',
                                  fontSize: 11.5,
                                  cursor: 'pointer'
                                }}
                              >
                                Bỏ
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          TAB 4: NGUỒN (SOURCES REGISTRY & AUTO-COLLECTOR)
          ═══════════════════════════════════════════════════════════════════ */}
      {activeTab === 'sources' && (
        <div style={{ display: 'grid', gap: 16 }}>
          {/* Thông báo điều khoản nguồn */}
          <div style={{
            background: 'var(--n-surface-2, #18191e)',
            border: '1px solid var(--n-line, #2d3139)',
            borderRadius: 10,
            padding: '12px 16px',
            fontSize: 12.5,
            color: 'var(--n-ink-2, #94a3b8)',
            lineHeight: 1.5
          }}>
            Chỉ nguồn auto (RSS/API chính thức, robots.txt cho phép) được thu thập tự động. Nguồn thủ công có lý do ở cột Điều khoản: TradingView và MQL5 cấm truy cập tự động; số khác chưa kiểm điều khoản nên mặc định đọc tay.
          </div>

          {/* Thanh tác vụ Nguồn */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
            <button
              type="button"
              onClick={handleRunCollection}
              disabled={collectingSources}
              style={{
                background: 'var(--n-accent, #2563eb)',
                color: 'var(--n-accent-ink, #ffffff)',
                border: 'none',
                borderRadius: 8,
                padding: '8px 20px',
                fontSize: 13,
                fontWeight: 600,
                cursor: collectingSources ? 'not-allowed' : 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 8
              }}
            >
              {collectingSources ? '⏳ Đang quét & thu thập...' : 'Chạy thu thập ngay'}
            </button>

            <select
              value={sourcesTypeFilter}
              onChange={(e) => setSourcesTypeFilter(e.target.value)}
              style={{
                background: 'var(--n-surface-2, #18191e)',
                border: '1px solid var(--n-line, #2d3139)',
                color: 'var(--n-ink, #ffffff)',
                padding: '6px 12px',
                borderRadius: 6,
                fontSize: 12.5
              }}
            >
              <option value="all">Mọi kiểu</option>
              <option value="auto_api">Tự động API</option>
              <option value="auto_rss">Tự động RSS</option>
              <option value="manual">Thủ công</option>
            </select>
          </div>

          {/* Bảng danh sách Nguồn */}
          <div style={{
            background: 'var(--n-surface, #101216)',
            border: '1px solid var(--n-line, #2d3139)',
            borderRadius: 10,
            overflow: 'hidden'
          }}>
            {loadingSources ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--n-ink-2)' }}>
                Đang tải cấu hình nguồn thu thập...
              </div>
            ) : sourcesList.length === 0 ? (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--n-ink-2)' }}>
                Không có nguồn nào được cấu hình.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: 13 }}>
                  <thead>
                    <tr style={{
                      background: 'var(--n-surface-2, #18191e)',
                      borderBottom: '1px solid var(--n-line, #2d3139)',
                      color: 'var(--n-ink-2, #94a3b8)',
                      fontSize: 12
                    }}>
                      <th style={{ padding: '10px 14px', width: 260 }}>Nguồn</th>
                      <th style={{ padding: '10px 14px', width: 100 }}>Tầng</th>
                      <th style={{ padding: '10px 14px', width: 110 }}>Kiểu</th>
                      <th style={{ padding: '10px 14px', width: 220 }}>Lần chạy gần nhất</th>
                      <th style={{ padding: '10px 14px', width: 140 }}>Trong hộp thư</th>
                      <th style={{ padding: '10px 14px' }}>Điều khoản / ghi chú</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sourcesList
                      .filter((s) => {
                        if (sourcesTypeFilter === 'auto_api') return s.type.includes('api')
                        if (sourcesTypeFilter === 'auto_rss') return s.type.includes('rss')
                        if (sourcesTypeFilter === 'manual') return s.type.includes('thủ công')
                        return true
                      })
                      .map((src) => (
                        <tr
                          key={src.id}
                          style={{ borderBottom: '1px solid var(--n-line, #2d3139)' }}
                        >
                          <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                            <div style={{ display: 'grid', gap: 2 }}>
                              <a
                                href={src.url || '#'}
                                target="_blank"
                                rel="noreferrer"
                                style={{
                                  color: 'var(--n-accent, #38bdf8)',
                                  textDecoration: 'none',
                                  fontWeight: 500,
                                  fontSize: 13
                                }}
                              >
                                {src.name}
                              </a>
                              <div style={{ fontSize: 11, color: 'var(--n-ink-3, #64748b)', fontFamily: 'monospace' }}>
                                {src.id}
                              </div>
                            </div>
                          </td>
                          <td style={{ padding: '12px 14px', fontSize: 12, color: 'var(--n-ink-2, #94a3b8)', verticalAlign: 'top' }}>
                            {src.tier}
                          </td>
                          <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                            <span style={{
                              fontSize: 11,
                              padding: '2px 7px',
                              borderRadius: 4,
                              background: src.type.includes('tự động') ? 'var(--n-pos-wash, rgba(16,185,129,0.12))' : 'var(--n-surface-2, #18191e)',
                              color: src.type.includes('tự động') ? 'var(--n-pos, #10b981)' : 'var(--n-ink-2, #94a3b8)',
                              border: `1px solid ${src.type.includes('tự động') ? 'var(--n-pos, #10b981)' : 'var(--n-line, #2d3139)'}`
                            }}>
                              {src.type}
                            </span>
                          </td>
                          <td style={{ padding: '12px 14px', fontSize: 12, color: 'var(--n-ink-2, #94a3b8)', verticalAlign: 'top' }}>
                            {src.last_run}
                          </td>
                          <td style={{ padding: '12px 14px', fontSize: 12, color: 'var(--n-ink, #ffffff)', fontWeight: 500, verticalAlign: 'top' }}>
                            {src.in_box}
                          </td>
                          <td style={{ padding: '12px 14px', fontSize: 12, color: 'var(--n-ink-2, #94a3b8)', lineHeight: 1.4, verticalAlign: 'top' }}>
                            {src.terms}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════════════════
          TAB 5: CẤU HÌNH LLM & ENGINE (STATUS & VALIDATOR)
          ═══════════════════════════════════════════════════════════════════ */}
      {activeTab === 'config' && (
        <div style={{ display: 'grid', gap: 18 }}>
          {/* Thông tin Engine hiện hành */}
          <div style={{
            background: 'var(--n-surface)',
            border: '1px solid var(--n-line)',
            borderRadius: 12,
            padding: 18,
            display: 'grid',
            gap: 12
          }}>
            <div style={{ fontWeight: 700, fontSize: 16 }}>
              🤖 Trạng thái AI Engine & LLM Provider
            </div>

            <div style={{ fontSize: 13, color: 'var(--n-ink-2)', lineHeight: 1.5 }}>
              Hệ thống Nora Alpha Research hỗ trợ cả công cụ rule-based/heuristics lẫn các mô hình ngôn ngữ lớn (LLM).
              Toàn bộ API key được lưu trữ bảo mật tại biến môi trường phía máy chủ và <b>không bao giờ</b> lộ ra client response, log hay mã nguồn frontend.
            </div>

            {engineInfo && (
              <div style={{ display: 'grid', gap: 8, marginTop: 4 }}>
                <div style={{ fontSize: 13 }}>
                  <b>Nhà cung cấp đang dùng:</b>{' '}
                  <span style={{ fontFamily: 'monospace', color: 'var(--n-accent)', fontWeight: 600 }}>
                    {engineInfo.active_provider}
                  </span>
                </div>
                <div style={{ fontSize: 13 }}>
                  <b>Mô hình hoạt động:</b>{' '}
                  <span style={{ fontFamily: 'monospace', color: 'var(--n-ink)', fontWeight: 600 }}>
                    {engineInfo.model}
                  </span>
                </div>

                <div style={{ marginTop: 8 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
                    Các nhà cung cấp được cấu hình:
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
                    {(engineInfo.providers || []).map((prov, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--n-surface-2)',
                          border: '1px solid var(--n-line)',
                          borderRadius: 8,
                          padding: '10px 12px',
                          display: 'grid',
                          gap: 4
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontWeight: 600, textTransform: 'uppercase', fontSize: 12 }}>
                            {prov.provider}
                          </span>
                          <span style={{
                            fontSize: 10.5,
                            padding: '1px 6px',
                            borderRadius: 8,
                            background: prov.key_configured ? 'var(--n-pos-wash)' : 'var(--n-surface)',
                            color: prov.key_configured ? 'var(--n-pos)' : 'var(--n-ink-3)',
                            border: `1px solid ${prov.key_configured ? 'var(--n-pos)' : 'var(--n-line)'}`
                          }}>
                            {prov.key_configured ? '✓ Đã cấu hình Key' : 'Chưa có Key'}
                          </span>
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--n-ink-2)' }}>
                          Mô hình: {(prov.models || []).join(', ')}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Công cụ kiểm tra cấu hình tương tác */}
          <div style={{
            background: 'var(--n-surface)',
            border: '1px solid var(--n-line)',
            borderRadius: 12,
            padding: 18,
            display: 'grid',
            gap: 12
          }}>
            <div style={{ fontWeight: 700, fontSize: 16 }}>
              🔍 Kiểm tra Cấu hình Alpha Research (Configuration Validator)
            </div>

            <div style={{ fontSize: 13, color: 'var(--n-ink-2)' }}>
              Kiểm tra tính hợp lệ của tham số cấu hình mà không làm lộ các giá trị bí mật.
            </div>

            {cfgError && (
              <div style={{ padding: '8px 12px', background: 'var(--n-neg-wash)', color: 'var(--n-neg)', borderRadius: 6, fontSize: 12 }}>
                ⚠️ {cfgError}
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
              <label style={{ fontSize: 12.5, display: 'grid', gap: 4 }}>
                <b>Nhà cung cấp (Provider):</b>
                <select
                  value={cfgProvider}
                  onChange={(e) => setCfgProvider(e.target.value)}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink)',
                    padding: '6px 8px',
                    borderRadius: 6
                  }}
                >
                  <option value="heuristics">Heuristics / Rule-based (Mặc định offline)</option>
                  <option value="deepseek">DeepSeek</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Google Gemini</option>
                  <option value="anthropic">Anthropic Claude</option>
                </select>
              </label>

              <label style={{ fontSize: 12.5, display: 'grid', gap: 4 }}>
                <b>Mô hình (Model name):</b>
                <input
                  type="text"
                  value={cfgModel}
                  onChange={(e) => setCfgModel(e.target.value)}
                  placeholder="Để trống để dùng mặc định"
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink)',
                    padding: '6px 8px',
                    borderRadius: 6
                  }}
                />
              </label>

              <label style={{ fontSize: 12.5, display: 'grid', gap: 4 }}>
                <b>Tài sản (Symbol):</b>
                <select
                  value={cfgSymbol}
                  onChange={(e) => setCfgSymbol(e.target.value)}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink)',
                    padding: '6px 8px',
                    borderRadius: 6
                  }}
                >
                  <option value="BTC-USDT">BTC-USDT</option>
                  <option value="ETH-USDT">ETH-USDT</option>
                  <option value="SOL-USDT">SOL-USDT</option>
                </select>
              </label>

              <label style={{ fontSize: 12.5, display: 'grid', gap: 4 }}>
                <b>Khung nến (Timeframe):</b>
                <select
                  value={cfgTf}
                  onChange={(e) => setCfgTf(e.target.value)}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink)',
                    padding: '6px 8px',
                    borderRadius: 6
                  }}
                >
                  <option value="15m">15m</option>
                  <option value="1h">1h</option>
                  <option value="4h">4h</option>
                </select>
              </label>

              <label style={{ fontSize: 12.5, display: 'grid', gap: 4 }}>
                <b>Hướng giao dịch (Side):</b>
                <select
                  value={cfgSide}
                  onChange={(e) => setCfgSide(e.target.value)}
                  style={{
                    background: 'var(--n-surface-2)',
                    border: '1px solid var(--n-line)',
                    color: 'var(--n-ink)',
                    padding: '6px 8px',
                    borderRadius: 6
                  }}
                >
                  <option value="both">Both (Long & Short)</option>
                  <option value="long">Chỉ Long</option>
                  <option value="short">Chỉ Short</option>
                </select>
              </label>
            </div>

            <div>
              <button
                type="button"
                onClick={handleValidateConfig}
                disabled={validatingCfg}
                style={{
                  background: 'var(--n-accent)',
                  color: 'var(--n-accent-ink)',
                  fontWeight: 600,
                  border: 'none',
                  borderRadius: 6,
                  padding: '7px 18px',
                  fontSize: 13,
                  cursor: validatingCfg ? 'not-allowed' : 'pointer'
                }}
              >
                {validatingCfg ? 'Đang kiểm tra...' : 'Kiểm tra Cấu hình'}
              </button>
            </div>

            {cfgValidationResult && (
              <div style={{
                background: cfgValidationResult.valid ? 'var(--n-pos-wash)' : 'var(--n-neg-wash)',
                border: `1px solid ${cfgValidationResult.valid ? 'var(--n-pos)' : 'var(--n-neg)'}`,
                borderRadius: 8,
                padding: '12px 16px',
                display: 'grid',
                gap: 6
              }}>
                <div style={{ fontWeight: 700, color: cfgValidationResult.valid ? 'var(--n-pos)' : 'var(--n-neg)', fontSize: 13.5 }}>
                  {cfgValidationResult.valid ? '✓ Cấu hình hợp lệ' : '✗ Cấu hình không hợp lệ'}
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--n-ink)' }}>
                  {cfgValidationResult.message}
                </div>
                <div style={{ fontSize: 12, color: 'var(--n-ink-2)' }}>
                  Provider: <b>{cfgValidationResult.provider}</b> (Key configured: {cfgValidationResult.key_configured ? 'Yes' : 'No'}) · Symbol: <b>{cfgValidationResult.symbol}</b> · Timeframe: <b>{cfgValidationResult.timeframe}</b> · Side: <b>{cfgValidationResult.side}</b>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
