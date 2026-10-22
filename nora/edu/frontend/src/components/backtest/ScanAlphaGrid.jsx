import React, { useState, useMemo } from 'react'
import { fmtNum } from '../../lib/format'
import { Spinner } from '../ui'

/**
 * Danh mục 3 Chiến lược cốt lõi với cấu trúc tham số chuẩn xác 100% khớp Nora Backtest Engine
 * và phân chia chuẩn định lượng Sova:
 * - 1. CHỈ BÁO KỸ THUẬT (INDICATOR: EMA, ATR, High/Low Vol Factor, Delta, RSI, BB)
 * - 2. QUẢN LÝ VỊ THẾ & RỦI RO (POSITION SIZING - PS: IR, ER, OR, Leverage, Layers)
 * - 3. THỰC THI & THOÁT LỆNH (BUY/SELL ENGINE & EXIT: SL, TP, Trailing Stop, Cooldown)
 *
 * Tính năng chuẩn Sova:
 * - Không giới hạn số lượng tổ hợp Alpha: từ vài chục đến 500k, 700k, 1M+ Alpha
 * - Đặt tên chiến dịch Backtest (Campaign Name)
 * - Quy trình tuần tự: Phải [1. Tạo tổ hợp Alpha] trước thì mới xuất hiện nút [2. Run Backtest] và [Lưu cấu hình JSON]
 * - Toàn bộ thông số và từng dòng đều được căn giữa hoàn hảo (Centered Alignment)
 */
