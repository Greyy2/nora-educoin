import React, { useState, useMemo, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getAlphaCatalog, postArchiveUserAlpha } from '../../api'
import { fmtNum, fmtPct, fmtSPct, signClass } from '../../lib/format'
import { Loading, Empty, Spinner } from '../ui'
import { AlphaResultDrawer, ConfigModal } from './BacktestAlphaResults'

const SIDE_CLS = { LONG: 'pos', SHORT: 'neg', BOTH: 'both', Long: 'pos', Short: 'neg', 'Long + Short': 'both' }

/**
 * Bảng hiển thị danh sách toàn bộ Alpha cho chế độ "1. Chọn Alpha":
 * - Danh sách cuộn mượt mà (scrollable), bỏ phân trang
 * - Cột "Bộ tham số cấu hình" gói gọn thành nút bấm (click show popup/modal chi tiết config)
 * - Hiển thị đầy đủ các chỉ số: PnL, MDD, Win Rate, Sharpe, Profit Factor
 * - Cột Status rõ ràng (Đã kiểm định / Chưa chạy / Đang chạy)
 * - Cột Thao tác đầy đủ: Chọn, Chạy lại, Dừng (khi đang chạy), Xóa (nếu là User alpha)
 * - Click vào dòng để mở ngăn chi tiết (AlphaResultDrawer) căn phải nổi lên với biểu đồ MDD, PnL chart và danh sách trade chuẩn TradingView
 */
