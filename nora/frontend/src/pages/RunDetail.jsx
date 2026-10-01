import React, { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Loading, ErrorBox, Empty, Card, Block, BarCell, Spark, Legend } from '../components/common'
import MetricTable from '../components/MetricTable'
import StrategyCard from '../components/StrategyCard'
import { money, pct, int, num, dur, dt } from '../lib/format'

export default function RunDetail() {
  const { id } = useParams()
  const [info, setInfo] = useState(null)
  const [ov, setOv] = useState(null)
  const [flows, setFlows] = useState(null)
  const [beh, setBeh] = useState(null)
  const [syms, setSyms] = useState(null)
  const [tl, setTl] = useState(null)
  const [eq, setEq] = useState(null)
  const [ins, setIns] = useState(null)
  const [met, setMet] = useState(null)
  const [cls, setCls] = useState(null)
  const [gocNhin, setGocNhin] = useState('coin')   // bảng diễn biến: theo coin hay theo tháng
  const [err, setErr] = useState(null)

  useEffect(() => {
    setErr(null)
    api.run(id).then(setInfo).catch(setErr)
    api.overview(id).then(setOv).catch(setErr)
    api.byFlow(id).then((r) => setFlows(r.rows)).catch(() => setFlows([]))
    api.behavior(id).then(setBeh).catch(() => setBeh(null))
    api.bySymbol(id).then((r) => setSyms(r.rows)).catch(() => setSyms([]))
    api.timeline(id).then((r) => setTl(r.rows)).catch(() => setTl([]))
    api.equity(id, 1200).then(setEq).catch(() => setEq(null))
    api.insights(id).then((r) => setIns(r.rows)).catch(() => setIns([]))
    api.metrics(id).then(setMet).catch(() => setMet(null))
    api.chienLuocRun(id).then((r) => setCls(r.rows)).catch(() => setCls([]))
  }, [id])

  if (err) return <ErrorBox error={err} />
  if (!ov) return <Loading text="Đang tổng hợp kết quả…" />

  const maxFlowPnl = Math.max(...(flows || []).map((f) => Math.abs(Number(f.pnl || 0))), 1)
  const maxSymPnl = Math.max(...(syms || []).map((s) => Math.abs(Number(s.pnl || 0))), 1)
  const maxTlPnl = Math.max(...(tl || []).map((t) => Math.abs(Number(t.pnl || 0))), 1)

  return (
    <>
      <p className="crumb"><Link to="/library/result">Các lần chạy</Link> · mã {id}</p>
      <div className="head">
        <div className="head-row">
          <div>
            <h1>{info?.name || `Lần chạy ${id}`}</h1>
            <p>
              {info?.campaigns || 0} coin · dữ liệu <span className="mono">{info?.dataset}</span>
              {info?.margin_type ? ` · ${info.margin_type}` : ''}
              {info?.running ? ' · đang chạy' : ''}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              className="btn"
              disabled
              title="Run legacy (MySQL) chưa có snapshot AST nên không chạy được WFA. Hãy chạy lại chiến lược trong Studio."
            >
              🔄 WFA: cần chạy lại trong Studio
            </button>
          </div>
        </div>
      </div>

      {/* ---------- Tầng 1: tổng quan ---------- */}
      <div className="cards">
        <Card label="Tổng lãi lỗ" value={ov.pnl} tone="auto" sub="USDT" />
        <Card label="Tỷ lệ thắng" value={pct(ov.winrate)} sub={`${int(ov.so_lenh)} lệnh`} />
        <Card label="Lãi / lỗ mỗi lệnh"
          value={ov.ty_le_lai_lo ? `${num(ov.ty_le_lai_lo)} : 1` : '—'}
          tone={ov.ty_le_lai_lo >= 1.5 ? 'up' : ov.ty_le_lai_lo < 0.8 ? 'down' : ''}
          sub={`${money(ov.lai_tb)} / ${money(ov.lo_tb)}`} />
        <Card label="Số coin" value={int(ov.so_coin)} sub={`giữ TB ${dur(ov.gio_giu_tb)}`} />
        <Card label="Bậc nhồi sâu nhất" value={String(ov.phase_max ?? '—')}
          tone={ov.phase_max === 0 ? 'down' : ''}
          sub={ov.phase_max === 0 ? 'không nhồi lệnh' : 'bậc DCA'} />
        <Card label="Vốn cao nhất" value={ov.von_cao_nhat}
          sub={`thấp nhất ${money(ov.von_thap_nhat)}`} />
      </div>

      {/* ---------- Chiến lược đã dùng ---------- */}
      {cls && cls.length > 0 && (
        <Block title="Chiến lược đã chạy" note="bấm để xem điều kiện vào lệnh">
          {cls.map((s) => <StrategyCard key={s.id} s={s} />)}
        </Block>
      )}

      {/* ---------- Tầng 6: nhận xét tự động ---------- */}
      {ins && ins.length > 0 && (
        <Block title="Nhận xét" note="rút ra tự động từ dữ liệu">
          {ins.map((i, k) => (
            <div key={k} className={`insight ${i.muc}`}>
              <b>{i.tieu_de}</b>
              <p>{i.chi_tiet}</p>
            </div>
          ))}
        </Block>
      )}

      {/* ---------- Tầng 2: phân rã theo nhánh ---------- */}
      <Block title="Phân rã theo nhánh chiến lược"
        note="chỗ lộ ra bộ phận nào sinh lời" flush>
        {!flows ? <Loading /> : flows.length === 0 ? <Empty /> : (
          <div className="tblwrap">
            <table>
              <thead>
                <tr>
                  <th>Nhánh</th><th className="n">Số lệnh</th><th className="n">Tỷ lệ thắng</th>
                  <th className="n">Giữ TB</th><th className="n">Lãi lỗ</th><th className="n">TB mỗi lệnh</th>
                </tr>
              </thead>
              <tbody>
                {flows.map((f) => (
                  <tr key={f.flow}>
                    <td className="mono">{f.flow || '—'}</td>
                    <td className="n">{int(f.so_lenh)}</td>
                    <td className="n">{pct(f.winrate)}</td>
                    <td className="n">{dur(f.gio_giu_tb)}</td>
                    <BarCell value={f.pnl} max={maxFlowPnl} />
                    <td className="n">{money(f.pnl_tb)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Block>

      {/* ---------- Đường vốn ---------- */}
      {eq && eq.points?.length > 0 && (
        <Block title="Đường vốn"
          note={`${int(eq.total)} điểm, hiển thị ${int(eq.points.length)}`}>
          <Spark series={[
            { data: eq.points.map((p) => Number(p.balance)), color: 'var(--amber)' },
            { data: eq.points.map((p) => Number(p.margin_balance)), color: 'var(--info)' },
            { data: eq.points.map((p) => Number(p.unrealize)), color: 'var(--down)' },
          ]} />
          <Legend items={[
            { label: 'Số dư', color: 'var(--amber)' },
            { label: 'Số dư ký quỹ', color: 'var(--info)' },
            { label: 'Lỗ chưa thực hiện', color: 'var(--down)', value: ov.lo_chua_thuc_hien_max },
          ]} />
        </Block>
      )}

      {/* ---------- Tầng 3: hành vi ---------- */}
      {beh && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(300px,1fr))', gap: 20 }}>
          <Block title="Kết cục lệnh" flush>
            <div className="tblwrap">
              <table>
                <thead><tr><th>Trạng thái</th><th className="n">Số lệnh</th><th className="n">Lãi lỗ</th></tr></thead>
                <tbody>
                  {beh.status.map((s) => (
                    <tr key={s.ma}>
                      <td>{s.ten}</td>
                      <td className="n">{int(s.so_lenh)}</td>
                      <td className={`n ${Number(s.pnl) > 0 ? 'up' : Number(s.pnl) < 0 ? 'down' : ''}`}>
                        {money(s.pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Block>

          <Block title="Thời gian giữ lệnh" flush>
            <div className="tblwrap">
              <table>
                <thead><tr><th>Khoảng</th><th className="n">Số lệnh</th><th className="n">Lãi lỗ</th></tr></thead>
                <tbody>
                  {beh.hold.map((h) => (
                    <tr key={h.khoang}>
                      <td>{h.khoang}</td>
                      <td className="n">{int(h.so_lenh)}</td>
                      <td className={`n ${Number(h.pnl) > 0 ? 'up' : Number(h.pnl) < 0 ? 'down' : ''}`}>
                        {money(h.pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Block>

          <Block title="Theo hướng lệnh" flush>
            <div className="tblwrap">
              <table>
                <thead><tr><th>Hướng</th><th className="n">Số lệnh</th><th className="n">Thắng</th><th className="n">Lãi lỗ</th></tr></thead>
                <tbody>
                  {beh.side.map((s) => (
                    <tr key={s.huong}>
                      <td>{s.huong}</td>
                      <td className="n">{int(s.so_lenh)}</td>
                      <td className="n">{pct(s.winrate)}</td>
                      <td className={`n ${Number(s.pnl) > 0 ? 'up' : Number(s.pnl) < 0 ? 'down' : ''}`}>
                        {money(s.pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Block>

          <Block title="Bậc nhồi lệnh (DCA)" flush>
            <div className="tblwrap">
              <table>
                <thead><tr><th>Bậc</th><th className="n">Số lệnh</th><th className="n">Lãi lỗ</th></tr></thead>
                <tbody>
                  {beh.phases.map((p) => (
                    <tr key={p.phase}>
                      <td>Bậc {p.phase}</td>
                      <td className="n">{int(p.so_lenh)}</td>
                      <td className={`n ${Number(p.pnl) > 0 ? 'up' : Number(p.pnl) < 0 ? 'down' : ''}`}>
                        {money(p.pnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Block>
        </div>
      )}

      {/* ---------- Diễn biến: một bảng, đổi góc nhìn bằng nút ---------- */}
      <Block
        title="Diễn biến"
        note={gocNhin === 'coin'
          ? 'bấm vào coin để xem biểu đồ'
          : `${(tl || []).length} tháng có lệnh`}
        actions={(
          <div className="switch">
            <button className={gocNhin === 'coin' ? 'on' : ''} onClick={() => setGocNhin('coin')}>
              Theo coin
            </button>
            <button className={gocNhin === 'thang' ? 'on' : ''} onClick={() => setGocNhin('thang')}>
              Theo tháng
            </button>
          </div>
        )}
        flush
      >
        {gocNhin === 'coin' ? (
          !syms ? <Loading /> : syms.length === 0 ? <Empty /> : (
            <div className="tblwrap">
              <table>
                <thead>
                  <tr>
                    <th>Coin</th><th className="n">Số lệnh</th><th className="n">Tỷ lệ thắng</th>
                    <th className="n">Lãi lỗ</th><th className="n">Lãi TB</th><th className="n">Lỗ TB</th>
                    <th className="n">Giữ TB</th>
                  </tr>
                </thead>
                <tbody>
                  {syms.map((s) => (
                    <tr key={s.symbol} className="rowlink">
                      <td className="mono">
                        <Link to={`/library/result/${id}/chart?symbol=${s.symbol}`} style={{ color: 'var(--amber)' }}>
                          {s.symbol}
                        </Link>
                      </td>
                      <td className="n">{int(s.so_lenh)}</td>
                      <td className="n">{pct(s.winrate)}</td>
                      <BarCell value={s.pnl} max={maxSymPnl} />
                      <td className="n up">{money(s.lai_tb)}</td>
                      <td className="n down">{money(s.lo_tb)}</td>
                      <td className="n">{dur(s.gio_giu_tb)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          !tl ? <Loading /> : tl.length === 0 ? <Empty /> : (
            <div className="tblwrap">
              <table>
                <thead>
                  <tr><th>Tháng</th><th className="n">Số lệnh</th><th className="n">Tỷ lệ thắng</th><th className="n">Lãi lỗ</th></tr>
                </thead>
                <tbody>
                  {tl.map((t) => (
                    <tr key={t.thang}>
                      <td className="mono">{t.thang}</td>
                      <td className="n">{int(t.so_lenh)}</td>
                      <td className="n">{pct(t.winrate)}</td>
                      <BarCell value={t.pnl} max={maxTlPnl} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </Block>

      {/* ---------- Bảng thống kê theo tham số đánh giá ---------- */}
      <Block title="Chỉ số đánh giá"
        note="lãi lỗ, rủi ro và chất lượng — không phải thống kê từng lệnh" flush>
        {!met ? <Loading text="Đang tính chỉ số…" /> : <MetricTable m={met} />}
      </Block>

      <div className="bar-ctl" style={{ marginTop: 6 }}>
        <Link className="btn" to={`/library/result/${id}/trades`}>Xem danh sách lệnh</Link>
        <Link className="btn pri" to={`/library/result/${id}/chart`}>Mở biểu đồ</Link>
      </div>
    </>
  )
}