const CORE_STRATEGIES = [
  {
    id: 'kema',
    name: 'Trend Following (KEMA)',
    tag: 'Động lượng xu hướng',
    desc: 'Bắt xu hướng động lượng theo kênh Keltner (KEMA): mở vị thế khi giá phá dải kênh, kết hợp dời chặn lỗ Trailing Stop ATR và quản lý rủi ro đa tầng (Position Sizing IR/ER).',
    side: 'Long + Short',
    groups: [
      {
        id: 'indicator',
        name: '1. CHỈ BÁO KỸ THUẬT (INDICATOR)',
        badge: 'Keltner Channel',
        params: [
          { key: 'sig.ema_n', label: 'Chu kỳ EMA', start: 20, end: 50, step: 10, unit: 'nến', help: 'Chu kỳ EMA đường giữa kênh Keltner' },
          { key: 'sig.atr_n', label: 'Chu kỳ ATR', start: 10, end: 14, step: 2, unit: 'nến', help: 'ATR đo độ rộng biên độ kênh' },
          { key: 'sig.k_up', label: 'High Vol Factor (k_up)', start: 1.5, end: 2.5, step: 0.5, unit: '× ATR', help: 'Hệ số dải trên = EMA + k_up × ATR' },
          { key: 'sig.k_dn', label: 'Low Vol Factor (k_dn)', start: 1.5, end: 2.5, step: 0.5, unit: '× ATR', help: 'Hệ số dải dưới = EMA - k_dn × ATR' },
        ],
      },
      {
        id: 'position',
        name: '2. QUẢN LÝ VỊ THẾ & RỦI RO (POSITION SIZING - PS)',
        badge: 'Risk Engine',
        params: [
          { key: 'risk_per_trade_pct', label: 'Initial Risk - IR', start: 0.5, end: 1.5, step: 0.5, unit: '% vốn', help: 'Mức rủi ro ban đầu mở mỗi vị thế' },
          { key: 'max_notional_pct', label: 'Equity Risk - ER', start: 100, end: 300, step: 100, unit: '% vốn', help: 'Trần giá trị danh nghĩa vị thế mở' },
          { key: 'leverage', label: 'Đòn bẩy ký quỹ', start: 3, end: 5, step: 1, unit: 'x', help: 'Đòn bẩy trần cho phép sử dụng' },
          { key: 'sig.use_delta', label: 'Delta Breakout', start: 0.0, end: 0.1, step: 0.1, unit: '%', help: 'Ngưỡng chênh lệch Delta phá vỡ dải' },
        ],
      },
      {
        id: 'exit',
        name: '3. THỰC THI & THOÁT LỆNH (BUY/SELL ENGINE & EXIT)',
        badge: 'Order Execution',
        params: [
          { key: 'stop_loss_rate', label: 'Cắt lỗ Stop Loss (SL)', start: 2.0, end: 3.0, step: 0.5, unit: '× ATR', help: 'Khoảng cách dừng lỗ theo số lần ATR' },
          { key: 'take_profit_rate', label: 'Chốt lời Take Profit (TP)', start: 0.0, end: 0.0, step: 1.0, unit: '× ATR', help: 'Chốt lời cố định (0 = để trend chạy)' },
          { key: 'trailing_stop', label: 'Trailing Stop (TS)', start: 1.5, end: 2.0, step: 0.5, unit: '× ATR', help: 'Khoảng cách dời lỗ theo đỉnh/đáy' },
          { key: 'cooldown', label: 'Thời gian nghỉ Cooldown', start: 60, end: 60, step: 30, unit: 'phút', help: 'Thời gian chờ trước khi nhận tín hiệu mới' },
        ],
      },
    ],
  },
  {
    id: 'sideway',
    name: 'Sideway Mean-Reversion',
    tag: 'Đảo chiều biên độ',
    desc: 'Bắt đảo chiều trong vùng biên độ khi thị trường đi ngang (ER thấp): RSI chạm cực trị và giá đóng cửa vượt ngoài dải Bollinger Bands.',
    side: 'Long + Short',
    groups: [
      {
        id: 'indicator',
        name: '1. CHỈ BÁO KỸ THUẬT (INDICATOR)',
        badge: 'RSI & Bollinger',
        params: [
          { key: 'sig.rsi_n', label: 'Chu kỳ RSI', start: 14, end: 14, step: 2, unit: 'nến', help: 'Số nến tính dao động RSI' },
          { key: 'sig.rsi_lo', label: 'RSI quá bán (Oversold)', start: 20, end: 30, step: 5, unit: 'điểm', help: 'Ngưỡng RSI kích hoạt mua' },
          { key: 'sig.rsi_hi', label: 'RSI quá mua (Overbought)', start: 70, end: 80, step: 5, unit: 'điểm', help: 'Ngưỡng RSI kích hoạt bán' },
          { key: 'sig.bb_n', label: 'Chu kỳ Bollinger', start: 20, end: 20, step: 5, unit: 'nến', help: 'Số nến dải Bollinger Bands' },
        ],
      },
      {
        id: 'position',
        name: '2. QUẢN LÝ VỊ THẾ & RỦI RO (POSITION SIZING - PS)',
        badge: 'Risk Engine',
        params: [
          { key: 'risk_per_trade_pct', label: 'Initial Risk - IR', start: 0.5, end: 1.0, step: 0.5, unit: '% vốn', help: 'Rủi ro trần mỗi lệnh' },
          { key: 'max_notional_pct', label: 'Equity Risk - ER', start: 100, end: 200, step: 100, unit: '% vốn', help: 'Trần danh nghĩa vị thế' },
          { key: 'leverage', label: 'Đòn bẩy ký quỹ', start: 2, end: 3, step: 1, unit: 'x', help: 'Đòn bẩy sử dụng' },
          { key: 'sig.bb_k', label: 'Độ rộng Bollinger (k)', start: 2.0, end: 2.0, step: 0.2, unit: 'σ', help: 'Độ lệch chuẩn dải biên' },
        ],
      },
      {
        id: 'exit',
        name: '3. THỰC THI & THOÁT LỆNH (BUY/SELL ENGINE & EXIT)',
        badge: 'Order Execution',
        params: [
          { key: 'stop_loss_rate', label: 'Cắt lỗ Stop Loss (SL)', start: 2.5, end: 3.0, step: 0.5, unit: '× ATR', help: 'Cắt lỗ bảo vệ vị thế' },
          { key: 'take_profit_rate', label: 'Chốt lời Take Profit (TP)', start: 1.5, end: 2.0, step: 0.5, unit: '× ATR', help: 'Mục tiêu chốt lời' },
          { key: 'sig.er_max', label: 'Lọc đi ngang ER Gate', start: 0.35, end: 0.40, step: 0.05, unit: '', help: 'Chỉ vào lệnh khi ER dưới ngưỡng' },
          { key: 'cooldown', label: 'Thời gian nghỉ Cooldown', start: 60, end: 60, step: 30, unit: 'phút', help: 'Khoảng chờ trước khi vào lại' },
        ],
      },
    ],
  },
  {
    id: 'dca',
    name: 'DCA Rebound (Safety Grid)',
    tag: 'Gom trung bình giá',
    desc: 'Thuật toán gom vị thế hồi phục khi quá bán: chỉ dồn thêm tầng theo bước ATR khi thị trường vẫn đi ngang (ER & ADX thấp), cắt lỗ toàn bộ rổ.',
    side: 'Long-only',
    groups: [
      {
        id: 'indicator',
        name: '1. CHỈ BÁO KỸ THUẬT (INDICATOR)',
        badge: 'Trigger Signal',
        params: [
          { key: 'sig.rsi_n', label: 'Chu kỳ RSI', start: 14, end: 14, step: 2, unit: 'nến', help: 'Số nến tính RSI' },
          { key: 'sig.rsi_lo', label: 'RSI quá bán tầng 1', start: 25, end: 35, step: 5, unit: 'điểm', help: 'Ngưỡng kích hoạt lệnh cơ sở' },
          { key: 'sig.bb_n', label: 'Chu kỳ Bollinger', start: 20, end: 20, step: 5, unit: 'nến', help: 'Số nến dải Bollinger' },
          { key: 'sig.bb_k', label: 'Độ rộng Bollinger (k)', start: 2.0, end: 2.0, step: 0.2, unit: 'σ', help: 'Độ rộng dải đo biên độ' },
        ],
      },
      {
        id: 'position',
        name: '2. QUẢN LÝ VỊ THẾ DỒN (POSITION SIZING & GRID)',
        badge: 'Multi-layer Grid',
        params: [
          { key: 'dca_step_pct', label: 'Bước giá dồn tầng', start: 1.5, end: 2.5, step: 0.5, unit: '%', help: 'Khoảng cách dồn thêm tầng' },
          { key: 'dca_max_layers', label: 'Số tầng dồn tối đa', start: 2, end: 4, step: 1, unit: 'tầng', help: 'Số tầng DCA cho phép' },
          { key: 'dca_size_multiplier', label: 'Hệ số tăng khối lượng', start: 1.2, end: 1.5, step: 0.3, unit: 'x', help: 'Hệ số nhân vị thế tầng sau' },
          { key: 'leverage', label: 'Đòn bẩy ký quỹ', start: 2, end: 3, step: 1, unit: 'x', help: 'Đòn bẩy sử dụng' },
        ],
      },
      {
        id: 'exit',
        name: '3. THỰC THI & THOÁT LỆNH (BUY/SELL ENGINE & EXIT)',
        badge: 'Order Execution',
        params: [
          { key: 'take_profit_rate', label: 'Chốt lời trung bình rổ (TP)', start: 1.5, end: 2.0, step: 0.5, unit: '× ATR', help: 'Chốt lời từ giá trung bình' },
          { key: 'stop_loss_rate', label: 'Cắt lỗ toàn bộ rổ (SL)', start: 4.0, end: 5.0, step: 1.0, unit: '× ATR', help: 'Cắt lỗ cả rổ từ giá trung bình' },
          { key: 'risk_per_trade_pct', label: 'Initial Risk tầng 1', start: 0.5, end: 0.5, step: 0.1, unit: '% vốn', help: 'Rủi ro mở tầng 1' },
          { key: 'sig.gate_adx_max', label: 'Ngưỡng chặn ADX Gate', start: 25, end: 25, step: 5, unit: 'điểm', help: 'Ngừng dồn khi xu hướng mạnh' },
        ],
      },
    ],
  },
]

