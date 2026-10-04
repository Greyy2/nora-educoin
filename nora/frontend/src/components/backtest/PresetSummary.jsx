import React from 'react'
import { PARAM_GROUPS, paramLabel, paramHint, fmtParamFull } from '../../lib/params'

/** Tham số preset (bộ tốt nhất đã tối ưu) chỉ đọc, mỗi dòng kèm mô tả bằng lời; nhóm theo tín hiệu / thoát lệnh / rủi ro. */
export default function PresetSummary({ strat }) {
  const schema = strat.params_schema
  const params = strat.preset?.params || {}
  const groups = PARAM_GROUPS.map((g) => ({ ...g, keys: Object.keys(schema).filter((k) => schema[k].group === g.key) })).filter((g) => g.keys.length)
  return (
    <div className="n-bt-sum">
      {groups.map((g) => (
        <div key={g.key} className="n-bt-sum-g">
          <h5>{g.label}</h5>
          <dl>
            {g.keys.map((k) => (
              <div key={k} title={k}>
                <dt>{paramLabel(k) === k ? schema[k].label_vi || k : paramLabel(k)}</dt>
                <dd className="mono">{fmtParamFull(k, params[k] ?? schema[k].default)}</dd>
                <dd className="d">{paramHint(k) || schema[k].help_vi}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  )
}
