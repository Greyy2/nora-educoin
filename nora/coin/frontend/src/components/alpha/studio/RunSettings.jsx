import React, { useState } from 'react'
import { Field } from '../../ui'
import { DateInput } from '../../ui/DateField'
import ExecModeSelect from '../../common/ExecModeSelect'
import RunModeSelect from '../../common/RunModeSelect'
import { paramLabel, paramUnit, paramHint } from '../../../lib/params'

/** Các tham số quản lý vị thế (khoá = tên khoá `position` của API). Để trống = dùng giá trị trong code / mặc định của engine. */
export const POSITION_FIELDS = [
  { key: 'fee_rate', min: 0, max: 0.02, step: 0.0001 },
  { key: 'maker_fee_rate', min: 0, max: 0.02, step: 0.0001 },
  { key: 'slippage_rate', min: 0, max: 0.1, step: 0.0001 },
  { key: 'stop_loss_rate', min: 0, max: 50, step: 0.1 },
  { key: 'take_profit_rate', min: 0, max: 50, step: 0.1 },
  { key: 'trailing_stop', min: 0, max: 50, step: 0.1 },
  { key: 'timeout', min: 0, max: 525600, step: 1 },
  { key: 'cooldown', min: 0, max: 525600, step: 1 },
  { key: 'risk_per_trade_pct', min: 0.05, max: 5, step: 0.05 },
  { key: 'leverage', min: 1, max: 125, step: 1 },
]

const symName = (s) => String(s).replace('@perp', '')

