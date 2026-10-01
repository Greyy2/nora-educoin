import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Cond } from '../components/Cond'
import StudioEditor from '../components/StudioEditor'
import StudioResults from '../components/StudioResults'

const API_BASE = '/api/studio'
const DAY_MS = 86_400_000
const COMPARISON_OPERATORS = ['>', '<', '>=', '<=', '==', '!=']
const DEFAULT_SETTINGS = {
  initial_capital: 10000,
  leverage: 1,
  using_match_price: true,
  max_open_trades: 45,
  stop_loss_rate: 4,
  take_profit_rate: 7.5,
  timeout: 0,
  result_trade_limit: 300,
}

const field = (frame, column) => ({ frame, column, index: '0' })
const clone = (value) => JSON.parse(JSON.stringify(value))
const nodeKey = (node) => JSON.stringify(node)
const parseNumber = (value, fallback) => {
  const next = Number(value)
  return Number.isFinite(next) ? next : fallback
}

const DEFAULT_NODE_OPTIONS = [
  { label: '1m Open', node: field('1m', 'open') },
  { label: '1m High', node: field('1m', 'high') },
  { label: '1m Low', node: field('1m', 'low') },
  { label: '1m Close', node: field('1m', 'close') },
  { label: '1m Volume', node: field('1m', 'volume') },
  { label: '4h Open', node: field('4h', 'open') },
  { label: '4h High', node: field('4h', 'high') },
  { label: '4h Low', node: field('4h', 'low') },
  { label: '4h Close', node: field('4h', 'close') },
  { label: '4h Volume', node: field('4h', 'volume') },
  { label: '4h ATR', node: field('4h', 'atr') },
  { label: '4h Keltner Upper 17/0.5', node: field('4h', 'kup17_05') },
  { label: '4h Keltner Mid 17/0.5', node: field('4h', 'kmid17_05') },
  { label: '4h Keltner Lower 17/0.5', node: field('4h', 'klo17_05') },
  { label: '4h Keltner Upper 20/1.5', node: field('4h', 'kup20_15') },
  { label: '4h Keltner Mid 20/1.5', node: field('4h', 'kmid20_15') },
  { label: '4h Keltner Lower 20/1.5', node: field('4h', 'klo20_15') },
]

const defaultTriplet = (type, section) => {
  if (type === 'SHORT') {
    return section === 'match'
      ? [field('1m', 'low'), '<', field('4h', 'klo17_05')]
      : [field('1m', 'high'), '>', field('4h', 'kmid17_05')]
  }
  return section === 'match'
    ? [field('1m', 'high'), '>', field('4h', 'kup17_05')]
    : [field('1m', 'low'), '<', field('4h', 'kmid17_05')]
}

const defaultConditionTree = (type, section) => {
  const tree = [[defaultTriplet(type, section)]]
  if (section === 'match') tree[0].push([field('4h', 'atr'), '>', 0])
  return tree
}

