import React, { useMemo, useState } from 'react'
import { isNum, fmtNum } from '../../../lib/format'

function getCriteria(capital) {
  const hasCap = isNum(capital) && capital > 0
  const isWhale = hasCap && capital >= 100000
  const isLarge = hasCap && capital >= 10000 && !isWhale
  const isSmall = hasCap && capital < 10000

  // Ngưỡng MDD & chỉ số: vốn to khống chế khắt khe MDD < 20%; vốn nhỏ nới lỏng < 30% để gia tăng sức bật
  const mddTarget = isWhale ? -18.0 : isLarge ? -20.0 : isSmall ? -30.0 : -40.0
  const cagrTarget = isWhale ? 20.0 : isSmall ? 20.0 : 25.0
  const sharpeTarget = isSmall ? 1.1 : 1.2
  const calmarTarget = isSmall ? 0.8 : 0.9

  return [
    {
      id: 'sharpe',
      name: 'Sharpe Ratio',
      target: `Target: ≥ ${sharpeTarget}`,
      test: (m) => (isNum(m?.sharpe) ? (m.sharpe >= sharpeTarget ? 'pass' : 'fail') : 'pending'),
      format: (m) => (isNum(m?.sharpe) ? fmtNum(m.sharpe, 2) : '—'),
    },
    {
      id: 'cagr',
      name: 'CAGR',
      target: `Target: ≥ ${fmtNum(cagrTarget, 0)}%`,
      test: (m) => (isNum(m?.cagr) ? (m.cagr >= cagrTarget ? 'pass' : 'fail') : 'pending'),
      format: (m) => (isNum(m?.cagr) ? `${fmtNum(m.cagr, 1)}%` : '—'),
    },
    {
      id: 'mdd',
      name: 'Max Drawdown',
      target: `Target: ≥ ${fmtNum(mddTarget, 0)}%`,
      test: (m) => (isNum(m?.mdd) ? (m.mdd >= mddTarget ? 'pass' : 'fail') : 'pending'),
      format: (m) => (isNum(m?.mdd) ? `${fmtNum(m.mdd, 1)}%` : '—'),
    },
    {
      id: 'pf',
      name: 'Profit factor',
      target: 'Target: ≥ 1.7',
      test: (m) => (isNum(m?.pfTrades) ? (m.pfTrades >= 1.7 ? 'pass' : 'fail') : 'pending'),
      format: (m) => (isNum(m?.pfTrades) ? fmtNum(m.pfTrades, 2) : '—'),
    },
    {
      id: 'calmar',
      name: 'Calmar',
      target: `Target: ≥ ${calmarTarget}`,
      test: (m) => (isNum(m?.calmar) ? (m.calmar >= calmarTarget ? 'pass' : 'fail') : 'pending'),
      format: (m) => (isNum(m?.calmar) ? fmtNum(m.calmar, 2) : '—'),
    },
  ]
}

