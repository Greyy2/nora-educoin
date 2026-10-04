import React from 'react'
import { Panel, Status } from '../ui'
import { isNum, fmtNum } from '../../lib/format'
import { fmtTs, fmtVal } from './chartUtil'
import { legLabel } from '../../lib/strategyLabel'

const OP = { '<': '<', '>': '>', '<=': '≤', '>=': '≥', '==': '=', '!=': '≠' }

// Cây điều kiện: các khối AND nối với nhau bằng HOẶC
function CondTree({ title, blocks }) {
  if (!blocks?.length) return <div className="n-ex-tree"><b>{title}</b><div className="n-note">Không có điều kiện (thoát theo SL/TP/trailing/hết hạn).</div></div>
  return (
    <div className="n-ex-tree">
      <b>{title}</b>
      {blocks.map((conds, i) => (
        <React.Fragment key={i}>
          {i > 0 && <div className="or">HOẶC</div>}
          <ul className="blk">{conds.map((c, k) => <li key={k}>{k > 0 && <span className="and">VÀ </span>}{c}</li>)}</ul>
        </React.Fragment>
      ))}
    </div>
  )
}

function PositionParams({ p }) {
  if (!p) return null
  const atr = p.exit_unit === 'atr'
  const u = atr ? '× ATR' : '%'
  const f = (v) => (isNum(v) && v > 0 ? `${fmtNum(v, 2)} ${u}` : 'không dùng')
  const items = [
    ['Cắt lỗ', f(p.stop_loss_rate)], ['Chốt lời', f(p.take_profit_rate)],
    ['Trailing', isNum(p.trailing_stop) && p.trailing_stop > 0 ? `${fmtNum(p.trailing_stop, 2)} ${u}${isNum(p.trailing_activation_pct) && p.trailing_activation_pct > 0 ? ` (kích hoạt từ ${fmtNum(p.trailing_activation_pct, 2)} ${u})` : ''}` : 'không dùng'],
    ['Hết hạn', p.timeout > 0 ? `${p.timeout} phút` : 'không giới hạn'], ['Chờ vào lại', p.cooldown > 0 ? `${p.cooldown} phút` : 'không chờ'],
    ['Đòn bẩy', isNum(p.leverage) ? `${p.leverage}x` : '—'],
  ]
  if (atr) items.push(['ATR', `${p.atr_frame} · chu kỳ ${p.atr_period}`])
  if (p.dca_steps?.length) items.push(['DCA', p.dca_steps.map((s, i) => `${s}%${p.dca_multipliers?.[i] != null ? `×${p.dca_multipliers[i]}` : ''}`).join(', ')])
  return (
    <dl className="n-ex-kv">
      {items.map(([k, v]) => <div key={k}><dt>{k}</dt><dd className="mono">{v}</dd></div>)}
    </dl>
  )
}

function SelectedSignal({ sig }) {
  const entry = sig.kind === 'entry'
  const blocks = [...new Set((sig.conditions || []).map((c) => c.block))].sort((a, b) => a - b)
  const okSet = new Set(sig.blocks_ok || [])
  return (
    <div>
      <div className="n-ex-sel">
        <Status tone={entry ? 'ok' : 'warn'}>{entry ? 'Tín hiệu vào' : 'Tín hiệu thoát'}</Status>
        <span className="mono">{fmtTs(sig.t)} UTC</span>
        <span className="mono">giá đóng {fmtVal(sig.price)}</span>
      </div>
      <div className="n-tblwrap">
        <table className="n-tbl n-ex-tbl">
          <thead><tr><th>Điều kiện</th><th className="r">Giá trị trái</th><th className="c">So</th><th className="r">Giá trị phải</th><th className="c">Kết quả</th></tr></thead>
          <tbody>
            {blocks.map((b) => (
              <React.Fragment key={b}>
                {blocks.length > 1 && <tr className="grp"><td colSpan={5}><b>Khối {b + 1}</b> · {okSet.has(b) ? <span className="pos">thoả cả khối</span> : <span className="neg">chưa thoả cả khối</span>}</td></tr>}
                {sig.conditions.filter((c) => c.block === b).map((c, i) => (
                  <tr key={i}>
                    <td className="wrap">{c.text}</td>
                    <td className="r mono">{fmtVal(c.left)}</td><td className="c mono">{OP[c.op] || c.op}</td><td className="r mono">{fmtVal(c.right)}</td>
                    <td className={`c ${c.ok ? 'pos' : 'neg'}`}><b aria-label={c.ok ? 'Thoả' : 'Không thoả'}>{c.ok ? '✓' : '✗'}</b></td>
                  </tr>
                ))}
              </React.Fragment>
            ))}
            {!blocks.length && <tr><td colSpan={5} className="muted">Không có chi tiết điều kiện.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Giải thích vì sao có tín hiệu: chiến lược, cây điều kiện, tham số lệnh, giá trị từng điều kiện của tín hiệu đang chọn. */
export default function SignalExplainPanel({ data, selected }) {
  if (!data) return null
  const s = data.strategy || {}
  const src = s.book ? `sổ ${s.book === 'explore' ? 'thử nghiệm' : 'chính'}${s.book_source ? ` · ${s.book_source}` : ''}` : s.alpha_id ? `phễu ${s.run_id} · alpha ${s.alpha_id}` : null
  return (
    <div className="n-ex">
      <Panel title="Chiến lược">
        <div className="n-ex-head">
          <span title={s.id}><b>{legLabel(s.id)}</b></span>
          {s.side && legLabel(s.id) === s.id && <span className={`n-badge ${String(s.side).toLowerCase()}`}>{s.side}</span>}
          {s.family && <span className="n-note">{s.family}</span>}
          {s.unvalidated && <Status tone="warn">⚠ chưa kiểm định</Status>}
          {s.regime && <span className="n-badge">regime {s.regime}</span>}
        </div>
        {s.description && <p className="n-note" style={{ margin: '6px 0' }}>{s.description}</p>}
        {src && <div className="n-note">Nguồn: <span className="mono">{src}</span></div>}
      </Panel>
      <Panel title="Điều kiện của chiến lược">
        <CondTree title="Vào lệnh" blocks={data.conditions?.entry} />
        <CondTree title="Thoát" blocks={data.conditions?.exit} />
        <PositionParams p={data.position} />
      </Panel>
      <Panel title="Tín hiệu đang chọn">
        {selected ? <SelectedSignal sig={selected} /> : <p className="n-note">Bấm vào một điểm tín hiệu trên biểu đồ.</p>}
        {data.note && <p className="n-note" style={{ marginTop: 8 }}>{data.note}</p>}
      </Panel>
    </div>
  )
}
