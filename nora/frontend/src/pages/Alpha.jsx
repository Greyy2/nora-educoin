import React from 'react'
import { useSearchParams } from 'react-router-dom'
import KhoAlpha from './Strategies'
import PhienDao from './PhienDao'
import Studio from './Studio'

/**
 * Alpha — gộp chung Kho chiến thuật, Alpha Builder (phòng thí nghiệm) và Đào alpha (quét tham số)
 * vào một nơi, đổi góc nhìn bằng thanh switch chuyển tab.
 */
export default function Alpha() {
  const [sp, setSp] = useSearchParams()
  const currentTab = sp.get('tab')
  const tab = currentTab === 'dao' ? 'dao' : currentTab === 'builder' ? 'builder' : 'kho'

  const doi = (t) => {
    if (t === 'kho') setSp({}, { replace: true })
    else setSp({ tab: t }, { replace: true })
  }

  return (
    <>
      <div className="head">
        <div className="head-row">
          <h1>Alpha</h1>
          <div className="switch">
            <button className={tab === 'kho' ? 'on' : ''} onClick={() => doi('kho')}>Kho alpha</button>
            <button className={tab === 'builder' ? 'on' : ''} onClick={() => doi('builder')}>Alpha builder</button>
            <button className={tab === 'dao' ? 'on' : ''} onClick={() => doi('dao')}>Đào alpha</button>
          </div>
        </div>
        <p>
          {tab === 'kho'
            ? 'Kho chiến thuật đang có — bấm vào một dòng để xem điều kiện vào lệnh.'
            : tab === 'builder'
            ? 'Phòng nghiên cứu & xây dựng chiến lược — tùy biến AST flow, thử nghiệm nhanh trên dữ liệu nến và đo lường chất lượng alpha.'
            : 'Quét dải tham số để đào ra alpha mới. Bấm vào một phiên để xem bảng xếp hạng và tinh chỉnh tham số.'}
        </p>
      </div>

      {tab === 'kho' ? <KhoAlpha /> : tab === 'builder' ? <Studio /> : <PhienDao />}
    </>
  )
}