function calcCount(start, end, step) {
  const s = Number(start)
  const e = Number(end)
  const st = Number(step)
  if (!st || st <= 0 || s > e) return 1
  return Math.max(1, Math.floor((e - s) / st + 1e-9) + 1)
}

/**
 * ScanAlphaGrid: Trình tạo và quét tổ hợp Alpha chuẩn phong cách định lượng Sova
 * - Không giới hạn số lượng tổ hợp Alpha (hỗ trợ hàng trăm nghìn đến triệu Alpha)
 * - Đặt tên chiến dịch Backtest rõ ràng
 * - Toàn bộ thông số căn giữa đẹp mắt, tối ưu bố cục 3-4 mục trên 1 hàng
 * - Quy trình 2 bước: Bắt buộc Gen Alpha trước -> Sau đó mới xuất hiện nút Run Backtest
 */
export default function ScanAlphaGrid({ onLaunchScan, isScanning = false }) {
  const [selectedStratId, setSelectedStratId] = useState('kema')
  const curStrat = CORE_STRATEGIES.find((s) => s.id === selectedStratId) || CORE_STRATEGIES[0]

  // Tên đợt Backtest / Chiến dịch (Campaign Name)
  const [campaignName, setCampaignName] = useState(() => {
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
    return `KEMA_SCAN_${today}_01`
  })

  // Cấu hình thị trường và vốn
  const [symbols, setSymbols] = useState(['BTC@perp'])
  const [timeframe, setTimeframe] = useState('15m')
  const [capital, setCapital] = useState(10000)

  // Trạng thái đã Gen Alpha hay chưa (CHỈ KHI GEN XONG MỚI HIỆN NÚT RUN BACKTEST)
  const [isGenerated, setIsGenerated] = useState(false)
  const [generatedTimestamp, setGeneratedTimestamp] = useState(null)
  const [scanDoneMsg, setScanDoneMsg] = useState(null)

  // Khởi tạo state grid cho từng chiến lược
  const [gridValues, setGridValues] = useState(() => {
    const initial = {}
    CORE_STRATEGIES.forEach((s) => {
      initial[s.id] = {}
      ;(s.groups || []).forEach((g) => {
        g.params.forEach((p) => {
          initial[s.id][p.key] = { start: p.start, end: p.end, step: p.step }
        })
      })
    })
    return initial
  })

  const curValues = gridValues[selectedStratId] || {}

  const handleParamChange = (key, field, val) => {
    const num = Number(val)
    setGridValues((prev) => ({
      ...prev,
      [selectedStratId]: {
        ...prev[selectedStratId],
        [key]: {
          ...prev[selectedStratId][key],
          [field]: Number.isNaN(num) ? val : num,
        },
      },
    }))
    // Khi thay đổi bất kỳ tham số nào, reset trạng thái bắt buộc phải Gen Alpha lại!
    setIsGenerated(false)
    setScanDoneMsg(null)
  }

  const handleResetDefaults = () => {
    setGridValues((prev) => {
      const resetOne = {}
      ;(curStrat.groups || []).forEach((g) => {
        g.params.forEach((p) => {
          resetOne[p.key] = { start: p.start, end: p.end, step: p.step }
        })
      })
      return { ...prev, [selectedStratId]: resetOne }
    })
    setIsGenerated(false)
    setScanDoneMsg(null)
  }

  // Danh sách phẳng tất cả tham số của chiến lược hiện tại
  const allParams = useMemo(() => {
    return (curStrat.groups || []).flatMap((g) => g.params)
  }, [curStrat])

  // Tính số lượng biến thể từng nhóm và tổng biến thể
  const groupStats = useMemo(() => {
    return (curStrat.groups || []).map((group) => {
      let combos = 1
      let active = 0
      group.params.forEach((p) => {
        const v = curValues[p.key] || { start: p.start, end: p.end, step: p.step }
        const count = calcCount(v.start, v.end, v.step)
        combos *= count
        if (count > 1) active += 1
      })
      return { id: group.id, name: group.name, combos, active, totalParams: group.params.length }
    })
  }, [curStrat, curValues])

  const { totalVariants, activeParamCount } = useMemo(() => {
    let total = 1
    let active = 0
    allParams.forEach((p) => {
      const v = curValues[p.key] || { start: p.start, end: p.end, step: p.step }
      const count = calcCount(v.start, v.end, v.step)
      total *= count
      if (count > 1) active += 1
    })
    return { totalVariants: total, activeParamCount: active }
  }, [allParams, curValues])

  // Bước 1: Tạo tổ hợp Alpha (Gen Alpha)
  const handleGenerateAlpha = () => {
    setIsGenerated(true)
    setGeneratedTimestamp(new Date().toLocaleTimeString())
    setScanDoneMsg(`Đã tạo thành công ${fmtNum(totalVariants, 0)} tổ hợp Alpha cho chiến dịch "${campaignName}"!`)
  }

  // Bước 2: Khởi chạy Run Backtest (Chỉ gọi được sau khi đã Gen)
  const handleRunBacktest = () => {
    setScanDoneMsg(null)
    if (onLaunchScan) {
      onLaunchScan({
        campaignName: campaignName || `${curStrat.name}_SCAN`,
        strategyId: selectedStratId,
        strategyName: curStrat.name,
        paramsGrid: curValues,
        totalVariants,
        capital,
        symbols,
        timeframe,
      })
    } else {
      setScanDoneMsg(`Đã nạp lệnh Run Backtest ${fmtNum(totalVariants, 0)} Alpha vào hệ thống kiểm định.`)
    }
  }

  // Xuất file cấu hình tổ hợp
  const handleExportConfigs = () => {
    const exportData = {
      campaign_name: campaignName,
      strategy_id: selectedStratId,
      strategy_name: curStrat.name,
      market: symbols[0],
      timeframe,
      capital,
      total_alphas: totalVariants,
      created_at: new Date().toISOString(),
      parameter_ranges: curValues,
    }
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${campaignName}_${totalVariants}_alphas.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      {/* Khung Card bọc toàn bộ giao diện quét tham số */}
      <div
        style={{
          background: 'var(--n-surface)',
          borderRadius: 8,
          border: '1px solid var(--n-line)',
          overflow: 'hidden',
          boxShadow: 'var(--n-shadow)',
        }}
      >
        {/* THANH CẤU HÌNH CHIẾN DỊCH, THỊ TRƯỜNG & VỐN (TOP BAR) - CĂN GIỮA TOÀN BỘ */}
        <div
          style={{
            padding: '12px 18px',
            borderBottom: '1px solid var(--n-line)',
            background: 'var(--n-surface-2)',
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 16,
            textAlign: 'center',
          }}
        >
          {/* Nhập tên Backtest */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
            <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--n-ink)', whiteSpace: 'nowrap' }}>
              Tên Backtest:
            </span>
            <input
              type="text"
              className="n-in sm"
              value={campaignName}
              onChange={(e) => setCampaignName(e.target.value)}
              placeholder="Đặt tên chiến dịch..."
              style={{
                width: 220,
                fontSize: 12.5,
                height: 32,
                fontWeight: 700,
                background: 'var(--n-surface)',
                color: 'var(--n-accent, #d97706)',
                border: '1px solid var(--n-accent, #f59e0b)',
                borderRadius: 6,
                textAlign: 'center',
                fontFamily: 'monospace',
                letterSpacing: '0.02em',
              }}
            />
          </div>

          {/* Chọn kiểu chiến lược */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
            <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--n-ink)', whiteSpace: 'nowrap' }}>
              Chiến lược:
            </span>
            <select
              className="n-sel"
              value={selectedStratId}
              onChange={(e) => {
                const newId = e.target.value
                setSelectedStratId(newId)
                setCampaignName(`${newId.toUpperCase()}_SCAN_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}`)
                setIsGenerated(false)
                setScanDoneMsg(null)
              }}
              style={{
                fontSize: 12.5,
                fontWeight: 600,
                padding: '4px 10px',
                minWidth: 230,
                height: 32,
                background: 'var(--n-surface)',
                color: 'var(--n-ink)',
                borderColor: 'var(--n-line)',
                textAlign: 'center',
              }}
            >
              {CORE_STRATEGIES.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.tag})
                </option>
              ))}
            </select>
          </div>

          <span className="n-badge both" style={{ fontSize: 11, padding: '3px 8px', textAlign: 'center' }}>
            {curStrat.side}
          </span>

          <button
            type="button"
            className="n-btn sm"
            onClick={handleResetDefaults}
            style={{ fontSize: 11.5, padding: '0 10px', height: 28 }}
            title="Khôi phục lại khoảng giá trị mặc định của chiến lược"
          >
            Mặc định chuẩn
          </button>

          {/* Cặp coin, Khung nến & Vốn mô phỏng */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ fontSize: 12, color: 'var(--n-ink-2)', fontWeight: 600 }}>Thị trường:</span>
              <select
                className="n-sel sm"
                value={symbols[0]}
                onChange={(e) => setSymbols([e.target.value])}
                style={{ width: 115, fontSize: 12, height: 30, background: 'var(--n-surface)', textAlign: 'center' }}
              >
                <option value="BTC@perp">BTC@perp</option>
                <option value="ETH@perp">ETH@perp</option>
                <option value="SOL@perp">SOL@perp</option>
                <option value="BNB@perp">BNB@perp</option>
                <option value="XRP@perp">XRP@perp</option>
                <option value="DOGE@perp">DOGE@perp</option>
                <option value="ADA@perp">ADA@perp</option>
                <option value="AVAX@perp">AVAX@perp</option>
              </select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ fontSize: 12, color: 'var(--n-ink-2)', fontWeight: 600 }}>TF:</span>
              <select
                className="n-sel sm"
                value={timeframe}
                onChange={(e) => setTimeframe(e.target.value)}
                style={{ width: 75, fontSize: 12, height: 30, background: 'var(--n-surface)', textAlign: 'center' }}
              >
                <option value="15m">15m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
              </select>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ fontSize: 12, color: 'var(--n-ink-2)', fontWeight: 600 }}>Vốn:</span>
              <input
                type="number"
                className="n-in sm"
                value={capital}
                onChange={(e) => setCapital(Number(e.target.value))}
                style={{ width: 85, fontSize: 12, height: 30, background: 'var(--n-surface)', fontWeight: 600, textAlign: 'center' }}
              />
              <span style={{ fontSize: 11.5, color: 'var(--n-ink-3)' }}>USDT</span>
            </div>
          </div>
        </div>

        {/* Dòng mô tả chiến lược - CĂN GIỮA */}
        <div
          style={{
            padding: '9px 18px',
            background: 'var(--n-surface-3)',
            borderBottom: '1px solid var(--n-line)',
            fontSize: 12.5,
            color: 'var(--n-ink-2)',
            lineHeight: 1.45,
            textAlign: 'center',
          }}
        >
          {curStrat.desc}
        </div>

        {/* BANNER THÔNG BÁO TẠO THÀNH CÔNG TỔ HỢP ALPHA (CHỈ HIỆN KHI ĐÃ GEN XONG) */}
        {isGenerated && (
          <div
            style={{
              padding: '14px 20px',
              background: 'var(--n-accent-wash, rgba(56, 189, 248, 0.1))',
              borderBottom: '1px solid var(--n-accent, #38bdf8)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexWrap: 'wrap',
              gap: 16,
              textAlign: 'center',
            }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--n-ink)' }}>
                🎉 Đã tạo thành công <span style={{ color: 'var(--n-accent)', fontSize: 16 }}>{fmtNum(totalVariants, 0)}</span> tổ hợp Alpha cho chiến dịch <span className="mono" style={{ color: 'var(--n-accent)' }}>"{campaignName}"</span>
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--n-ink-2)' }}>
                Thời gian tạo: {generatedTimestamp} · Thị trường: {symbols[0]} · Khung nến: {timeframe} · Vốn mô phỏng: {fmtNum(capital, 0)} USDT
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
              <button
                type="button"
                className="n-btn sm"
                onClick={handleExportConfigs}
                style={{ fontSize: 12, padding: '0 12px', height: 32, textAlign: 'center' }}
                title="Tải về file cấu hình JSON của toàn bộ các tổ hợp Alpha này để lưu trữ"
              >
                📋 Lưu cấu hình JSON
              </button>

              <button
                type="button"
                className="n-btn primary"
                onClick={handleRunBacktest}
                disabled={isScanning}
                style={{
                  fontSize: 13,
                  padding: '0 20px',
                  height: 34,
                  fontWeight: 700,
                  boxShadow: '0 0 12px var(--n-accent-wash, rgba(56, 189, 248, 0.4))',
                  textAlign: 'center',
                }}
              >
                {isScanning ? <Spinner /> : `🚀 Khởi chạy Run Backtest (${fmtNum(totalVariants, 0)} Alpha)`}
              </button>
            </div>
          </div>
        )}

        {/* KHUNG CẤU HÌNH THAM SỐ: THIẾT KẾ 4 CỘT CHUẨN XÁC THEO SOVA */}
        <div style={{ padding: '16px 18px', display: 'grid', gap: 18 }}>
          {(curStrat.groups || []).map((group) => {
            const stat = groupStats.find((s) => s.id === group.id) || {}
            const groupCombos = stat.combos || 1
            const groupActive = stat.active || 0

            return (
              <div
                key={group.id}
                style={{
                  background: 'var(--n-surface)',
                  border: '1px solid var(--n-line)',
                  borderRadius: 8,
                  overflow: 'hidden',
                  textAlign: 'center',
                }}
              >
                {/* Banner nhóm tham số (Thanh ngang tiêu đề tinh gọn) */}
                <div
                  style={{
                    padding: '8px 16px',
                    background: 'var(--n-surface-2, #f3f4f6)',
                    borderBottom: '1px solid var(--n-line)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexWrap: 'wrap',
                    gap: 12,
                    textAlign: 'center',
                  }}
                >
                  <span
                    style={{
                      fontSize: 12.5,
                      fontWeight: 700,
                      letterSpacing: '0.03em',
                      textTransform: 'uppercase',
                      color: 'var(--n-ink, #334155)',
                    }}
                  >
                    {group.name}
                  </span>
                  <span
                    style={{
                      fontSize: 11,
                      padding: '2px 8px',
                      borderRadius: 4,
                      background: 'var(--n-surface)',
                      color: 'var(--n-ink-2)',
                      border: '1px solid var(--n-line)',
                      fontWeight: 600,
                      textAlign: 'center',
                    }}
                  >
                    {group.badge}
                  </span>
                  <span
                    className="mono"
                    style={{
                      fontSize: 11.5,
                      padding: '2px 10px',
                      borderRadius: 4,
                      background: groupActive > 0 ? 'var(--n-accent-wash, rgba(217, 119, 6, 0.1))' : 'var(--n-surface)',
                      color: groupActive > 0 ? 'var(--n-ink-2, #475569)' : 'var(--n-ink-3)',
                      border: '1px solid var(--n-line)',
                      fontWeight: 600,
                      textAlign: 'center',
                    }}
                  >
                    {groupActive > 0 ? `${fmtNum(groupCombos, 0)} tổ hợp nhóm` : 'Cố định 1 giá trị'}
                  </span>
                </div>

                {/* Bố cục 4 cột tham số thoáng đãng (Frameless 4-column row) */}
                <div
                  style={{
                    padding: '20px 24px',
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
                    gap: '20px 24px',
                    justifyContent: 'center',
                    alignItems: 'start',
                    maxWidth: 1400,
                    margin: '0 auto',
                  }}
                >
                  {group.params.map((p) => {
                    const v = curValues[p.key] || { start: p.start, end: p.end, step: p.step }
                    const count = calcCount(v.start, v.end, v.step)
                    const isActive = count > 1

                    return (
                      <div
                        key={p.key}
                        style={{
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          gap: 6,
                          textAlign: 'center',
                          width: '100%',
                        }}
                      >
                        {/* Tiêu đề & Tag đơn vị */}
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, flexWrap: 'wrap' }}>
                          <span
                            style={{
                              fontSize: 13,
                              fontWeight: 700,
                              color: 'var(--n-ink)',
                              lineHeight: 1.25,
                              textAlign: 'center',
                            }}
                          >
                            {p.label}
                          </span>
                          {p.unit && (
                            <span
                              style={{
                                fontSize: 10.5,
                                padding: '1px 6px',
                                borderRadius: 4,
                                background: 'var(--n-surface-2)',
                                color: 'var(--n-ink-2)',
                                border: '1px solid var(--n-line)',
                                fontWeight: 600,
                                textAlign: 'center',
                              }}
                            >
                              {p.unit}
                            </span>
                          )}
                        </div>

                        {/* Mã key tham số (Monospace) */}
                        <div
                          className="mono"
                          style={{
                            fontSize: 11,
                            color: 'var(--n-ink-3, #94a3b8)',
                            textAlign: 'center',
                          }}
                          title={p.help || p.key}
                        >
                          {p.key}
                        </div>

                        {/* Huy hiệu số mốc giá trị (Ví dụ: 4 mốc, 3 mốc, 1 cố định) */}
                        <div style={{ display: 'flex', justifyContent: 'center', margin: '2px 0 6px 0' }}>
                          <span
                            className="mono"
                            style={{
                              fontSize: 11,
                              padding: '2px 12px',
                              borderRadius: 12,
                              fontWeight: 600,
                              textAlign: 'center',
                              background: 'var(--n-surface-2)',
                              color: 'var(--n-ink-2)',
                              border: '1px solid var(--n-line)',
                            }}
                          >
                            {count} {isActive ? 'mốc' : 'cố định'}
                          </span>
                        </div>

                        {/* Tiêu đề 3 cột nhỏ: Bắt đầu | Kết thúc | Bước (Δ) */}
                        <div
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(3, 1fr)',
                            gap: 8,
                            width: '100%',
                            textAlign: 'center',
                          }}
                        >
                          <div style={{ fontSize: 11, color: 'var(--n-ink-3, #64748b)', fontWeight: 500 }}>
                            Bắt đầu
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--n-ink-3, #64748b)', fontWeight: 500 }}>
                            Kết thúc
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--n-ink-3, #64748b)', fontWeight: 500 }}>
                            Bước (Δ)
                          </div>
                        </div>

                        {/* 3 ô nhập Bắt đầu | Kết thúc | Bước (Δ) */}
                        <div
                          style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(3, 1fr)',
                            gap: 8,
                            width: '100%',
                          }}
                        >
                          <input
                            type="number"
                            step={p.step}
                            className="n-in"
                            value={v.start}
                            onChange={(e) => handleParamChange(p.key, 'start', e.target.value)}
                            style={{
                              width: '100%',
                              fontSize: 12.5,
                              padding: '4px',
                              textAlign: 'center',
                              height: 32,
                              background: 'var(--n-surface)',
                              border: '1px solid var(--n-line)',
                              borderRadius: 6,
                              color: 'var(--n-ink)',
                              fontWeight: 600,
                            }}
                          />
                          <input
                            type="number"
                            step={p.step}
                            className="n-in"
                            value={v.end}
                            onChange={(e) => handleParamChange(p.key, 'end', e.target.value)}
                            style={{
                              width: '100%',
                              fontSize: 12.5,
                              padding: '4px',
                              textAlign: 'center',
                              height: 32,
                              background: 'var(--n-surface)',
                              border: '1px solid var(--n-line)',
                              borderRadius: 6,
                              color: 'var(--n-ink)',
                              fontWeight: 600,
                            }}
                          />
                          <input
                            type="number"
                            step="any"
                            className="n-in"
                            value={v.step}
                            onChange={(e) => handleParamChange(p.key, 'step', e.target.value)}
                            style={{
                              width: '100%',
                              fontSize: 12.5,
                              padding: '4px',
                              textAlign: 'center',
                              height: 32,
                              background: 'var(--n-surface)',
                              border: '1px solid var(--n-line)',
                              borderRadius: 6,
                              color: 'var(--n-ink)',
                              fontWeight: 600,
                            }}
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>

        {/* THANH ĐIỀU KHIỂN DƯỚI: NÚT GEN ALPHA TRƯỚC -> XONG MỚI HIỆN NÚT RUN BACKTEST */}
        <div
          style={{
            padding: '14px 20px',
            borderTop: '2px solid var(--n-line)',
            background: 'var(--n-surface-2)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          {/* Tóm tắt thông tin tổ hợp */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span
              className="mono"
              style={{
                fontSize: 12,
                color: 'var(--n-ink-2)',
                background: 'var(--n-surface)',
                padding: '5px 12px',
                borderRadius: 4,
                border: '1px solid var(--n-line)',
                textAlign: 'center',
              }}
            >
              Đang quét: <b>{activeParamCount}</b>/{allParams.length} chiều tham số
            </span>

            <span
              className="n-badge brand"
              style={{
                fontSize: 13,
                padding: '6px 16px',
                fontWeight: 700,
                letterSpacing: '0.02em',
                background: 'var(--n-accent-wash)',
                color: 'var(--n-accent)',
                border: '1px solid var(--n-accent)',
                textAlign: 'center',
              }}
            >
              Tổng không gian: {fmtNum(totalVariants, 0)} Alpha
            </span>
          </div>

          {/* CÁC NÚT HÀNH ĐỘNG: BẮT BUỘC PHẢI GEN ALPHA TRƯỚC, XONG MỚI HIỆN NÚT RUN BACKTEST */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {scanDoneMsg && !isGenerated && (
              <span className="n-badge ok" style={{ fontSize: 12, padding: '4px 10px', textAlign: 'center' }}>
                {scanDoneMsg}
              </span>
            )}

            {/* Bước 1: Nút Tạo tổ hợp Alpha */}
            <button
              type="button"
              className={isGenerated ? 'n-btn' : 'n-btn primary'}
              onClick={handleGenerateAlpha}
              style={{
                fontSize: 13,
                padding: '0 18px',
                height: 36,
                fontWeight: 700,
                textAlign: 'center',
                ...(isGenerated
                  ? { borderColor: 'var(--n-accent)', color: 'var(--n-accent)', background: 'var(--n-surface)' }
                  : {}),
              }}
              title="Tính toán và sinh toàn bộ danh sách tổ hợp Alpha cho chiến dịch này"
            >
              {isGenerated
                ? `⚡ Tạo lại tổ hợp (${fmtNum(totalVariants, 0)})`
                : `⚡ 1. Tạo tổ hợp Alpha (${fmtNum(totalVariants, 0)})`}
            </button>

            {/* Bước 2: CHỈ XUẤT HIỆN SAU KHI ĐÃ GEN THÀNH CÔNG! */}
            {isGenerated && (
              <>
                <button
                  type="button"
                  className="n-btn sm"
                  onClick={handleExportConfigs}
                  style={{ fontSize: 12, padding: '0 12px', height: 36, textAlign: 'center' }}
                  title="Tải về file cấu hình JSON của toàn bộ các tổ hợp Alpha này"
                >
                  📋 Lưu cấu hình JSON
                </button>

                <button
                  type="button"
                  className="n-btn primary"
                  onClick={handleRunBacktest}
                  disabled={isScanning || totalVariants <= 0}
                  style={{
                    fontSize: 13,
                    padding: '0 22px',
                    height: 36,
                    fontWeight: 700,
                    textAlign: 'center',
                    boxShadow: '0 0 10px var(--n-accent-wash, rgba(56, 189, 248, 0.4))',
                  }}
                  title="Khởi chạy kiểm định Backtest cho toàn bộ tổ hợp Alpha đã tạo"
                >
                  {isScanning ? (
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <Spinner /> Đang chạy Backtest...
                    </span>
                  ) : (
                    `🚀 2. Run Backtest (${fmtNum(totalVariants, 0)} Alpha)`
                  )}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
