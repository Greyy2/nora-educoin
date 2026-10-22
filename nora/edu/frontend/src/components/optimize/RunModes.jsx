import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Segmented } from '../ui'
import Term from '../ui/Term'
import useAsync from '../../hooks/useAsync'
import { getStrategies, getStrategyCatalog, postValidateStrategy } from '../../api'
import { getParamGroups, registerParamSchema, paramLabel, paramHint, paramUnit, fmtParamFull } from '../../lib/params'
import { MODES, modeText, CUSTOM_BADGE, CUSTOM_REASON, presetInfo, validateStrategy, coerceParams, sameValue, changedKeys, WFA_PENDING_NOTE } from '../../lib/modes'
import { fmtSPct, fmtPct, fmtNum } from '../../lib/format'

export function LockIcon() {
  return (
    <svg className="n-ico" width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="7" width="10" height="7" rx="1.5" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
  )
}

/** Các chiến lược lõi (lược đồ + preset) từ GET /api/studio/strategies. */
export function useStrategies() {
  const q = useAsync(() => getStrategies().then((data) => {
    registerParamSchema(data)
    return data
  }), [])
  const byId = useMemo(() => Object.fromEntries((q.data || []).map((s) => [s.id, s])), [q.data])
  return { list: q.data || [], byId, loading: q.loading, error: q.error, reload: () => { getStrategies(true); q.reload() } }
}

/** Danh mục 3 chiến lược (KEMA / Sideway / DCA) kèm id chân lệnh theo chiều, từ GET /api/studio/strategies/catalog. */
export function useStrategyCatalog() {
  const q = useAsync(() => getStrategyCatalog(), [])
  return { list: q.data || [], loading: q.loading, error: q.error, reload: () => { getStrategyCatalog(true); q.reload() } }
}

/** Kiểm tham số qua POST /strategies/validate (debounce); chỉ gọi cho chiến lược đã qua kiểm tra phía client. -> { [id]: { [khoá]: msg } } khớp bản tham số hiện tại. */
export function useServerValidation(strats, paramsById, enabled) {
  const [res, setRes] = useState({})
  const sigs = {}
  Object.keys(paramsById).forEach((id) => {
    const s = strats[id]
    if (!s) return
    const p = coerceParams(s.params_schema, paramsById[id])
    sigs[id] = JSON.stringify(p)
  })
  const key = JSON.stringify(sigs)
  const resRef = useRef(res)
  resRef.current = res
  useEffect(() => {
    if (!enabled) return undefined
    const t = setTimeout(() => {
      Object.entries(sigs).forEach(([id, sig]) => {
        if (resRef.current[id]?.sig === sig) return
        const params = JSON.parse(sig)
        if (Object.keys(validateStrategy(strats[id].params_schema, params)).length) return // lỗi phía client đã đủ
        postValidateStrategy(id, params).then((r) => {
          const errors = {}
          ;(r.errors || []).forEach((e) => { errors[String(e.field).replace(/^params\.?/, '')] = String(e.message).replace(/^[a-z0-9_]+:\s*/, '') })
          setRes((x) => ({ ...x, [id]: { sig, errors } }))
        }, () => { /* không kiểm được: bỏ qua, backend vẫn kiểm khi chạy */ })
      })
    }, 500)
    return () => clearTimeout(t)
  }, [key, enabled]) // eslint-disable-line react-hooks/exhaustive-deps
  const out = {}
  Object.entries(res).forEach(([id, r]) => { if (r.sig === sigs[id]) out[id] = r.errors })
  return out
}

