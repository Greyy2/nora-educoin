import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'
import useAsync from '../../hooks/useAsync'
import { getLiveBotChart } from '../../api'
import { Panel, Loading, ErrorState, Empty } from '../ui'
import { fmtTs, fmtVal, snapTime } from '../charts/chartFormat'
import { fmtNum, isNum } from '../../lib/format'

const base = (s) => String(s || '').split(/[@\-/_:]/)[0].toUpperCase()
const FRAMES = ['1m', '5m', '15m', '1h', '4h', '24h']
const EXIT = { SL: 'Cắt lỗ', TP: 'Chốt lời', TRAIL: 'Trailing', TIMEOUT: 'Hết hạn', SIGNAL: 'Tín hiệu thoát' }
const GROUP = { entry: 'Vào', dca: 'DCA', exit: 'Thoát' }
const grp = (k) => (k === 'ENTRY' ? 'entry' : k === 'DCA' ? 'dca' : 'exit')

function cssVar(el, k, d) { return getComputedStyle(el).getPropertyValue(k).trim() || d }
// lightweight-charts vẽ trục giờ theo UTC: lệch múi giờ để hiện GIỜ ĐỊA PHƯƠNG
const loc = (ms) => ms / 1000 - new Date(ms).getTimezoneOffset() * 60
const fmtLoc = (sec) => new Date(sec * 1000).toISOString().slice(5, 16).replace('T', ' ')
const sgn = (v) => (v > 0 ? '+' : '') + fmtVal(v)

// Helper tính bộ 3 đường EMA (EMA 9, EMA 21, EMA 50)
function computeEmas(candles, times) {
  const calcOne = (period) => {
    const k = 2 / (period + 1)
    let ema = candles[0][4]
    const out = []
    for (let i = 0; i < candles.length; i++) {
      const close = candles[i][4]
      ema = i === 0 ? close : close * k + ema * (1 - k)
      out.push({ time: times[i], value: Math.round(ema * 1e6) / 1e6 })
    }
    return out
  }
  return {
    ema9: calcOne(9),
    ema21: calcOne(21),
    ema50: calcOne(50),
  }
}

// Helper tính dải Bollinger Bands (chu kỳ 20, độ lệch k=2.0)
function computeBB(candles, times, period = 20, k = 2.0) {
  const upper = []
  const mid = []
  const lower = []
  for (let i = 0; i < candles.length; i++) {
    if (i < period - 1) continue
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) {
      sum += candles[j][4]
    }
    const m = sum / period
    let sumSq = 0
    for (let j = i - period + 1; j <= i; j++) {
      sumSq += (candles[j][4] - m) ** 2
    }
    const std = Math.sqrt(sumSq / period)
    mid.push({ time: times[i], value: Math.round(m * 1e6) / 1e6 })
    upper.push({ time: times[i], value: Math.round((m + k * std) * 1e6) / 1e6 })
    lower.push({ time: times[i], value: Math.round((m - k * std) * 1e6) / 1e6 })
  }
  return { upper, mid, lower }
}

// Helper tính kênh ATR (Kênh biên độ biến động ± 2 * ATR(14))
function computeATR(candles, times, period = 14) {
  const tr = []
  for (let i = 0; i < candles.length; i++) {
    const high = candles[i][2]
    const low = candles[i][3]
    if (i === 0) {
      tr.push(high - low)
    } else {
      const prevClose = candles[i - 1][4]
      tr.push(Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose)))
    }
  }
  let atr = tr[0]
  const upper = []
  const lower = []
  const atrVals = []
  for (let i = 0; i < candles.length; i++) {
    atr = (atr * (period - 1) + tr[i]) / period
    if (i >= period - 1) {
      const close = candles[i][4]
      atrVals.push({ time: times[i], value: Math.round(atr * 1e6) / 1e6 })
      upper.push({ time: times[i], value: Math.round((close + 2 * atr) * 1e6) / 1e6 })
      lower.push({ time: times[i], value: Math.round((close - 2 * atr) * 1e6) / 1e6 })
    }
  }
  return { upper, lower, atrVals }
}

