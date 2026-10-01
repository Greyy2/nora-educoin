import React from 'react'

export function Segmented({ value, onChange, options, label }) {
  return (
    <div className="n-seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  )
}

export function Panel({ title, meta, children, className = '', bodyClass = '' }) {
  return (
    <section className={`n-panel ${className}`}>
      {(title || meta) && (
        <div className="n-panel-h">
          {title && <h2>{title}</h2>}
          {meta && <div className="meta">{meta}</div>}
        </div>
      )}
      <div className={`n-panel-b ${bodyClass}`}>{children}</div>
    </section>
  )
}

export function Status({ tone = '', children }) {
  return <span className={`n-status ${tone}`}>{children}</span>
}

export function Empty({ title, children }) {
  return <div className="n-empty"><h3>{title}</h3>{children && <div>{children}</div>}</div>
}

export const ErrorBox = ({ children }) => (children ? <div className="n-err" role="alert">{children}</div> : null)

export function Field({ id, label, children }) {
  return <div className="n-field"><label htmlFor={id}>{label}</label>{children}</div>
}

export function Spinner() { return <span className="n-spin" aria-hidden="true" /> }

export function PageHead({ kicker, title, subtitle, children }) {
  return (
    <div className="n-page-h">
      <div>
        {kicker && <div className="kick">{kicker}</div>}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="n-ctrls">{children}</div>}
    </div>
  )
}

/** Bắt lỗi render của một vùng nội dung để không làm trắng cả trang. */
export class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { err: null } }
  static getDerivedStateFromError(err) { return { err } }
  render() {
    if (this.state.err) {
      return <div className="n-err" role="alert">Không hiển thị được nội dung này: {String(this.state.err.message || this.state.err)}</div>
    }
    return this.props.children
  }
}

/** Trạng thái đang tải thống nhất. */
export function Loading({ what = 'dữ liệu' }) {
  return <div className="n-empty" role="status"><h3>Đang tải {what}</h3><Spinner /></div>
}

/** Trạng thái lỗi thống nhất, kèm nút thử lại. */
export function ErrorState({ title = 'Không tải được dữ liệu', error, onRetry }) {
  return (
    <div className="n-err n-err-state" role="alert">
      <div><b>{title}</b>{error ? <>: {error}</> : null}</div>
      {onRetry && <button type="button" className="n-btn sm" onClick={onRetry}>Thử lại</button>}
    </div>
  )
}
