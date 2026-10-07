import React from 'react'
import { Segmented, Field } from '../ui'
import { DateInput, DatePresets } from '../DateField'
import { paramLabel, paramUnit, paramHint } from '../../lib/params'

export const PROFILES = [
  { value: 'xno', label: 'xno', title: 'Giống xnoquant' },
  { value: 'nora', label: 'nora', title: 'Quản lý vị thế của Nora' },
]
const PROFILE_NOTE = {
  xno: 'Giống xnoquant: giữ vị thế theo tín hiệu, không cắt lỗ / chốt lời, phí 0,1 %, vốn chia cho rổ TOP10 theo tỉ trọng vốn hoá cố định.',
  nora: 'Quản lý vị thế của Nora: cắt lỗ / chốt lời theo ATR, rủi ro mỗi lệnh theo vốn, phí và trượt giá theo sàn.',
}
const TOP10 = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'SOL', 'DOGE', 'TRX', 'LINK', 'BCH']

/** Các tham số quản lý vị thế của hồ sơ nora (khoá = tên khoá `position` của API). Để trống = dùng giá trị trong code / mặc định hồ sơ. */
export const POSITION_FIELDS = [
  { key: 'stop_loss_rate', min: 0, max: 50, step: 0.1 },
  { key: 'take_profit_rate', min: 0, max: 50, step: 0.1 },
  { key: 'trailing_stop', min: 0, max: 50, step: 0.1 },
  { key: 'timeout', min: 0, max: 525600, step: 1 },
  { key: 'cooldown', min: 0, max: 525600, step: 1 },
  { key: 'risk_per_trade_pct', min: 0.05, max: 5, step: 0.05 },
  { key: 'leverage', min: 1, max: 125, step: 1 },
]

const symName = (s) => String(s).replace('@perp', '')

export default function RunSettings({ form, setForm, universe, catalogLoading, catalogError, windows, problems }) {
  const nora = form.profile === 'nora'
  const toggleSym = (s) => setForm({ symbols: form.symbols.includes(s) ? form.symbols.filter((x) => x !== s) : [...form.symbols, s] })
  const setPos = (k, v) => setForm({ pos: { ...form.pos, [k]: v } })
  const nPos = Object.values(form.pos || {}).filter((v) => v !== '' && v != null).length

  return (
    <div className="se-set">
      <div className="n-field">
        <span className="n-lbl" id="se-prof-l">Hồ sơ thực thi</span>
        <Segmented label="Hồ sơ thực thi" value={form.profile} onChange={(v) => setForm({ profile: v })} options={PROFILES} />
        <span className="n-note">{PROFILE_NOTE[form.profile]}</span>
      </div>

      <div className="n-field">
        <span className="n-lbl" id="se-uni-l">{nora ? `Tài sản (${form.symbols.length} đã chọn)` : 'Rổ tài sản'}</span>
        {nora ? (
          <>
            <div className="n-chips" role="group" aria-labelledby="se-uni-l">
              {universe.map((s) => {
                const on = form.symbols.includes(s)
                return <label key={s} className={`n-chip-lbl ${on ? 'on' : ''}`}><input type="checkbox" checked={on} onChange={() => toggleSym(s)} />{symName(s)}</label>
              })}
            </div>
            {universe.length === 0 && <span className="n-note">{catalogLoading ? 'Đang tải danh sách tài sản…' : `Chưa có danh sách tài sản${catalogError ? `: ${catalogError}` : ''}.`}</span>}
            {universe.length > 0 && (
              <div className="se-row">
                <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: universe })}>Chọn tất cả</button>
                <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: [] })}>Bỏ chọn</button>
              </div>
            )}
          </>
        ) : (
          <>
            <div className="n-chips" role="group" aria-labelledby="se-uni-l">
              <span className="n-badge">TOP10</span>
              {TOP10.map((s) => <span key={s} className="n-badge">{s}</span>)}
            </div>
            <span className="n-note">Rổ cố định như xnoquant (spot USDT, nến ngày). Muốn chọn tài sản khác, dùng hồ sơ nora.</span>
          </>
        )}
      </div>

      <div className="n-form-row">
        <Field id="se-start" label="Từ ngày"><DateInput id="se-start" label="Từ ngày" value={form.start} onChange={(v) => setForm({ start: v })} /></Field>
        <Field id="se-end" label="Đến ngày"><DateInput id="se-end" label="Đến ngày" value={form.end} onChange={(v) => setForm({ end: v })} /></Field>
        <Field id="se-ratio" label="Tỉ lệ train">
          <input id="se-ratio" type="number" className="n-in" inputMode="decimal" min="0.1" max="0.95" step="0.05" value={form.train_ratio}
            onChange={(e) => setForm({ train_ratio: e.target.value })} />
        </Field>
        <Field id="se-cap" label="Vốn ban đầu (USDT)">
          <input id="se-cap" type="number" className="n-in" inputMode="decimal" min="1" step="any" value={form.capital} onChange={(e) => setForm({ capital: e.target.value })} />
        </Field>
      </div>
      {windows?.start && windows?.end && <DatePresets windows={windows} start={form.start} end={form.end} onPick={(s, e) => setForm({ start: s, end: e })} />}

      {nora && (
        <details className="n-details se-pos">
          <summary>Quản lý vị thế{nPos ? ` (đã đặt ${nPos})` : ''}</summary>
          <p className="n-note" style={{ margin: '8px 0' }}>Để trống = dùng giá trị khai báo trong code, hoặc mặc định của hồ sơ nora. Cắt lỗ / chốt lời / trailing tính theo bội số ATR; timeout và cooldown tính bằng phút.</p>
          <div className="n-params">
            {POSITION_FIELDS.map((f) => {
              const unit = paramUnit(f.key)
              const lbl = paramLabel(f.key)
              return (
                <div className="n-pf" key={f.key}>
                  <label htmlFor={`se-pos-${f.key}`} title={`${f.key}${paramHint(f.key) ? ` — ${paramHint(f.key)}` : ''}`}>
                    {lbl}{unit && !lbl.includes('(') ? <span className="u"> ({unit})</span> : null}
                  </label>
                  <input id={`se-pos-${f.key}`} type="number" inputMode="decimal" className="n-in" min={f.min} max={f.max} step={f.step} placeholder="mặc định"
                    value={form.pos?.[f.key] ?? ''} onChange={(e) => setPos(f.key, e.target.value)} />
                </div>
              )
            })}
          </div>
        </details>
      )}

      {problems.length > 0 && (
        <ul className="se-problems" role="status">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
    </div>
  )
}
