import React, { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import useAsync from '../../hooks/useAsync'
import { getLiveCandidates, getRunDefaults, postLiveBot, postCandidateBacktest, getJob, getCandidateSchema } from '../../api'
import { Loading, ErrorState, Empty } from '../ui'
import { fmtNum, fmtSPct, signClass, isNum } from '../../lib/format'
import '../../styles/alpha.css'

const COLS = [
  { k: 'name', label: 'Chiến lược', text: true },
  { k: 'timeframe', label: 'Khung tín hiệu', text: true },
  { k: 'ret_pct', label: 'Lãi %' },
  { k: 'mdd_pct', label: 'MDD %' },
  { k: 'sharpe', label: 'Sharpe' },
  { k: 'win_rate', label: 'Thắng %' },
  { k: 'trades', label: 'Lệnh' },
]
const FRAMES = ['1m', '5m', '15m', '1h', '4h', '24h']
const day = (s) => (s ? String(s).slice(0, 10) : '—')

const sameVal = (a, b) => (typeof a === 'number' && typeof b === 'number' ? Math.abs(a - b) < 1e-12 : a === b)

function launchErrorMessage(error) {
  if (error?.code === 'LIVE_LEDGER_UNAVAILABLE') {
    return 'Không thể bật bot: sổ cái Master chưa có dữ liệu authoritative. Hệ thống đang chặn khởi chạy để bảo vệ vốn; cần khôi phục nguồn sổ cái rồi thử lại.'
  }
  if (error?.code === 'LIVE_RISK_STATE_UNAVAILABLE') {
    return 'Không thể bật bot: trạng thái Master Risk chưa xác định. Hệ thống đang chặn khởi chạy an toàn; cần khôi phục nguồn trạng thái rủi ro rồi thử lại.'
  }
  if (error?.code === 'ALPHA_RESULT_STALE_OR_UNPROVEN') {
    return `Không thể bật bot: ${error.message || 'Kết quả backtest cũ thiếu provenance parity. Hệ thống đang cách ly an toàn.'}`
  }
  return error?.message || String(error)
}

/** Lỗi nhập của một trường theo spec schema ('' = hợp lệ). */
function fieldError(spec, v) {
  if (spec.type === 'choice') return (spec.choices || []).includes(v) ? '' : 'Giá trị không hợp lệ'
  if (spec.type === 'text') return ''
  const n = Number(v)
  if (v === '' || v == null || !Number.isFinite(n)) return 'Phải là số'
  if (spec.type === 'int' && !Number.isInteger(n)) return 'Phải là số nguyên'
  if (spec.min != null && n < spec.min) return `Tối thiểu ${spec.min}`
  if (spec.max != null && n > spec.max) return `Tối đa ${spec.max}`
  return ''
}

/** Trình sửa tham số chiến lược từ schema; values = giá trị đang sửa, defaults = cấu hình gốc. */
function ParamEditor({ schema, values, onChange }) {
  const { fields, defaults } = schema
  const groups = {}
  Object.entries(fields).forEach(([k, spec]) => { (groups[spec.group || 'other'] = groups[spec.group || 'other'] || []).push([k, spec]) })
  const changed = Object.keys(fields).filter((k) => !sameVal(values[k], defaults[k]))
  return (
    <div style={{ flexBasis: '100%' }}>
      {Object.entries(groups).map(([g, items]) => (
        <details key={g} open={g !== 'signal' || changed.some((k) => fields[k].group === g)} style={{ marginBottom: 6 }}>
          <summary className="n-note" style={{ cursor: 'pointer' }}>{g}</summary>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, padding: '6px 0' }}>
            {items.map(([k, spec]) => {
              const err = fieldError(spec, values[k])
              const dirty = !sameVal(values[k], defaults[k])
              return (
                <div className="n-field" key={k} style={{ width: 150 }} title={spec.help_vi || ''}>
                  <label style={dirty ? { fontWeight: 700 } : undefined}>{spec.label_vi || k}{spec.unit ? ` (${spec.unit})` : ''}</label>
                  {spec.type === 'choice'
                    ? <select value={values[k]} onChange={(e) => onChange(k, e.target.value)}>{spec.choices.map((c) => <option key={c} value={c}>{c}</option>)}</select>
                    : <input type={spec.type === 'text' ? 'text' : 'number'} value={values[k] ?? ''} min={spec.min} max={spec.max} step={spec.step || 'any'}
                        onChange={(e) => onChange(k, spec.type === 'text' ? e.target.value : e.target.value === '' ? '' : Number(e.target.value))} />}
                  {err && <span className="n-field-err">{err}</span>}
                </div>
              )
            })}
          </div>
        </details>
      ))}
      <div className="n-note" data-testid="param-diff">
        {changed.length
          ? <>Khác mặc định: {changed.map((k) => <span key={k} className="n-badge warn" style={{ marginRight: 4 }}>{fields[k].label_vi || k}: {String(defaults[k])} → {String(values[k])}</span>)}</>
          : 'Đang dùng đúng cấu hình mặc định (không sửa tham số).'}
      </div>
    </div>
  )
}