/** Công tắc Cơ bản | Nâng cao ở đầu mỗi bước. */
export function ModeSwitch({ mode, onChange, className = '' }) {
  return (
    <div className={`n-modebar ${className}`}>
      <div className="n-field">
        <span className="n-lbl">Chế độ chạy</span>
        <Segmented label="Chế độ chạy" value={mode} onChange={onChange} options={MODES} />
      </div>
      <p className="n-note">
        {mode === 'basic'
          ? <><Term k="mode_basic">Cơ bản</Term>: dùng <Term k="preset">preset</Term> (bộ tham số tốt nhất) đã khoá; máy chủ bỏ qua mọi tham số khác.</>
          : <><Term k="mode_advanced">Nâng cao</Term>: chỉnh được từng tham số, khung thời gian, ngày và cổng. Đổi cổng hoặc dùng ít kịch bản mô phỏng hơn mức chuẩn thì kết quả <b>không xuất bản được</b>.</>}
      </p>
    </div>
  )
}

/** Huy hiệu chế độ + cảnh báo cấu hình tuỳ chỉnh (không xuất bản được). */
export function ModeStamp({ mode, customGates, promotable, ignored }) {
  if (!mode) return null
  const custom = !!customGates || promotable === false
  return (
    <div className="n-stamp" role="group" aria-label="Chế độ chạy của kết quả">
      <span className={`n-mode-badge ${mode}`}>{mode === 'advanced' ? <Term k="mode_advanced">Nâng cao</Term> : <Term k="mode_basic">Cơ bản</Term>}</span>
      {custom && <span className="n-custom-badge" title={CUSTOM_REASON}>⚠ {CUSTOM_BADGE}</span>}
      {custom && <span className="n-note">{CUSTOM_REASON}</span>}
      {mode === 'basic' && ignored && <span className="n-note">Máy chủ đã bỏ qua tham số do client gửi (chế độ Cơ bản dùng preset).</span>}
    </div>
  )
}

/** Nút Xuất bản bị khoá kèm lý do (chỉ hiện khi kết quả không xuất bản được). */
export function PublishBlocked({ customGates, promotable }) {
  if (!customGates && promotable !== false) return null
  return (
    <div className="n-sticky-actions" style={{ marginTop: 8 }}>
      <button type="button" className="n-btn" disabled title={CUSTOM_REASON} aria-describedby="publish-blocked-why">Xuất bản</button>
      <span id="publish-blocked-why" className="n-note"><LockIcon /> {CUSTOM_BADGE}.</span>
    </div>
  )
}

const fmtResolved = (k, v) => (v == null ? '—' : fmtParamFull(k, v))

