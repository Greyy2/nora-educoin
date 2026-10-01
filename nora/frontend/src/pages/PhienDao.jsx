import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Loading, ErrorBox, Empty, Block } from '../components/common'
import { Pager, usePaged } from '../components/Pager'
import ParamTuner from '../components/ParamTuner'
import { int, num, money, pct } from '../lib/format'

/** Bảng xếp hạng các tổ hợp tham số của một phiên đào, kèm nút tinh chỉnh */
function ResultTable({ oid, onCreated }) {
  const [rows, setRows] = useState(null)
  const [sort, setSort] = useState('balance')
  const [err, setErr] = useState(null)
  const [tinhChinh, setTinhChinh] = useState(false)
  const [prog, setProg] = useState(null)
  const [msg, setMsg] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setRows(null); setErr(null); setTinhChinh(false); setMsg(null)
    api.optimizationResults(oid, { limit: 60, sort })
      .then((r) => setRows(r.rows)).catch(setErr)
  }, [oid, sort])

  const doiTienDo = () => api.optProgress(oid).then(setProg).catch(() => {})
  useEffect(() => { doiTienDo() }, [oid])

  // đang chạy thì theo dõi tiến độ quét
  useEffect(() => {
    if (!prog?.busy) return undefined
    const t = setInterval(doiTienDo, 4000)
    return () => clearInterval(t)
  }, [prog?.busy, oid])

  const chay = async () => {
    if (!window.confirm('Chạy phiên quét này? Mỗi tổ hợp tham số là một lần backtest.')) return
    setBusy(true); setMsg(null)
    try {
      await api.optStart(oid)
      setMsg('Đã gửi lệnh chạy phiên quét.')
      setTimeout(doiTienDo, 2500)
    } catch (e) { setErr(e) } finally { setBusy(false) }
  }
  const dung = async () => {
    setBusy(true)
    try { await api.optStop(oid); setMsg('Đã gửi lệnh dừng.'); setTimeout(doiTienDo, 1500) }
    catch (e) { setErr(e) } finally { setBusy(false) }
  }

  const than = (
    <div style={{ background: 'var(--panel-2)', borderTop: '1px solid var(--line-2)', padding: '14px 16px' }}>
      <div className="bar-ctl" style={{ marginBottom: 12 }}>
        <button className="btn" onClick={() => setTinhChinh(!tinhChinh)}>
          ⚙ {tinhChinh ? 'Ẩn tinh chỉnh' : 'Tinh chỉnh tham số quét'}
        </button>
        {prog?.busy ? (
          <button className="btn" onClick={dung} disabled={busy}
            style={{ borderColor: 'var(--down)', color: 'var(--down)' }}>■ Dừng quét</button>
        ) : (
          <button className="btn" onClick={chay} disabled={busy}>▶ Chạy quét</button>
        )}
        {prog && (prog.busy || prog.total > 0) && (
          <span style={{ fontSize: 12.5, color: 'var(--ink-2)' }}>
            <span className={`tag ${prog.busy ? 'run' : 'stop'}`}>
              {prog.state === 'running' ? 'Đang quét'
                : prog.state === 'starting' ? 'Đang khởi động'
                : prog.state === 'done' ? 'Đã quét xong' : 'Chưa chạy'}
            </span>
            {' '}{int(prog.processed)}/{int(prog.total)} tổ hợp
            {prog.percent !== null && prog.percent !== undefined ? ` · ${prog.percent}%` : ''}
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12.5, color: 'var(--ink-3)' }}>Xếp theo</span>
        <select value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="balance">Số dư cuối</option>
          <option value="position">Số lệnh</option>
          <option value="invest">Vốn dùng ít nhất</option>
          <option value="unrealize">Lỗ tạm thời thấp nhất</option>
        </select>
      </div>

      {msg && <div className="pre luu_y">{msg}</div>}
      {err && <div className="pre loi">{String(err.message || err)}</div>}
      {tinhChinh && (
        <ParamTuner oid={oid} onClose={() => setTinhChinh(false)}
          onCreated={(id) => { setTinhChinh(false); onCreated && onCreated(id) }} />
      )}

      {!rows ? <Loading text="Đang tải bảng xếp hạng…" />
        : rows.length === 0 ? <Empty text="Phiên này chưa có kết quả" />
        : bangXepHang(rows)}
    </div>
  )
  return than
}

