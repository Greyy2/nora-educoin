import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts'
import { snapTime, fmtTs } from './chartFormat'

const LINE_COLORS = ['#e5a93c', '#5aa0e6', '#b07be0', '#2fb3b8', '#e0679a', '#8bc34a', '#e58a2e']
const OSC_COLOR = '#5aa0e6'
const NONE = []
const MAIN_H = 420
const OSC_H = 120

// Màu nền/chữ/lưới lấy từ biến CSS của giao diện hiện tại (sáng/tối)
function readTheme(el) {
  const cs = getComputedStyle(el)
  const v = (k, d) => (cs.getPropertyValue(k).trim() || d)
  return { bg: v('--n-surface', '#17171a'), text: v('--n-ink-2', '#aeaeb6'), grid: v('--n-line-soft', '#212126'), line: v('--n-line', '#2a2a30'),
    pos: v('--n-pos', '#3ecf8e'), neg: v('--n-neg', '#f0616d'), accent: v('--n-accent', '#e58a2e'), info: v('--n-info', '#5aa0e6'), warn: v('--n-warn', '#e5a93c') }
}
const chartOpts = (c) => ({
  layout: { background: { color: c.bg }, textColor: c.text, fontFamily: "'IBM Plex Sans', system-ui, sans-serif", fontSize: 11 },
  grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
  rightPriceScale: { borderColor: c.line, scaleMargins: { top: 0.15, bottom: 0.22 } },
  timeScale: { borderColor: c.line },
  crosshair: { mode: CrosshairMode.Normal },
})

