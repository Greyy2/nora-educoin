import React from 'react'
import { Field } from '../ui'
import { useMeta } from '../../meta/MetaProvider'

const MODE_LABELS = {
  backtest: 'Backtest (Lịch sử)',
  paper: 'Paper (OKX Sandbox)',
  testnet: 'Testnet (OKX Demo)',
  live: 'Live (Tiền thật)',
}

/** Chọn chế độ thực thi: Backtest / Paper / Testnet (đọc từ meta.engine.run_modes). */
export default function RunModeSelect({ id = 'run-mode-select', value, onChange }) {
  const { meta } = useMeta()
  const modes = meta?.engine?.run_modes || ['backtest', 'paper', 'testnet']

  return (
    <Field id={id} label="Chế độ chạy">
      <select id={id} className="n-sel" value={value || 'backtest'} onChange={(e) => onChange(e.target.value)}>
        {modes.map((m) => (
          <option key={m} value={m}>
            {MODE_LABELS[m] || m}
          </option>
        ))}
      </select>
    </Field>
  )
}
