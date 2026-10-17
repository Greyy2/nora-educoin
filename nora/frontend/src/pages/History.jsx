import React, { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageHead, Panel, Segmented, Status, Spinner, Empty, Loading, ErrorState } from '../components/ui'
import useJobList from '../hooks/useJobList'
import { useMeta } from '../meta/MetaProvider'
import { ResolvedParams } from '../components/optimize/RunModes'
import { CUSTOM_BADGE, CUSTOM_REASON } from '../lib/modes'
import Term from '../components/ui/Term'
import { JOB_STATUS, jobKindText, jobLink, jobElapsed, isActiveJob, jobDetail } from '../lib/jobs'
import { fmtDuration, fmtDateTime, toMs, fmtMoney, fmtPct, fmtSPct, isNum } from '../lib/format'
import { useResource } from '../hooks/useAsync'
import { getLiveArchive } from '../api'

const STATES = [
  { value: 'all', label: 'Tất cả' }, { value: 'running', label: 'Đang chạy' }, { value: 'queued', label: 'Đang chờ' }, { value: 'done', label: 'Hoàn tất' }, { value: 'failed', label: 'Thất bại' },
]

const TABS = [{ value: 'backtest', label: 'Backtest' }, { value: 'testnet', label: 'Testnet' }, { value: 'live', label: 'Live' }]
const BACKTEST_KIND = /backtest|wfa|^mc|carlo/ // backtest / custom / walk-forward / Monte Carlo
const BOT_NAME = { 'paper:main': 'Paper · sổ chính', 'paper:explore': 'Paper · thử nghiệm 15m', 'demo:main': 'Demo OKX · sổ chính', 'demo:legacy': 'Demo OKX · bản cũ' }