/** Biểu đồ nến + đường chỉ báo + dấu tín hiệu/lệnh. trades: [{enter_ms, close_ms, enter_price, close_price, side, reason, pnl}] */
export default function SignalChart({ data, trades = NONE, selectedT = null, onSelectSignal }) {
  const mainRef = useRef(null)
  const oscRefs = useRef([])
  const h = useRef(null) // { charts, candle, times, bar, colors }
  const live = useRef({})
  live.current = { selectedT, trades, onSelectSignal, signals: data?.signals || [] }
  const [ready, setReady] = useState(0)
  const [themeTick, setThemeTick] = useState(0)

  const candles = data?.candles
  const oscs = data?.oscillators || []
  const side = String(data?.strategy?.side || 'LONG').toUpperCase()

  // đổi giao diện sáng/tối -> áp lại màu, không dựng lại biểu đồ
  useEffect(() => {
    const mo = new MutationObserver(() => setThemeTick((n) => n + 1))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => mo.disconnect()
  }, [])

  // dựng biểu đồ khi dữ liệu đổi
  useEffect(() => {
    if (!candles?.length || !mainRef.current) return undefined
    const col = readTheme(mainRef.current)
    const times = candles.map((c) => c.t)
    const bar = times.length > 1 ? times[1] - times[0] : 3600
    const last = candles[candles.length - 1].c
    const precision = last >= 1000 ? 2 : last >= 100 ? 3 : last >= 1 ? 4 : 6
    const pf = { type: 'price', precision, minMove: 1 / 10 ** precision }

    const oscCount = oscs.length
    const main = createChart(mainRef.current, { ...chartOpts(col), autoSize: true, timeScale: { ...chartOpts(col).timeScale, visible: oscCount === 0, timeVisible: true, secondsVisible: false } })
    const candle = main.addCandlestickSeries({ upColor: col.pos, downColor: col.neg, borderUpColor: col.pos, borderDownColor: col.neg, wickUpColor: col.pos, wickDownColor: col.neg, priceFormat: pf })
    candle.setData(candles.map((c) => ({ time: c.t, open: c.o, high: c.h, low: c.l, close: c.c })))
    ;(data.overlays || []).forEach((o, i) => {
      const s = main.addLineSeries({ color: LINE_COLORS[i % LINE_COLORS.length], lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: pf, title: '' })
      s.setData(times.map((t, k) => (Number.isFinite(o.values[k]) ? { time: t, value: o.values[k] } : { time: t })))
    })
    const charts = [main]
    oscs.forEach((o, i) => {
      const el = oscRefs.current[i]
      if (!el) return
      const c = createChart(el, { ...chartOpts(col), autoSize: true, timeScale: { ...chartOpts(col).timeScale, visible: i === oscCount - 1, timeVisible: true, secondsVisible: false } })
      const s = c.addLineSeries({ color: OSC_COLOR, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, priceFormat: { type: 'price', precision: 2, minMove: 0.01 } })
      s.setData(times.map((t, k) => (Number.isFinite(o.values[k]) ? { time: t, value: o.values[k] } : { time: t })))
      ;(o.levels || []).forEach((lv) => s.createPriceLine({ price: lv, color: col.text, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: '' }))
      charts.push(c)
    })

    // đồng bộ trục thời gian giữa các khung
    let syncing = false
    charts.forEach((c, i) => {
      c.timeScale().subscribeVisibleLogicalRangeChange((r) => {
        if (syncing || !r) return
        syncing = true
        charts.forEach((o, j) => { if (j !== i) o.timeScale().setVisibleLogicalRange(r) })
        syncing = false
      })
      c.subscribeClick((p) => {
        if (typeof p.time !== 'number') return
        let best = null
        let bd = 6 * bar
        live.current.signals.forEach((s) => { const d = Math.abs(s.t - p.time); if (d <= bd) { bd = d; best = s } })
        if (best) live.current.onSelectSignal?.(best)
      })
    })

    // khung nhìn ban đầu: quanh lệnh/tín hiệu đang chọn, nếu không có thì toàn bộ
    const { selectedT: st, trades: tr } = live.current
    const focus = st ?? (tr[0] ? tr[0].enter_ms / 1000 : null)
    if (focus != null) {
      const closeT = tr[0]?.close_ms ? tr[0].close_ms / 1000 : focus
      const from = Math.max(times[0], focus - 120 * bar)
      const to = Math.min(times[times.length - 1], Math.max(focus, closeT) + 40 * bar)
      if (to > from) main.timeScale().setVisibleRange({ from, to }); else main.timeScale().fitContent()
    } else main.timeScale().fitContent()

    h.current = { charts, candle, times, bar }
    setReady((n) => n + 1)
    return () => { h.current = null; charts.forEach((c) => c.remove()) }
  }, [data]) // eslint-disable-line react-hooks/exhaustive-deps

  // áp lại màu theo giao diện
  useEffect(() => {
    if (!h.current || !mainRef.current) return
    const col = readTheme(mainRef.current)
    h.current.charts.forEach((c) => c.applyOptions(chartOpts(col)))
    h.current.candle.applyOptions({ upColor: col.pos, downColor: col.neg, borderUpColor: col.pos, borderDownColor: col.neg, wickUpColor: col.pos, wickDownColor: col.neg })
  }, [themeTick, ready])

  // dấu tín hiệu + dấu lệnh; tín hiệu đang chọn nổi bật
  useEffect(() => {
    const cur = h.current
    if (!cur || !mainRef.current) return
    const col = readTheme(mainRef.current)
    const long = side !== 'SHORT'
    const m = []
    ;(data.signals || []).forEach((s) => {
      const sel = selectedT != null && s.t === selectedT
      const time = snapTime(cur.times, s.t)
      if (s.kind === 'entry') {
        m.push({ time, position: long ? 'belowBar' : 'aboveBar', shape: long ? 'arrowUp' : 'arrowDown', color: sel ? col.accent : (long ? col.pos : col.neg), text: long ? '▲ Tín hiệu' : '▼ Tín hiệu', size: sel ? 2 : 1.2 })
      } else {
        m.push({ time, position: long ? 'aboveBar' : 'belowBar', shape: long ? 'arrowDown' : 'arrowUp', color: sel ? col.accent : col.warn, text: long ? '▼ Thoát' : '▲ Thoát', size: sel ? 2 : 1.2 })
      }
    })
    trades.forEach((t) => {
      const tl = String(t.side || side).toUpperCase() !== 'SHORT'
      m.push({
        time: snapTime(cur.times, t.enter_ms / 1000),
        position: tl ? 'belowBar' : 'aboveBar',
        shape: tl ? 'arrowUp' : 'arrowDown',
        color: tl ? col.pos : col.neg,
        text: tl ? '▲ Vào Long' : '▼ Vào Short',
        size: 1.3,
      })
      if (t.close_ms) {
        const isWin = Number.isFinite(t.pnl) ? t.pnl >= 0 : true
        const c = isWin ? col.pos : col.neg
        const reasonTxt = t.reason ? ` ${t.reason}` : ''
        m.push({
          time: snapTime(cur.times, t.close_ms / 1000),
          position: tl ? 'aboveBar' : 'belowBar',
          shape: tl ? 'arrowDown' : 'arrowUp',
          color: c,
          text: tl ? `▼ Chốt${reasonTxt}` : `▲ Chốt${reasonTxt}`,
          size: 1.3,
        })
      }
    })
    m.sort((a, b) => a.time - b.time)
    cur.candle.setMarkers(m)
  }, [data, trades, selectedT, side, ready, themeTick])

  // cuộn tới tín hiệu đang chọn nếu nằm ngoài khung nhìn
  useEffect(() => {
    const cur = h.current
    if (!cur || selectedT == null) return
    const ts = cur.charts[0].timeScale()
    const vr = ts.getVisibleRange()
    if (!vr || (selectedT >= vr.from && selectedT <= vr.to)) return
    const half = (vr.to - vr.from) / 2
    ts.setVisibleRange({ from: selectedT - half, to: selectedT + half })
  }, [selectedT, ready])

  const sigs = useMemo(() => [...(data?.signals || [])].sort((a, b) => a.t - b.t), [data])
  if (!candles?.length) return <div className="n-empty"><h3>Không có nến trong khoảng này</h3></div>
  const nOverlay = (data.overlays || []).length
  return (
    <div className="n-sc">
      <div className="n-sc-legend">
        <span className="mono"><b>{data.symbol}</b> · {data.timeframe}</span>
        {(data.overlays || []).map((o, i) => <span key={o.name} className="it" title={o.name}><i style={{ background: LINE_COLORS[i % LINE_COLORS.length] }} />{o.name}</span>)}
        {nOverlay === 0 && <span className="muted">không có đường chỉ báo trên giá</span>}
      </div>
      <div className="n-sc-main" ref={mainRef} style={{ height: MAIN_H }} role="img" aria-label={`Biểu đồ nến ${data.symbol} ${data.timeframe}`} />
      {oscs.map((o, i) => (
        <div key={o.name} className="n-sc-osc">
          <div className="n-sc-osc-t"><i style={{ background: OSC_COLOR }} />{o.name}{o.levels?.length ? <span className="muted"> · ngưỡng {o.levels.join(', ')}</span> : null}</div>
          <div ref={(el) => { oscRefs.current[i] = el }} style={{ height: OSC_H }} />
        </div>
      ))}
      {sigs.length > 0 && (
        <div className="n-sc-sigs" role="group" aria-label="Danh sách tín hiệu">
          <span className="muted">Tín hiệu ({sigs.length}):</span>
          {sigs.map((s) => (
            <button key={`${s.kind}${s.t}`} type="button" className={`n-chip-btn ${selectedT === s.t ? 'on' : ''}`} aria-pressed={selectedT === s.t} onClick={() => onSelectSignal?.(s)}>
              {s.kind === 'entry' ? 'Vào' : 'Thoát'} · {fmtTs(s.t)}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