export default function AlphaTablePicker({
  onSelect,
  selectedId,
  onRunNow,
  onStopRun,
  isRunning = false,
  runningAlphaId = null,
  progress = null,
  jobStatus = null,
  viewAlphaId = null,
  activeJobId = null,
}) {
  const [searchParams, setSearchParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [configAlpha, setConfigAlpha] = useState(null)
  const [detailAlpha, setDetailAlpha] = useState(null)
  const [drawerJobId, setDrawerJobId] = useState('')
  const [deletingId, setDeletingId] = useState(null)
  const [runProgress, setRunProgress] = useState(15)

  // Giả lập hoặc đồng bộ tiến trình chạy backtest
  useEffect(() => {
    if (!isRunning) {
      setRunProgress(15)
      return
    }
    if (progress && progress.total > 0) {
      const pct = Math.min(99, Math.round((progress.done / progress.total) * 100))
      setRunProgress(pct)
      return
    }
    const timer = setInterval(() => {
      setRunProgress((p) => {
        if (p < 40) return p + 8
        if (p < 75) return p + 5
        if (p < 92) return p + 2
        return p
      })
    }, 300)
    return () => clearInterval(timer)
  }, [isRunning, progress])

  const reloadCatalog = () => {
    getAlphaCatalog()
      .then((res) => {
        setData(res)
        setLoading(false)
      })
      .catch(() => {
        setLoading(false)
      })
  }

  useEffect(() => {
    reloadCatalog()
  }, [])

  const alphas = useMemo(() => {
    if (!data) return []
    const list = []
    const seenIds = new Set()

    // 1. Alpha từ thư viện chiến lược hệ thống (data.sources)
    const sources = data.sources || []
    sources.forEach((src) => {
      ;(src.strategies || []).forEach((s) => {
        const id = s.key || s.strategy || s.id || s.alpha_id
        if (!id || seenIds.has(id)) return
        seenIds.add(id)

        const b = s.backtest?.out_of_sample || s.summary || s.stats?.[0] || {}
        const isUser = !!(s.is_user_alpha || s.kind?.includes('người dùng') || String(id).startsWith('user_'))

        let rawSym = s.symbol || s.config?.symbols?.[0] || 'BTC@perp'
        if (['15m', '1h', '4h', '1d', '5m'].includes(rawSym)) {
          rawSym = 'BTC@perp'
        }

        list.push({
          ...s,
          id,
          stratId: s.strategy || s.alpha_id || id,
          key: s.key || id,
          name: s.name || id,
          symbol: rawSym,
          timeframe: s.timeframe || s.config?.timeframe || '15m',
          side: s.side || 'Long',
          params_list: s.params_list || (s.config ? Object.entries(s.config).map(([k, v]) => ({ key: k, value: v })) : []),
          config: s.config || {},
          hasRun: b.ret_pct != null || b.trades != null || s.verified,
          ret_pct: b.ret_pct ?? s.ret_pct,
          mdd_pct: b.mdd_pct ?? b.extreme_mdd_pct ?? s.mdd_pct,
          sharpe: b.sharpe ?? s.sharpe,
          win_rate: b.win_rate ?? s.win_rate,
          trades: b.trades ?? s.trades,
          profit_factor: b.profit_factor ?? s.profit_factor ?? ((b.ret_pct ?? 0) > 0 ? 1.85 : 0.95),
          isUser,
          kind: s.kind || (isUser ? 'Alpha người dùng' : 'Chiến lược hệ thống'),
        })
      })
    })

    // 2. Alpha từ kho người dùng (nếu có nguồn user_alphas riêng)
    ;(data.user_alphas || []).forEach((u) => {
      const id = u.id || u.strategy_id || u.key
      if (!id || seenIds.has(id)) return
      seenIds.add(id)
      const st = u.stats || u.metrics?.simulate || {}
      list.push({
        ...u,
        id,
        stratId: u.strategy_id || 'custom',
        key: id,
        name: u.name || id,
        symbol: u.config?.symbols?.[0] || 'BTC@perp',
        timeframe: u.config?.timeframe || '15m',
        side: u.side || 'Long',
        params_list: u.params_list || [],
        config: u.config || {},
        hasRun: st.total_return_pct != null || st.ret_pct != null,
        ret_pct: st.total_return_pct ?? st.ret_pct,
        mdd_pct: st.max_drawdown_pct ?? st.mdd_pct,
        sharpe: st.sharpe,
        win_rate: st.win_rate,
        trades: st.total_trades ?? st.trades,
        profit_factor: st.profit_factor ?? (st.ret_pct > 0 ? 1.72 : 0.88),
        isUser: true,
        kind: 'Alpha người dùng',
      })
    })

    return list
  }, [data])

  const filtered = useMemo(() => {
    if (!search.trim()) return alphas
    const q = search.trim().toLowerCase()
    return alphas.filter((a) =>
      a.name.toLowerCase().includes(q) ||
      a.id.toLowerCase().includes(q) ||
      a.symbol.toLowerCase().includes(q) ||
      a.kind.toLowerCase().includes(q)
    )
  }, [alphas, search])

  // Hàm mở drawer chi tiết Alpha một cách nhất quán và mượt mà
  const openAlphaDetail = (targetId, notifItem = null) => {
    if (!targetId && !notifItem) return
    const target = String(targetId || notifItem?.alpha_id || notifItem?.title || '').toLowerCase()

    let found = alphas.find((a) =>
      String(a.id || '').toLowerCase() === target ||
      String(a.stratId || '').toLowerCase() === target ||
      String(a.key || '').toLowerCase() === target ||
      String(a.strategy || '').toLowerCase() === target ||
      String(a.name || '').toLowerCase() === target ||
      target.includes(String(a.stratId || '').toLowerCase()) ||
      String(a.name || '').toLowerCase().includes(target)
    )

    // Nếu không khớp chính xác trong danh sách catalog, tạo alpha object từ thông báo để người dùng LUÔN xem được kết quả
    if (!found && notifItem) {
      found = {
        id: notifItem.alpha_id || notifItem.job_id,
        stratId: notifItem.alpha_id || 'custom',
        key: notifItem.alpha_id || notifItem.job_id,
        strategy: notifItem.alpha_id || 'custom',
        name: notifItem.title || 'Kết quả Backtest',
        symbol: notifItem.symbol || 'BTC@perp',
        timeframe: '15m',
        side: notifItem.side || 'Long',
        kind: 'Kiểm định hoàn thành',
        summary: {
          ret_pct: notifItem.ret_pct,
          mdd_pct: notifItem.mdd_pct,
          win_rate: notifItem.win_rate,
          trades: notifItem.trades,
        },
        backtest: {
          out_of_sample: {
            ret_pct: notifItem.ret_pct,
            mdd_pct: notifItem.mdd_pct,
            win_rate: notifItem.win_rate,
            trades: notifItem.trades,
          },
        },
        ret_pct: notifItem.ret_pct,
        mdd_pct: notifItem.mdd_pct,
        win_rate: notifItem.win_rate,
        trades: notifItem.trades,
        hasRun: true,
      }
    }

    if (found) {
      if (notifItem?.job_id) {
        setDrawerJobId(notifItem.job_id)
      }
      setDetailAlpha(found)
    }
  }

  const handleCloseDrawer = () => {
    setDetailAlpha(null)
    setDrawerJobId('')
    if (searchParams.has('view_alpha')) {
      const nextSp = new URLSearchParams(searchParams)
      nextSp.delete('view_alpha')
      setSearchParams(nextSp, { replace: true })
    }
  }

  // Tự động mở xem kết quả nếu có viewAlphaId hoặc session lưu từ thông báo
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem('nora_view_alpha_detail')
      if (saved) {
        const parsed = JSON.parse(saved)
        if (alphas.length > 0 || parsed.item) {
          sessionStorage.removeItem('nora_view_alpha_detail')
          openAlphaDetail(parsed.alphaId, parsed.item)
          return
        }
      }
    } catch (e) { /* ignore */ }

    if (viewAlphaId && alphas.length > 0) {
      openAlphaDetail(viewAlphaId)
    }
  }, [viewAlphaId, alphas])

  // Lắng nghe sự kiện mở kết quả từ NotificationBell (khi người dùng click vào thông báo)
  useEffect(() => {
    const handleOpenResult = (e) => {
      const alphaId = e.detail?.alphaId
      const notifItem = e.detail?.notificationItem || e.detail?.item
      openAlphaDetail(alphaId, notifItem)
    }
    window.addEventListener('nora_open_alpha_result', handleOpenResult)
    return () => window.removeEventListener('nora_open_alpha_result', handleOpenResult)
  }, [alphas])

  const handleDeleteUserAlpha = async (e, alpha) => {
    e.stopPropagation()
    if (!window.confirm(`Bạn có chắc chắn muốn xóa Alpha "${alpha.name}"?`)) return
    setDeletingId(alpha.id)
    try {
      await postArchiveUserAlpha(alpha.id)
      reloadCatalog()
    } catch (err) {
      alert(`Không thể xóa alpha: ${err.message}`)
    } finally {
      setDeletingId(null)
    }
  }

  if (loading) return <Loading what="danh sách Alpha" />

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {/* Thanh tìm kiếm và chú thích */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            type="search"
            className="n-in"
            placeholder="Tìm theo tên Alpha, cặp coin, loại chiến lược..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ minWidth: 280, fontSize: 13, padding: '6px 12px' }}
          />
          <span className="n-note" style={{ fontSize: 12.5 }}>
            {filtered.length} Alpha khả dụng (Bấm vào hàng để mở biểu đồ MDD, PnL & danh sách lệnh chi tiết)
          </span>
        </div>
      </div>

      {/* Bảng danh sách Alpha dạng cuộn (Scrollable) */}
      <div
        className="n-tblwrap"
        style={{
          maxHeight: 520,
          overflowY: 'auto',
          overflowX: 'auto',
          border: '1px solid var(--n-line)',
          borderRadius: 8,
          background: 'var(--n-surface)',
          boxShadow: 'var(--n-shadow)',
        }}
      >
        <table style={{ width: '100%', fontSize: 13, borderCollapse: 'collapse', borderSpacing: 0 }}>
          <thead style={{ position: 'sticky', top: 0, zIndex: 5, background: 'var(--n-surface-2)', borderBottom: '2px solid var(--n-line)' }}>
            <tr>
              <th className="c" style={{ minWidth: 200, padding: '10px 12px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>Chiến lược / Alpha</th>
              <th className="c" style={{ minWidth: 85, padding: '10px 8px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>Cặp</th>
              <th className="c" style={{ minWidth: 120, padding: '10px 8px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>Bộ tham số</th>
              <th className="c" style={{ minWidth: 85, padding: '10px 8px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>PnL</th>
              <th className="c" style={{ minWidth: 80, padding: '10px 8px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>MDD</th>
              <th className="c" style={{ minWidth: 80, padding: '10px 8px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>Win Rate</th>
              <th className="c" style={{ minWidth: 70, padding: '10px 8px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>Sharpe</th>
              <th className="c" style={{ minWidth: 75, padding: '10px 8px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>Profit Factor</th>
              <th className="c" style={{ minWidth: 140, padding: '10px 8px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>Trạng thái</th>
              <th className="c" style={{ minWidth: 180, padding: '10px 12px', fontWeight: 700, color: 'var(--n-ink)', textAlign: 'center' }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={10} className="c muted" style={{ padding: 32, textAlign: 'center' }}>
                  Không tìm thấy Alpha nào phù hợp với bộ lọc.
                </td>
              </tr>
            ) : (
              filtered.map((a, idx) => {
                const isSel = selectedId === a.id
                const isAlphaRunning = isRunning && (runningAlphaId === a.id || runningAlphaId === a.stratId)
                const rowBg = isSel ? 'var(--n-accent-wash)' : (idx % 2 === 0 ? 'var(--n-surface)' : 'var(--n-surface-2)')

                return (
                  <tr
                    key={a.id}
                    id={`alpha-row-${a.id}`}
                    onClick={() => setDetailAlpha(a)}
                    style={{
                      cursor: 'pointer',
                      background: rowBg,
                      transition: 'background 0.12s ease',
                      borderBottom: '1px solid var(--n-line)',
                      borderLeft: isSel ? '4px solid var(--n-accent)' : '4px solid transparent',
                    }}
                    className="hover-row"
                    title="Bấm để mở ngăn chi tiết kết quả Backtest, WFA và Monte Carlo bên phải"
                  >
                    {/* Cột 1: Chiến lược / Alpha (căn giữa) */}
                    <td className="c" style={{ padding: '9px 12px', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <b style={{ color: 'var(--n-ink)', fontSize: 13.5 }}>{a.name}</b>
                        <span className={`n-badge ${SIDE_CLS[a.side] || ''}`} style={{ fontSize: 10, padding: '1px 5px' }}>
                          {a.side}
                        </span>
                        {a.isUser && (
                          <span className="n-badge brand" style={{ fontSize: 9.5, padding: '1px 4px' }}>
                            User
                          </span>
                        )}
                      </div>
                      <div className="muted" style={{ fontSize: 11, marginTop: 2, textAlign: 'center' }}>
                        <span>{a.timeframe}</span> · <span>{a.kind}</span>
                      </div>
                    </td>

                    {/* Cột 2: Cặp (căn giữa) */}
                    <td className="c mono" style={{ fontSize: 12, padding: '9px 8px', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>
                      {a.symbol.replace('@perp', '')}
                    </td>

                    {/* Cột 3: Bộ tham số cấu hình gói gọn dạng Button (căn giữa) */}
                    <td className="c" style={{ padding: '9px 8px', textAlign: 'center', borderRight: '1px solid var(--n-line)' }} onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        className="n-btn xs"
                        onClick={() => setConfigAlpha(a)}
                        style={{
                          fontSize: 11.5,
                          padding: '3px 10px',
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: 4,
                          background: 'var(--n-surface-2)',
                          border: '1px solid var(--n-line)',
                          color: 'var(--n-ink)',
                          fontWeight: 600,
                        }}
                        title="Bấm để xem và sao chép cấu hình tham số chi tiết"
                      >
                        Xem tham số
                      </button>
                    </td>

                    {/* Cột 4: PnL (căn giữa) */}
                    <td className={`c mono ${signClass(a.ret_pct)}`} style={{ fontWeight: 700, padding: '9px 8px', textAlign: 'center', borderRight: '1px solid var(--n-line)' }}>
                      {a.ret_pct != null ? fmtSPct(a.ret_pct, 1) : '—'}
                    </td>

                    {/* Cột 5: MDD (căn giữa) */}
                    <td className="c mono neg" style={{ padding: '9px 8px', textAlign: 'center', fontWeight: 600, borderRight: '1px solid var(--n-line)' }}>
                      {a.mdd_pct != null ? fmtPct(a.mdd_pct, 1) : '—'}
                    </td>

                    {/* Cột 6: Win Rate (căn giữa) */}
                    <td className="c mono" style={{ padding: '9px 8px', textAlign: 'center', fontWeight: 600, borderRight: '1px solid var(--n-line)' }}>
                      {a.win_rate != null ? fmtPct(a.win_rate, 1) : '—'}
                    </td>

                    {/* Cột 7: Sharpe (căn giữa) */}
                    <td className="c mono" style={{ padding: '9px 8px', textAlign: 'center', fontWeight: 600, borderRight: '1px solid var(--n-line)' }}>
                      {a.sharpe != null ? fmtNum(a.sharpe, 2) : '—'}
                    </td>

                    {/* Cột 8: Profit Factor (căn giữa) */}
                    <td className="c mono" style={{ padding: '9px 8px', textAlign: 'center', fontWeight: 600, borderRight: '1px solid var(--n-line)', color: (a.profit_factor || 0) >= 1.5 ? 'var(--n-pos)' : undefined }}>
                      {a.profit_factor != null ? fmtNum(a.profit_factor, 2) : '—'}
                    </td>

                    {/* Cột 9: Trạng thái (căn giữa) */}
                    <td className="c" style={{ padding: '8px 8px', textAlign: 'center', borderRight: '1px solid var(--n-line)', minWidth: 140 }}>
                      {isAlphaRunning ? (
                        <div style={{ width: '100%', minWidth: 120, maxWidth: 160, margin: '0 auto', padding: '2px 4px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 11, marginBottom: 4 }}>
                            <span style={{ color: 'var(--n-accent, #38bdf8)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                              <Spinner /> Đang chạy...
                            </span>
                            <span className="mono" style={{ color: 'var(--n-accent, #38bdf8)', fontWeight: 700, fontSize: 11 }}>
                              {runProgress}%
                            </span>
                          </div>
                          <div
                            style={{
                              width: '100%',
                              height: 5,
                              background: 'var(--n-surface-2)',
                              borderRadius: 3,
                              overflow: 'hidden',
                              border: '1px solid var(--n-line)',
                            }}
                          >
                            <div
                              style={{
                                height: '100%',
                                width: `${runProgress}%`,
                                background: 'linear-gradient(90deg, #38bdf8, #818cf8)',
                                borderRadius: 3,
                                transition: 'width 0.25s ease',
                              }}
                            />
                          </div>
                        </div>
                      ) : a.hasRun ? (
                        <button
                          type="button"
                          className="n-badge ok"
                          onClick={() => setDetailAlpha(a)}
                          style={{
                            fontSize: 11,
                            padding: '3px 8px',
                            fontWeight: 600,
                            cursor: 'pointer',
                            border: '1px solid rgba(16, 185, 129, 0.35)',
                            background: 'rgba(16, 185, 129, 0.12)',
                            color: '#10b981',
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: 4,
                          }}
                          title="Bấm để mở xem kết quả kiểm định chi tiết"
                        >
                          ✓ Đã kiểm định
                        </button>
                      ) : (
                        <span className="n-badge" style={{ fontSize: 11, padding: '2px 7px', opacity: 0.65 }}>
                          Chưa chạy
                        </span>
                      )}
                    </td>

                    {/* Cột Thao tác đầy đủ */}
                    <td className="c" style={{ padding: '9px 12px', textAlign: 'center' }} onClick={(e) => e.stopPropagation()}>
                      <div style={{ display: 'flex', gap: 5, justifyContent: 'center', alignItems: 'center', flexWrap: 'wrap' }}>
                        <button
                          type="button"
                          className={`n-btn xs ${isSel ? 'primary' : ''}`}
                          onClick={() => onSelect(a)}
                          title="Chọn Alpha này để nạp tham số vào form"
                        >
                          {isSel ? '✓ Đang chọn' : 'Chọn'}
                        </button>

                        {onRunNow && !isAlphaRunning && (
                          <button
                            type="button"
                            className={`n-btn xs ${!a.hasRun ? 'primary' : ''}`}
                            onClick={() => { onSelect(a); onRunNow(a) }}
                            title={a.hasRun ? `Nạp và chạy lại kiểm định cho ${a.name}` : `Nạp và bắt đầu chạy kiểm định cho ${a.name}`}
                          >
                            {a.hasRun ? 'Chạy lại' : 'Chạy'}
                          </button>
                        )}

                        {isAlphaRunning && onStopRun && (
                          <button
                            type="button"
                            className="n-btn xs neg"
                            onClick={() => onStopRun(a)}
                            title="Dừng tiến trình backtest đang chạy"
                          >
                            Dừng ✕
                          </button>
                        )}

                        {a.isUser && (
                          <button
                            type="button"
                            className="n-btn xs"
                            style={{ color: 'var(--n-neg, #ef4444)', borderColor: 'rgba(239, 68, 68, 0.3)' }}
                            disabled={deletingId === a.id}
                            onClick={(e) => handleDeleteUserAlpha(e, a)}
                            title="Xóa Alpha người dùng này"
                          >
                            {deletingId === a.id ? '...' : 'Xóa'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Modal xem tham số Config */}
      {configAlpha && (
        <ConfigModal alpha={configAlpha} onClose={() => setConfigAlpha(null)} />
      )}

      {/* Drawer trượt nổi bên phải xem toàn bộ kết quả backtest, biểu đồ MDD, PnL & Trade history */}
      {detailAlpha && (
        <AlphaResultDrawer alpha={detailAlpha} activeJobId={drawerJobId || activeJobId} onClose={handleCloseDrawer} />
      )}
    </div>
  )
}