function Chart({ candles, fills, replay, signals, trades, position, showSignals, showReplay, showLines, showEma, showBb, showAtr, startedAt }) {
  const containerRef = useRef(null)
  const tipRef = useRef(null)
  const chartInstanceRef = useRef(null)
  const seriesRef = useRef(null)
  const linesRef = useRef([])
  const priceLinesRef = useRef([])
  const [themeTick, setThemeTick] = useState(0)
  const [activeInd, setActiveInd] = useState(null)

  useEffect(() => {
    const mo = new MutationObserver(() => setThemeTick((n) => n + 1))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => mo.disconnect()
  }, [])

  // Khởi tạo chart 1 lần (chỉ huỷ khi đổi theme hoặc unmount)
  useEffect(() => {
    if (!containerRef.current) return undefined
    const el = containerRef.current
    const c = {
      bg: cssVar(el, '--n-surface', '#17171a'),
      text: cssVar(el, '--n-ink-2', '#aeaeb6'),
      grid: cssVar(el, '--n-line-soft', '#212126'),
      line: cssVar(el, '--n-line', '#2a2a30'),
      pos: cssVar(el, '--n-pos', '#10b981'),
      neg: cssVar(el, '--n-neg', '#f43f5e'),
      info: cssVar(el, '--n-info', '#3b82f6'),
      warn: cssVar(el, '--n-warn', '#f59e0b'),
    }
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { color: c.bg }, textColor: c.text, fontSize: 11 },
      grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: c.line, scaleMargins: { top: 0.15, bottom: 0.22 } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: c.line, rightOffset: 6 },
    })
    const candleSeries = chart.addCandlestickSeries({
      upColor: c.pos, downColor: c.neg, borderUpColor: c.pos, borderDownColor: c.neg, wickUpColor: c.pos, wickDownColor: c.neg,
      priceFormat: { type: 'custom', formatter: (v) => fmtVal(v), minMove: 1e-8 },
    })
    const volSeries = chart.addHistogramSeries({
      priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false,
    })
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } })

    chartInstanceRef.current = chart
    seriesRef.current = { candleSeries, volSeries, chart, colors: c }

    return () => {
      chart.remove()
      chartInstanceRef.current = null
      seriesRef.current = null
    }
  }, [themeTick])

  // Cập nhật dữ liệu nến, marker, vị thế, nối lệnh mượt mà không load lại canvas
  useEffect(() => {
    const inst = seriesRef.current
    if (!inst || !candles?.length) return
    const { candleSeries, volSeries, chart, colors: c } = inst
    const el = containerRef.current

    try {
      // 1. Chuẩn hoá nến: lọc số hợp lệ, sắp xếp tăng dần theo thời gian và khử trùng lặp
      const rawSorted = [...candles]
        .filter((x) => Array.isArray(x) && isNum(x[0]) && isNum(x[1]) && isNum(x[2]) && isNum(x[3]) && isNum(x[4]))
        .sort((a, b) => a[0] - b[0])

      const cleanCandles = []
      const seenTime = new Set()
      for (const item of rawSorted) {
        if (!seenTime.has(item[0])) {
          seenTime.add(item[0])
          cleanCandles.push(item)
        }
      }

      if (!cleanCandles.length) return

      const times = cleanCandles.map((x) => loc(x[0]))
      const frameSec = times.length > 1 ? Math.max(1, times[1] - times[0]) : 60

      // Binary search chuẩn xác: luôn trả về timestamp hợp lệ từ `times`
      const snap = (ms) => {
        if (!times.length || !isNum(ms)) return null
        const t = loc(ms)
        if (t <= times[0]) return times[0]
        if (t >= times[times.length - 1]) return times[times.length - 1]
        let low = 0, high = times.length - 1
        while (low <= high) {
          const mid = (low + high) >> 1
          if (times[mid] === t) return times[mid]
          if (times[mid] < t) low = mid + 1
          else high = mid - 1
        }
        const prev = times[high] ?? times[0]
        const next = times[low] ?? times[times.length - 1]
        return Math.abs(t - prev) <= Math.abs(next - t) ? prev : next
      }

      candleSeries.setData(cleanCandles.map((x, i) => ({ time: times[i], open: x[1], high: x[2], low: x[3], close: x[4] })))
      volSeries.setData(cleanCandles.map((x, i) => ({ time: times[i], value: isNum(x[5]) ? x[5] : 0, color: (x[4] >= x[1] ? c.pos : c.neg) + '55' })))

      // Xoá priceLines và lineSeries của render trước
      priceLinesRef.current.forEach((pl) => {
        try { candleSeries.removePriceLine(pl) } catch (_) {}
      })
      priceLinesRef.current = []
      linesRef.current.forEach((ls) => {
        try { chart.removeSeries(ls) } catch (_) {}
      })
      linesRef.current = []

      const closeOf = (f) => (trades || []).find((t) => t.close_time && Math.abs(t.close_time - f.t) < 120000 && t.symbol === f.symbol)
      const m = []
      const info = {}
      const note = (t, txt) => {
        if (t != null) {
          info[t] = info[t] || []
          info[t].push(txt)
        }
      }
      const dcaN = {}

      ;(fills || []).forEach((f) => {
        if (!f || !isNum(f.t)) return
        const g = grp(f.kind)
        const buy = String(f.side).toUpperCase() === 'BUY'
        const t = snap(f.t)
        if (!isNum(t)) return

        if (g === 'entry' || g === 'dca') {
          const long = buy
          const isDca = g === 'dca'
          const dcaNum = (dcaN[f.symbol] = (dcaN[f.symbol] || 0) + 1)
          const txt = isDca ? `▲ DCA ${dcaNum}` : (long ? '▲ Mua' : '▼ Bán')
          m.push({
            time: t,
            position: long ? 'belowBar' : 'aboveBar',
            shape: long ? 'arrowUp' : 'arrowDown',
            color: long ? c.pos : c.neg,
            size: isDca ? 1.0 : 1.3,
            text: txt,
          })
          note(t, `${txt} (${fmtVal(f.qty)}@${fmtVal(f.price)})`)
        } else {
          const tr = closeOf(f)
          const pnlTxt = tr && isNum(tr.pnl) ? ` (${sgn(tr.pnl)})` : ''
          const k = f.kind
          const exitedLong = !buy
          const isWin = tr ? tr.pnl >= 0 : (k === 'TP')
          const col = isWin ? c.pos : (k === 'SL' ? c.neg : c.warn)
          const label = k === 'TP' ? 'TP' : k === 'SL' ? 'SL' : k === 'TRAIL' ? 'Trail' : 'Thoát'
          const txt = exitedLong ? `▼ ${label}${pnlTxt}` : `▲ ${label}${pnlTxt}`
          m.push({
            time: t,
            position: exitedLong ? 'aboveBar' : 'belowBar',
            shape: exitedLong ? 'arrowDown' : 'arrowUp',
            color: col,
            size: 1.3,
            text: txt,
          })
          note(t, `${EXIT[k] || k} @${fmtVal(f.price)}${pnlTxt ? ` · PnL${pnlTxt}` : ''}`)
        }
      })

      if (showReplay) {
        ;(replay || []).forEach((f) => {
          if (!f || !isNum(f.t)) return
          const t = snap(f.t)
          if (!isNum(t)) return
          const buy = String(f.side).toUpperCase() === 'BUY'
          const g = grp(f.kind)
          m.push({
            time: t,
            position: buy ? 'belowBar' : 'aboveBar',
            shape: buy ? 'arrowUp' : 'arrowDown',
            color: c.text,
            size: 0.7,
            text: `○ ${g === 'exit' ? 'Thoát' : g === 'dca' ? 'DCA' : 'Vào'}`,
          })
          note(t, `○ Backtest: ${g === 'exit' ? 'thoát' : g === 'dca' ? 'DCA' : 'vào'} @${fmtVal(f.price)}`)
        })
      }

      // Lọc sạch tuyệt đối mọi marker không có time hoặc time không phải số
      const validMarkers = m.filter((item) => isNum(item.time) && !isNaN(item.time) && item.time != null)
      validMarkers.sort((a, b) => a.time - b.time)
      candleSeries.setMarkers(validMarkers)

      // Vị thế đang mở: giá vốn, SL, TP, mức DCA kế tiếp
      ;(position || []).forEach((p) => {
        if (!p) return
        const L = p.levels || {}
        const addLine = (price, color, title, lineStyle) => {
          if (isNum(price) && !isNaN(price)) {
            try {
              const pl = candleSeries.createPriceLine({ price: Number(price), color, lineWidth: 1, lineStyle, axisLabelVisible: true, title })
              priceLinesRef.current.push(pl)
            } catch (_) {}
          }
        }
        addLine(p.avg_price, c.info, 'Giá vốn', LineStyle.Solid)
        addLine(L.sl, c.neg, 'SL', LineStyle.Dashed)
        addLine(L.tp, c.pos, 'TP', LineStyle.Dashed)
        addLine(L.dca, c.warn, 'DCA kế', LineStyle.Dotted)
      })

      // Lệnh đã đóng: nối điểm vào -> điểm thoát
      if (showLines) {
        ;(trades || []).forEach((t) => {
          if (!t || !t.enter_time || !t.close_time || !isNum(t.enter_price) || !isNum(t.close_price)) return
          const a = snap(t.enter_time)
          const b = snap(t.close_time)
          if (!isNum(a) || !isNum(b) || a >= b) return
          try {
            const ls = chart.addLineSeries({ color: t.pnl >= 0 ? c.pos : c.neg, lineWidth: 1, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false })
            ls.setData([{ time: a, value: Number(t.enter_price) }, { time: b, value: Number(t.close_price) }])
            linesRef.current.push(ls)
          } catch (_) {}
        })
      }

      // ─── TÍNH TOÁN & VẼ CÁC ĐƯỜNG CHỈ BÁO TÍN HIỆU (EMA, BOLLINGER BANDS, ATR) ───
      const indMap = new Map()

      // 1. Bộ 3 đường EMA
      let emasData = null
      if (cleanCandles.length >= 3) {
        emasData = computeEmas(cleanCandles, times)
        if (showEma) {
          const addEma = (arr, col) => {
            if (!arr?.length) return
            const ls = chart.addLineSeries({ color: col, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
            ls.setData(arr.filter((pt) => isNum(pt.time) && isNum(pt.value)))
            linesRef.current.push(ls)
          }
          addEma(emasData.ema9, '#f59e0b')
          addEma(emasData.ema21, '#ec4899')
          addEma(emasData.ema50, '#06b6d4')
        }
      }

      // 2. Dải Bollinger Bands
      let bbData = null
      if (cleanCandles.length >= 20) {
        bbData = computeBB(cleanCandles, times, 20, 2.0)
        if (showBb) {
          const addLine = (arr, col, style = LineStyle.Solid, width = 1.2) => {
            if (!arr?.length) return
            const ls = chart.addLineSeries({ color: col, lineWidth: width, lineStyle: style, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
            ls.setData(arr.filter((pt) => isNum(pt.time) && isNum(pt.value)))
            linesRef.current.push(ls)
          }
          addLine(bbData.upper, '#a855f7')
          addLine(bbData.mid, '#94a3b8', LineStyle.Dotted, 1)
          addLine(bbData.lower, '#a855f7')
        }
      }

      // 3. Kênh ATR Bands
      let atrData = null
      if (cleanCandles.length >= 14) {
        atrData = computeATR(cleanCandles, times, 14)
        if (showAtr) {
          const addAtr = (arr, col) => {
            if (!arr?.length) return
            const ls = chart.addLineSeries({ color: col, lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false })
            ls.setData(arr.filter((pt) => isNum(pt.time) && isNum(pt.value)))
            linesRef.current.push(ls)
          }
          addAtr(atrData.upper, '#10b981')
          addAtr(atrData.lower, '#f43f5e')
        }
      }

      // Lưu bảng tra chỉ số theo thời gian để hiển thị HUD
      const bbUpMap = new Map((bbData?.upper || []).map((x) => [x.time, x.value]))
      const bbMidMap = new Map((bbData?.mid || []).map((x) => [x.time, x.value]))
      const bbDnMap = new Map((bbData?.lower || []).map((x) => [x.time, x.value]))
      const atrValMap = new Map((atrData?.atrVals || []).map((x) => [x.time, x.value]))
      const ema9Map = new Map((emasData?.ema9 || []).map((x) => [x.time, x.value]))
      const ema21Map = new Map((emasData?.ema21 || []).map((x) => [x.time, x.value]))
      const ema50Map = new Map((emasData?.ema50 || []).map((x) => [x.time, x.value]))

      times.forEach((t) => {
        indMap.set(t, {
          ema9: ema9Map.get(t),
          ema21: ema21Map.get(t),
          ema50: ema50Map.get(t),
          bbUpper: bbUpMap.get(t),
          bbMid: bbMidMap.get(t),
          bbLower: bbDnMap.get(t),
          atr: atrValMap.get(t),
        })
      })

      const lastTime = times[times.length - 1]
      const defaultInd = indMap.get(lastTime) || null
      setActiveInd(defaultInd)

      // Khoảng hiển thị: từ lúc bot chạy (đệm 25 nến) tới nến cuối
      const startCandidate = startedAt ? loc(startedAt) : cleanCandles[0][0]
      const first = Math.max(times[0], (isNum(startCandidate) ? startCandidate : times[0]) - 25 * frameSec)
      chart.timeScale().setVisibleRange({ from: first, to: times[times.length - 1] + 8 * frameSec })

      // Tooltip & Cập nhật HUD chỉ báo khi di chuột
      const byT = new Map(cleanCandles.map((x, i) => [times[i], x]))
      const tip = tipRef.current
      const onCrosshair = (pm) => {
        if (pm.time != null && indMap.has(pm.time)) {
          setActiveInd(indMap.get(pm.time))
        } else {
          setActiveInd(defaultInd)
        }
        if (!tip) return
        const x = pm.time != null ? byT.get(pm.time) : null
        if (!x || !pm.point) { tip.style.display = 'none'; return }
        const rows = info[pm.time] || []
        tip.innerHTML = `<b>${fmtLoc(pm.time)}</b><br/>O ${fmtVal(x[1])} · H ${fmtVal(x[2])} · L ${fmtVal(x[3])} · C ${fmtVal(x[4])}<br/>KL ${fmtVal(x[5])}${rows.map((r) => `<br/>${r}`).join('')}`
        tip.style.display = 'block'
        tip.style.left = `${Math.min(pm.point.x + 14, el.clientWidth - 230)}px`
        tip.style.top = `${Math.max(pm.point.y - 10, 4)}px`
      }
      chart.subscribeCrosshairMove(onCrosshair)
      return () => chart.unsubscribeCrosshairMove(onCrosshair)
    } catch (err) {
      console.warn('LiveBotChart render warning:', err)
    }
  }, [candles, fills, replay, trades, position, showReplay, showLines, showEma, showBb, showAtr, startedAt])

  return (
    <div style={{ position: 'relative' }}>
      {/* HUD Chỉ báo trực tiếp trên biểu đồ chuẩn phong cách OKX / TradingView */}
      <div
        style={{
          position: 'absolute',
          top: 10,
          left: 12,
          zIndex: 4,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 12,
          fontSize: 11.5,
          fontFamily: 'system-ui, -apple-system, sans-serif',
          background: 'rgba(23, 23, 26, 0.85)',
          backdropFilter: 'blur(6px)',
          border: '1px solid rgba(255, 255, 255, 0.12)',
          padding: '4px 10px',
          borderRadius: 6,
          pointerEvents: 'none',
          boxShadow: '0 2px 8px rgba(0,0,0,0.35)',
          color: 'var(--n-ink, #fff)',
        }}
      >
        {showEma && activeInd && (
          <>
            <span><span style={{ color: '#f59e0b', fontWeight: 700 }}>● EMA(9):</span> {activeInd.ema9 ? fmtVal(activeInd.ema9) : '—'}</span>
            <span><span style={{ color: '#ec4899', fontWeight: 700 }}>● EMA(21):</span> {activeInd.ema21 ? fmtVal(activeInd.ema21) : '—'}</span>
            <span><span style={{ color: '#06b6d4', fontWeight: 700 }}>● EMA(50):</span> {activeInd.ema50 ? fmtVal(activeInd.ema50) : '—'}</span>
          </>
        )}
        {showBb && activeInd && activeInd.bbUpper && (
          <span><span style={{ color: '#a855f7', fontWeight: 700 }}>● BB(20,2):</span> [{fmtVal(activeInd.bbLower)} — {fmtVal(activeInd.bbUpper)}]</span>
        )}
        {showAtr && activeInd && activeInd.atr && (
          <span><span style={{ color: '#10b981', fontWeight: 700 }}>● ATR(14):</span> {fmtVal(activeInd.atr)}</span>
        )}
      </div>

      <div ref={containerRef} style={{ height: 480 }} role="img" aria-label="Biểu đồ nến của bot" />
      <div ref={tipRef} style={{ display: 'none', position: 'absolute', pointerEvents: 'none', zIndex: 5, padding: '6px 9px', fontSize: 11.5, lineHeight: 1.45,
        background: 'var(--n-surface-2, #222)', border: '1px solid var(--n-line)', borderRadius: 6, color: 'var(--n-ink)', maxWidth: 230, boxShadow: '0 4px 14px rgba(0,0,0,.25)' }} />
    </div>
  )
}

const chip = { display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 9px', borderRadius: 999, border: '1px solid var(--n-line)', background: 'var(--n-surface-2)', fontSize: 12, color: 'var(--n-ink-2)' }
const Mk = ({ color, glyph, children }) => <span style={chip}><span style={{ color, fontSize: 13, lineHeight: 1 }} aria-hidden>{glyph}</span>{children}</span>
const Stat = ({ k, v }) => <span style={chip}>{k}<b style={{ color: 'var(--n-ink)', fontWeight: 600 }}>{v}</b></span>

function Legend({ d, cur, nFills, nTrades, nRep, replay, hasOpen, showEma, showBb, showAtr }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, margin: '4px 0 10px', alignItems: 'center' }}>
      <Mk color="var(--n-pos)" glyph="▲">Vào Long</Mk>
      <Mk color="var(--n-neg)" glyph="▼">Vào Short</Mk>
      <Mk color="var(--n-pos)" glyph="✓">Chốt lời (TP)</Mk>
      <Mk color="var(--n-neg)" glyph="✕">Cắt lỗ (SL)</Mk>
      {showEma && (
        <>
          <span style={chip}><span style={{ width: 10, height: 3, background: '#f59e0b', display: 'inline-block', borderRadius: 1 }} aria-hidden></span> EMA 9 (Vàng - Nhanh)</span>
          <span style={chip}><span style={{ width: 10, height: 3, background: '#ec4899', display: 'inline-block', borderRadius: 1 }} aria-hidden></span> EMA 21 (Hồng - Trung)</span>
          <span style={chip}><span style={{ width: 10, height: 3, background: '#06b6d4', display: 'inline-block', borderRadius: 1 }} aria-hidden></span> EMA 50 (Xanh - Xu hướng)</span>
        </>
      )}
      {showBb && (
        <span style={chip}><span style={{ width: 10, height: 3, background: '#a855f7', display: 'inline-block', borderRadius: 1 }} aria-hidden></span> BB 20,2 (Dải Bollinger)</span>
      )}
      {showAtr && (
        <span style={chip}><span style={{ width: 10, height: 3, background: '#10b981', display: 'inline-block', borderRadius: 1, borderTop: '1px dashed #f43f5e' }} aria-hidden></span> ATR 14 (Kênh biên độ)</span>
      )}
      {hasOpen && <span style={{ ...chip, background: 'rgba(59, 130, 246, 0.15)', color: 'var(--n-info)', borderColor: 'var(--n-info)' }}>Đang mở vị thế 🟢</span>}
      {replay && <Mk color="var(--n-ink-2)" glyph="○">Khớp backtest</Mk>}
      <span style={{ flex: 1 }} />
      <Stat k="Cặp đang xem " v={`${base(cur)}: ${nTrades || 0} lệnh chốt (${nFills} lượt khớp)`} />
      <Stat k="Toàn bot " v={`${d.trades?.length || 0} lệnh chốt / ${(d.fills_live || []).length} lượt khớp (${d.symbols?.length || 0} cặp)`} />
      <Stat k="Khung chạy " v={d.base_frame} />
    </div>
  )
}

export default function LiveBotChart({ botId, running, selectedSymbol, onSelectSymbol }) {
  const [frame, setFrame] = useState(null)
  const [replay, setReplay] = useState(false)
  const [sym, setSym] = useState(null)
  const [showLines, setShowLines] = useState(true)
  const [showEma, setShowEma] = useState(true)
  const [showBb, setShowBb] = useState(true)
  const [showAtr, setShowAtr] = useState(false)
  const q = useAsync(() => getLiveBotChart(botId, frame, replay), [botId, frame, replay], { poll: running && !replay ? () => 60000 : undefined })
  const d = q.data
  const symbols = d?.symbols || []

  // Đồng bộ symbol từ prop ngoài nếu có
  const activeSym = selectedSymbol || sym
  const cur = (activeSym && symbols.includes(activeSym))
    ? activeSym
    : (symbols.find((s) => base(s) === base(activeSym)) || symbols[0])

  const handleSymChange = (nextSym) => {
    setSym(nextSym)
    if (onSelectSymbol) onSelectSymbol(nextSym)
  }

  const fills = useMemo(() => (d?.fills_live || []).filter((f) => f.symbol === cur), [d, cur])
  const rep = useMemo(() => (d?.fills_replay || []).filter((f) => f.symbol === cur), [d, cur])
  const poss = useMemo(() => (d?.positions || []).filter((p) => p.symbol === cur), [d, cur])
  const trs = useMemo(() => (d?.trades || []).filter((t) => t.symbol === cur), [d, cur])
  const cmp = d?.compare
  const hasOpen = poss.length > 0
  const rows = useMemo(() => (cmp ? [
    ...cmp.matched.filter((r) => r.symbol === cur).map((r) => ({ ...r, st: 'khớp' })),
    ...cmp.only_live.filter((r) => r.symbol === cur).map((r) => ({ symbol: r.symbol, group: grp(r.kind), kind_live: r.kind, side: r.side, t_live: r.t, price_live: r.price, st: 'chỉ bot' })),
    ...cmp.only_replay.filter((r) => r.symbol === cur).map((r) => ({ symbol: r.symbol, group: grp(r.kind), kind_replay: r.kind, side: r.side, t_replay: r.t, price_replay: r.price, st: 'chỉ replay' })),
  ].sort((a, b) => (a.t_live ?? a.t_replay) - (b.t_live ?? b.t_replay)) : []), [cmp, cur])
  const nm = cmp ? cmp.matched.filter((r) => r.symbol === cur).length : 0

  return (
    <Panel
      id="live-bot-chart-panel"
      title="Biểu đồ vào lệnh / chốt lệnh"
      meta={
        <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <select value={cur || ''} onChange={(e) => handleSymChange(e.target.value)} aria-label="Cặp">
            {symbols.map((s) => {
              const sFills = (d?.fills_live || []).filter((f) => f.symbol === s)
              const sOpen = (d?.positions || []).some((p) => p.symbol === s)
              const sTrades = (d?.trades || []).filter((t) => t.symbol === s)
              const statusTxt = sOpen
                ? ' · Đang mở 🟢'
                : sTrades.length > 0
                ? ` · ${sTrades.length} lệnh đã chốt (${sFills.length} lượt khớp)`
                : sFills.length > 0
                ? ` · ${sFills.length} lượt khớp`
                : ''
              return (
                <option key={s} value={s}>
                  {base(s)}{statusTxt}
                </option>
              )
            })}
          </select>
          <select value={frame || d?.frame || ''} onChange={(e) => setFrame(e.target.value)} aria-label="Khung nến">{FRAMES.map((f) => <option key={f} value={f}>{f}</option>)}</select>
          <label style={{ fontSize: 13, cursor: 'pointer' }}><input type="checkbox" checked={showEma} onChange={(e) => setShowEma(e.target.checked)} /> EMA (9/21/50)</label>
          <label style={{ fontSize: 13, cursor: 'pointer' }}><input type="checkbox" checked={showBb} onChange={(e) => setShowBb(e.target.checked)} /> Bollinger (20,2)</label>
          <label style={{ fontSize: 13, cursor: 'pointer' }}><input type="checkbox" checked={showAtr} onChange={(e) => setShowAtr(e.target.checked)} /> Kênh ATR (14)</label>
          <label style={{ fontSize: 13, cursor: 'pointer' }}><input type="checkbox" checked={showLines} onChange={(e) => setShowLines(e.target.checked)} /> Nối lệnh đóng</label>
          <label style={{ fontSize: 13, cursor: 'pointer' }}><input type="checkbox" checked={replay} onChange={(e) => setReplay(e.target.checked)} /> So với backtest</label>
        </span>
      }
    >
      {q.error && <ErrorState title="Không dựng được biểu đồ bot" error={q.error} onRetry={q.reload} />}
      {q.loading && !d && <Loading what={replay ? 'biểu đồ và backtest replay (có thể mất vài chục giây)' : 'biểu đồ'} />}
      {d && (
        <>
          {/* Thanh chọn coin nhanh cho biểu đồ */}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '4px 0 10px', alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: 'var(--n-ink-2)', marginRight: 4, fontWeight: 600 }}>Cặp nến:</span>
            {symbols.map((s) => {
              const sFills = (d?.fills_live || []).filter((f) => f.symbol === s)
              const sOpen = (d?.positions || []).some((p) => p.symbol === s)
              const sTrades = (d?.trades || []).filter((t) => t.symbol === s)
              const isCur = s === cur
              return (
                <button
                  key={s}
                  type="button"
                  className={`n-btn xs ${isCur ? 'primary' : ''}`}
                  style={{
                    borderRadius: 6,
                    fontWeight: isCur ? 700 : 500,
                    padding: '3px 10px',
                    fontSize: 12,
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    cursor: 'pointer',
                    background: isCur ? 'var(--n-accent, #6366f1)' : 'var(--n-surface-2)',
                    color: isCur ? '#fff' : 'var(--n-ink)',
                    borderColor: isCur ? 'var(--n-accent, #6366f1)' : 'var(--n-line)',
                    boxShadow: isCur ? '0 1px 4px rgba(99,102,241,0.3)' : 'none',
                  }}
                  onClick={() => handleSymChange(s)}
                  title={`Xem biểu đồ của ${base(s)}`}
                >
                  <span>{base(s)}</span>
                  {sOpen ? (
                    <span style={{ fontSize: 10, background: '#10b981', color: '#fff', borderRadius: 4, padding: '1px 5px', fontWeight: 600 }}>🟢 Mở</span>
                  ) : sTrades.length > 0 ? (
                    <span style={{ fontSize: 10, opacity: isCur ? 1 : 0.7, borderRadius: 4, padding: '1px 5px', background: isCur ? 'rgba(255,255,255,0.25)' : 'var(--n-line)', fontWeight: 600 }}>
                      {sTrades.length} lệnh đã chốt
                    </span>
                  ) : null}
                </button>
              )
            })}
          </div>

          <Legend d={d} cur={cur} nFills={fills.length} nTrades={trs.length} nRep={rep.length} replay={replay} hasOpen={hasOpen} showEma={showEma} showBb={showBb} showAtr={showAtr} />

          <div style={{ padding: '6px 12px', background: 'var(--n-surface-2)', border: '1px solid var(--n-line)', borderRadius: 6, marginBottom: 10, fontSize: 12, color: 'var(--n-ink-2)', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>📊</span>
            <span>Biểu đồ đang hiển thị nến & điểm vào/chốt lệnh của cặp <b>{base(cur)}</b> ({trs.length} lệnh đã chốt, {fills.length} lượt khớp). Để xem các cặp khác (ví dụ: XRP, DOGE, SOL...), hãy bấm vào các tab coin ở trên hoặc bấm vào hàng lệnh trong bảng <b>Lịch sử lệnh</b> bên dưới.</span>
          </div>

          {hasOpen && (
            <div style={{ padding: '6px 12px', background: 'rgba(59, 130, 246, 0.1)', border: '1px solid var(--n-info)', borderRadius: 6, marginBottom: 10, fontSize: 12.5, color: 'var(--n-ink)' }}>
              🟢 <b>Vị thế đang mở trên {base(cur)}:</b> Biểu đồ hiển thị giá vốn (đường xanh), mục tiêu chốt lời TP (đường xanh lá), cắt lỗ SL (đường đỏ) và mức DCA kế tiếp.
            </div>
          )}
          {d.replay?.note && <p className="n-note">{d.replay.note}</p>}
          {(d.warnings || []).map((w) => <p key={w} className="n-note">{w}</p>)}
          {d.candles?.[cur]?.length ? <Chart candles={d.candles[cur]} fills={fills} replay={rep} trades={trs} position={poss} showReplay={replay} showLines={showLines} showEma={showEma} showBb={showBb} showAtr={showAtr} startedAt={d.started_at} />
            : <Empty title="Chưa có nến">Không có dữ liệu nến trong khoảng của bot.</Empty>}
          {cmp && (
            <div style={{ marginTop: 12 }}>
              <p className="n-note">Ghép lệnh với replay (sai lệch giờ ≤ {Math.round(cmp.tol_ms / 60000)} phút): khớp {nm} · chỉ bot {rows.filter((r) => r.st === 'chỉ bot').length} · chỉ replay {rows.filter((r) => r.st === 'chỉ replay').length}. bps dương = bot khớp kém hơn replay.</p>
              <div className="n-tblwrap long">
                <table className="n-tbl">
                  <thead><tr><th>Loại</th><th>Hướng</th><th>Giờ bot (UTC)</th><th>Giờ replay (UTC)</th><th className="r">Lệch giờ (s)</th><th className="r">Giá bot</th><th className="r">Giá replay</th><th className="r">Lệch giá (bps)</th><th>Trạng thái</th></tr></thead>
                  <tbody>
                    {rows.slice(-300).map((r, i) => (
                      <tr key={i}>
                        <td>{GROUP[r.group]}{r.kind_live && r.group === 'exit' ? ` · ${EXIT[r.kind_live] || r.kind_live}` : ''}</td>
                        <td>{r.side}</td>
                        <td className="num">{r.t_live != null ? fmtTs(r.t_live) : '—'}</td>
                        <td className="num">{r.t_replay != null ? fmtTs(r.t_replay) : '—'}</td>
                        <td className="r">{r.dt_ms != null ? fmtNum(r.dt_ms / 1000, 0) : '—'}</td>
                        <td className="r">{r.price_live != null ? fmtVal(r.price_live) : '—'}</td>
                        <td className="r">{r.price_replay != null ? fmtVal(r.price_replay) : '—'}</td>
                        <td className="r">{r.bps != null ? fmtNum(r.bps, 1) : '—'}</td>
                        <td><span className={`n-badge ${r.st === 'khớp' ? 'ok' : 'warn'}`}>{r.st}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </Panel>
  )
}
