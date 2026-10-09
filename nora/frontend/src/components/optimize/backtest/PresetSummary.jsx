import React from 'react'
import { getParamGroups, paramLabel, paramHint, fmtParamFull } from '../../../lib/params'

/** Tham số preset (bộ tốt nhất đã tối ưu) chỉ đọc, mỗi dòng kèm mô tả bằng lời; nhóm theo tín hiệu / thoát lệnh / rủi ro. */
export default function PresetSummary({ strat }) {
  const schema = strat.params_schema
  const params = strat.preset?.params || {}
  const groups = getParamGroups(schema)
  return (
    <div className="n-bt-sum">
      {groups.map((g) => (
        <div key={g.key} className="n-bt-sum-g">
          <h5>{g.label}</h5>
          <dl>
            {g.keys.map((k) => (
              <div key={k} title={k}>
                <dt>{paramLabel(k, schema) === k ? schema[k]?.label_vi || k : paramLabel(k, schema)}</dt>
                <dd className="mono">{fmtParamFull(k, params[k] ?? schema[k]?.default, schema)}</dd>
                <dd className="d">{paramHint(k, schema) || schema[k]?.help_vi}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  )
}