function StartForm({ row, onCancel, onStarted }) {
  const sigTf = row.signal_tf || row.timeframe || '1h'
  const defaultSyms = (row.symbols || []).join(', ')

  const [mode, setMode] = useState('paper')
  const [confirmReal, setConfirmReal] = useState(false)
  const [capital, setCapital] = useState(1000)
  const [symbols, setSymbols] = useState(defaultSyms)
  const [enter, setEnter] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const frames = useMemo(() => [...new Set([sigTf, '1m'].filter(Boolean))], [sigTf])
  const [frame, setFrame] = useState(sigTf || '1h')

  const [btBusy, setBtBusy] = useState(false)
  const [btResult, setBtResult] = useState(null)
  const [btJobId, setBtJobId] = useState(null)
  const [schema, setSchema] = useState(null)
  const [pvals, setPvals] = useState({})
  const [schemaErr, setSchemaErr] = useState(null)
  const [availableAssets, setAvailableAssets] = useState([])
  const [assetsErr, setAssetsErr] = useState(null)

  useEffect(() => {
    let live = true
    setSchema(null); setSchemaErr(null)
    getCandidateSchema(row.id, sigTf, row.book)
      .then((sc) => {
        if (live) {
          setSchema(sc)
          setPvals({ ...(sc?.defaults || {}) })
        }
      })
      .catch((ex) => {
        if (live) setSchemaErr(ex.message || String(ex))
      })
    return () => { live = false }
  }, [row.id, sigTf, row.book])

  useEffect(() => {
    let active = true
    getRunDefaults()
      .then((defaults) => {
        if (!active) return
        const available = defaults.available_symbols || defaults.symbols || []
        setAvailableAssets(available)
        setAssetsErr(null)
      })
      .catch((error) => {
        if (active) setAssetsErr(error.message || String(error))
      })
    return () => { active = false }
  }, [])

  const changedParams = () => {
    const out = {}
    if (schema) {
      Object.keys(schema.fields).forEach((k) => {
        if (!sameVal(pvals[k], schema.defaults[k])) out[k] = pvals[k]
      })
    }
    return out
  }

  const paramErrors = schema ? Object.keys(schema.fields).filter((k) => fieldError(schema.fields[k], pvals[k])) : []
  const editParam = (k, v) => {
    setPvals((o) => ({ ...o, [k]: v }))
    setBtResult(null)
    setBtJobId(null)
  }

  const runBacktest = async () => {
    const syms = symbols.split(/[,\s]+/).filter(Boolean)
    if (!syms.length) { setErr('Cần ít nhất một cặp giao dịch'); return }
    if (!schema || paramErrors.length) { setErr('Sửa các tham số chưa hợp lệ trước khi backtest'); return }
    setBtBusy(true); setErr(null); setBtResult(null); setBtJobId(null)
    try {
      const resp = await postCandidateBacktest({
        alpha_id: row.id,
        signal_tf: sigTf,
        symbols: syms,
        capital: Number(capital),
        params: changedParams(),
        book_source: row.book || undefined,
      })
      const jid = resp.job_id
      setBtJobId(jid)
      const t0 = Date.now()
      const poll = async () => {
        if (Date.now() - t0 > 45000) {
          setErr('Backtest quá thời gian chờ (timeout)')
          setBtBusy(false)
          return
        }
        try {
          const j = await getJob(jid)
          if (j.status === 'done') {
            const res = j.result || {}
            const sim = res.metrics?.simulate || res.metrics || res
            const ret = sim.ret_pct != null ? sim.ret_pct : res.ret_pct
            const mdd = sim.mdd_pct != null ? sim.mdd_pct : res.mdd_pct
            const sharpe = sim.sharpe != null ? sim.sharpe : res.sharpe
            const trades = Array.isArray(res.trades) ? res.trades.length : (sim.trades ?? res.trades ?? 0)
            setBtResult({ ret_pct: ret, mdd_pct: mdd, sharpe, trades })
            setBtBusy(false)
          } else if (j.status === 'failed' || j.status === 'error') {
            setErr(`Backtest thất bại: ${j.error || 'Lỗi không xác định'}`)
            setBtBusy(false)
          } else {
            setTimeout(poll, 600)
          }
        } catch (ex) {
          setErr(`Lỗi kiểm tra job backtest: ${ex.message || String(ex)}`)
          setBtBusy(false)
        }
      }
      setTimeout(poll, 600)
    } catch (ex) {
      setErr(`Không khởi chạy được backtest: ${ex.message || String(ex)}`)
      setBtBusy(false)
    }
  }

  const submit = async (e) => {
    e.preventDefault()
    const syms = symbols.split(/[,\s]+/).filter(Boolean)
    if (!syms.length) { setErr('Cần ít nhất một cặp giao dịch'); return }
    if (!(Number(capital) > 0)) { setErr('Vốn phải lớn hơn 0'); return }
    if (mode === 'live' && !confirmReal) { setErr('Live dùng tiền thật: hãy tích xác nhận trước khi bật'); return }
    if (schema && paramErrors.length) { setErr('Sửa các tham số chưa hợp lệ trước khi bật bot'); return }
    setBusy(true); setErr(null)
    try {
      const changed = changedParams()
      const payload = {
        mode: mode === 'live' ? 'live' : 'testnet',
        confirm_live: mode === 'live' && confirmReal,
        alpha_id: row.id,
        symbols: syms,
        capital: Number(capital),
        base_frame: frame,
        enter_on_start: enter,
        signal_tf: sigTf,
        from_picker: true,
        book_source: row.book || undefined,
      }
      if (Object.keys(changed).length > 0 || syms.join(',') !== (row.symbols || []).join(',')) {
        payload.params = changed
      }
      if (btJobId) {
        payload.backtest_job_id = btJobId
      }
      const r = await postLiveBot(payload)
      onStarted(r)
    } catch (ex) { setErr(launchErrorMessage(ex)); setBusy(false) }
  }

  return (
    <div style={{ padding: '16px 18px', background: 'var(--n-surface-subtle, rgba(255,255,255,0.03))', borderRadius: 8, marginTop: 8, border: '1px solid var(--n-line-soft, rgba(255,255,255,0.08))' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
        <span className="n-badge ok">Khung tín hiệu: <b>{sigTf}</b></span>
        <span className="n-note">KPI chuẩn backtest: Lãi <b>{fmtSPct(row.ret_pct)}</b> · MDD <b>{fmtNum(row.mdd_pct, 2)}%</b> · Sharpe <b>{fmtNum(row.sharpe, 2)}</b></span>
      </div>

      <form onSubmit={submit} style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'flex-end' }}>
        {/* Chọn Asset / Cặp giao dịch */}
        <div className="n-field" style={{ flex: '1 1 260px' }}>
          <label style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>Tài sản giao dịch (Asset / Cặp)</span>
            <span style={{ fontSize: 11, color: 'var(--n-ink-3)' }}>Khuyên dùng: {defaultSyms}</span>
          </label>
          <input
            value={symbols}
            onChange={(e) => { setSymbols(e.target.value); setBtResult(null); setBtJobId(null) }}
            list="live-market-options"
            placeholder="Nhập market đã chọn, ví dụ: BTC-USDT-SWAP"
          />
          <datalist id="live-market-options">
            {availableAssets.map((asset) => <option key={asset} value={asset} />)}
          </datalist>
          {assetsErr
            ? <span className="n-field-err">Không tải được danh sách market: {assetsErr}</span>
            : <span className="n-note">Gợi ý lấy từ market có dữ liệu; có thể nhập market OKX khác nếu instrument được hỗ trợ.</span>}
        </div>

        {/* Chế độ chạy */}
        <div className="n-field">
          <label>Chế độ</label>
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="paper">Paper (tài khoản mô phỏng OKX)</option>
            <option value="live">Live (tài khoản thật)</option>
          </select>
          {mode === 'live' && (
            <label className="n-note" style={{ display: 'flex', gap: 6, alignItems: 'center', color: 'var(--n-neg)', marginTop: 4 }}>
              <input type="checkbox" checked={confirmReal} onChange={(e) => setConfirmReal(e.target.checked)} /> Tôi xác nhận chạy bằng TIỀN THẬT
            </label>
          )}
        </div>

        {/* Vốn phân bổ */}
        <div className="n-field">
          <label>Vốn phân bổ (USDT)</label>
          <input type="number" min="1" value={capital} onChange={(e) => setCapital(e.target.value)} style={{ width: 110 }} />
        </div>

        {/* Khung chạy nến */}
        <div className="n-field">
          <label>Khung chạy</label>
          <select value={frame} onChange={(e) => setFrame(e.target.value)}>
            {frames.map((f) => <option key={f} value={f}>{f === '1m' ? '1m (Chuẩn)' : `${f} (Nhanh)`}</option>)}
          </select>
        </div>

        {/* Vào lệnh ngay */}
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13, marginBottom: 8 }}>
          <input type="checkbox" checked={enter} onChange={(e) => setEnter(e.target.checked)} />
          Vào lệnh ngay khi khởi động
        </label>

        {/* Cấu hình tham số & Rủi ro đã cài đặt sẵn */}
        <div style={{ flexBasis: '100%', marginTop: 4 }}>
          {schemaErr && <div className="n-field-err">Không tải được tham số: {schemaErr}</div>}
          {!schema && !schemaErr && <span className="n-note">Đang nạp cấu hình mặc định đã backtest…</span>}
          {schema && <ParamEditor schema={schema} values={pvals} onChange={editParam} />}
        </div>

        {/* Tuỳ chọn chạy lại backtest nếu muốn kiểm tra */}
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" className="n-btn sm" onClick={runBacktest} disabled={btBusy || !schema || paramErrors.length > 0}>
            {btBusy ? 'Đang backtest…' : 'Chạy thử backtest'}
          </button>
          <span className="n-note" style={{ fontSize: 11.5 }}>
            (Tham số & rủi ro đã được cấu hình tối ưu sẵn theo backtest có lãi. Bạn có thể bật bot ngay hoặc chạy thử lại nếu vừa chỉnh sửa).
          </span>
        </div>

        {btResult && (
          <div style={{ flexBasis: '100%', display: 'flex', gap: 16, alignItems: 'center', padding: '8px 12px', background: 'var(--n-surface, #1e1e24)', borderRadius: 6, flexWrap: 'wrap' }}>
            <span>KPI thử nghiệm: Lãi <b className={signClass(btResult.ret_pct)}>{fmtSPct(btResult.ret_pct)}</b></span>
            <span>MDD: <b>{fmtNum(btResult.mdd_pct, 2)}%</b></span>
            <span>Sharpe: <b>{fmtNum(btResult.sharpe, 2)}</b></span>
            <span>Lệnh: <b>{btResult.trades}</b></span>
            {btResult.ret_pct < 0 && <span className="n-badge bad">Cảnh báo: Cấu hình điều chỉnh đang lỗ!</span>}
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginLeft: 'auto', marginTop: 8 }}>
          <button type="submit" className="n-btn sm primary" disabled={busy || (schema && paramErrors.length > 0)}>
            {busy ? 'Đang bật…' : 'Bật bot'}
          </button>
          <button type="button" className="n-btn sm" onClick={onCancel} disabled={busy}>Huỷ</button>
        </div>

        {err && <div className="n-field-err" style={{ flexBasis: '100%', marginTop: 4 }}>{err}</div>}
      </form>
    </div>
  )
}