export default function RunSettings({ form, setForm, universe, defaultsError, problems, specDefaults = {}, specHash = null }) {
  const [showComboInfo, setShowComboInfo] = useState(false)
  const toggleSym = (s) => setForm({ symbols: form.symbols.includes(s) ? form.symbols.filter((x) => x !== s) : [...form.symbols, s] })
  const setPos = (k, v) => setForm({ pos: { ...form.pos, [k]: v }, last_spec_hash: specHash || form.last_spec_hash })
  const resetAllPos = () => setForm({ pos: {}, last_spec_hash: specHash })
  const nPos = Object.values(form.pos || {}).filter((v) => v !== '' && v != null).length
  const hasSpecHashMismatch = !!(specHash && form.last_spec_hash && form.last_spec_hash !== specHash && nPos > 0)

  return (
    <div className="se-set">
      <div className="n-field">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <span className="n-lbl" id="se-uni-l" style={{ margin: 0 }}>{`Tài sản (${form.symbols.length} đã chọn)`}</span>
          <button
            type="button"
            className="n-btn xs"
            style={{ fontSize: 11, padding: '2px 8px', display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', background: showComboInfo ? 'var(--n-accent, #38bdf8)' : 'rgba(56, 189, 248, 0.1)', color: showComboInfo ? '#000' : 'var(--n-accent, #38bdf8)', border: '1px solid var(--n-accent, #38bdf8)', borderRadius: 14 }}
            onClick={() => setShowComboInfo((v) => !v)}
            title="Xem so sánh: Chơi 1 con vs Combo nhiều con"
          >
            <span style={{ fontWeight: 800, borderRadius: '50%', background: showComboInfo ? '#000' : 'var(--n-accent, #38bdf8)', color: showComboInfo ? '#fff' : '#000', width: 14, height: 14, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 10 }}>i</span>
            <span style={{ fontWeight: 600 }}>Mẹo Combo</span>
          </button>
        </div>

        {showComboInfo && (
          <div style={{
            margin: '6px 0 10px',
            padding: '10px 12px',
            borderRadius: 8,
            background: 'var(--n-bg-panel, #0f172a)',
            border: '1px solid var(--n-accent, #38bdf8)',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            fontSize: 12
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontWeight: 700, color: 'var(--n-accent, #38bdf8)', display: 'flex', alignItems: 'center', gap: 6 }}>
                💡 Hướng dẫn: Chơi 1 tài sản vs Combo nhiều tài sản
              </span>
              <button type="button" className="n-btn xs ghost" style={{ padding: '0 4px', fontSize: 12 }} onClick={() => setShowComboInfo(false)}>✕</button>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, lineHeight: 1.45 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--n-border, rgba(255,255,255,0.1))', color: 'var(--n-text-muted, #94a3b8)' }}>
                  <th style={{ textAlign: 'left', padding: '4px 6px', width: '22%' }}>Tiêu chí</th>
                  <th style={{ textAlign: 'left', padding: '4px 6px', width: '38%', color: '#f59e0b' }}>Chơi 1 tài sản (vd: BTC)</th>
                  <th style={{ textAlign: 'left', padding: '4px 6px', width: '40%', color: '#10b981' }}>Chơi Combo (BTC + ETH + SOL)</th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                  <td style={{ padding: '5px 6px', fontWeight: 600, color: '#cbd5e1' }}>Bản chất</td>
                  <td style={{ padding: '5px 6px' }}>"Bỏ tất cả trứng vào 1 giỏ"</td>
                  <td style={{ padding: '5px 6px', color: '#34d399' }}>"Chia trứng vào 3 ngăn riêng"</td>
                </tr>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                  <td style={{ padding: '5px 6px', fontWeight: 600, color: '#cbd5e1' }}>Đường vốn (MDD)</td>
                  <td style={{ padding: '5px 6px' }}>Giật rất mạnh: BTC sập là tài khoản cắm đầu, đường cong gãy khúc.</td>
                  <td style={{ padding: '5px 6px', color: '#34d399' }}>Mượt mà hơn (Smooth): Con này lỗ thì con kia lãi gánh lại.</td>
                </tr>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                  <td style={{ padding: '5px 6px', fontWeight: 600, color: '#cbd5e1' }}>Cơ hội vào lệnh</td>
                  <td style={{ padding: '5px 6px' }}>Thấp: Khi BTC sideway, bot ngồi chơi, đọng vốn không sinh lời.</td>
                  <td style={{ padding: '5px 6px', color: '#34d399' }}>Liên tục: Dòng tiền xoay vòng, bắt được sóng của nhiều hệ.</td>
                </tr>
                <tr>
                  <td style={{ padding: '5px 6px', fontWeight: 600, color: '#cbd5e1' }}>Tâm lý giao dịch</td>
                  <td style={{ padding: '5px 6px' }}>Đau tim, phụ thuộc 100% vào số phận 1 đồng coin.</td>
                  <td style={{ padding: '5px 6px', color: '#34d399' }}>Tâm lý ổn định, ngủ ngon vì danh mục có sự bọc lót.</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}

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
                  return <label key={s} className={`n-chip-lbl ${on ? 'on' : ''}`}><input type="checkbox" checked={on} onChange={() => toggleSym(s)} />{symName(s)}</label>
                })}
              </div>
              {universe.length === 0 && <span className="n-note">{defaultsError ? `Không tải được mặc định từ kho dữ liệu: ${defaultsError}` : 'Đang tải danh sách tài sản…'}</span>}
              {universe.length > 0 && (
                <div className="se-row" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                  <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: sortedUni })}>Chọn tất cả ({sortedUni.length})</button>
                  <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: sortedUni.slice(0, 10) })}>Chọn Top 10</button>
                  <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: sortedUni.slice(0, 5) })}>Chọn Top 5</button>
                  <button type="button" className="n-btn sm" onClick={() => setForm({ symbols: [] })}>Bỏ chọn</button>
                </div>
              )}
            </>
          )
        })()}
        <span className="n-note">Hợp đồng vĩnh cửu OKX (perp); khối lượng theo rủi ro mỗi lệnh, cắt lỗ mặc định 3×ATR, phí và trượt giá theo sàn.</span>
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
          <input id="se-cap" type="number" className="n-in" inputMode="decimal" min="1" step="any" value={form.capital} onChange={(e) => setForm({ capital: e.target.value })} />
        </Field>
      </div>


      <details className="n-details se-pos">
          <summary style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span>Quản lý vị thế{nPos ? ` (${nPos} tham số đã ghi đè)` : ' (mặc định từ Spec)'}</span>
            {nPos > 0 && (
              <button
                type="button"
                className="n-btn xs"
                style={{ fontSize: 11, padding: '2px 8px', color: '#f59e0b', border: '1px solid #f59e0b', background: 'transparent' }}
                onClick={(e) => { e.preventDefault(); e.stopPropagation(); resetAllPos(); }}
                title="Xóa mọi ghi đè và khôi phục về giá trị mặc định của Spec"
              >
                Khôi phục mặc định ({nPos})
              </button>
            )}
          </summary>

          {hasSpecHashMismatch && (
            <div
              className="n-alert-warn"
              style={{
                margin: '8px 0',
                padding: '8px 12px',
                background: 'rgba(245, 158, 11, 0.15)',
                border: '1px solid #f59e0b',
                borderRadius: 6,
                fontSize: 12,
                color: '#f59e0b',
              }}
            >
              ⚠️ <b>Mã nguồn / Spec của chiến lược đã thay đổi</b> so với cấu hình ghi đè trước đó. Các tham số ghi đè có thể không còn tương thích. Bấm nút <b>"Khôi phục mặc định"</b> để đồng bộ lại với Spec.
            </div>
          )}

          <p className="n-note" style={{ margin: '8px 0' }}>
            Spec sở hữu giá trị mặc định; mọi thay đổi ở đây chỉ lưu dưới dạng ghi đè (overrides). Phí và trượt giá nhập dạng tỷ lệ thập phân (0.0005 = 5 bps). Cắt lỗ / chốt lời / trailing tính theo bội số ATR; timeout và cooldown tính bằng phút.
          </p>

          <div className="n-params">
            {POSITION_FIELDS.map((f) => {
              const unit = paramUnit(f.key)
              const lbl = paramLabel(f.key)
              const hasOverride = form.pos?.[f.key] !== '' && form.pos?.[f.key] != null
              const specVal = specDefaults[f.key]
              return (
                <div className="n-pf" key={f.key}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
                    <label htmlFor={`se-pos-${f.key}`} title={`${f.key}${paramHint(f.key) ? ` — ${paramHint(f.key)}` : ''}`} style={{ margin: 0 }}>
                      {lbl}{unit && !lbl.includes('(') ? <span className="u"> ({unit})</span> : null}
                    </label>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      {hasOverride ? (
                        <>
                          <span
                            className="n-badge n-badge-override"
                            style={{ fontSize: 10, padding: '1px 5px', background: 'rgba(245, 158, 11, 0.15)', color: '#f59e0b', borderRadius: 4, fontWeight: 600 }}
                          >
                            [Đã ghi đè]
                          </span>
                          <button
                            type="button"
                            className="n-btn xs ghost"
                            style={{ fontSize: 10, padding: '0 4px', color: '#f59e0b' }}
                            title="Khôi phục về giá trị từ Spec"
                            onClick={() => setPos(f.key, '')}
                          >
                            ↺
                          </button>
                        </>
                      ) : (
                        <span
                          className="n-badge n-badge-spec"
                          style={{ fontSize: 10, padding: '1px 5px', background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', borderRadius: 4, fontWeight: 500 }}
                        >
                          [Từ spec]
                        </span>
                      )}
                    </div>
                  </div>
                  <input
                    id={`se-pos-${f.key}`}
                    type="number"
                    inputMode="decimal"
                    className="n-in"
                    min={f.min}
                    max={f.max}
                    step={f.step}
                    placeholder={specVal !== undefined ? String(specVal) : 'mặc định'}
                    value={form.pos?.[f.key] ?? ''}
                    onChange={(e) => setPos(f.key, e.target.value)}
                  />
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