/** Phần bảng xếp hạng thuần — tách ra cho gọn */
function bangXepHang(rows) {
  const maxBal = Math.max(...rows.map((r) => Math.abs(Number(r.balance || 0))), 1)
  return (
    <>
      <div style={{ border: '1px solid var(--line)', background: 'var(--panel)', maxHeight: 460, overflow: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th className="n">#</th><th className="n">Số dư</th><th className="n">Lệnh</th>
              <th className="n">Thắng</th><th className="n">Mua</th><th className="n">Bán</th>
              <th className="n">Vốn đỉnh</th><th className="n">Lỗ tạm đỉnh</th><th>Tham số</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.id}>
                <td className="n" style={{ color: i < 3 ? 'var(--amber)' : 'var(--ink-3)' }}>{i + 1}</td>
                <td className="n bar">
                  <i style={{
                    width: `${Math.min(100, (Math.abs(Number(r.balance || 0)) / maxBal) * 100)}%`,
                    background: 'var(--up)',
                  }} />
                  <span>{money(r.balance)}</span>
                </td>
                <td className="n">{int(r.positions)}</td>
                <td className="n">{r.winrate !== null ? pct(r.winrate) : '—'}</td>
                <td className="n">{int(r.longs)}</td>
                <td className="n">{int(r.shorts)}</td>
                <td className="n">{money(r.invest_max)}</td>
                <td className="n down">{money(r.unrealize_max)}</td>
                <td className="mono" style={{
                  fontSize: 11.5, color: 'var(--ink-3)', maxWidth: 260,
                  overflow: 'hidden', textOverflow: 'ellipsis',
                }}>
                  {String(r.params || '').slice(0, 90)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

/** Phiên đào alpha: quét dải tham số để tìm bộ số cho kết quả tốt nhất */
export default function PhienDao() {
  const [rows, setRows] = useState(null)
  const [q, setQ] = useState('')
  const [err, setErr] = useState(null)
  const [open, setOpen] = useState(null)

  const [taoMoi, setTaoMoi] = useState(false)

  const load = () => {
    setRows(null); setErr(null); setOpen(null)
    api.optimizations({ q, limit: 300 }).then((r) => setRows(r.rows)).catch(setErr)
  }
  useEffect(load, [])

  const pg = usePaged(rows)

  return (
    <>
      <div className="bar-ctl">
        <button className="btn pri" onClick={() => setTaoMoi(true)}>＋ Tạo phiên đào mới</button>
        <input placeholder="Tìm theo tên phiên…" value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()} style={{ minWidth: 260 }} />
        <button className="btn" onClick={load}>Tìm</button>
      </div>

      {taoMoi && (
        <ParamTuner onClose={() => setTaoMoi(false)}
          onCreated={() => { setTaoMoi(false); load() }} />
      )}

      <Block flush>
        {err ? <ErrorBox error={err} onRetry={load} />
          : rows === null ? <Loading />
          : rows.length === 0 ? <Empty />
          : (
            <>
              <div className="tblwrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 26 }}></th>
                    <th>Mã</th><th>Tên phiên</th><th className="n">Chạy gốc</th>
                    <th className="n">Luồng</th><th className="n">Tổ hợp</th><th>Tiến độ</th>
                  </tr>
                </thead>
                <tbody>
                  {pg.slice.map((o) => {
                    const pctDone = o.total ? Math.round((o.done / o.total) * 100) : 0
                    return (
                      <React.Fragment key={o.id}>
                        <tr className="rowlink"
                          onClick={() => setOpen(open === o.id ? null : o.id)}
                          style={open === o.id ? { background: 'var(--panel-2)' } : undefined}>
                          <td style={{ color: 'var(--amber)', fontFamily: 'var(--mono)' }}>
                            {open === o.id ? '▾' : '▸'}
                          </td>
                          <td className="mono">{o.id}</td>
                          <td style={{ maxWidth: 330, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {o.name || '—'}
                          </td>
                          <td className="n mono">{o.base_run || '—'}</td>
                          <td className="n">{o.workers || '—'}</td>
                          <td className="n">{int(o.total)}</td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <div style={{ width: 70, height: 5, background: 'var(--panel-3)' }}>
                                <div style={{ height: '100%', width: `${pctDone}%`, background: 'var(--amber)' }} />
                              </div>
                              <span style={{ fontSize: 12, color: 'var(--ink-3)', fontVariantNumeric: 'tabular-nums' }}>
                                {int(o.done)}/{int(o.total)}
                              </span>
                            </div>
                          </td>
                        </tr>
                        {open === o.id && (
                          <tr>
                            <td colSpan={7} style={{ padding: 0, whiteSpace: 'normal' }}>
                              <ResultTable oid={o.id} onCreated={() => load()} />
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    )
                  })}
                </tbody>
              </table>
              </div>
              <Pager {...pg} unit="phiên" />
            </>
          )}
      </Block>
    </>
  )
}