const createFlow = (type = 'LONG', name) => ({
  id: `flow_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
  name: name || `${type} Flow`,
  enabled: true,
  ast: {
    type,
    match: [{ enter_price: 'touch', condition: defaultConditionTree(type, 'match') }],
    stop: [{ condition: defaultConditionTree(type, 'stop') }],
  },
})

const createDefaultTab = (index = 1) => ({
  id: `tab_${Date.now()}_${index}`,
  name: `Strategy ${index}`,
  symbol: '',
  startDate: '',
  endDate: '',
  activeFlowIndex: 0,
  settings: { ...DEFAULT_SETTINGS },
  flows: [createFlow('LONG', 'LONG Keltner Breakout')],
})

const dateInputFromTs = (ts) => {
  const date = new Date(Number(ts || 0))
  if (Number.isNaN(date.getTime())) return ''
  return date.toISOString().slice(0, 10)
}

const dateToStartTs = (value) => Date.parse(`${value}T00:00:00.000Z`)
const dateToEndTs = (value) => Date.parse(`${value}T23:59:59.999Z`)

const rangeFromDataset = (dataset) => {
  const fallbackEnd = Date.now()
  const endTs = Number(dataset?.end_ts || fallbackEnd)
  const startFloor = Number(dataset?.start_ts || endTs - 60 * DAY_MS)
  const startTs = Math.max(startFloor, endTs - 60 * DAY_MS)
  return {
    startDate: dateInputFromTs(startTs),
    endDate: dateInputFromTs(endTs),
  }
}

const normalizeSampleFlows = (sample) => {
  const flows = Array.isArray(sample.flows) ? sample.flows : []
  return flows.map((flow, index) => {
    const ast = flow.ast || flow
    const type = String(ast.type || 'LONG').toUpperCase() === 'SHORT' ? 'SHORT' : 'LONG'
    return {
      id: flow.id || `sample_flow_${index + 1}`,
      name: flow.name || `${type} Flow ${index + 1}`,
      enabled: flow.enabled !== false,
      ast: clone({ ...ast, type }),
    }
  })
}

export default function Studio() {
  const [tabs, setTabs] = useState(() => [createDefaultTab(1)])
  const [activeTabId, setActiveTabId] = useState(() => tabs[0]?.id || 'tab_1')
  const [rightTab, setRightTab] = useState('samples')
  const [samples, setSamples] = useState([])
  const [features, setFeatures] = useState([])
  const [operators, setOperators] = useState([])
  const [datasets, setDatasets] = useState([])
  const [maxBacktestDays, setMaxBacktestDays] = useState(1100)
  const [sampleSearch, setSampleSearch] = useState('')
  const [sampleCategory, setSampleCategory] = useState('ALL')
  const [savedStrategies, setSavedStrategies] = useState(() => {
    try {
      const raw = localStorage.getItem('nora.studio.strategies')
      const parsed = raw ? JSON.parse(raw) : []
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  })
  const [simResults, setSimResults] = useState(null)
  const [simLoading, setSimLoading] = useState(false)
  const [simError, setSimError] = useState(null)
  const [showSettings, setShowSettings] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [layoutMode, setLayoutMode] = useState(() => {
    try {
      return localStorage.getItem('nora.studio.layout') || 'wide'
    } catch {
      return 'wide'
    }
  })

  const navigate = useNavigate()

  const handleSendToBase = (results) => {
    const payload = {
      source_handle: results.source_handle,
      strategy_snapshot: results.strategy_snapshot || {
        name: activeTab.name,
        symbol: activeTab.symbol,
        flows: activeTab.flows,
        start_ts: dateToStartTs(startDate),
        end_ts: dateToEndTs(endDate),
        initial_capital: activeTab.settings.initial_capital,
        leverage: activeTab.settings.leverage,
        stop_loss_rate: activeTab.settings.stop_loss_rate,
        take_profit_rate: activeTab.settings.take_profit_rate,
        timeout: activeTab.settings.timeout,
      },
      symbol: activeTab.symbol,
      metrics: results.metrics,
      trades: results.trades,
    }
    try {
      localStorage.setItem('nora.active_strategy_snapshot', JSON.stringify(payload))
    } catch {}
    navigate('/library/base', { state: { strategyInput: payload } })
  }


  const activeTab = tabs.find((tab) => tab.id === activeTabId) || tabs[0]
  const flows = activeTab?.flows || []
  const activeFlowIndex = Math.min(Math.max(activeTab?.activeFlowIndex || 0, 0), Math.max(flows.length - 1, 0))
  const activeFlow = flows[activeFlowIndex]
  const activeDataset = datasets.find((dataset) => dataset.symbol === activeTab?.symbol || dataset.asset === activeTab?.symbol)
  const effectiveRange = rangeFromDataset(activeDataset)
  const startDate = activeTab?.startDate || effectiveRange.startDate
  const endDate = activeTab?.endDate || effectiveRange.endDate

  const valueNodeOptions = useMemo(() => {
    const catalogOptions = features.flatMap((feature) =>
      (feature.nodes || []).map((node) => ({
        label: node.label || feature.name,
        node: node.node,
      }))
    )
    const source = catalogOptions.length ? catalogOptions : DEFAULT_NODE_OPTIONS
    const seen = new Set()
    return source.filter((item) => {
      if (item.node === undefined) return false
      const key = nodeKey(item.node)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [features])

  const fieldNodeOptions = useMemo(
    () => valueNodeOptions.filter((item) => item.node && typeof item.node === 'object' && item.node.frame),
    [valueNodeOptions]
  )

  const categories = useMemo(
    () => ['ALL', ...Array.from(new Set(samples.map((sample) => sample.category).filter(Boolean)))],
    [samples]
  )

  const filteredSamples = useMemo(() => {
    return samples.filter((sample) => {
      const needle = sampleSearch.toLowerCase()
      const haystack = [sample.name, sample.description, ...(sample.tags || [])].join(' ').toLowerCase()
      const matchSearch = !needle || haystack.includes(needle)
      const matchCategory = sampleCategory === 'ALL' || sample.category === sampleCategory
      return matchSearch && matchCategory
    })
  }, [samples, sampleCategory, sampleSearch])

  const rangeDays = useMemo(() => {
    const startTs = dateToStartTs(startDate)
    const endTs = dateToEndTs(endDate)
    if (!Number.isFinite(startTs) || !Number.isFinite(endTs)) return 0
    return (endTs - startTs) / DAY_MS
  }, [startDate, endDate])

  const studioWarnings = useMemo(() => {
    const warnings = []
    if (activeDataset && !activeDataset.has_required_frames) warnings.push('Asset này thiếu 1m hoặc 4h nên chưa đủ điều kiện chạy Studio canonical.')
    if (activeDataset?.warnings) warnings.push(...activeDataset.warnings)
    if (rangeDays > maxBacktestDays) warnings.push(`Khoảng mô phỏng đang vượt giới hạn ${maxBacktestDays} ngày của BacktestEngine.`)
    return Array.from(new Set(warnings))
  }, [activeDataset, rangeDays, maxBacktestDays])

  const astPreview = useMemo(
    () => ({
      strategy: activeTab?.name || 'Strategy',
      symbol: activeTab?.symbol || '',
      execution_frame: '1m',
      indicator_frame: '4h',
      range: { start_date: startDate, end_date: endDate },
      settings: activeTab?.settings || DEFAULT_SETTINGS,
      flows,
    }),
    [activeTab, endDate, flows, startDate]
  )

  useEffect(() => {
    fetch(`${API_BASE}/samples`)
      .then((res) => res.json())
      .then((data) => setSamples(data.samples || []))
      .catch(() => {})

    fetch(`${API_BASE}/features`)
      .then((res) => res.json())
      .then((data) => setFeatures(data.features || []))
      .catch(() => {})

    fetch(`${API_BASE}/operators`)
      .then((res) => res.json())
      .then((data) => setOperators(data.operators || []))
      .catch(() => {})

    fetch(`${API_BASE}/datasets`)
      .then((res) => res.json())
      .then((data) => {
        setDatasets(data.datasets || [])
        if (data.max_backtest_days) setMaxBacktestDays(data.max_backtest_days)
      })
      .catch(() => {})
  }, [])

  // Chọn asset mặc định = asset đầu tiên đủ 1m + 4h (không mặc định cứng 'SOL')
  useEffect(() => {
    if (!datasets.length) return
    const known = new Set(datasets.map((d) => d.symbol || d.asset))
    const firstReady = datasets.find((d) => d.has_required_frames) || datasets[0]
    const fallback = firstReady ? (firstReady.symbol || firstReady.asset) : ''
    setTabs((prev) => prev.map((t) => (t.symbol && known.has(t.symbol) ? t : { ...t, symbol: fallback })))
  }, [datasets])

  const showToast = (message) => {
    setSaveMessage(message)
    setTimeout(() => setSaveMessage(null), 2600)
  }

  const toggleLayout = () => {
    const next = layoutMode === 'wide' ? 'focus' : 'wide'
    setLayoutMode(next)
    try {
      localStorage.setItem('nora.studio.layout', next)
    } catch {}
  }

  const persistSavedStrategies = (items) => {
    setSavedStrategies(items)
    try {
      localStorage.setItem('nora.studio.strategies', JSON.stringify(items.slice(0, 30)))
    } catch {}
  }

  const saveActiveStrategy = () => {
    if (!activeTab) return
    const snapshot = {
      id: `strategy_${Date.now()}`,
      name: activeTab.name || 'Untitled Strategy',
      symbol: activeTab.symbol,
      saved_at: new Date().toISOString(),
      tab: clone(activeTab),
    }
    persistSavedStrategies([snapshot, ...savedStrategies.filter((item) => item.name !== snapshot.name)].slice(0, 30))
    showToast(`Đã lưu "${snapshot.name}" vào Strategy List`)
  }

  const loadSavedStrategy = (item) => {
    if (!item?.tab) return
    const nextTab = clone(item.tab)
    nextTab.id = `tab_${Date.now()}_saved`
    nextTab.name = item.name || nextTab.name || 'Saved Strategy'
    setTabs((prev) => [...prev, nextTab])
    setActiveTabId(nextTab.id)
    showToast(`Đã mở "${nextTab.name}"`)
  }

  const deleteSavedStrategy = (id) => {
    persistSavedStrategies(savedStrategies.filter((item) => item.id !== id))
  }

  const updateActiveTab = (updater) => {
    setTabs((prev) =>
      prev.map((tab) => {
        if (tab.id !== activeTabId) return tab
        const patch = typeof updater === 'function' ? updater(tab) : updater
        return { ...tab, ...patch }
      })
    )
  }

  const updateSettings = (patch) => {
    updateActiveTab((tab) => ({ settings: { ...tab.settings, ...patch } }))
  }

  const addTab = () => {
    const nextTab = createDefaultTab(tabs.length + 1)
    setTabs((prev) => [...prev, nextTab])
    setActiveTabId(nextTab.id)
  }

  const forkActiveTab = () => {
    const source = activeTab || createDefaultTab(tabs.length + 1)
    const forked = clone(source)
    forked.id = `tab_${Date.now()}_fork`
    forked.name = `${source.name || 'Strategy'} Fork`
    forked.flows = (forked.flows || []).map((flow, index) => ({
      ...flow,
      id: `flow_${Date.now()}_${index}_${Math.random().toString(36).slice(2, 7)}`,
      name: flow.name || `Flow ${index + 1}`,
    }))
    setTabs((prev) => [...prev, forked])
    setActiveTabId(forked.id)
    showToast(`Đã fork "${source.name || 'Strategy'}"`)
  }

  const closeTab = (e, tabId) => {
    e.stopPropagation()
    if (tabs.length === 1) return
    const remaining = tabs.filter((tab) => tab.id !== tabId)
    setTabs(remaining)
    if (activeTabId === tabId) setActiveTabId(remaining[0].id)
  }

  const loadSample = (sample) => {
    const sampleFlows = normalizeSampleFlows(sample)
    const defaults = sample.default_params || {}
    updateActiveTab((tab) => ({
      name: sample.name || tab.name,
      flows: sampleFlows.length ? sampleFlows : tab.flows,
      activeFlowIndex: 0,
      settings: {
        ...tab.settings,
        initial_capital: parseNumber(defaults.initial_capital ?? defaults.capital, tab.settings.initial_capital),
        leverage: parseNumber(defaults.leverage, tab.settings.leverage),
        stop_loss_rate: parseNumber(defaults.stop_loss_rate ?? defaults.stop_loss_pct, tab.settings.stop_loss_rate),
        take_profit_rate: parseNumber(defaults.take_profit_rate ?? defaults.take_profit_pct, tab.settings.take_profit_rate),
        using_match_price: defaults.using_match_price ?? tab.settings.using_match_price,
      },
    }))
    showToast(`Đã nạp sample "${sample.name}" vào Builder`)
  }

  const updateFlow = (index, updater) => {
    updateActiveTab((tab) => ({
      flows: (tab.flows || []).map((flow, flowIndex) => {
        if (flowIndex !== index) return flow
        return typeof updater === 'function' ? updater(flow) : { ...flow, ...updater }
      }),
    }))
  }

  const addFlow = (type) => {
    updateActiveTab((tab) => {
      const nextFlows = [...(tab.flows || []), createFlow(type)]
      return { flows: nextFlows, activeFlowIndex: nextFlows.length - 1 }
    })
  }

  const removeFlow = (index) => {
    if (flows.length <= 1) return
    updateActiveTab((tab) => {
      const nextFlows = (tab.flows || []).filter((_, flowIndex) => flowIndex !== index)
      return { flows: nextFlows, activeFlowIndex: Math.max(0, Math.min(index, nextFlows.length - 1)) }
    })
  }

  const withSectionBlocks = (section, transform) => {
    updateFlow(activeFlowIndex, (flow) => {
      const ast = flow.ast || { type: 'LONG', match: [], stop: [] }
      const blocks = clone(Array.isArray(ast[section]) ? ast[section] : [])
      return { ...flow, ast: { ...ast, [section]: transform(blocks, ast.type || 'LONG') } }
    })
  }

  const updateBlock = (section, blockIndex, patch) => {
    withSectionBlocks(section, (blocks, type) => {
      const block = blocks[blockIndex] || { condition: defaultConditionTree(type, section) }
      blocks[blockIndex] = { ...block, ...patch }
      return blocks
    })
  }

  const addBlock = (section) => {
    withSectionBlocks(section, (blocks, type) => [
      ...blocks,
      section === 'match'
        ? { enter_price: 'touch', condition: defaultConditionTree(type, section) }
        : { condition: defaultConditionTree(type, section) },
    ])
  }

  const removeBlock = (section, blockIndex) => {
    withSectionBlocks(section, (blocks) => (blocks.length <= 1 ? blocks : blocks.filter((_, index) => index !== blockIndex)))
  }

  const addOrGroup = (section, blockIndex) => {
    withSectionBlocks(section, (blocks, type) => {
      const block = blocks[blockIndex] || { condition: [] }
      const condition = Array.isArray(block.condition) ? block.condition : []
      condition.push([defaultTriplet(type, section)])
      blocks[blockIndex] = { ...block, condition }
      return blocks
    })
  }

  const addAndCondition = (section, blockIndex, groupIndex) => {
    withSectionBlocks(section, (blocks, type) => {
      const block = blocks[blockIndex] || { condition: [] }
      const condition = Array.isArray(block.condition) ? block.condition : []
      const group = Array.isArray(condition[groupIndex]) ? condition[groupIndex] : []
      group.push(defaultTriplet(type, section))
      condition[groupIndex] = group
      blocks[blockIndex] = { ...block, condition }
      return blocks
    })
  }

  const removeCondition = (section, blockIndex, groupIndex, conditionIndex) => {
    withSectionBlocks(section, (blocks, type) => {
      const block = blocks[blockIndex] || { condition: [] }
      const condition = Array.isArray(block.condition) ? block.condition : []
      const group = Array.isArray(condition[groupIndex]) ? condition[groupIndex] : []
      if (group.length > 1) {
        group.splice(conditionIndex, 1)
        condition[groupIndex] = group
      } else {
        condition.splice(groupIndex, 1)
      }
      if (!condition.length) condition.push([defaultTriplet(type, section)])
      blocks[blockIndex] = { ...block, condition }
      return blocks
    })
  }

  const updateConditionValue = (section, blockIndex, groupIndex, conditionIndex, partIndex, nextValue) => {
    withSectionBlocks(section, (blocks, type) => {
      const block = blocks[blockIndex] || { condition: defaultConditionTree(type, section) }
      const condition = Array.isArray(block.condition) ? block.condition : []
      const group = Array.isArray(condition[groupIndex]) ? condition[groupIndex] : []
      const current = Array.isArray(group[conditionIndex]) && group[conditionIndex].length === 3 ? group[conditionIndex] : defaultTriplet(type, section)
      const next = [...current]
      next[partIndex] = nextValue
      group[conditionIndex] = next
      condition[groupIndex] = group
      blocks[blockIndex] = { ...block, condition }
      return blocks
    })
  }

  const handleJsonNode = (value, onChange) => {
    try {
      onChange(JSON.parse(value))
    } catch {
      showToast('JSON node chưa hợp lệ')
    }
  }

  const renderFieldSelect = (node, onChange) => {
    const known = fieldNodeOptions.find((item) => nodeKey(item.node) === nodeKey(node))
    return (
      <div className="studio-node-control">
        <select className="studio-node-select" value={known ? nodeKey(known.node) : ''} onChange={(e) => e.target.value && onChange(JSON.parse(e.target.value))}>
          {!known && <option value="">Custom field</option>}
          {fieldNodeOptions.map((item) => (
            <option key={nodeKey(item.node)} value={nodeKey(item.node)}>
              {item.label}
            </option>
          ))}
        </select>
        {!known && <pre className="studio-inline-json">{JSON.stringify(node)}</pre>}
      </div>
    )
  }

  const renderRightNode = (node, onChange) => {
    const options = valueNodeOptions.filter((item) => typeof item.node !== 'number')
    const known = options.find((item) => nodeKey(item.node) === nodeKey(node))
    const mode = typeof node === 'number' ? 'number' : known ? 'node' : 'json'
    return (
      <div className="studio-node-control">
        <select
          className="studio-node-mode-select"
          value={mode}
          onChange={(e) => {
            if (e.target.value === 'number') onChange(0)
            if (e.target.value === 'node' && options[0]) onChange(clone(options[0].node))
          }}
        >
          <option value="node">Feature node</option>
          <option value="number">Number</option>
          <option value="json">Custom JSON</option>
        </select>
        {mode === 'number' && (
          <input className="studio-number-input" type="number" value={node} onChange={(e) => onChange(parseNumber(e.target.value, 0))} />
        )}
        {mode === 'node' && (
          <select className="studio-node-select" value={known ? nodeKey(known.node) : ''} onChange={(e) => e.target.value && onChange(JSON.parse(e.target.value))}>
            {options.map((item) => (
              <option key={nodeKey(item.node)} value={nodeKey(item.node)}>
                {item.label}
              </option>
            ))}
          </select>
        )}
        {mode === 'json' && (
          <textarea
            key={nodeKey(node)}
            className="studio-node-json-input"
            defaultValue={JSON.stringify(node, null, 2)}
            onBlur={(e) => handleJsonNode(e.target.value, onChange)}
          />
        )}
      </div>
    )
  }

  const renderConditionRow = (section, blockIndex, groupIndex, condition, conditionIndex) => {
    const flowType = activeFlow?.ast?.type || 'LONG'
    const triplet = Array.isArray(condition) && condition.length === 3 ? condition : defaultTriplet(flowType, section)
    const op = COMPARISON_OPERATORS.includes(triplet[1]) ? triplet[1] : '>'
    return (
      <div key={conditionIndex} className="studio-condition-row">
        <div className="studio-condition-side">{renderFieldSelect(triplet[0], (value) => updateConditionValue(section, blockIndex, groupIndex, conditionIndex, 0, value))}</div>
        <select className="studio-operator-select" value={op} onChange={(e) => updateConditionValue(section, blockIndex, groupIndex, conditionIndex, 1, e.target.value)}>
          {COMPARISON_OPERATORS.map((operator) => (
            <option key={operator} value={operator}>
              {operator}
            </option>
          ))}
        </select>
        <div className="studio-condition-side">{renderRightNode(triplet[2], (value) => updateConditionValue(section, blockIndex, groupIndex, conditionIndex, 2, value))}</div>
        <button className="studio-inline-danger" onClick={() => removeCondition(section, blockIndex, groupIndex, conditionIndex)}>
          Remove
        </button>
      </div>
    )
  }

  const renderConditionSection = (section, title, description) => {
    if (!activeFlow) return null
    const flowType = activeFlow.ast?.type || 'LONG'
    const blocks = Array.isArray(activeFlow.ast?.[section]) && activeFlow.ast[section].length
      ? activeFlow.ast[section]
      : [{ condition: defaultConditionTree(flowType, section) }]

    return (
      <div className="studio-builder-card">
        <div className="studio-builder-card-head">
          <div>
            <h3>{title}</h3>
            <p>{description}</p>
          </div>
          <button className="studio-secondary-btn" onClick={() => addBlock(section)}>
            Add block
          </button>
        </div>
        <div className="studio-block-list">
          {blocks.map((block, blockIndex) => {
            const conditionTree = Array.isArray(block.condition) && block.condition.length ? block.condition : defaultConditionTree(flowType, section)
            return (
              <div key={blockIndex} className="studio-condition-block">
                <div className="studio-condition-block-head">
                  <span>{section === 'match' ? 'Entry block' : 'Exit block'} {blockIndex + 1}</span>
                  <div className="studio-block-actions">
                    {section === 'match' && (
                      <select className="studio-small-select" value={block.enter_price || 'touch'} onChange={(e) => updateBlock(section, blockIndex, { enter_price: e.target.value })}>
                        <option value="touch">Match by touch</option>
                        <option value="close">Match by close</option>
                      </select>
                    )}
                    <button className="studio-inline-btn" onClick={() => addOrGroup(section, blockIndex)}>
                      Add OR group
                    </button>
                    <button className="studio-inline-danger" disabled={blocks.length <= 1} onClick={() => removeBlock(section, blockIndex)}>
                      Remove block
                    </button>
                  </div>
                </div>
                <div className="studio-or-list">
                  {conditionTree.map((group, groupIndex) => (
                    <div key={groupIndex} className="studio-or-group">
                      <div className="studio-or-label">OR group {groupIndex + 1}</div>
                      {(Array.isArray(group) ? group : []).map((condition, conditionIndex) => renderConditionRow(section, blockIndex, groupIndex, condition, conditionIndex))}
                      <button className="studio-inline-btn" onClick={() => addAndCondition(section, blockIndex, groupIndex)}>
                        Add AND condition
                      </button>
                    </div>
                  ))}
                </div>
                <div className="studio-readable-condition">
                  <Cond node={conditionTree} />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const handleSimulate = async () => {
    if (simLoading) return
    const startTs = dateToStartTs(startDate)
    const endTs = dateToEndTs(endDate)
    if (!Number.isFinite(startTs) || !Number.isFinite(endTs) || endTs <= startTs) {
      setSimError(new Error('Cần chọn start/end date hợp lệ trước khi simulate.'))
      setRightTab('results')
      return
    }

    setSimLoading(true)
    setSimError(null)
    setSimResults(null)
    setRightTab('results')

    try {
      const res = await fetch(`${API_BASE}/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: activeTab.symbol,
          start_ts: startTs,
          end_ts: endTs,
          flows: activeTab.flows,
          initial_capital: activeTab.settings.initial_capital,
          leverage: activeTab.settings.leverage,
          using_match_price: activeTab.settings.using_match_price,
          max_open_trades: activeTab.settings.max_open_trades,
          stop_loss_rate: activeTab.settings.stop_loss_rate,
          take_profit_rate: activeTab.settings.take_profit_rate,
          timeout: activeTab.settings.timeout,
          result_trade_limit: activeTab.settings.result_trade_limit,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Lỗi chạy mô phỏng Studio')
      setSimResults(data)
    } catch (err) {
      setSimError(err)
    } finally {
      setSimLoading(false)
    }
  }

  return (
    <div className="studio-root">
      <div className="studio-topbar">
        <div className="studio-tabs-bar">
          {tabs.map((tab) => (
            <div key={tab.id} className={`studio-tab-item ${tab.id === activeTabId ? 'active' : ''}`} onClick={() => setActiveTabId(tab.id)}>
              <span className="studio-tab-name">{tab.name}</span>
              {tabs.length > 1 && (
                <button className="studio-tab-close" onClick={(e) => closeTab(e, tab.id)} title="Đóng tab">
                  ×
                </button>
              )}
            </div>
          ))}
          <button className="studio-tab-add" onClick={addTab} title="Mở chiến lược mới">
            +
          </button>
        </div>

        <div className="studio-top-controls">
          <input className="studio-title-input" value={activeTab.name} onChange={(e) => updateActiveTab({ name: e.target.value })} placeholder="Tên chiến lược" />
          <select className="studio-select" value={activeTab.symbol} onChange={(e) => updateActiveTab({ symbol: e.target.value, startDate: '', endDate: '' })} title="Asset local PKL">
            {['cex', 'dex', 'legacy'].map((venue) => {
              const items = datasets.filter((d) => (d.venue || 'legacy') === venue)
              if (!items.length) return null
              const label = venue === 'cex' ? 'CEX · nến sàn (3 năm)' : venue === 'dex' ? 'DEX · pool on-chain' : 'Khác'
              return (
                <optgroup key={venue} label={label}>
                  {items.map((d) => (
                    <option key={d.symbol} value={d.symbol}>
                      {d.symbol}{d.exchange ? ` · ${d.exchange}` : ''}{d.network ? `/${d.network}` : ''}
                    </option>
                  ))}
                </optgroup>
              )
            })}
          </select>
          <input className="studio-date-input" type="date" value={startDate} onChange={(e) => updateActiveTab({ startDate: e.target.value })} />
          <input className="studio-date-input" type="date" value={endDate} onChange={(e) => updateActiveTab({ endDate: e.target.value })} />
          <button className="studio-btn-icon" onClick={() => setShowSettings(!showSettings)} title="Cài đặt mô phỏng">
            Settings
          </button>
          <button className="studio-btn-icon" onClick={toggleLayout} title="Đổi layout Studio">
            {layoutMode === 'wide' ? 'Focus' : 'Wide'}
          </button>
          <button className="studio-btn-icon" onClick={forkActiveTab} title="Fork strategy hiện tại thành tab mới">
            Fork
          </button>
          <button className="studio-btn-icon" onClick={saveActiveStrategy} title="Lưu strategy vào danh sách local">
            Save
          </button>
          <button className="studio-simulate-btn" onClick={handleSimulate} disabled={simLoading} title="Chạy mô phỏng AST">
            {simLoading ? <><span className="studio-btn-spinner"></span> Running...</> : 'Simulate'}
          </button>
        </div>
      </div>

      {saveMessage && <div className="studio-toast-banner">{saveMessage}</div>}

      {showSettings && (
        <div className="studio-settings-drawer">
          <div className="studio-settings-header">
            <b>Cài đặt NoraBT canonical simulation</b>
            <button className="studio-tab-close" onClick={() => setShowSettings(false)}>
              ×
            </button>
          </div>
          <div className="studio-settings-grid">
            <label>
              <span>Initial capital ($)</span>
              <input type="number" value={activeTab.settings.initial_capital} onChange={(e) => updateSettings({ initial_capital: parseNumber(e.target.value, 10000) })} />
            </label>
            <label>
              <span>Leverage</span>
              <input type="number" min="1" max="100" value={activeTab.settings.leverage} onChange={(e) => updateSettings({ leverage: parseNumber(e.target.value, 1) })} />
            </label>
            <label>
              <span>Max open trades</span>
              <input type="number" min="1" max="100" value={activeTab.settings.max_open_trades} onChange={(e) => updateSettings({ max_open_trades: parseNumber(e.target.value, 45) })} />
            </label>
            <label>
              <span>Hard StopLoss (%)</span>
              <input type="number" step="0.5" value={activeTab.settings.stop_loss_rate} onChange={(e) => updateSettings({ stop_loss_rate: parseNumber(e.target.value, 0) })} />
            </label>
            <label>
              <span>Hard TakeProfit (%)</span>
              <input type="number" step="0.5" value={activeTab.settings.take_profit_rate} onChange={(e) => updateSettings({ take_profit_rate: parseNumber(e.target.value, 0) })} />
            </label>
            <label>
              <span>Timeout (minutes)</span>
              <input type="number" min="0" value={activeTab.settings.timeout} onChange={(e) => updateSettings({ timeout: parseNumber(e.target.value, 0) })} />
            </label>
            <label>
              <span>Trade rows returned</span>
              <input type="number" min="1" max="2000" value={activeTab.settings.result_trade_limit} onChange={(e) => updateSettings({ result_trade_limit: parseNumber(e.target.value, 300) })} />
            </label>
            <label className="studio-check-label">
              <span>Using match price</span>
              <input type="checkbox" checked={activeTab.settings.using_match_price} onChange={(e) => updateSettings({ using_match_price: e.target.checked })} />
            </label>
          </div>
        </div>
      )}

      <div className={`studio-main-split ${layoutMode === 'focus' ? 'studio-main-split-focus' : ''}`}>
        <div className="studio-left-pane">
          <div className="studio-builder-workspace">
            <div className="studio-builder-hero">
              <div>
                <h2>Alpha Strategy Builder</h2>
                <p>Builder-first workflow: AST flows được validate rồi chạy qua BacktestEngine với 1m execution và 4h indicator context.</p>
              </div>
              <div className="studio-builder-meta">
                <span>Range: {startDate} → {endDate}</span>
                <span>{rangeDays > 0 ? `${rangeDays.toFixed(1)} ngày` : 'Chưa chọn range'}</span>
              </div>
            </div>

            {studioWarnings.length > 0 && (
              <div className="studio-warning-stack">
                {studioWarnings.map((warning) => (
                  <div key={warning} className="studio-warning-box">{warning}</div>
                ))}
              </div>
            )}

            <div className="studio-flow-toolbar">
              <div className="studio-flow-tabs">
                {flows.map((flow, index) => (
                  <button key={flow.id || index} className={`studio-flow-tab ${index === activeFlowIndex ? 'active' : ''}`} onClick={() => updateActiveTab({ activeFlowIndex: index })}>
                    <span className={`studio-flow-dot ${flow.ast?.type === 'SHORT' ? 'short' : 'long'}`}></span>
                    {flow.name || `Flow ${index + 1}`}
                    {flow.enabled === false && <span className="studio-flow-muted">off</span>}
                  </button>
                ))}
              </div>
              <div className="studio-flow-actions">
                <button className="studio-secondary-btn" onClick={() => addFlow('LONG')}>Add LONG</button>
                <button className="studio-secondary-btn" onClick={() => addFlow('SHORT')}>Add SHORT</button>
              </div>
            </div>

            {activeFlow && (
              <div className="studio-builder-card studio-flow-config-card">
                <div className="studio-flow-config-grid">
                  <label>
                    <span>Flow name</span>
                    <input value={activeFlow.name} onChange={(e) => updateFlow(activeFlowIndex, { name: e.target.value })} />
                  </label>
                  <label>
                    <span>Position type</span>
                    <select value={activeFlow.ast?.type || 'LONG'} onChange={(e) => updateFlow(activeFlowIndex, (flow) => ({ ...flow, ast: { ...(flow.ast || {}), type: e.target.value } }))}>
                      <option value="LONG">LONG</option>
                      <option value="SHORT">SHORT</option>
                    </select>
                  </label>
                  <label className="studio-check-label compact">
                    <span>Enabled</span>
                    <input type="checkbox" checked={activeFlow.enabled !== false} onChange={(e) => updateFlow(activeFlowIndex, { enabled: e.target.checked })} />
                  </label>
                  <button className="studio-inline-danger" disabled={flows.length <= 1} onClick={() => removeFlow(activeFlowIndex)}>
                    Remove flow
                  </button>
                </div>
              </div>
            )}

            {renderConditionSection('match', 'Match / Entry', 'Điều kiện mở vị thế. Mỗi OR group là một nhánh; các dòng bên trong nhánh là AND conditions.')}
            {renderConditionSection('stop', 'Stop / Exit', 'Điều kiện đóng vị thế ngoài hard SL/TP. Backend sẽ kết hợp toàn bộ blocks khi chạy PositionTracker.')}
          </div>
        </div>

        <div className="studio-right-pane">
          <div className="studio-toolkit-nav">
            {['samples', 'strategies', 'results', 'data', 'features', 'operators', 'ast'].map((tab) => (
              <button key={tab} className={`studio-toolkit-tab ${rightTab === tab ? 'active' : ''}`} onClick={() => setRightTab(tab)}>
                {tab === 'samples' ? 'Samples' : tab === 'strategies' ? 'Strategy List' : tab === 'results' ? 'Results' : tab === 'data' ? 'Data' : tab === 'features' ? 'Features' : tab === 'operators' ? 'Operators' : 'AST'}
                {tab === 'results' && simResults && <span className="studio-badge-dot"></span>}
                {tab === 'strategies' && savedStrategies.length > 0 && <span className="studio-badge-count">{savedStrategies.length}</span>}
              </button>
            ))}
          </div>

          <div className="studio-toolkit-content">
            {rightTab === 'samples' && (
              <div className="studio-samples-view">
                <div className="studio-samples-filter-bar">
                  <input className="studio-search-input" placeholder="Search samples by name, desc, tag..." value={sampleSearch} onChange={(e) => setSampleSearch(e.target.value)} />
                  <select className="studio-category-select" value={sampleCategory} onChange={(e) => setSampleCategory(e.target.value)}>
                    {categories.map((category) => (
                      <option key={category} value={category}>{category === 'ALL' ? 'Tất cả' : category}</option>
                    ))}
                  </select>
                </div>
                <div className="studio-samples-list">
                  {filteredSamples.map((sample) => (
                    <div key={sample.id} className="studio-sample-card">
                      <div className="studio-sample-header">
                        <div className="studio-sample-title">{sample.name}</div>
                        <span className="studio-sample-tag">{sample.category}</span>
                      </div>
                      <p className="studio-sample-desc">{sample.description}</p>
                      <div className="studio-sample-meta-line">
                        <span>{sample.execution_frame || '1m'} execution</span>
                        <span>{sample.indicator_frame || '4h'} indicator</span>
                        <span>{(sample.flows || []).length} flow</span>
                      </div>
                      <div className="studio-sample-footer">
                        <div className="studio-pill-tags">
                          {(sample.tags || []).map((tag) => <span key={tag} className="studio-mini-tag">#{tag}</span>)}
                        </div>
                        <button className="studio-use-sample-btn" onClick={() => loadSample(sample)} title="Nạp AST sample vào Builder">
                          Nạp Builder
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {rightTab === 'strategies' && (
              <div className="studio-strategy-list-view">
                <div className="studio-data-header">
                  <b>Strategy List</b>
                  <button className="studio-use-sample-btn" onClick={saveActiveStrategy}>Save current</button>
                </div>
                {savedStrategies.length === 0 ? (
                  <div className="studio-empty-state">Chưa có strategy đã lưu. Bấm Save để giữ lại bản đang build, hoặc Fork để thử biến thể mới.</div>
                ) : (
                  <div className="studio-samples-list">
                    {savedStrategies.map((item) => (
                      <div key={item.id} className="studio-sample-card">
                        <div className="studio-sample-header">
                          <div className="studio-sample-title">{item.name}</div>
                          <span className="studio-sample-tag">{item.symbol || 'LOCAL'}</span>
                        </div>
                        <p className="studio-sample-desc">{new Date(item.saved_at).toLocaleString()} · {(item.tab?.flows || []).length} flow</p>
                        <div className="studio-sample-footer">
                          <button className="studio-use-sample-btn" onClick={() => loadSavedStrategy(item)}>Open</button>
                          <button className="studio-inline-danger" onClick={() => deleteSavedStrategy(item.id)}>Delete</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {rightTab === 'results' && (
              <StudioResults
                results={simResults}
                loading={simLoading}
                error={simError}
                onSendToBase={handleSendToBase}
              />
            )}

            {rightTab === 'data' && (
              <div className="studio-data-view">
                <div className="studio-data-header">
                  <b>Local PKL datasets</b>
                  <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>Required: 1m + 4h</span>
                </div>
                <div className="studio-datasets-grid">
                  {datasets.map((dataset) => {
                    const isActive = activeTab.symbol === dataset.asset || activeTab.symbol === dataset.symbol
                    return (
                      <div key={dataset.asset} className={`studio-dataset-card ${isActive ? 'active' : ''}`}>
                        <div className="studio-dataset-top">
                          <span className="studio-dataset-symbol">{dataset.asset}</span>
                          <span className="studio-dataset-range">{dataset.date_range}</span>
                        </div>
                        <div className="studio-dataset-stats">
                          <span>1m: {(dataset.frame_summaries?.['1m']?.candles || 0).toLocaleString()}</span>
                          <span>4h: {(dataset.frame_summaries?.['4h']?.candles || 0).toLocaleString()}</span>
                        </div>
                        {(dataset.warnings || []).map((warning) => <div key={warning} className="studio-dataset-warning">{warning}</div>)}
                        <div className="studio-timeframes-pill-wrap">
                          {(dataset.timeframes || []).map((tf) => (
                            <span key={tf} className={`studio-tf-badge ${['1m', '4h'].includes(tf) ? 'active' : ''}`}>{tf}</span>
                          ))}
                        </div>
                        <button className="studio-use-sample-btn" onClick={() => {
                          const nextRange = rangeFromDataset(dataset)
                          updateActiveTab({ symbol: dataset.symbol || dataset.asset, startDate: nextRange.startDate, endDate: nextRange.endDate })
                        }}>
                          Dùng dataset
                        </button>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {rightTab === 'features' && (
              <div className="studio-features-view">
                <div className="studio-toolkit-section-title">Feature nodes backend đang hỗ trợ</div>
                <div className="studio-features-list">
                  {features.map((feature) => (
                    <div key={feature.id || feature.name} className="studio-feature-card">
                      <div className="studio-feature-header">
                        <span className="studio-feature-name">{feature.name}</span>
                        <span className="studio-feature-cat">{feature.category}</span>
                      </div>
                      <p className="studio-feature-desc">{feature.description}</p>
                      <div className="studio-column-list">
                        {(feature.columns || []).map((column) => <span key={column} className="studio-mini-tag">{feature.frame || 'node'}:{column}</span>)}
                      </div>
                      <div className="studio-node-chip-list">
                        {(feature.nodes || []).map((item) => (
                          <span key={item.label} className="studio-node-chip">{item.label}</span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {rightTab === 'operators' && (
              <div className="studio-operators-view">
                <div className="studio-toolkit-section-title">Operators AST hợp lệ</div>
                <div className="studio-operators-list">
                  {operators.map((operator) => (
                    <div key={operator.id || operator.name} className="studio-operator-card">
                      <div className="studio-operator-header">
                        <span className="studio-operator-name">{operator.name}</span>
                        <span className="studio-operator-symbol">{operator.category}</span>
                      </div>
                      <p className="studio-operator-desc">{operator.description}</p>
                      <div className="studio-code-snippet"><code>{JSON.stringify(operator.example)}</code></div>
                      {operator.operators && <div className="studio-column-list">{operator.operators.map((op) => <span key={op} className="studio-mini-tag">{op}</span>)}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {rightTab === 'ast' && (
              <div className="studio-ast-view">
                <div className="studio-toolkit-section-title">AST Preview</div>
                <div className="studio-ast-summary">
                  {flows.map((flow, index) => (
                    <div key={flow.id || index} className="studio-ast-flow-preview">
                      <b>{flow.name}</b>
                      <span>{flow.ast?.type || 'LONG'} · {flow.enabled === false ? 'disabled' : 'enabled'}</span>
                      <div className="studio-readable-condition"><Cond node={flow.ast?.match?.[0]?.condition || []} /></div>
                    </div>
                  ))}
                </div>
                <div className="studio-ast-json-editor">
                  <StudioEditor code={JSON.stringify(astPreview, null, 2)} readOnly disabled={simLoading} placeholder="AST JSON preview" />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
