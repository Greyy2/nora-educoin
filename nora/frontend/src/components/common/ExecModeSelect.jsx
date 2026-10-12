import React from 'react'
import { Field } from '../ui'
import { useMeta } from '../../meta/MetaProvider'
import { EXEC_MODES, defaultExecMode } from '../../lib/metaDefaults'

/** Ô chọn độ chi tiết khớp lệnh (Chuẩn 1m / Nhanh) dùng chung cho Studio và Backtest. value rỗng -> mặc định từ meta. */
export default function ExecModeSelect({ id, value, onChange }) {
  const { meta } = useMeta()
  return (
    <Field id={id} label="Độ chi tiết khớp lệnh">
      <select id={id} className="n-sel" value={value || defaultExecMode(meta)} onChange={(e) => onChange(e.target.value)}>
        {EXEC_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
      </select>
    </Field>
  )
}
