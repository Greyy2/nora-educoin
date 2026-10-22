import React, { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { PageHead, Panel, Segmented, Status, Spinner, Empty, Loading, ErrorState } from '../components/ui'
import useJobList from '../hooks/useJobList'
import { useMeta } from '../meta/MetaProvider'
import { ResolvedParams } from '../components/optimize/RunModes'
import { CUSTOM_BADGE, CUSTOM_REASON } from '../lib/modes'
import Term from '../components/ui/Term'
import { JOB_STATUS, jobKindText, jobLink, jobElapsed, isActiveJob, jobDetail } from '../lib/jobs'
import { fmtDuration, fmtDateTime, toMs, fmtMoney, fmtPct, fmtSPct, isNum, signClass } from '../lib/format'
import { useResource } from '../hooks/useAsync'
import { getLiveArchive, listLiveBots } from '../api'

const STATES = [
  { value: 'all', label: 'Tất cả' },
  { value: 'running', label: 'Đang chạy' },
  { value: 'queued', label: 'Đang chờ' },
  { value: 'done', label: 'Hoàn tất' },
  { value: 'failed', label: 'Thất bại' },
]

const TABS = [
  { value: 'backtest', label: 'Backtest' },
  { value: 'testnet', label: 'Testnet' },
  { value: 'live', label: 'Live' },
]

const BACKTEST_KIND = /backtest|wfa|^mc|carlo/

function BotHistory({ tab, stateFilter }) {
  const qArch = useResource('live:archive', getLiveArchive)
  const qList = useResource('live:bots', () => listLiveBots())

  const loading = (qArch.loading && !qArch.data) || (qList.loading && !qList.data)
  const error = qArch.error || qList.error

  const allBots = useMemo(() => {
    const listBots = (qList.data?.bots || []).map((b) => ({
      id: b.bot_id || b.id,
      name: b.name || `${(b.mode || '').toUpperCase()} · ${b.strategy || (b.strategies || []).join(', ') || 'Bot'}`,
      mode: b.mode,
      tab: b.mode === 'live' ? 'live' : 'testnet',
      started: b.started_at,
      ended: b.stopped_at,
      capital: b.capital,
      equity: b.equity,
      pnl_pct: b.pnl_pct,
      pnl_usd: b.pnl_usd,
      mdd_pct: b.mdd_pct,
      trades: b.trades_count ?? b.samples ?? (b.trades != null ? b.trades : 0),
      status: b.status === 'running' ? 'running' : (b.status === 'failed' || b.status === 'error' ? 'failed' : 'done'),
      symbols: b.symbols || [],
    }))

    const archBots = (qArch.data?.bots || []).map((b) => ({
      id: b.bot_id || `${b.mode}:${b.book}:${b.engine}`,
      name: b.name || `${(b.mode || '').toUpperCase()} · ${b.book || 'Bot'}`,
      mode: b.mode,
      tab: b.tab === 'live' ? 'live' : 'testnet',
      started: b.started,
      ended: b.ended,
      capital: b.start_equity,
      equity: b.equity,
      pnl_pct: b.pnl_pct,
      pnl_usd: isNum(b.equity) && isNum(b.start_equity) ? b.equity - b.start_equity : null,
      mdd_pct: b.mdd_pct,
      trades: b.trades ?? 0,
      status: b.status === 'running' ? 'running' : (b.status === 'failed' ? 'failed' : 'done'),
      symbols: b.symbols || [],
    }))

    // Gộp và loại trừ trùng id
    const seen = new Set()
    const merged = []
    for (const b of [...listBots, ...archBots]) {
      if (!seen.has(b.id)) {
        seen.add(b.id)
        merged.push(b)
      }
    }
    return merged.sort((a, b) => (b.ended || b.started || 0) - (a.ended || a.started || 0))
  }, [qList.data, qArch.data])

  const rows = useMemo(() => {
    return allBots.filter((b) => {
      const matchTab = (tab === 'testnet' ? b.tab === 'testnet' || b.mode === 'paper' || b.mode === 'testnet' : b.tab === 'live' || b.mode === 'live')
      const matchState = (stateFilter === 'all' || b.status === stateFilter || (stateFilter === 'done' && (b.status === 'done' || b.status === 'stopped')))
      return matchTab && matchState
    })
  }, [allBots, tab, stateFilter])

  if (error) return <ErrorState title="Không tải được lịch sử bot" error={error} onRetry={() => { qArch.reload(); qList.reload() }} />
  if (loading) return <Loading what="lịch sử bot giao dịch" />
  if (!rows.length) {
    return (
      <Empty title={tab === 'live' ? 'Chưa có lượt chạy Live nào phù hợp' : 'Chưa có lượt chạy Testnet / Paper nào phù hợp'}>
        Kiểm tra trạng thái bot hoặc chuyển sang trang <Link to="/coin/live" style={{ color: 'var(--n-accent)' }}>Giao dịch Live</Link> để bật bot mới.
      </Empty>
    )
  }

  return (
    <Panel
      title={tab === 'live' ? 'Lịch sử Bot Live' : 'Lịch sử Bot Testnet & Paper'}
      meta={
        <>
          <span>{rows.length} bot</span>
          <button type="button" className="n-btn sm" onClick={() => { qArch.reload(); qList.reload() }}>Làm mới</button>
        </>
      }
    >
      <div className="n-tblwrap">
        <table className="n-tbl">
          <thead>
            <tr>
              <th>Bot / Chiến lược</th>
              <th>Cặp giao dịch</th>
              <th>Bắt đầu (UTC)</th>
              <th>Kết thúc (UTC)</th>
              <th className="r">Vốn</th>
              <th className="r">Lãi/lỗ</th>
              <th className="r">MDD</th>
              <th className="r">Lệnh khớp</th>
              <th>Trạng thái</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id}>
                <td><b>{b.name}</b></td>
                <td><small>{(b.symbols || []).slice(0, 3).join(', ')}{(b.symbols || []).length > 3 ? '…' : ''}</small></td>
                <td className="mono">{isNum(b.started) ? fmtDateTime(b.started) : '—'}</td>
                <td className="mono">{isNum(b.ended) ? fmtDateTime(b.ended) : '—'}</td>
                <td className="r">{isNum(b.capital) ? `${fmtMoney(b.capital)} USDT` : '—'}</td>
                <td className={`r ${signClass(b.pnl_pct)}`}>
                  <b>{fmtSPct(b.pnl_pct, 2)}</b>
                  {isNum(b.pnl_usd) && <small> ({fmtMoney(b.pnl_usd, true)})</small>}
                </td>
                <td className="r">{isNum(b.mdd_pct) ? fmtPct(b.mdd_pct, 2) : '—'}</td>
                <td className="r"><b>{b.trades}</b></td>
                <td>
                  <Status tone={b.status === 'running' ? 'ok' : (b.status === 'failed' ? 'bad' : 'warn')}>
                    {b.status === 'running' ? 'Đang chạy' : (b.status === 'failed' ? 'Thất bại' : 'Đã dừng')}
                  </Status>
                </td>
                <td><Link className="n-btn sm" to="/coin/live">Mở ↗</Link></td>
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
  const [state, setState] = useState('all')
  const { jobs: allJobs, loading, error, reload, running, queued, updatedAt } = useJobList(100)
  const jobs = useMemo(() => allJobs.filter((j) => BACKTEST_KIND.test(String(j.kind || ''))), [allJobs])
  const { meta: appMeta } = useMeta()
  const nav = useNavigate()
  const now = Date.now()

  // Lọc chỉ theo trạng thái
  const rows = useMemo(() => jobs.filter((j) => (state === 'all' || j.status === state)), [jobs, state])

  const openOnPortfolio = (j) => {
    try { localStorage.setItem('nora-v2-portfolio', JSON.stringify({ jobId: j.job_id, period: 'ALL' })) } catch (e) { /* bỏ qua */ }
    nav('/portfolio')
  }

  return (
    <>
      <PageHead
        kicker="Công việc nền"
        title="Lịch sử chạy"
        subtitle="Theo dõi tiến độ và lịch sử kiểm định backtest, walk-forward, Monte Carlo cũng như bot chạy sàn Testnet / Live."
      >
        <Segmented label="Nhóm chạy" value={tab} onChange={setTab} options={TABS} />
        <Segmented label="Trạng thái" value={state} onChange={setState} options={STATES} />
      </PageHead>

      {tab !== 'backtest' && <BotHistory tab={tab} stateFilter={state} />}

      {tab === 'backtest' && (
        <>
          {error && <ErrorState title="Không tải được lịch sử chạy" error={error} onRetry={reload} />}
          {loading && !jobs.length && <Loading what="lịch sử chạy" />}
          {!loading && !error && !jobs.length && (
            <Empty title="Chưa có lần backtest nào">
              Chạy thử tại <Link to="/coin/alpha/create" style={{ color: 'var(--n-accent)' }}>Alpha</Link> hoặc <Link to="/coin/backtest" style={{ color: 'var(--n-accent)' }}>Backtest</Link>.
            </Empty>
          )}

          {jobs.length > 0 && (
            <Panel
              title="Các lần chạy kiểm định"
              meta={
                <>
                  <span>{rows.length}/{jobs.length} lần</span>
                  {(running + queued) > 0 && <span><Spinner /> {running} đang chạy{queued ? ` · ${queued} đang chờ` : ''}</span>}
                  {updatedAt && <span className="muted">tự làm mới</span>}
                  <button type="button" className="n-btn sm" onClick={reload}>Làm mới</button>
                </>
              }
            >
              <div className="n-tblwrap long">
                <table className="n-tbl">
                  <thead>
                    <tr>
                      <th>Bắt đầu (UTC)</th>
                      <th>Loại</th>
                      <th>Chế độ</th>
                      <th>Nội dung</th>
                      <th>Trạng thái</th>
                      <th className="r">Thời lượng</th>
                      <th>Mã job</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((j) => {
                      const meta = JOB_STATUS[j.status] || { text: j.status, cls: '' }
                      const el = jobElapsed(j, now)
                      return (
                        <tr key={j.job_id}>
                          <td className="mono">{fmtDateTime(toMs(j.created))}</td>
                          <td>{jobKindText(j.kind, appMeta)}</td>
                          <td>
                            {j.mode ? (
                              <span className="n-modecell">
                                <span className={`n-mode-badge ${j.mode}`}>
                                  {j.mode === 'advanced' ? <Term k="mode_advanced">Nâng cao</Term> : <Term k="mode_basic">Cơ bản</Term>}
                                </span>
                                {(j.custom_gates || j.promotable === false) && (
                                  <span className="n-custom-badge" title={CUSTOM_REASON}>⚠ {CUSTOM_BADGE}</span>
                                )}
                              </span>
                            ) : <span className="muted">—</span>}
                          </td>
                          <td className="wrap" title={j.label}>
                            {jobDetail(j)}
                            <ResolvedParams job={j} />
                          </td>
                          <td>
                            <Status tone={meta.cls}>
                              {isActiveJob(j) && <Spinner />}
                              {meta.text}
                            </Status>
                          </td>
                          <td className="r">{el != null ? fmtDuration(el) : '—'}</td>
                          <td className="mono muted">{j.job_id}</td>
                          <td>
                            <div className="acts">
                              {jobLink(j) && <Link className="n-btn sm" to={jobLink(j)}>Mở</Link>}
                              {j.kind === 'book_backtest' && j.status === 'done' && (
                                <button type="button" className="n-btn sm" onClick={() => openOnPortfolio(j)}>Danh mục ↗</button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                    {!rows.length && <tr><td colSpan={8} className="muted">Không có lần chạy nào khớp bộ lọc.</td></tr>}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </>
      )}
    </>
  )
}