export default function StrategyPicker({ onClose, onStarted }) {
  const q = useAsync(() => getLiveCandidates(), [])
  const [sort, setSort] = useState({ k: 'sharpe', dir: -1 })
  const [open, setOpen] = useState(null)
  const rows = useMemo(() => {
    const r = [...(q.data?.candidates || [])]
    const { k, dir } = sort
    r.sort((a, b) => {
      const x = a[k], y = b[k]
      if (typeof x === 'string' || typeof y === 'string') return dir * String(x ?? '').localeCompare(String(y ?? ''))
      return dir * ((isNum(x) ? x : -Infinity) - (isNum(y) ? y : -Infinity))
    })
    return r
  }, [q.data, sort])
  const rk = (r) => `${r.id}|${r.timeframe}`

  return createPortal(
    <div className="n-modal-backdrop" onClick={onClose}>
      <div className="n-modal-content push-alpha-modal" role="dialog" aria-modal="true" style={{ maxWidth: 1060, maxHeight: '90vh' }} onClick={(e) => e.stopPropagation()}>
        <header className="push-alpha-header">
          <div>
            <div className="push-alpha-kicker">Mỗi dòng = một chiến lược ở đúng khung đã backtest có lãi · cùng nguồn Thư viện alpha</div>
            <h2 className="push-alpha-title">Chọn chiến lược để chạy</h2>
          </div>
          <button type="button" className="push-alpha-close-btn" onClick={onClose} aria-label="Đóng">✕</button>
        </header>
        <div style={{ padding: '0 20px 20px', overflow: 'auto' }}>
          {q.loading && !q.data && <Loading what="danh sách chiến lược" />}
          {q.error && <ErrorState title="Không tải được danh sách chiến lược" error={q.error} onRetry={q.reload} />}
          {q.data && !rows.length && <Empty title="Chưa có chiến lược nào có lãi">Chạy backtest và lưu chiến lược trước.</Empty>}
          {rows.length > 0 && (
            <table className="n-tbl">
              <thead><tr>
                {COLS.map((c) => (
                  <th key={c.k} className={c.text ? '' : 'r'} style={{ cursor: 'pointer' }} onClick={() => setSort((s) => ({ k: c.k, dir: s.k === c.k ? -s.dir : -1 }))}>
                    {c.label}{sort.k === c.k ? (sort.dir < 0 ? ' ▼' : ' ▲') : ''}
                  </th>
                ))}
                <th>WFA</th><th>Monte Carlo</th><th>Backtest</th><th />
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <React.Fragment key={rk(r)}>
                    <tr>
                      <td>
                        <b>{r.name}</b>{r.side ? ` · ${r.side}` : ''} <span className={`n-badge ${r.source === 'hệ thống' ? 'ok' : ''}`}>{r.source}</span>
                        {(!r.promotable || r.quarantine_status === 'QUARANTINED') && (
                          <span className="n-badge warn" style={{ marginLeft: 6 }} title={r.quarantine_reason || 'Kết quả pre-parity bị cách ly'}>
                            Cách ly (pre-parity)
                          </span>
                        )}
                      </td>
                      <td><span className="n-badge ok" title="Khung tín hiệu của kết quả backtest lãi này"><b>{r.timeframe || '—'}</b></span></td>
                      <td className={`r ${signClass(r.ret_pct)}`}>{fmtSPct(r.ret_pct)}</td>
                      <td className="r">{isNum(r.mdd_pct) ? fmtNum(r.mdd_pct, 2) : '—'}</td>
                      <td className="r">{isNum(r.sharpe) ? fmtNum(r.sharpe, 2) : '—'}</td>
                      <td className="r">{isNum(r.win_rate) ? fmtNum(r.win_rate, 1) : '—'}</td>
                      <td className="r">{r.trades ?? '—'}</td>
                      <td>{r.wfa
                        ? <span className={`n-badge ${r.wfa.passed ? 'ok' : 'warn'}`} title={`OOS ${fmtSPct(r.wfa.oos_ret_pct)} · ${r.wfa.folds_profitable ?? '?'}/${r.wfa.folds ?? '?'} fold có lãi`}>{r.wfa.passed ? 'Đạt' : 'Không đạt'} · OOS {fmtSPct(r.wfa.oos_ret_pct)}</span>
                        : <span className="n-note">chưa có</span>}</td>
                      <td>{r.mc
                        ? <span className={`n-badge ${r.mc.passed ? 'ok' : 'warn'}`} title={`MDD p95 ${r.mc.mdd_p95 ?? '—'}%`}>P(MDD≥30%) {isNum(r.mc.p_ruin) ? fmtNum(r.mc.p_ruin, 2) : '—'}%</span>
                        : <span className="n-note">chưa có</span>}</td>
                      <td>{day(typeof r.backtested_at === 'number' ? new Date(r.backtested_at).toISOString() : r.backtested_at)}</td>
                      <td className="r"><button type="button" className="n-btn sm" onClick={() => setOpen(open === rk(r) ? null : rk(r))}>Bật bot</button></td>
                    </tr>
                    {open === rk(r) && (
                      <tr><td colSpan={COLS.length + 4}>
                        <StartForm row={r} onCancel={() => setOpen(null)} onStarted={(res) => { onStarted?.(res); onClose() }} />
                      </td></tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>,
    document.querySelector('.v2') || document.body,
  )
}