// Bot cũ (đã dừng) đọc từ data/live: testnet = data/live/testnet, live = data/live/live. Số liệu thật từ state/events, không có thì để trống.
function BotHistory({ tab }) {
  const q = useResource('live:archive', getLiveArchive)
  const bots = (q.data?.bots || []).filter((b) => (tab === 'testnet' ? b.tab === 'testnet' || b.tab === 'paper' : b.tab === 'live'))
  if (q.error) return <ErrorState title="Không tải được lịch sử bot" error={q.error} onRetry={q.reload} />
  if (q.loading && !q.data) return <Loading what="lịch sử bot" />
  if (!bots.length) return <Empty title={tab === 'live' ? 'Chưa có lần chạy Live nào' : 'Chưa có lần chạy Testnet nào'}>Bot mới chạy trên engine mới — sắp có.</Empty>
  return (
    <Panel title={tab === 'live' ? 'Bot Live (đã dừng)' : 'Bot Testnet / Paper (đã dừng)'} meta={<span>Dữ liệu bot cũ (đã dừng)</span>}>
      <div className="n-tblwrap">
        <table className="n-tbl">
          <thead><tr><th>Bot</th><th>Bắt đầu (UTC)</th><th>Ghi nhận cuối (UTC)</th><th className="r">Vốn đầu</th><th className="r">Vốn cuối</th><th className="r">Lãi/lỗ</th><th className="r">MDD</th><th className="r">Lệnh đã đóng</th><th /></tr></thead>
          <tbody>
            {bots.map((b) => (
              <tr key={`${b.mode}${b.book}${b.engine}`}>
                <td>{BOT_NAME[`${b.mode}:${b.mode === 'demo' && b.engine === 'legacy' ? 'legacy' : b.book}`] || `${b.mode} · ${b.book}`}</td>
                <td className="mono">{isNum(b.started) ? fmtDateTime(b.started) : '—'}</td>
                <td className="mono">{isNum(b.ended) ? fmtDateTime(b.ended) : '—'}</td>
                <td className="r">{isNum(b.start_equity) ? fmtMoney(b.start_equity) : '—'}</td>
                <td className="r">{isNum(b.equity) ? fmtMoney(b.equity) : '—'}</td>
                <td className="r">{isNum(b.pnl_pct) ? fmtSPct(b.pnl_pct) : '—'}</td>
                <td className="r">{isNum(b.mdd_pct) ? fmtPct(b.mdd_pct) : '—'}</td>
                <td className="r">{b.trades}</td>
                <td><Link className="n-btn sm" to="/coin/live">Mở</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

export default function History() {
  const [tab, setTab] = useState('backtest')
  const { jobs: allJobs, loading, error, reload, running, queued, updatedAt } = useJobList(100)
  const jobs = useMemo(() => allJobs.filter((j) => BACKTEST_KIND.test(String(j.kind || ''))), [allJobs])
  const { meta: appMeta } = useMeta()
  const [kind, setKind] = useState('all')
  const KINDS = useMemo(() => [{ value: 'all', label: 'Tất cả' }, ...[...new Set(jobs.map((j) => j.kind).filter(Boolean))].map((k) => ({ value: k, label: jobKindText(k, appMeta) }))], [jobs, appMeta])
  const [state, setState] = useState('all')
  const nav = useNavigate()
  const rows = useMemo(() => jobs.filter((j) => (kind === 'all' || j.kind === kind) && (state === 'all' || j.status === state)), [jobs, kind, state])
  const now = Date.now()

  const openOnPortfolio = (j) => {
    try { localStorage.setItem('nora-v2-portfolio', JSON.stringify({ jobId: j.job_id, period: 'ALL' })) } catch (e) { /* bỏ qua */ }
    nav('/portfolio')
  }

  return (
    <>
      <PageHead kicker="Công việc nền" title="Lịch sử chạy"
        subtitle="Backtest: các lần chạy backtest, walk-forward và Monte Carlo (tối đa 100 job gần nhất). Testnet / Live: bot giao dịch đã chạy trên sàn.">
        <Segmented label="Nhóm lịch sử" value={tab} onChange={setTab} options={TABS} />
        {tab === 'backtest' && <Segmented label="Lọc theo loại" value={kind} onChange={setKind} options={KINDS} />}
        {tab === 'backtest' && <Segmented label="Lọc theo trạng thái" value={state} onChange={setState} options={STATES} />}
      </PageHead>

      {tab !== 'backtest' && <BotHistory tab={tab} />}
      {tab === 'backtest' && <>

      {error && <ErrorState title="Không tải được lịch sử chạy" error={error} onRetry={reload} />}
      {loading && !jobs.length && <Loading what="lịch sử chạy" />}
      {!loading && !error && !jobs.length && <Empty title="Chưa có lần backtest nào">Chạy thử tại <Link to="/coin/alpha/create" style={{ color: 'var(--n-accent)' }}>Alpha</Link> hoặc <Link to="/coin/backtest" style={{ color: 'var(--n-accent)' }}>Backtest</Link>.</Empty>}

      {jobs.length > 0 && (
        <Panel title="Các lần chạy" meta={
          <>
            <span>{rows.length}/{jobs.length} lần</span>
            {(running + queued) > 0 && <span><Spinner /> {running} đang chạy{queued ? ` · ${queued} đang chờ` : ''}</span>}
            {updatedAt && <span className="muted">tự làm mới</span>}
            <button type="button" className="n-btn sm" onClick={reload}>Làm mới</button>
          </>
        }>
          <div className="n-tblwrap long">
            <table className="n-tbl">
              <thead>
                <tr><th>Bắt đầu (UTC)</th><th>Loại</th><th>Chế độ</th><th>Nội dung</th><th>Trạng thái</th><th className="r">Thời lượng</th><th>Mã job</th><th /></tr>
              </thead>
              <tbody>
                {rows.map((j) => {
                  const meta = JOB_STATUS[j.status] || { text: j.status, cls: '' }
                  const el = jobElapsed(j, now)
                  return (
                    <tr key={j.job_id}>
                      <td className="mono">{fmtDateTime(toMs(j.created))}</td>
                      <td>{jobKindText(j.kind, appMeta)}</td>
                      <td>{j.mode ? (
                        <span className="n-modecell">
                          <span className={`n-mode-badge ${j.mode}`}>{j.mode === 'advanced' ? <Term k="mode_advanced">Nâng cao</Term> : <Term k="mode_basic">Cơ bản</Term>}</span>
                          {(j.custom_gates || j.promotable === false) && <span className="n-custom-badge" title={CUSTOM_REASON}>⚠ {CUSTOM_BADGE}</span>}
                        </span>
                      ) : <span className="muted">—</span>}</td>
                      <td className="wrap" title={j.label}>{jobDetail(j)}<ResolvedParams job={j} /></td>
                      <td><Status tone={meta.cls}>{isActiveJob(j) && <Spinner />}{meta.text}</Status></td>
                      <td className="r">{el != null ? fmtDuration(el) : '—'}</td>
                      <td className="mono muted">{j.job_id}</td>
                      <td><div className="acts">
                        {jobLink(j) && <Link className="n-btn sm" to={jobLink(j)}>Mở</Link>}
                        {j.kind === 'book_backtest' && j.status === 'done' && <button type="button" className="n-btn sm" onClick={() => openOnPortfolio(j)}>Danh mục ↗</button>}
                      </div></td>
                    </tr>
                  )
                })}
                {!rows.length && <tr><td colSpan={8} className="muted">Không có lần chạy nào khớp bộ lọc.</td></tr>}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
      </>}
    </>
  )
}
