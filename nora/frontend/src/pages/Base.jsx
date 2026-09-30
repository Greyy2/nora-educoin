import React, { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Loading, ErrorBox, Empty, Block } from '../components/common'
import { Pager, usePaged } from '../components/Pager'
import AlphaBuilder from '../components/AlphaBuilder'
import Relaunch from '../components/Relaunch'
import { useRunProgress, useRunLog } from '../hooks/useRunSocket'
import { int, money, dateOnly } from '../lib/format'

const STATE = {
  starting: 'Đang khởi động',
  running: 'Đang chạy',
  done: 'Đã chạy xong',
  stopped: 'Chưa chạy',
  interrupted: 'Dừng giữa chừng',
}

/** Bảng điều khiển một lần chạy: kiểm tra cấu hình, chạy, dừng, xem log và tiến độ */
function RunPanel({ runId, onChanged }) {
  const [info, setInfo] = useState(null)
  const [pre, setPre] = useState(null)
  const [manualLog, setManualLog] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const [err, setErr] = useState(null)
  const [chayLai, setChayLai] = useState(false)
  const [xong, setXong] = useState(null)      // thông báo chạy xong + đếm ngược
  const dieuHuong = useNavigate()

  // Tiến độ đẩy về theo thời gian thực; mất kết nối thì tự lùi về hỏi định kỳ
  const { progress: prog, live, refresh } = useRunProgress(runId, true)
  const liveLog = useRunLog(runId, !!(prog?.busy || prog?.running))
  const log = liveLog || manualLog

  useEffect(() => {
    setInfo(null); setPre(null); setManualLog(null); setMsg(null); setErr(null)
    api.run(runId).then(setInfo).catch(setErr)
    api.preflight(runId).then(setPre).catch(() => {})
  }, [runId])

  // Chỉ làm mới danh sách bên ngoài khi một lượt chạy THẬT SỰ vừa kết thúc.
  //
  // Trước đây hễ thấy trạng thái "đã chạy xong" là gọi onChanged, kể cả với lần
  // chạy đã xong từ đời nào. Mà onChanged nạp lại danh sách -> bảng bị xoá trắng
  // -> dòng đang mở biến mất -> bảng điều khiển tháo ra rồi lắp lại -> lại thấy
  // "đã chạy xong" -> gọi tiếp. Vòng lặp đó chính là chỗ màn hình nháy liên tục
  // và không xem được kết quả.
  const dangChay = useRef(false)
  useEffect(() => {
    const ban = !!(prog?.busy || prog?.running)
    if (ban) {
      dangChay.current = true
    } else if (dangChay.current) {
      dangChay.current = false
      onChanged && onChanged()
      // Chỉ run hoàn tất bình thường mới được báo thành công và tự chuyển trang.
      // `interrupted` vẫn có kết quả dở dang để xem, nhưng không phải backtest xong.
      if (prog?.state === 'done') setXong({ trades: prog?.trades || 0, dem: 6 })
    }
  }, [prog?.busy, prog?.running, prog?.state, prog?.trades])

  // đếm ngược rồi chuyển trang
  useEffect(() => {
    if (!xong) return undefined
    if (xong.dem <= 0) {
      dieuHuong(`/library/result/${runId}`)
      return undefined
    }
    const t = setTimeout(() => setXong((x) => (x ? { ...x, dem: x.dem - 1 } : x)), 1000)
    return () => clearTimeout(t)
  }, [xong, runId])

  const doStop = async () => {
    if (!window.confirm('Dừng backtest đang chạy?')) return
    setBusy(true); setMsg(null); setErr(null)
    try {
      await api.stop(runId)
      setMsg('Đã gửi lệnh dừng.')
      refresh()
    } catch (e) { setErr(e) } finally { setBusy(false) }
  }

  const showLog = () => api.log(runId, 120).then((r) => setManualLog(r.data || '(chưa có log)')).catch(setErr)

  if (err && !info) return <div className="msg err">{String(err.message || err)}</div>
  if (!info) return <Loading />

  const busy_run = prog?.busy || prog?.running    // đang khởi động cũng tính là đang bận
  const running = prog?.running
  const loi = (pre?.issues || []).filter((i) => i.muc === 'loi')
  const luuY = (pre?.issues || []).filter((i) => i.muc === 'luu_y')

  return (
    <div style={{ background: 'var(--panel-2)', borderTop: '1px solid var(--line-2)', padding: '15px 18px' }}>
      {/* thông số cấu hình */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(158px,1fr))', gap: 1,
        background: 'var(--line)', border: '1px solid var(--line)', marginBottom: 14,
      }}>
        {[
          ['Số coin', int(info.campaigns)],
          ['Vốn', money(info.balance)],
          ['Kiểu ký quỹ', info.margin_type || '—'],
          ['Khối dữ liệu', info.data_length ? `${info.data_length} ngày` : '—'],
          ['Bắt đầu', info.period?.t1 ? dateOnly(info.period.t1 * 1000) : '—'],
          ['Kết thúc', info.period?.t2 ? dateOnly(info.period.t2 * 1000) : '—'],
        ].map(([k, v]) => (
          <div key={k} style={{ background: 'var(--panel)', padding: '11px 14px' }}>
            <div style={{
              fontFamily: 'var(--mono)', fontSize: 10.5, letterSpacing: '.1em',
              textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: 5,
            }}>{k}</div>
            <b style={{ fontVariantNumeric: 'tabular-nums' }}>{v}</b>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 13, color: 'var(--ink-2)', marginBottom: 12 }}>
        Dữ liệu <span className="mono" style={{ color: 'var(--amber)' }}>{info.dataset || '—'}</span>
        {pre?.account?.node && <> · node <span className="mono">{pre.account.node}</span></>}
      </div>

      {/* kiểm tra trước khi chạy */}
      {loi.map((i, k) => <div key={`e${k}`} className="pre loi">{i.text}</div>)}
      {luuY.map((i, k) => <div key={`w${k}`} className="pre luu_y">{i.text}</div>)}

      {/* tiến độ */}
      {prog && (busy_run || prog.trades > 0 || prog.total > 0) && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5,
            color: 'var(--ink-2)', marginBottom: 5, flexWrap: 'wrap' }}>
            <span className={`tag ${busy_run ? 'run' : 'stop'}`}>{STATE[prog.state] || '—'}</span>
            {busy_run && live && (
              <span style={{ color: 'var(--up)', fontSize: 11.5 }}>● trực tiếp</span>
            )}
            {prog.state === 'starting' ? (
              <span>Đang chờ tiến trình khởi động…</span>
            ) : (
              <>
                <span>{int(prog.trades)} lệnh đã sinh</span>
                {prog.total > 0 && (
                  <span style={{ color: 'var(--ink-3)' }}>
                    {int(prog.processed)} / {int(prog.total)} nến
                  </span>
                )}
              </>
            )}
            {prog.state !== 'starting' && prog.percent !== null && prog.percent !== undefined && (
              <b style={{ marginLeft: 'auto', fontVariantNumeric: 'tabular-nums' }}>
                {prog.percent}%
              </b>
            )}
          </div>
          {prog.total > 0 && prog.state !== 'starting' && (
            <div className="prog"><i style={{ width: `${Math.min(100, prog.percent || 0)}%` }} /></div>
          )}
          {prog.state === 'starting' && <div className="prog dang-cho"><i /></div>}
          {prog.state === 'interrupted' && (
            <div className="pre loi" style={{ marginTop: 8 }}>
              Tiến trình đã dừng giữa chừng — chưa chạy hết dữ liệu.
            </div>
          )}
        </div>
      )}

      {xong && (
        <div className="xong">
          <b>Chạy xong</b>
          <span>{int(xong.trades)} lệnh đã sinh · sang trang kết quả sau {xong.dem} giây</span>
          <Link className="btn pri" to={`/library/result/${runId}`}>Xem kết quả ngay</Link>
          <button className="btn" onClick={() => setXong(null)}>Ở lại</button>
        </div>
      )}

      {/* nút điều khiển */}
      <div className="bar-ctl" style={{ marginBottom: log ? 12 : 0 }}>
        {busy_run ? (
          <button className="btn" onClick={doStop} disabled={busy}
            style={{ borderColor: 'var(--down)', color: 'var(--down)' }}>
            {busy ? 'Đang gửi…' : '■ Dừng'}
          </button>
        ) : (
          <button className="btn pri" onClick={() => setChayLai(true)} disabled={busy || !pre?.ok}
            title={pre?.ok ? '' : 'Cấu hình chưa hợp lệ'}>
            {info?.state === 'done' || info?.state === 'interrupted' ? '▶ Chạy lại backtest' : '▶ Chạy backtest'}
          </button>
        )}
        <button className="btn" onClick={showLog}>Xem log</button>
        <button className="btn" onClick={refresh}>Làm mới</button>
        <Link className="btn" to={`/library/result/${runId}`}>Xem kết quả</Link>
      </div>

      {chayLai && (
        <Relaunch
          runId={runId}
          canhBao={(pre?.issues || []).filter((i) => i.muc === 'luu_y').map((i) => i.text)}
          onClose={() => setChayLai(false)}
          onXong={(r) => {
            if (r.kieu === 'nguyen') refresh()
            onChanged && onChanged()
          }} />
      )}

      {msg && <div className="pre luu_y" style={{ marginTop: 10 }}>{msg}</div>}
      {err && <div className="pre loi" style={{ marginTop: 10 }}>{String(err.message || err)}</div>}
      {log && <pre className="logbox">{log}</pre>}
    </div>
  )
}