export default function TestingStatusCard({ metrics, stage = 'all', title, capital }) {
  const [filter, setFilter] = useState('all')

  const criteriaList = useMemo(() => getCriteria(capital), [capital])

  const evaluated = useMemo(() => {
    return criteriaList.map((c) => {
      const status = c.test(metrics)
      const val = c.format(metrics)
      return { ...c, status, val }
    })
  }, [criteriaList, metrics])

  const counts = useMemo(() => {
    let pass = 0
    let fail = 0
    let pending = 0
    evaluated.forEach((item) => {
      if (item.status === 'pass') pass++
      else if (item.status === 'fail') fail++
      else pending++
    })
    return { all: evaluated.length, pass, fail, pending }
  }, [evaluated])

  const displayed = useMemo(() => {
    if (filter === 'all') return evaluated
    return evaluated.filter((x) => x.status === filter)
  }, [evaluated, filter])

  const cardTitle = title || (stage === 'test' ? 'OOS Testing Status' : 'IS Testing Status')

  return (
    <div
      style={{
        background: 'var(--n-card, #ffffff)',
        borderRadius: 12,
        border: '1px solid var(--n-line, #e2e8f0)',
        padding: '20px 24px',
        marginBottom: 20,
        boxShadow: '0 4px 16px rgba(0, 0, 0, 0.05)',
      }}
    >
      {/* Header with Title and Filter Pills */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
          marginBottom: 16,
          paddingBottom: 14,
          borderBottom: '1px solid var(--n-line, #e2e8f0)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0, fontSize: 16.5, fontWeight: 700, color: 'var(--n-ink, #0f172a)', letterSpacing: '-0.01em' }}>
            {cardTitle}
          </h3>
          {isNum(capital) && capital > 0 && (
            <span
              style={{
                fontSize: 11.5,
                fontWeight: 600,
                padding: '2.5px 8px',
                borderRadius: 6,
                background: capital >= 10000 ? 'rgba(59, 130, 246, 0.1)' : 'rgba(245, 158, 11, 0.1)',
                color: capital >= 10000 ? 'var(--n-brand, #2563eb)' : '#d97706',
                border: `1px solid ${capital >= 10000 ? 'rgba(59, 130, 246, 0.25)' : 'rgba(245, 158, 11, 0.25)'}`,
              }}
            >
              {capital >= 100000
                ? `Vốn lớn $${fmtNum(capital, 0)} · Khống chế MDD < 18%`
                : capital >= 10000
                ? `Phân bổ Quỹ $${fmtNum(capital, 0)} · Khống chế MDD < 20%`
                : `Tăng tốc tích lũy $${fmtNum(capital, 0)} · Nới lỏng MDD`}
            </span>
          )}
          <span
            style={{
              fontSize: 11,
              padding: '3px 9px',
              borderRadius: 6,
              background: counts.pass === counts.all ? 'rgba(16, 185, 129, 0.15)' : 'rgba(244, 63, 94, 0.12)',
              color: counts.pass === counts.all ? 'var(--n-pos, #10b981)' : 'var(--n-neg, #f43f5e)',
              border: `1px solid ${counts.pass === counts.all ? 'rgba(16, 185, 129, 0.25)' : 'rgba(244, 63, 94, 0.25)'}`,
              fontWeight: 600,
            }}
          >
            {counts.pass === counts.all ? 'ĐẠT TOÀN BỘ TIÊU CHÍ ✓' : `ĐẠT ${counts.pass}/${counts.all} TIÊU CHÍ`}
          </span>
        </div>

        {/* Filter Pills: All, Pass, Fail, Pending */}
        <div
          style={{
            display: 'inline-flex',
            background: 'var(--n-card-sub, rgba(125, 125, 125, 0.08))',
            borderRadius: 999,
            padding: 3,
            border: '1px solid var(--n-line, #e2e8f0)',
          }}
        >
          {[
            { key: 'all', label: 'All', count: counts.all },
            { key: 'pass', label: 'Pass', count: counts.pass },
            { key: 'fail', label: 'Fail', count: counts.fail },
            { key: 'pending', label: 'Pending', count: counts.pending },
          ].map((btn) => {
            const active = filter === btn.key
            return (
              <button
                key={btn.key}
                type="button"
                onClick={() => setFilter(btn.key)}
                style={{
                  background: active ? 'var(--n-card, #ffffff)' : 'transparent',
                  color: active ? 'var(--n-ink, #0f172a)' : 'var(--n-ink-2, #64748b)',
                  border: active ? '1px solid var(--n-line, #cbd5e1)' : '1px solid transparent',
                  boxShadow: active ? '0 1px 3px rgba(0, 0, 0, 0.08)' : 'none',
                  padding: '3px 12px',
                  borderRadius: 999,
                  fontSize: 12,
                  fontWeight: active ? 600 : 500,
                  cursor: 'pointer',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  transition: 'all 0.15s ease',
                }}
              >
                <span>{btn.label}</span>
                <span style={{ opacity: active ? 1 : 0.75, fontSize: 11 }}>{btn.count}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Rows */}
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {displayed.map((item, idx) => (
          <div
            key={item.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '13px 4px',
              borderBottom: idx === displayed.length - 1 ? 'none' : '1px solid var(--n-line, rgba(125, 125, 125, 0.1))',
            }}
          >
            {/* Left: Icon + Label + Target */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              {item.status === 'pass' && (
                <span
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: '50%',
                    background: 'rgba(16, 185, 129, 0.12)',
                    border: '1.5px solid var(--n-pos, #10b981)',
                    color: 'var(--n-pos, #10b981)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 13,
                    fontWeight: 'bold',
                    flexShrink: 0,
                  }}
                  title="Đạt tiêu chí"
                >
                  ✓
                </span>
              )}
              {item.status === 'fail' && (
                <span
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: '50%',
                    background: 'rgba(244, 63, 94, 0.12)',
                    border: '1.5px solid var(--n-neg, #f43f5e)',
                    color: 'var(--n-neg, #f43f5e)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 12,
                    fontWeight: 'bold',
                    flexShrink: 0,
                  }}
                  title="Chưa đạt tiêu chí"
                >
                  ✕
                </span>
              )}
              {item.status === 'pending' && (
                <span
                  style={{
                    width: 24,
                    height: 24,
                    borderRadius: '50%',
                    background: 'rgba(148, 163, 184, 0.12)',
                    border: '1.5px solid var(--n-line, #94a3b8)',
                    color: 'var(--n-ink-2, #94a3b8)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 13,
                    flexShrink: 0,
                  }}
                  title="Chưa có dữ liệu"
                >
                  —
                </span>
              )}

              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--n-ink, #0f172a)', marginBottom: 2 }}>
                  {item.name}
                </div>
                <div style={{ fontSize: 11.5, color: 'var(--n-ink-2, #64748b)', letterSpacing: '0.01em' }}>
                  {item.target}
                </div>
              </div>
            </div>

            {/* Right: Value */}
            <div
              style={{
                fontSize: 15,
                fontWeight: 600,
                color: item.status === 'pass' ? 'var(--n-pos, #10b981)' : item.status === 'fail' ? 'var(--n-neg, #f43f5e)' : 'var(--n-ink-2, #64748b)',
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
              }}
            >
              {item.val}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
