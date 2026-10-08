import React from 'react'
import SavedAlphaList from './SavedAlphaList'

/** Tab "Mẫu" dùng chung /alpha/create và /education: danh sách phẳng các mẫu (GET /api/studio/education/samples, đúng thứ tự samples.json): tên + ý tưởng ngắn; bấm để mở vào tab file mới; kèm mục "Đã lưu". */
export default function SamplesPane({ samples, onUse, saved, onOpenSaved, openingId, activeId }) {
  return (
    <div className="se-samples">
      <h3 className="se-h3">Mẫu chiến lược ({samples.length})</h3>
      <div className="se-cards">
        {samples.map((s) => (
          <button key={s.key || s.name} type="button" className="n-card-sel" onClick={() => onUse(s)}>
            <div className="se-card-h"><b>{s.name}</b></div>
            <span className="n-note">{s.summary || s.note}</span>
          </button>
        ))}
      </div>
      <SavedAlphaList list={saved} onOpen={onOpenSaved} openingId={openingId} activeId={activeId} />
    </div>
  )
}