/** Alpha vừa được phiên đào sinh ra nhưng chưa có lần chạy nào — trạng thái "chưa chạy" */
function AlphaMoi({ onDung }) {
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)
  const [sort, setSort] = useState('balance')
  const [dung, setDung] = useState(null)

  const load = () => {
    setRows(null); setErr(null)
    api.alphaMoi({ limit: 200, sort }).then((r) => setRows(r.rows)).catch(setErr)
  }
  useEffect(load, [sort])

  const pg = usePaged(rows)

  return (
    <>
      <div className="bar-ctl">
        <span style={{ fontSize: 12.5, color: 'var(--ink-3)' }}>Xếp theo</span>
        <select value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="balance">Số dư mô phỏng cao nhất</option>
          <option value="moi">Mới sinh gần đây</option>
        </select>
        <button className="btn" onClick={load}>Làm mới</button>
      </div>

      {dung && (
        <AlphaBuilder rid={dung}
          onClose={() => setDung(null)}
          onCreated={load}
          onDone={() => { setDung(null); onDung && onDung() }} />
      )}

      <Block flush>
        {err ? <ErrorBox error={err} onRetry={load} />
          : rows === null ? <Loading />
          : rows.length === 0 ? <Empty text="Chưa có alpha nào được sinh ra" />
          : (
            <>
              <div className="tblwrap">
                <table>
                  <thead>
                    <tr>
                      <th>Mã alpha</th><th>Sinh từ phiên đào</th>
                      <th className="n">Số dư mô phỏng</th><th className="n">Lệnh</th>
                      <th className="n">Mua</th><th className="n">Bán</th>
                      <th>Trạng thái</th><th />
                    </tr>
                  </thead>
                  <tbody>
                    {pg.slice.map((a) => (
                      <tr key={a.id}>
                        <td className="mono">{a.id}</td>
                        <td style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          <span className="mono" style={{ color: 'var(--ink-3)' }}>{a.opt_id}</span>{' '}
                          {a.opt_name || '—'}
                        </td>
                        <td className="n up">{money(a.balance)}</td>
                        <td className="n">{int(a.positions)}</td>
                        <td className="n">{int(a.longs)}</td>
                        <td className="n">{int(a.shorts)}</td>
                        <td>
                          {a.run_id
                            ? <span className="tag run">Đã dựng · {a.run_id}</span>
                            : <span className="tag stop">Chưa chạy</span>}
                        </td>
                        <td>
                          {a.run_id
                            ? <Link className="btn" to={`/library/result/${a.run_id}`}>Xem</Link>
                            : <button className="btn pri" onClick={() => setDung(a.id)}>▶ Run backtest</button>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager {...pg} unit="alpha" />
            </>
          )}
      </Block>
    </>
  )
}

export default function Base() {
  const [rows, setRows] = useState(null)
  const [groups, setGroups] = useState([])
  const [group, setGroup] = useState('')
  const [q, setQ] = useState('')
  const [err, setErr] = useState(null)
  const [open, setOpen] = useState(null)
  const [node, setNode] = useState(null)
  const [cheDo, setCheDo] = useState('run')   // run: lần chạy đã có · alpha: alpha mới gen

  // Không xoá trắng bảng khi nạp lại: bảng trắng làm dòng đang mở bị tháo ra,
  // mất cả bảng điều khiển đang xem. Chỉ để trắng ở lần tải đầu.
  const load = ({ lam_moi = false } = {}) => {
    if (!lam_moi) setRows(null)
    setErr(null)
    api.runs({ group, q, limit: 300 }).then((r) => setRows(r.rows)).catch(setErr)
  }
  useEffect(() => {
    api.groups().then((r) => setGroups(r.rows)).catch(() => {})
    api.node().then(setNode).catch(() => {})
  }, [])
  useEffect(load, [group])

  const pg = usePaged(rows)

  return (
    <>
      <div className="head">
        <div className="head-row">
          <h1>Cấu hình chạy</h1>
          <div className="switch">
            <button className={cheDo === 'run' ? 'on' : ''} onClick={() => setCheDo('run')}>
              Lần chạy
            </button>
            <button className={cheDo === 'alpha' ? 'on' : ''} onClick={() => setCheDo('alpha')}>
              Alpha mới gen
            </button>
          </div>
        </div>
        <p>
          {cheDo === 'run'
            ? 'Mỗi dòng là một lần chạy. Bấm vào để xem cấu hình và bấm nút chạy backtest.'
            : 'Alpha do phiên đào sinh ra, chưa có lần chạy nào. Dựng thành lần chạy rồi backtest.'}
        </p>
      </div>

      {cheDo === 'alpha' && <AlphaMoi onDung={() => { setCheDo('run'); load() }} />}

      {cheDo === 'run' && (
      <>
      <div className="bar-ctl">
        <select value={group} onChange={(e) => setGroup(e.target.value)}>
          <option value="">Tất cả nhóm</option>
          {groups.map((g) => <option key={g.name} value={g.name}>{g.name} ({g.n})</option>)}
        </select>
        <input placeholder="Tìm theo tên hoặc mã…" value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()} style={{ minWidth: 230 }} />
        <button className="btn" onClick={() => load()}>Tìm</button>
        {node && (
          <span className={`tag ${node.ready ? 'run' : 'stop'}`} style={{ marginLeft: 'auto' }}>
            Node {node.node}: {node.ready ? 'sẵn sàng' : 'chưa sẵn sàng'}
          </span>
        )}
      </div>

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
                      <th>Mã</th><th>Tên</th><th>Nhóm</th>
                      <th className="n">Vốn</th><th>Dữ liệu</th><th>Trạng thái</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pg.slice.map((r) => (
                      <React.Fragment key={r.id}>
                        <tr className="rowlink" onClick={() => setOpen(open === r.id ? null : r.id)}
                          style={open === r.id ? { background: 'var(--panel-2)' } : undefined}>
                          <td style={{ color: 'var(--amber)', fontFamily: 'var(--mono)' }}>
                            {open === r.id ? '▾' : '▸'}
                          </td>
                          <td className="mono">{r.id}</td>
                          <td>{r.name || '—'}</td>
                          <td style={{ color: 'var(--ink-3)' }}>{r.group || '—'}</td>
                          <td className="n">{money(r.balance)}</td>
                          <td className="mono" style={{ fontSize: 11.5, color: 'var(--ink-3)' }}>
                            {r.dataset || '—'}
                          </td>
                          <td>
                            <span className={`tag ${r.running ? 'run' : 'stop'}`}>
                              {r.running ? 'Đang chạy' : 'Đã dừng'}
                            </span>
                          </td>
                        </tr>
                        {open === r.id && (
                          <tr><td colSpan={7} style={{ padding: 0, whiteSpace: 'normal' }}>
                            <RunPanel runId={r.id} onChanged={() => load({ lam_moi: true })} />
                          </td></tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager {...pg} unit="lần chạy" />
            </>
          )}
      </Block>
      </>
      )}
    </>
  )
}