/** Tham số ĐẦY ĐỦ đã giải quyết của một job (job.resolved), thu gọn được. */
export function ResolvedParams({ job, open = false }) {
  const r = job?.resolved
  if (!r) return null
  const strategies = r.strategies || []
  const win = r.start && r.end ? `${r.start} → ${r.end}` : null
  return (
    <details className="n-details n-resolved" open={open}>
      <summary>Tham số đã dùng ({r.source || 'đã giải quyết'})</summary>
      <div className="n-resolved-b">
        <div className="n-resolved-line mono">
          {win && <span>ngày {win}</span>}
          {r.symbols && <span>{r.symbols.length} tài sản</span>}
          {r.risk_per_trade_pct != null && <span>rủi ro {r.risk_per_trade_pct}%/lệnh</span>}
          {r.stop_fill && <span>cắt lỗ: {r.stop_fill === 'extreme' ? 'giá xấu nhất' : 'đúng mức'}</span>}
          {r.train_days != null && <span>train/test {r.train_days}/{r.test_days}</span>}
          {r.step_days != null && <span>bước {r.step_days}</span>}
          {r.sims != null && <span>{r.sims} kịch bản</span>}
          {r.mc_seed != null && <span>seed {r.mc_seed}</span>}
        </div>
        {strategies.map((s) => {
          const list = s.configs || (s.params ? [s.params] : [])
          return (
            <div key={s.id} className="n-resolved-s">
              <b className="mono">{s.id}</b>
              {s.preset_source && <span className="muted"> · preset: {s.preset_source}</span>}
              {list.map((p, i) => (
                <div key={i} className="n-plist">
                  {Object.entries(p).map(([k, v]) => <span key={k} title={k}><b>{paramLabel(k)}</b>{fmtResolved(k, v)}</span>)}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </details>
  )
}

/* ------------------------------ ô nhập tham số ------------------------------ */
export function ParamField({ idBase, k, spec, value, onChange, error, disabled, note, changed }) {
  const id = `${idBase}-${k}`
  const unit = paramUnit(k) || spec.unit || ''
  const hint = paramHint(k) || spec.help_vi || ''
  const lbl = paramLabel(k)
  const errId = `${id}-e`
  const cls = `n-pf ${error ? 'bad' : ''} ${changed ? 'chg' : ''} ${disabled ? 'dis' : ''}`
  return (
    <div className={cls}>
      <label htmlFor={id} title={`${k}${hint ? ` — ${hint}` : ''}`}>{lbl}{unit && spec.type !== 'choice' && !lbl.includes('(') ? <span className="u"> ({unit})</span> : null}{changed ? <i className="dot" title="Khác preset" /> : null}</label>
      {spec.type === 'choice' ? (
        <select id={id} className="n-sel" value={value ?? ''} disabled={disabled} aria-invalid={!!error || undefined} aria-describedby={error ? errId : undefined} onChange={(e) => onChange(e.target.value)}>
          {!spec.choices.includes(value) && <option value={value ?? ''}>{value === '' || value == null ? '—' : String(value)}</option>}
          {spec.choices.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      ) : (
        <input id={id} type="number" inputMode="decimal" className="n-in" value={value ?? ''} min={spec.min} max={spec.max} step={spec.step ?? (spec.type === 'int' ? 1 : 'any')}
          disabled={disabled} aria-invalid={!!error || undefined} aria-describedby={error ? errId : undefined} onChange={(e) => onChange(e.target.value)} />
      )}
      {spec.type !== 'choice' && !disabled && <span className="rng mono">{spec.min}–{spec.max}</span>}
      {note && <span className="n-pf-note"><LockIcon /> {note}</span>}
      {error && <span id={errId} className="n-field-err" role="alert">{error}</span>}
    </div>
  )
}

function ReadonlyGrid({ schema, params }) {
  const groups = getParamGroups(schema)
  return (
    <div className="n-ro">
      {groups.map((g) => (
        <div key={g.key} className="n-ro-g">
          <h5>{g.label}</h5>
          <dl>
            {g.keys.map((k) => (
              <div key={k} title={k}><dt>{paramLabel(k)}</dt><dd className="mono">{fmtParamFull(k, params[k])}</dd></div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  )
}

function Evidence({ info }) {
  const m = (x) => (x ? `lãi ${fmtSPct(x.ret_pct, 1)} · MDD ${fmtPct(x.mdd_pct, 1)} · Sharpe ${fmtNum(x.sharpe, 2)} · ${fmtNum(x.trades, 0)} lệnh` : null)
  const rows = [['dev1', m(info.dev1)], ['dev2 (đúng mức)', m(info.dev2Level)], ['dev2 (giá xấu nhất)', m(info.dev2Extreme)]].filter((r) => r[1])
  if (!rows.length) return null
  return (
    <ul className="n-evid mono">
      {rows.map(([k, v]) => <li key={k}><span>{k}</span> {v}</li>)}
    </ul>
  )
}

/** Nguồn + bằng chứng của preset. Mặc định chưa tối ưu nói thẳng; preset trượt dev2 hiện bằng chứng và cảnh báo. */
export function PresetNote({ preset }) {
  const info = presetInfo(preset)
  return (
    <div className="n-preset-note">
      <div className="src">
        <Term k="preset">Preset</Term>
        {info.isDefault
          ? <span className="n-status warn">mặc định — chưa tối ưu</span>
          : <span className="n-status">{info.kindText || 'nguồn'}</span>}
        {info.timeframe && <span className="n-status info" title="Khung chạy lúc tối ưu preset">khung {info.timeframe}</span>}
        <span className="mono muted">{info.isDefault ? 'chưa có kết quả kiểm chứng' : info.sourceText}</span>
      </div>
      {info.failedDev2 && (
        <div className="n-err n-evid-fail" role="status">
          <b>Preset chưa qua kiểm chứng dev2</b>
          {info.stability ? <span className="muted"> · ổn định {info.stability}</span> : null}
          <Evidence info={info} />
        </div>
      )}
      {!info.failedDev2 && !info.isDefault && <Evidence info={info} />}
      {!info.failedDev2 && info.holdoutPass === false && <div className="n-note">Sổ chưa qua holdout{info.bookStatus ? ` (${info.bookStatus})` : ''}.</div>}
    </div>
  )
}

/**
 * Thẻ một chiến lược. mode=basic: preset chỉ đọc. mode=advanced: mọi tham số của lược đồ sửa được, trừ khoá không có trong `editableKeys` (khi truyền).
 * riskShared: { value, onChange } — rủi ro mỗi lệnh dùng chung cả danh mục (backend yêu cầu cùng mức giữa các chiến lược).
 */
export function StrategyCard({ strat, name = null, sideText = null, mode, params, onChange, onReset, errors = {}, editableKeys = null, lockedNote = WFA_PENDING_NOTE, riskShared = null, toggle = null, locked = {} }) {
  const schema = strat.params_schema
  const preset = strat.preset?.params || {}
  const on = toggle ? toggle.on : true
  const keysByGroup = getParamGroups(schema)
  const changed = mode === 'advanced' ? changedKeys(schema, params || {}, preset) : []
  const stratErrs = Object.entries(errors).filter(([k]) => !(k in schema))
  const nErr = Object.keys(errors).length
  return (
    <div className={`n-strat ${on ? 'on' : ''}`}>
      <div className="n-strat-h">
        {toggle && <input type="checkbox" id={`s-${strat.id}`} checked={toggle.on} onChange={toggle.onToggle} />}
        <label htmlFor={toggle ? `s-${strat.id}` : undefined} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', cursor: toggle ? 'pointer' : 'default' }}>
          <span className="id">{name || strat.id}</span>
          <span className={`n-badge ${String(strat.side).toLowerCase()}`}>{sideText || strat.side}</span>
          <span className="ds">{strat.description}</span>
        </label>
        {on && mode === 'advanced' && (
          <span className="n-strat-act">
            {nErr > 0 && <span className="n-status bad">{nErr} lỗi</span>}
            {changed.length > 0 && <span className="n-status info">{changed.length} khác preset</span>}
            {onReset && <button type="button" className="n-btn sm" onClick={onReset} disabled={!changed.length && !nErr}>Về mặc định tối ưu</button>}
          </span>
        )}
      </div>
      {on && <PresetNote preset={strat.preset} />}
      {on && mode === 'basic' && <ReadonlyGrid schema={schema} params={preset} />}
      {on && mode === 'advanced' && (
        <div className="n-pgroups">
          {stratErrs.map(([k, m]) => <div key={k} className="n-err" role="alert">{m}</div>)}
          {keysByGroup.map((g) => (
            <fieldset key={g.key} className="n-pgroup">
              <legend>{g.label}</legend>
              <div className="n-params">
                {g.keys.map((k) => {
                  const spec = schema[k]
                  const shared = k === 'risk_per_trade_pct' && riskShared
                  const lockedHere = locked[k]
                  const editable = !lockedHere && (!editableKeys || editableKeys.includes(k) || shared)
                  return (
                    <ParamField key={k} idBase={`p-${strat.id}`} k={k} spec={spec}
                      value={shared ? riskShared.value : params?.[k]}
                      onChange={(v) => (shared ? riskShared.onChange(v) : onChange({ ...params, [k]: v }))}
                      error={errors[k]} disabled={!editable} note={!editable ? (lockedHere || lockedNote) : shared ? 'dùng chung cả danh mục' : null}
                      changed={!shared && !sameValue(params?.[k], preset[k])} />
                  )
                })}
              </div>
            </fieldset>
          ))}
        </div>
      )}
    </div>
  )
}

export { modeText }
