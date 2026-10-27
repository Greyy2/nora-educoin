import React, { useState } from 'react'
import { Field } from '../../ui'
import { DateInput } from '../../ui/DateField'
import ExecModeSelect from '../../common/ExecModeSelect'
import RunModeSelect from '../../common/RunModeSelect'
import { paramLabel, paramUnit, paramHint } from '../../../lib/params'

/** Các tham số quản lý vị thế (khoá = tên khoá `position` của API). Để trống = dùng giá trị trong code / mặc định của engine. */
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

export default function RunSettings({ form, setForm, universe, defaultsError, problems, signalFrame, defaultExecMode = 'fast' }) {
  const toggleSym = (s) => setForm({ symbols: form.symbols.includes(s) ? form.symbols.filter((x) => x !== s) : [...form.symbols, s] })
  const setPos = (k, v) => setForm({ pos: { ...form.pos, [k]: v } })
  const nPos = Object.values(form.pos || {}).filter((v) => v !== '' && v != null).length
  const execMode = form.exec_mode || defaultExecMode

  return (
    <div className="se-set">
      <div className="n-field">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <span className="n-lbl" id="se-uni-l" style={{ margin: 0 }}>{`Tài sản (${form.symbols.length} đã chọn)`}</span>
        </div>

        {/* Sắp xếp tài sản: top assets lên đầu (BTC, ETH, SOL, BNB...) */}
        {(() => {
          const topOrder = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'ADA', 'AVAX', 'LINK', 'TRX']
          const sortedUni = [...universe].sort((a, b) => {
            const baseA = symName(a).toUpperCase()
            const baseB = symName(b).toUpperCase()
            const idxA = topOrder.indexOf(baseA)
            const idxB = topOrder.indexOf(baseB)
            if (idxA !== -1 && idxB !== -1) return idxA - idxB
            if (idxA !== -1) return -1
            if (idxB !== -1) return 1
            return baseA.localeCompare(baseB)
          })

          return (
            <>
              <div className="n-chips" role="group" aria-labelledby="se-uni-l">
                {sortedUni.map((s) => {
                  const on = form.symbols.includes(s)
                  return (
                    <label
                      key={s}
                      className={`n-chip-lbl ${on ? 'on' : ''}`}
                    >
                      <input type="checkbox" checked={on} onChange={() => toggleSym(s)} />
                      {symName(s)}
                    </label>
                  )
                })}
              </div>
              {universe.length === 0 && <span className="n-note">{defaultsError ? `Không tải được mặc định từ kho dữ liệu: ${defaultsError}` : 'Đang tải danh sách tài sản…'}</span>}
              {universe.length > 0 && (
                <div className="se-row" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
                  <button
                    type="button"
                    className="n-btn sm"
                    onClick={() => setForm({ symbols: sortedUni })}
                  >
                    Chọn tất cả ({sortedUni.length})
                  </button>
                  <button
                    type="button"
                    className="n-btn sm"
                    onClick={() => setForm({ symbols: sortedUni.slice(0, 10) })}
                  >
                    Chọn Top 10
                  </button>
                  <button
                    type="button"
                    className="n-btn sm"
                    onClick={() => setForm({ symbols: sortedUni.slice(0, 5) })}
                  >
                    Chọn Top 5
                  </button>
                  <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: [] })}>Bỏ chọn</button>
                </div>
              )}
            </>
          )
        })()}
        <span className="n-note">Hợp đồng vĩnh cửu OKX (perp); khối lượng theo rủi ro mỗi lệnh, cắt lỗ mặc định 3×ATR; khớp lệnh tại Open nến kế tiếp với synthetic quote spread proxy.</span>
      </div>

      <div className="n-form-row">
        <RunModeSelect id="se-run-mode" value={form.run_mode} onChange={(v) => setForm({ run_mode: v })} />
        <Field id="se-start" label="Từ ngày"><DateInput id="se-start" label="Từ ngày" value={form.start} onChange={(v) => setForm({ start: v })} /></Field>
        <Field id="se-end" label="Đến ngày"><DateInput id="se-end" label="Đến ngày" value={form.end} onChange={(v) => setForm({ end: v })} /></Field>
        <ExecModeSelect id="se-mode" value={form.exec_mode} onChange={(v) => setForm({ exec_mode: v })} />
        <Field id="se-ratio" label="Tỉ lệ train">
          <input id="se-ratio" type="number" className="n-in" inputMode="decimal" min="0.1" max="0.95" step="0.05" value={form.train_ratio}
            onChange={(e) => setForm({ train_ratio: e.target.value })} />
        </Field>
        <Field id="se-cap" label="Vốn ban đầu (USDT)">
          <input id="se-cap" type="number" className="n-in" inputMode="decimal" min="100" max="1000000000" step="any" value={form.capital} onChange={(e) => setForm({ capital: e.target.value })} />
        </Field>
      </div>
      <span className="n-note" aria-live="polite">
        {execMode === 'standard'
          ? `Khung mô phỏng: 1m${signalFrame ? ` · tín hiệu ${signalFrame}` : ''}.`
          : `Khung mô phỏng: khung tín hiệu${signalFrame ? ` ${signalFrame}` : ' (đọc từ code khi chạy)'}.`}
      </span>


      <details className="n-details se-pos">
          <summary>Quản lý vị thế{nPos ? ` (đã đặt ${nPos})` : ''}</summary>
          <p className="n-note" style={{ margin: '8px 0' }}>Để trống = dùng giá trị khai báo trong code, hoặc mặc định của engine. Cắt lỗ / chốt lời / trailing tính theo bội số ATR; timeout và cooldown tính bằng phút.</p>
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

      {problems.length > 0 && (
        <ul className="se-problems" role="status">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
    </div>
  )
}
