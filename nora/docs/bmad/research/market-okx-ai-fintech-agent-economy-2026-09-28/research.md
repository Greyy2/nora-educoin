---
title: 'market research: OKX AI & nền kinh tế AI agent fintech'
type: 'market'
topic: 'OKX AI & nền kinh tế AI agent fintech'
decision: 'Chọn ngách agent fintech để đầu tư xây dựng trên OKX AI / agent economy'
source: 'native-run'
status: complete
preset: 'deep'
validation: 'normal'
created: '2026-09-28'
updated: '2026-09-28 (deepen: Binance + top earners)'
claims: {verified: 10, disputed: 4, unverified: 1}
---

# Nghiên cứu thị trường: OKX AI & nền kinh tế AI agent fintech

**Quyết định mà nghiên cứu phục vụ:** chọn ngách agent fintech để đầu tư xây dựng trên OKX AI / nền kinh tế agent.

## 1. Tóm tắt điều hành

**Kết luận:** Không nên kỳ vọng doanh thu trả theo lượt (pay-per-call) trên OKX.AI trong 6–12 tháng tới. Nên dùng OKX.AI làm **kênh phân phối, nơi xây uy tín và nguồn giải thưởng hackathon**. Mô hình kiếm tiền nên là **gói thuê bao tín hiệu có hiệu suất (PnL) kiểm chứng on-chain** hoặc **SaaS kiểm tra rủi ro trước khi ký giao dịch, bán cho doanh nghiệp (B2B)**.

Ba phát hiện dẫn tới kết luận:

1. **OKX.AI có thật và bên cung đã đông, nhưng tiền còn rất ít.**
   - Ngày 28/09/2026 có 146 agent online, trong đó 106 thuộc fintech (72%) [1].
   - Tổng giá trị trên chợ task chỉ **$9,653 cho 81,236 task**, tức khoảng $0,12 mỗi task [2].
   - 57/106 agent fintech chưa có lượt dùng nào.
   - Riêng TradeDesk chiếm 92% tổng lượt dùng của nhóm fintech [1].
   - Bộ đếm "đã bán" còn tính cả lượt lấy mẫu miễn phí của OKX: một nhà bán thu thực tế 0,8 USDT trong 25 ngày [8].
2. **Tiền thật nằm ở khâu thực thi giao dịch và ở SaaS tài chính truyền thống, không nằm ở chợ agent-thuê-agent.**
   - Doanh thu 30 ngày của bot giao dịch: GMGN $42,6M, fomo $31,1M, Axiom $18,2M. Trong khi đó, nhóm được gắn nhãn "AI Agents" lớn nhất chỉ đạt $0,23M (TermiX) [12].
   - Toàn bộ x402 cộng dồn mới thanh toán khoảng **$41–50M** dù có tới 120–205M giao dịch, và các nguồn khớp nhau về độ lớn [15][52]. Theo Artemis, khoảng 50% số giao dịch là giao dịch ảo. Mức ~$28K/ngày là **tổng** volume x402; phần mua bán thật còn thấp hơn (disputed) [14].
   - Agent tài chính truyền thống có doanh thu lớn: Ramp $1,5B annualized, AlphaSense trên $500M ARR, Rogo trên $50M ARR [21][22][23]. Rillet tăng gấp đôi ARR trong một quý [24]; Erica của BofA có 24,6M người dùng [26].
3. **Dòng vốn lớn đang chảy vào "đường ray" thanh toán và lớp tin cậy cho agent, không vào token agent.**
   - Các ông lớn đều đã ra sản phẩm thanh toán cho agent: Stripe Tempo/MPP (03/2026), Mastercard Agent Pay for Machines (06/2026, có OKX là đối tác), Visa Intelligent Commerce Connect (04/2026) [32][33][34].
   - VC rót vào lớp danh tính, hạn mức chi và tuân thủ: Catena $30M, Natural $30M, Kite $18M [29][30][31].
   - Tỷ trọng VC crypto dành cho AI×crypto tăng từ 18% lên 40% [28].
   - Ngược lại, token agent đã giảm 70–90% so với đỉnh [28].

**Lưu ý lớn nhất:** OKX.AI mới hoạt động khoảng 3 tháng (beta từ 30/06/2026) và không công bố GMV hay phí nền tảng. Kết luận về "tiền ít" là ảnh chụp giai đoạn đầu, không phải xu hướng dài hạn. OKX có 150M người dùng, nên cầu có thể tăng rất nhanh nếu OKX đẩy phân phối [6].

## 2. Hệ sinh thái OKX AI (D1)

- **OnchainOS AI layer** ra mắt 03/03/2026. Agent dùng được ví, thanh toán, giao dịch và dữ liệu trên 60+ chain, 500+ nguồn DEX, qua AI Skills, MCP và REST [7]. Con số 1,2B API call/ngày và $300M volume/ngày là của toàn hạ tầng, không riêng agent (độ tin cậy trung bình, do OKX tự công bố) [7].
- **Agent Trade Kit** là MCP/CLI mã nguồn mở, miễn phí, gồm 167 công cụ, được 450 sao GitHub [9]. Lượt tải npm 30 ngày: 3,8K (MCP) và 5,8K (CLI) [10]. Tức là OKX cho không công cụ thực thi lệnh.
- **OKX.AI** ra mắt 30/06–01/07/2026 (hai nguồn ghi lệch một ngày), sau giai đoạn beta kín với 50 nhà cung cấp [6]. Nền tảng có ba vai trò: User, ASP (nhà cung cấp dịch vụ agent) và Evaluator (người phân xử, phải stake OKB). Có hai chế độ thu tiền:
  - **A2A:** tiền giữ trong escrow trên X Layer, nhả khi người dùng duyệt.
  - **A2MCP:** giá cố định mỗi lượt gọi, thanh toán qua x402.

  Thanh toán bằng USDT/USDG. **Chưa công bố phí nền tảng (take rate)** [4][5][55].
- **Số liệu OKX tự công bố:** 10.000+ danh tính agent, 4.000+ listing được duyệt, 2.700+ agent hoạt động trong một ngày, 20.000+ task (tính đến 10/08) [5]. Thực đo ngày 28/09 chỉ còn **146 agent online** [1]. Phần lớn listing đã tắt hoặc ngừng hoạt động.
- **OKX Agent Payments Protocol (APP)** được công bố khoảng 05/2026 để cạnh tranh với x402 và Stripe MPP (độ tin cậy trung bình) [50].
- **Đối thủ:**
  - Binance Agent OS (~08/2026) [48].
  - Bitget tự công bố 1M+ người dùng và $1,2B giao dịch nhờ AI cho **toàn bộ bộ công cụ AI**; riêng GetAgent có khoảng 450K người dùng (disputed) [49].
  - Coinbase dẫn đầu x402 với 67% hoạt động [52].

## 3. Khảo sát agent (D2): 106 agent fintech trên OKX.AI và 43 agent đối chứng toàn cầu

**Phương pháp:** tải trang công khai okx.ai/agents bằng trình duyệt headless ngày 28/09/2026, không đăng nhập. Ghi lại dữ liệu từ API mà chính trang gọi. Toàn bộ 146 agent online đã được phân loại thủ công. Dữ liệu thô nằm trong `digests/D2-okxai-live-agents-2026-09-28.json`.

| Ngách (OKX.AI) | Số agent | Lượt dùng | Tỷ trọng lượt dùng | Có niêm yết giá > 0 |
|---|---|---|---|---|
| Tín hiệu & dữ liệu thị trường | 38 | 8,736 | 93.2% | 30 |
| Rủi ro & bảo mật | 25 | 27 | 0.3% | 16 |
| Hạ tầng thanh toán / tin cậy agent | 14 | 9 | 0.1% | 3 |
| Giao dịch / copy-trade / định tuyến | 13 | 198 | 2.1% | 10 |
| Cổ phiếu token hoá (xStocks/RWA) | 6 | 3 | 0.0% | 2 |
| DeFi yield / LP | 4 | 373 | 4.0% | 1 |
| Thị trường dự đoán | 2 | 23 | 0.2% | 1 |
| Khác (kế toán, DAO…) | 4 | 0 | 0% | 4 |

- **Giá phổ biến:** 0,001–1 USDT mỗi lượt. Gói thuê bao 10–20 USDT/tháng dành cho tín hiệu copy-trade [1][3].
- **Trading Hackathon S1** (thi đấu 11–25/08/2026, mở đăng ký từ 31/07; bảng xếp hạng lấy từ API mà trang tải bằng JS): 57 ASP được xếp hạng theo PnL thực.
  - Hạng 1, 1M·斯巴达: lãi $24,907, lợi suất 2.319%, 154 lượt bán gói 20 USDT/tháng.
  - Hạng 2: $749. Hạng 3: $782.
  - Giải: $10K / $7K / $4,5K; hạng 4–40 mỗi đội nhận $500 [3].
- **CoinAnk**, đối tác ra mắt với 14,9K–16,6K lượt bán, **không còn online** ngày 28/09 [1][5].
- **Đối chứng toàn cầu** (doanh thu đo được):
  - Bot giao dịch trên DefiLlama [12].
  - Virtuals: doanh thu 1 năm $16,5M, nhịp 30 ngày gần nhất chỉ tương đương ~$7,2M/năm. aGDP ~$479M, trong đó có trợ cấp tới $1M/tháng [12][18][19].
  - Agent thực thi trên Virtuals ACP: Ethy $218M swap volume, Axelrod $107M; aixbt chỉ có $37,9K aGDP dù FDV $28,5M [20].
  - Olas Mech: 12M request nhưng chỉ thu $109,6K, khoảng $0,009 mỗi request [17].
  - Agent yield: Giza đã đóng ARMA, Almanak thu $411K/năm [12][51].
  - x402: CoinGecko $0,01 mỗi lượt [53], Nansen $0,01–0,05 [46]; gói thuê bao CoinGecko $35–999/tháng, phí vượt mức $0,0005/lượt [45]. AgentLISA đạt ~$3,1K/ngày theo thông cáo báo chí [47].

## 4. Dòng vốn và xu hướng thế giới (D4)

- **Tổng quan VC:** VC toàn cầu H1/2026 đạt $510B, và hơn 70% vốn quý 2 vào AI [27]. Không có nguồn chính thống nào tách riêng hạng mục "AI agent fintech", đây là một khoảng trống dữ liệu.
- **Đang nóng lên:**
  1. Đường ray thanh toán cho agent do các ông lớn vận hành (Stripe, Mastercard, Visa, Coinbase, OKX) [32][33][34].
  2. Lớp tin cậy: danh tính agent, ủy quyền (mandate), hạn mức chi, ngân hàng có giấy phép. Ví dụ Catena xin giấy phép trust charter của OCC [30][31].
  3. Thanh toán agent bằng stablecoin [29][28].
  4. Chợ agent do sàn giao dịch vận hành [6].
  5. Agent tài chính theo ngành dọc (kế toán, nghiên cứu đầu tư, tuân thủ) có ARR thật [21]–[25].
- **Đang nguội:**
  1. Token agent giảm 70–90%. VIRTUAL từ ~$5B xuống ~$0,46B [28].
  2. Số giao dịch x402 bị thổi phồng bởi meme PING và giao dịch ảo [13][14].
  3. Agent DeFi yield có doanh thu thấp [12][51].
- **Dự báo (chỉ là dự phóng):**
  - McKinsey: agentic commerce đạt $3–5T toàn cầu vào 2030 [35].
  - Morgan Stanley: $190–385B thương mại điện tử Mỹ vào 2030 [36].

## 5. Kinh tế đơn vị, rủi ro và pháp lý (D5)

- **Thu nhập của người bán rất nhỏ và tập trung:**
  - Chỉ khoảng 15 người bán x402 xuất hiện ổn định. Endpoint bận nhất ước chỉ thu $1,1K–5,4K/tháng (nguồn độc lập, chưa được thẩm định) [16].
  - Giao dịch lặp lại giữa máy với máy chiếm 64% số lượt thanh toán nhưng chỉ 1% giá trị [16].
- **Rủi ro kỹ thuật:**
  - Blockaid H1/2026: thiệt hại $1,1B qua 212 vụ (các tracker khác ghi $0,97–1,32B). Báo cáo gốc của Blockaid ghi 212 vụ, 76% thiệt hại đến từ lộ khóa, quy trình ký hoặc thông tin đăng nhập; tỷ lệ này chỉ có một nguồn [37][56].
  - Vụ khai thác AI agent đầu tiên (Grok/Bankrbot, prompt injection) gây thiệt hại khoảng $150–216K [37][38].
- **Pháp lý:**
  - Mỹ: GENIUS Act có hiệu lực chậm nhất 18/01/2027 [39]. Chưa có quy định riêng của SEC hay CFTC cho AI trading; các nghị sĩ đã gửi yêu cầu thông tin về agentic trading tháng 06/2026 [40].
  - EU: các quy định rủi ro cao của AI Act áp dụng từ 02/08/2026; MiCA điều chỉnh agent thực thi lệnh cho khách [41].
  - Việt Nam: Luật Công nghiệp công nghệ số có hiệu lực 01/01/2026, công nhận tài sản số [42]. Nghị quyết 05/2025 yêu cầu vốn 10.000 tỷ đồng, giao dịch bằng VND, loại trừ một số loại stablecoin [43]. Đến 30/08/2026 chưa cấp giấy phép nào [44]. **Chưa có quy định rõ về việc nhóm Việt Nam bán API ra nước ngoài và nhận stablecoin** (câu hỏi mở).

## 6. Nhận định chỉ thấy được khi ghép các hướng

- **Cung dồn vào chỗ dễ làm, cầu trả tiền cho chỗ khác.**
  - Trên OKX.AI, 25 agent rủi ro/bảo mật chỉ có 0,3% lượt dùng.
  - Người mua lớn đã có hàng miễn phí hoặc gần miễn phí: CertiK 0,001 USDT mỗi lượt [5], GoPlus có gói miễn phí [54].
  - Theo Blockaid, thiệt hại thật đến từ khâu ký và giữ khóa [37]. Cơ hội vì vậy nằm ở **tường lửa trước khi ký** bán cho ví và nền tảng agent, không nằm ở dịch vụ "quét token" bán lẻ từng lượt.
- **OKX tự lấy phần định tuyến và thực thi.**
  - OKX cho miễn phí Agent Trade Kit và DEX aggregator 500+ nguồn [7][9].
  - Hai ngách "Trade MCP $0,05/lệnh" và "Smart Router 0,03%" trong bản nháp đối đầu trực tiếp với hạ tầng miễn phí của chính nền tảng.
  - Giá trị còn lại cho bên thứ ba là **chiến lược/tín hiệu** (alpha), không phải đường ống.
- **Tín hiệu có PnL kiểm chứng là thứ duy nhất trên OKX.AI có người trả phí định kỳ**, và OKX đang thưởng tiền cho đúng hành vi này qua hackathon [3].

## 7. Khuyến nghị

1. **Ưu tiên 1: tín hiệu/chiến lược có PnL on-chain công khai, bán thuê bao 10–20 USDT/tháng, và tham gia Trading Hackathon cùng OKX Dev Day (quỹ giải $100K) [11].** Độ tin cậy trung bình, dựa trên số liệu trực tiếp [1][3]. Doanh thu phụ thuộc vào hiệu suất thực, không thể hứa trước.
2. **Ưu tiên 2: tường lửa kiểm tra trước khi ký giao dịch cho agent (ALLOW/WARN/DENY), bán B2B cho ví và nền tảng agent.** Độ tin cậy trung bình [37]. Trên OKX.AI đã có 6–8 đối thủ nhỏ; cần kênh B2B ngoài OKX.
3. **Không nên:** tự xây router DEX hoặc executor MCP để cạnh tranh với công cụ miễn phí của OKX. Không nên làm sản phẩm giữ hộ tài sản (custody) cho người dùng Việt Nam [43].
4. **Theo dõi:** cổ phiếu token hoá (xStocks) trên X Layer có 6 nhóm mới vào, gần như chưa có cầu [1]. Đây là ngách để quan sát, chưa nên đầu tư.
5. **Mọi dự phóng tài chính cần ghi là "kịch bản giả định".** Các con số trong bản nháp cũ (100 ASP, 640.000 lượt/tháng, $400–1.800/tháng/agent) **không có bằng chứng hỗ trợ**.

## 8. Câu hỏi mở

- GMV thật và phí nền tảng của OKX.AI: cần đối soát on-chain các ví ASP và hợp đồng escrow trên OKLink.
- Doanh thu thật của TradeDesk và 1M·斯巴达: đối soát chuyển USDT vào ví.
- Bảng xếp hạng x402scan: số liệu "revenue" top-10 (~$123M) mâu thuẫn với tổng on-chain (~$41,8M) [15]. Trạng thái: disputed.
- Pháp lý khi nhóm Việt Nam nhận thanh toán bằng stablecoin cho dịch vụ bán ra nước ngoài: cần hỏi luật sư.
- Kết quả OKX Dev Day (06–07/10/2026): cần cập nhật vì đây là một cuộc khảo sát ngách mới.

## 9. Phụ lục nguồn

| # | Hỗ trợ cho | Nhà xuất bản | Ngày | Truy cập | Tin cậy |
|---|---|---|---|---|---|
| [1] | Khảo sát 146 agent online | [OKX.AI agents](https://www.okx.ai/agents) | live | 2026-09-28 | cao |
| [2] | Bộ đếm chợ task $9,653 / 81,236 | [OKX.AI tasks](https://www.okx.ai/tasks) | live | 2026-09-28 | cao |
| [3] | Trading Hackathon S1 | [OKX.AI hackathon](https://www.okx.ai/hackathon) | 2026-08 | 2026-09-28 | cao |
| [4] | Cơ chế OKX.AI | [OKX Learn](https://www.okx.com/en-us/learn/okx-ai) | 2026-07-01 | 2026-09-28 | cao |
| [5] | 10K agent / 4K listing / 20K task; tỷ trọng ngành | [OKX Learn 2](https://www.okx.com/en-us/learn/okx-ai-2) | 2026-08/09 | 2026-09-28 | trung bình–cao |
| [6] | Ra mắt OKX.AI, 50 ASP beta | [TechCrunch](https://techcrunch.com/2026/06/30/crypto-exchange-okx-wants-ai-agents-to-hire-and-pay-each-other/) | 2026-06-30 | 2026-09-28 | cao |
| [7] | OnchainOS AI layer | [CoinDesk](https://www.coindesk.com/tech/2026/03/03/okx-jumps-into-ai-agent-race-with-new-onchainos-toolkit) | 2026-03-03 | 2026-09-28 | cao |
| [8] | Doanh thu thật 0,8 USDT / 25 ngày | [Leo Labs](https://leolabs.me/blog/ai-agent-paying-for-services/en/) | 2026-08 | 2026-09-28 | cao (trải nghiệm trực tiếp) |
| [9] | Agent Trade Kit | [GitHub okx](https://github.com/okx/agent-trade-kit) | 2026-09-23 | 2026-09-28 | cao |
| [10] | Lượt tải npm | [npm API](https://api.npmjs.org/downloads/point/last-month/@okx_ai/okx-trade-mcp) | 2026-09-26 | 2026-09-28 | cao |
| [11] | OKX Dev Day $100K | [OKX Learn](https://www.okx.com/en-us/learn/okx-dev-day-builder-kit) | 2026-09-15 | 2026-09-28 | cao |
| [12] | Doanh thu bot / Virtuals / yield | [DefiLlama](https://api.llama.fi/overview/fees) | 2026-09-27 | 2026-09-28 | cao |
| [13] | x402 100M giao dịch, PING | [Chainalysis](https://www.chainalysis.com/blog/x402-agentic-payments-adoption/) | 2026-06-03 | 2026-09-28 | cao |
| [14] | ~50% giao dịch ảo; ~$28K/ngày | [CoinDesk/Artemis](https://www.coindesk.com/markets/2026/03/11/coinbase-backed-ai-payments-protocol-wants-to-fix-micropayment-but-demand-is-just-not-there-yet) | 2026-03-11 | 2026-09-28 | cao |
| [15] | x402 188M giao dịch / $41,8M | [agenteconomy.to](https://agenteconomy.to/stats/x402-transactions) | 2026-09-23 | 2026-09-28 | trung bình |
| [16] | x402 Census, mức tập trung người bán | [GitHub x402-census](https://github.com/savecharlie/x402-census) | 2026-09-25 | 2026-09-28 | trung bình–thấp |
| [17] | Olas Mech | [Olas](https://olas.network/agent-economies/mech) | 2026-09-23 | 2026-09-28 | trung bình–cao |
| [18] | Virtuals Revenue Network $1M/tháng | [PR Newswire](https://www.prnewswire.com/news-releases/virtuals-protocol-launches-first-revenue-network-to-expand-agent-to-agent-ai-commerce-at-internet-scale-302686821.html) | 2026-02 | 2026-09-28 | trung bình |
| [19] | Virtuals aGDP $479M | [BlockEden](https://blockeden.xyz/blog/2026/04/21/agdp-agent-gdp-virtuals-protocol-ai-blockchain-valuation-primitive-tvl-displacement/) | 2026-04-21 | 2026-09-28 | trung bình |
| [20] | Ethy/Axelrod/aixbt aGDP | [ChainWard](https://chainward.ai/decodes/agdp-fdv-disconnect) | 2026 | 2026-09-28 | trung bình–thấp |
| [21] | Ramp $1,5B | [CNBC](https://www.cnbc.com/2026/06/04/ramp-valuation-funding-ai-spend.html) | 2026-06-04 | 2026-09-28 | cao |
| [22] | AlphaSense >$500M ARR | [PR Newswire](https://www.prnewswire.com/news-releases/alphasense-surpasses-500m-in-arr-as-adoption-of-applied-ai-workflows-surges-302576369.html) | 2025-10 | 2026-09-28 | cao |
| [23] | Rogo >$50M ARR | [Crypto Briefing](https://cryptobriefing.com/rogo-arr-triples-50m-surpasses-hebbia/) | 2026 | 2026-09-28 | trung bình |
| [24] | Rillet | [TechCrunch](https://techcrunch.com/2026/08/19/rillet-raises-100m-series-c-at-1b-valuation-2-years-after-emerging-from-stealth/) | 2026-08-19 | 2026-09-28 | cao |
| [25] | Norm Ai | [TechCrunch](https://techcrunch.com/2026/07/07/ai-law-startup-norm-raises-120m-hits-unicorn-valuation/) | 2026-07-07 | 2026-09-28 | cao |
| [26] | BofA Erica | [Yahoo Finance](https://finance.yahoo.com/technology/ai/articles/erica-powering-bank-americas-digital-125800674.html) | 2026 | 2026-09-28 | trung bình–cao |
| [27] | VC H1/2026 $510B | [Crunchbase News](https://news.crunchbase.com/venture/global-startup-exits-ipo-ma-soar-ai-q2-h1-2026/) | 2026-07-02 | 2026-09-28 | cao |
| [28] | AI×crypto 40% VC; token giảm | [FXStreet / Binance Research](https://www.fxstreet.com/cryptocurrencies/news/ai-is-booming-but-ai-crypto-tokens-are-missing-the-rally-202609250700) | 2026-09-25 | 2026-09-28 | trung bình |
| [29] | Natural $30M | [TechCrunch](https://techcrunch.com/2026/07/20/natural-raises-30m-to-reinvent-payments-for-ai-agents-and-take-on-stripe/) | 2026-07-20 | 2026-09-28 | cao |
| [30] | Catena Labs $30M | [Fortune](https://fortune.com/2026/05/20/catena-labs-series-a-sean-neville-ai-native-bank/) | 2026-05-20 | 2026-09-28 | cao |
| [31] | Kite $18M | [PayPal Newsroom](https://newsroom.paypal-corp.com/2025-09-02-Kite-Raises-18M-in-Series-A-Funding-To-Enforce-Trust-in-the-Agentic-Web) | 2025-09-02 | 2026-09-28 | cao |
| [32] | Stripe Tempo + MPP | [CoinDesk](https://www.coindesk.com/tech/2026/03/18/stripe-led-payments-blockchain-tempo-goes-live-with-protocol-for-ai-agents) | 2026-03-18 | 2026-09-28 | cao |
| [33] | Mastercard Agent Pay for Machines | [CoinDesk](https://www.coindesk.com/business/2026/06/10/mastercard-prepares-for-a-future-where-ai-agents-make-payments-with-latest-introduction) | 2026-06-10 | 2026-09-28 | cao |
| [34] | Visa Intelligent Commerce Connect | [Axios](https://www.axios.com/2026/04/08/visa-ai-agent-payments-platform) | 2026-04-08 | 2026-09-28 | trung bình |
| [35] | McKinsey $3–5T 2030 | [Digital Commerce 360](https://www.digitalcommerce360.com/2025/10/20/mckinsey-forecast-5-trillion-agentic-commerce-sales-2030/) | 2025-10-20 | 2026-09-28 | trung bình–cao |
| [36] | Morgan Stanley $190–385B | [Morgan Stanley](https://www.morganstanley.com/insights/articles/agentic-commerce-market-impact-outlook) | ~2025 | 2026-09-28 | trung bình |
| [37] | Blockaid H1/2026 | [The Block](https://www.theblock.co/post/409944/crypto-hacks-hit-record-high-in-h1-2026-as-losses-top-1-billion-blockaid-says) | 2026-07 | 2026-09-28 | cao–trung bình |
| [38] | Vụ Grok/Bankrbot | [OECD.AI](https://oecd.ai/en/incidents/2026-05-04-4a73) | 2026-05-04 | 2026-09-28 | trung bình |
| [39] | GENIUS Act | [Federal Register](https://www.federalregister.gov/documents/2026/08/18/2026-16796/genius-act-regulations-on-payment-stablecoin-issuance-offer-and-sale) | 2026-08-18 | 2026-09-28 | cao |
| [40] | RFI agentic trading | [US House](https://foster.house.gov/sites/evo-subsites/foster-evo.house.gov/files/evo-media-document/foster_sherman-request-for-information-re-agentic-trading-6.23.2026.pdf) | 2026-06-23 | 2026-09-28 | trung bình–cao |
| [41] | MiCA / AI Act | [ESMA](https://www.esma.europa.eu/esmas-activities/digital-finance-and-innovation/markets-crypto-assets-regulation-mica) | 2026 | 2026-09-28 | trung bình |
| [42] | Luật CN công nghệ số | [DFDL](https://www.dfdl.com/insights/legal-and-tax-updates/vietnam-landmark-law-on-digital-technology-industry-new-frameworks-for-ai-digital-assets/) | 2025 | 2026-09-28 | trung bình |
| [43] | Nghị quyết 05/2025 | [Acclime](https://vietnam.acclime.com/news-insights/vietnams-crypto-pilot-a-cautious-green-light/) | 2025-09-26 | 2026-09-28 | trung bình |
| [44] | Chưa cấp giấy phép | [CryptoRank](https://cryptorank.io/news/feed/b7225-nine-months-seven-applicants-zero-licences-vietnams-crypto-waiting-game) | 2026-08-30 | 2026-09-28 | trung bình–thấp |
| [45] | Bảng giá CoinGecko | [CoinGecko](https://www.coingecko.com/en/api/pricing) | live | 2026-09-28 | cao |
| [46] | Giá Nansen x402 | [Nansen docs](https://docs.nansen.ai/getting-started/agentic-payments/x402-payments) | 2026-04 | 2026-09-28 | cao |
| [47] | AgentLISA | [Chainwire](https://chainwire.org/2025/11/12/agentlisa-reaches-4-on-x402scan-leaderboard-pioneering-ai-security-for-the-agent-to-agent-economy/) | 2025-11-12 | 2026-09-28 | trung bình (thông cáo báo chí) |
| [48] | Binance Agent OS | [crypto.news](https://crypto.news/binance-agent-os-ai-trading-safeguards/) | 2026-08 | 2026-09-28 | trung bình |
| [49] | Bitget GetAgent | [Bitget](https://www.bitget.com/blog/articles/bitget-ai-1-million-users) | 2026 | 2026-09-28 | trung bình (tự công bố) |
| [50] | OKX APP | [Digital Today](https://www.digitaltoday.co.kr/en/view/52581/okx-unveils-agent-payments-protocol-app-to-rival-coinbase-x402-and-stripe) | 2026-05-03 | 2026-09-28 | trung bình |
| [51] | Giza đóng ARMA | [Crypto Briefing](https://cryptobriefing.com/giza-tech-returns-arma-pulse-funds/) | 2026-02/03 | 2026-09-28 | trung bình–cao |
| [52] | x402 205M giao dịch, Coinbase 67% | [CryptoRank](https://cryptorank.io/news/feed/c619a-ai-agents-205-million-transactions-x402-coinbase) | 2026-08 | 2026-09-28 | trung bình–thấp |
| [53] | CoinGecko x402 $0,01/lượt | [CoinGecko Learn](https://www.coingecko.com/learn/x402-pay-per-use-crypto-api) | 2026-09-01 | 2026-09-28 | cao |
| [54] | GoPlus gói miễn phí | [GoPlus docs](https://docs.gopluslabs.io/reference/api-overview) | live | 2026-09-28 | trung bình |
| [55] | ASP, A2A/A2MCP, x402, evaluator stake OKB | [OKX.AI tutorial](https://www.okx.ai/tutorial/asp) | live | 2026-09-28 | cao |
| [56] | Blockaid H1 report (212 vụ, 76%) | [Blockaid](https://blockaid.io/h1-report-2026) | 2026-07 | 2026-09-28 | trung bình (một nguồn) |
| [57] | OKX Bot Marketplace (600 bot, chia lợi nhuận) | [OKX](https://www.okx.com/trading-bot/marketplace) | live | 2026-09-28 | cao |
| [58] | OKX Signal Marketplace (31 kênh) | [OKX](https://www.okx.com/trading-bot/signal-marketplace) | live | 2026-09-28 | cao |
| [59] | Binance Futures Copy Trading, lead trader | [Binance](https://www.binance.com/en/copy-trading) | live | 2026-09-28 | cao |
| [60] | Binance Trading Bots, số bot đang chạy | [Binance](https://www.binance.com/en/trading-bots) | live | 2026-09-28 | cao |
| [61] | Chia lợi nhuận lead trader 10%/≤30% | [Binance FAQ](https://www.binance.com/en/support/faq/binance-futures-copy-trading-lead-trader-growth-plan-3160c961b2734d1cbb5342d1e86c6cdb) | 2026 | 2026-09-28 | trung bình–cao |
| [62] | Binance Agent OS | [TechCrunch](https://techcrunch.com/2026/08/20/binance-now-lets-ai-agents-trade-but-keeping-them-in-check-is-largely-up-to-users/) | 2026-08-20 | 2026-09-28 | cao |
| [63] | Binance Skills Hub (~20–23 skill chính thức) | [Binance](https://www.binance.com/en/skills) | live | 2026-09-28 | cao |
| [64] | Binance AI Pro $9,99/$29,99 | [Analytics Insight](https://www.analyticsinsight.net/press-release/binance-beta-launches-binance-ai-pro-bringing-ai-agentic-trading-to-users) | 2026-03-25 | 2026-09-28 | trung bình |
| [65] | Hackathon Build the Era, BNB Agent Studio | [BNB Chain](https://www.bnbchain.org/en/blog/build-the-era-build-the-official-bnb-agent-studio-marketplace) | 2026-08-05 | 2026-09-28 | cao |
| [66] | Doanh thu BSC 30 ngày | [DefiLlama](https://api.llama.fi/overview/fees/bsc) | 2026-09-27 | 2026-09-28 | cao |
| [67] | Dashboard AI agent BNB Chain (MAU) | [BNB Chain](https://www.bnbchain.org/en/solutions/ai-agent) | live | 2026-09-28 | trung bình (tự công bố) |
| [68] | Robinhood Gold 4,8M thuê bao | [Robinhood IR](https://investors.robinhood.com/news-releases/news-release-details/robinhood-reports-second-quarter-2026-results) | 2026-07-29 | 2026-09-28 | cao |
| [69] | Cleo ~$400M ARR | [Sacra](https://sacra.com/c/cleo/) | 2026-05 | 2026-09-28 | trung bình |
| [70] | Composer by SoFi $215M/ngày | [BusinessWire](https://www.businesswire.com/news/home/20260623095057/en/Introducing-Composer-by-SoFi-AI-Powered-Investing-From-Idea-to-Execution) | 2026-06-23 | 2026-09-28 | trung bình (thông cáo báo chí) |
| [71] | eToro Q2/2026, CopyTrader | [eToro IR](https://investors.etoro.com/news-releases/news-release-details/etoro-reports-second-quarter-2026-results) | 2026 | 2026-09-28 | cao |
| [72] | Bảng giá 3Commas | [3Commas](https://help.3commas.io/en/articles/8420093-available-subscription-plans) | 2026 | 2026-09-28 | trung bình |
| [73] | Bảng giá Cryptohopper | [Cryptohopper](https://www.cryptohopper.com/pricing) | 2026 | 2026-09-28 | trung bình |
| [74] | Bảng giá Trade Ideas | [Trade Ideas](https://www.trade-ideas.com/compare/trendspider) | 2026 | 2026-09-28 | trung bình |
| [75] | Olas Polystrat chuyển bảo trì | [Olas](https://olas.network/blog/q2-2026) | 2026 | 2026-09-28 | trung bình |
| [76] | Bot/AI chiếm volume thị trường dự đoán | [CoinDesk](https://www.coindesk.com/tech/2026/03/15/ai-agents-are-quietly-rewriting-prediction-market-trading) | 2026-03-15 | 2026-09-28 | trung bình–thấp |
| [77] | Autopilot $750M+ AUM, 80K thuê bao | [PR Newswire](https://www.prnewswire.com/news-releases/public-and-autopilot-partner-to-bring-a-new-model-of-managed-investing-to-retail-investors-302672071.html) | 2026 | 2026-09-28 | trung bình (có xung đột số liệu) |
| [78] | Bybit AI | [HackerNoon](https://hackernoon.com/bybit-launches-bybit-ai-turning-one-chat-window-into-the-front-door-for-80-million-users) | 2026-09-09 | 2026-09-28 | trung bình |
| [79] | Binance "AI/Auto Parameters" grid: tĩnh, backtest 7/30/180 ngày | [Binance FAQ](https://www.binance.com/en/support/faq/binance-futures-grid-trading-ai-parameters-guide-647b0dba72d145219688b04aa51405fc) | 2026-01-09 | 2026-09-28 | cao |
| [80] | OKX grid "AI strategy": backtest 7/20/90 ngày | [OKX Help](https://www.okx.com/en-us/help/how-do-i-automate-grid-trading-strategies-on-spot-grid-crypto-trading-bot) | n/v | 2026-09-28 | trung bình–cao |
| [81] | Pionex AI grid: backtest 7/30/180 ngày | [Pionex](https://www.pionex.com/blog/knowledge-base/should-i-use-the-ai-parameters/) | n/v | 2026-09-28 | trung bình–cao |
| [82] | Bitget grid AI mode: backtest 7 ngày | [Bitget](https://www.bitget.com/support/articles/12560603791272) | n/v | 2026-09-28 | trung bình–cao |
| [83] | 3Commas AI Assistant: cấu hình lúc tạo bot | [3Commas](https://3commas.io/ai-trading-bot) | 2026 | 2026-09-28 | cao |
| [84] | Cryptohopper Algorithm Intelligence: đổi chiến lược theo điều kiện thị trường | [Cryptohopper docs](https://docs.cryptohopper.com/docs/explore-features/algorithm-intelligence-ai/) | n/v | 2026-09-28 | trung bình–cao |
| [85] | Coinrule Market Regime Detection: bật/tắt luật theo regime | [Coinrule](https://coinrule.com/market-regime-detection/) | 2026 | 2026-09-28 | trung bình–cao |
| [86] | Độ dài lịch sử dữ liệu OKX API (đo trực tiếp) | [OKX API docs](https://www.okx.com/docs-v5/en/) | live | 2026-09-28 | cao |

## 12. Deepen (28/09/2026): Binance và các agent kiếm nhiều, phổ biến

**Bổ sung theo yêu cầu:** tìm thêm các agent có tiềm năng hoặc đang kiếm nhiều, có nhiều người dùng, mở rộng sang Binance. Nguồn chính là dữ liệu chụp trực tiếp từ các trang công khai của OKX và Binance ngày 28/09/2026 [57]–[60].

**Phát hiện mới làm thay đổi trọng tâm khuyến nghị:** dòng tiền lớn nhất dành cho người tạo chiến lược **không nằm ở chợ agent**, mà ở **chợ copy-trading, bot và tín hiệu của chính các sàn**. Người tạo được chia **10–30% lợi nhuận** của người copy, còn sàn giữ tiền.

- **OKX Bot Marketplace** có 600 bot công khai [57]. Các bot dẫn đầu đều là DCA futures ETH, chia 30% lợi nhuận. Bot top 1 có 10.055 người copy và $3,05M tài sản đang chạy theo. Bot top 2 có 7.705 người copy và $2,21M.
- **OKX Signal Marketplace** có 31 kênh tín hiệu, thu tiền bằng chia lợi nhuận hoặc phí tháng [58]. Kênh "[AM] Occultation" có 50.002 người theo; "[IntellyBot] BTC" có 14.512 người theo và AUM $95K. Các kênh hiển thị chia 10–30%; theo trang trợ giúp của OKX, người cung cấp tự đặt 1–30%.
- **Số bot đang chạy trên OKX** (theo trang): grid spot 691.642, grid futures 648.330, DCA futures 431.125, signal bot 75.460 [57].
- **Binance Futures Copy Trading** [59]:
  - Lead trader top theo PnL 30 ngày: Benny_256 $1,21M, Luke Alpha $0,99M (AUM $7,05M).
  - Bốn portfolio gắn nhãn **API** (vận hành bằng bot/thuật toán) có 365–798 người copy và AUM $165K–744K.
  - Lead trader nhận ≤30% lợi nhuận futures (10% với spot), cộng 10% hoa hồng phí [61].
- **Binance Trading Bots** đang chạy 85.346 bot loại 1 ($173,8M) và 41.065 bot loại 2 ($109,8M). Hai loại này nhiều khả năng là grid spot và grid futures; Binance không ghi nhãn [60].
- **Stack agent chính thức của Binance** gồm Agent OS (20/08/2026), Skills Hub khoảng 20–23 skill và Binance AI Pro ($9,99/tháng bản beta, giá niêm yết $29,99) [62][63][64].
  - **Không có chợ cho bên thứ ba bán agent có thu tiền** như OKX.AI.
  - Builder kiếm tiền trên Binance qua copy trading, hoàn phí Binance Link 30–50% và hackathon. "Build the Era" trao 30k USDT, và đội thắng được chọn làm BNB Agent Studio chính thức [65].
- **BNB Chain**, doanh thu 30 ngày [66]:
  - Nhóm dẫn đầu: GMGN $10,65M, Flap.sh $9,09M, fomo $2,96M, Binance Alpha $1,88M, Predict.fun $1,16M.
  - Không dự án nào trong nhóm dẫn đầu do LLM vận hành. Agent AI có doanh thu duy nhất là TermiX ($145K trên BSC).
  - Dashboard AI của BNB Chain báo MAU lớn (Alaya 1,69M, OptimAI 593K) nhưng không có doanh thu [67].
  - BNB Chain có nhiều agent ERC-8004 nhất: 34K (03/2026), tăng lên hơn 200K (16/07/2026). Hai con số khác thời điểm, không mâu thuẫn [65].
- **Thị trường dự đoán** là nguồn doanh thu lớn thứ hai sau app giao dịch: Polymarket $14,4M/30 ngày [12].
  - Bot chiếm phần lớn volume (độ tin cậy thấp–trung bình) [76].
  - Rủi ro nền tảng: Polystrat của Olas phải chuyển sang chế độ bảo trì sau khi Polymarket thay đổi [75].
- **Sản phẩm phổ biến toàn cầu có người trả tiền:**
  - Robinhood Gold: 4,8M thuê bao × $5/tháng; Cortex AI là quyền lợi đi kèm [68].
  - Cleo: ~$400M ARR [69].
  - Composer: SoFi đã mua lại (06/2026). Con số $215M+ giao dịch/ngày chỉ có trong thông cáo báo chí, chưa kiểm chứng được [70].
  - eToro: 4,3M tài khoản có nạp tiền; CopyTrader là động lực tăng trưởng [71]. Autopilot: $750M+ AUM, 80K+ thuê bao; số liệu giữa các nguồn chưa khớp [77].
  - Bybit AI, Bitget GetAgent, Coinbase for Agents, Kraken đều **miễn phí**; sàn thu tiền qua phí giao dịch [78].
- **Mức giá trader chấp nhận trả:**
  - Bot crypto: $15–129/tháng (3Commas, Cryptohopper) [72][73]. Bot grid/DCA đã thành hàng phổ thông, Pionex cho miễn phí.
  - Scanner AI cho cổ phiếu: $89–254/tháng (Trade Ideas) [74].

**Khuyến nghị cập nhật:** giữ Ưu tiên 1 nhưng **mở rộng kênh phân phối**. Cùng một chiến lược/agent giao dịch nên phát hành song song ở bốn nơi:
1. Làm **lead bot** trên OKX Bot Marketplace, hoặc làm **kênh signal bot** trên OKX Signal Marketplace, chia 20–30% lợi nhuận.
2. Làm **lead trader API** trên Binance Copy Trading, chia ≤30% lợi nhuận.
3. Bán **thuê bao** trên OKX.AI (10–20 USDT/tháng).
4. Thi **hackathon** của OKX và BNB Chain.

Mô hình này không giữ tiền của khách (sàn giữ), trả tiền theo hiệu suất và có sẵn hàng trăm triệu người dùng. Độ tin cậy **cao** về việc cơ chế và cầu tồn tại, vì số liệu được chụp trực tiếp. Độ tin cậy **thấp** về mức thu nhập mà một đội mới đạt được, vì phụ thuộc hoàn toàn vào hiệu suất.


## 13. Nhận định chéo: thực tế và kỳ vọng, tâm lý người dùng

- **Xu hướng chung OKX và Binance:** cả hai sàn đang xây hạ tầng agent (OKX.AI, Agent Trade Kit, Agent OS, AI Pro). Nhưng tiền người dùng vẫn nằm ở **bot có sẵn và copy-trade/tín hiệu** [57][58][59][60]. Chợ agent bên thứ ba gần như chưa có tiền [1][2]; Binance không có chợ này [63].
- **Kỳ vọng và thực tế:**
  - OKX công bố 10K+ agent; thực đo có 146 online, tổng $9.653 [1][2][5].
  - x402 có hàng trăm triệu giao dịch nhưng tổng $41–50M, trong đó ~50% là giao dịch ảo [14][15].
  - BNB Chain có 200K+ agent đăng ký, nhưng chỉ TermiX có doanh thu đáng kể [66].
  - Dự báo $3–5T vào 2030 [35], trong khi hôm nay tiền nằm ở app giao dịch [12].
- **Vì sao hệ thống phân tích khó bán:**
  - Người dùng mua kết quả, không mua thông tin.
  - Sàn đã cho số liệu cơ bản miễn phí.
  - Giá trị chỉ lộ ra sau khi đã lỗ.
  - ROI đẹp thắng cảnh báo: bot ROI 7.876% nhưng MDD 71,9% vẫn kín 570/600 suất [59].
  - Khó kiểm chứng ngay. Bằng chứng: ngách rủi ro trên OKX.AI chỉ có 27 lượt dùng [1].
- **Vì sao khai phá chiến lược tiềm năng dù giống signal:** cùng trả lời câu hỏi người dùng đang hỏi ("copy gì để có lãi"), nhưng đứng ở vị trí **tổng hợp độc lập** thay vì người bán tín hiệu của chính mình.
  - Nguồn cung đã quá nhiều và phân mảnh.
  - Tín hiệu tự báo thì không đáng tin: backtest +1.218% nhưng tỷ lệ thắng thực chỉ 43,8% [58].
  - Không phụ thuộc vào alpha của chính mình.
  - Mô hình tổng hợp đã có người trả tiền (Autopilot, eToro CopyTrader) [71][77].
  - Kết luận: engine rủi ro nên làm **động cơ xếp hạng**, và phần thu tiền là kiểm soát rủi ro (xem forge `norabt-discovery-risk`).


## 14. Khuyến nghị cập nhật: chào bán NoraBT

*Mục này thay cho khuyến nghị ở mục 7 và mục 12. Đội không tự giao dịch mà làm sản phẩm agent risk để bán.*

- **Định vị:** NoraBT là lớp bảo vệ cho người copy-trade: báo trước, cắt kịp thời, theo luật của chính người dùng. Không định vị là "công cụ đo rủi ro" [1][57][59].
- **Kênh 1: OKX.AI**, niêm yết với dùng thử miễn phí và thuê bao tháng.
  - Listing có dùng thử + thuê bao: 88% đã có người dùng, so với 43% các listing khác.
  - Giá 0,01–0,1 USDT chiếm 89% tổng lượt dùng.
  - Cả 25 agent rủi ro hiện có đều chỉ bán lẻ từng lượt; tổng cộng 27 lượt dùng [1].
  - Các con số trên là tương quan, chưa phải nhân quả.
- **Gói sản phẩm:**
  - Free: bảng xếp hạng bot theo rủi ro.
  - Pro 10–20 USDT/tháng: cảnh báo và báo cáo sâu.
  - Guard (sau khi điểm rủi ro được kiểm định): đề xuất một chạm và tự bảo vệ theo luật người dùng đặt.
  - API MCP/x402 0,01–0,1 USDT/lượt: kênh phụ.
- **Chưa quyết:** ai là người trả tiền chính, và vai trò của x402. Hai câu này để thử nghiệm T1–T4 trả lời (xem `_bmad-output/forge/norabt-discovery-risk/`).
- **Top 100 độ hot:** `digests/GTM-top100-hotness.json`. Điểm quy đổi theo thang log từ doanh thu, số người dùng hoặc lượt bán, nên chỉ dùng để xếp hạng tương đối.

## 15. Kiểm chứng hướng "regime + signal" (28/09/2026)

- **Tham số AI của các sàn chỉ đặt một lần:** Binance, OKX, Pionex, Bitget và Bybit đều gợi ý tham số grid khi tạo bot, dựa trên backtest 7–180 ngày. Không sàn nào tự chỉnh lại trong lúc bot đang chạy [79][80][81][82]. 3Commas AI Assistant cũng cấu hình lúc tạo bot [83].
- **Thích ứng theo regime chỉ có ở mức bật/tắt chiến lược:** Cryptohopper đổi chiến lược theo điều kiện thị trường [84], Coinrule bật/tắt luật theo regime [85]. Không bên nào chỉnh tham số.
- **Chẩn đoán vì sao bot lỗ** (tham số nào gặp regime nào): **không tìm thấy** sản phẩm nào làm việc này. Đây là khoảng trống cho NoraBT.
- **Độ dài lịch sử dữ liệu OKX** (đo trực tiếp [86], `digests/D9-okx-data-depth-r1-lead.md`):
  - Nến 1 giờ có từ 2021.
  - OI theo ngày có từ ≥ 02/2025; OI theo giờ chỉ vài ngày gần nhất.
  - Taker theo giờ ≥ 4 tháng.
  - Funding khoảng 3–4 tháng.
  - Long/short theo giờ ngắn.
  - Sổ lệnh không có lịch sử.
- **Hệ quả cho thử nghiệm:**
  - E1–E4 chạy được ngay trên nến có sẵn.
  - E5 ở mức theo giờ cần tự ghi dữ liệu từ bây giờ, hoặc thử trước ở mức theo ngày.

## 16. Giải mã 50 bot top OKX & Binance (29/09/2026)

**Phương pháp:**
- Mẫu gồm 26 lead OKX, lấy qua API copy-trading chính thức, và 24 lead Binance, lấy từ trang lead công khai.
- Tổng cộng 15.278 lệnh đã đóng; 97% số lệnh gắn được regime tại lúc vào lệnh (nến 4 giờ, EMA50/200, ADX14, ATR).
- Dữ liệu và script nằm trong `digests/bots50/`.

**Kết quả** (đây là suy luận từ hành vi giao dịch, không phải luật thật của bot):
- **DCA, bình quân giá xuống, là cách vận hành chủ đạo trên OKX:**
  - 23/26 lead mở thêm lệnh cùng mã, cùng chiều khi lệnh trước chưa đóng.
  - 16/26 lead có phần lớn lệnh mở thêm ở giá xấu hơn lệnh trước (trung vị 69% số lệnh mở thêm).
  - Chỉ 1/26 lead nhồi lệnh theo đà khi đang lãi.
  - Số vị thế cùng mở tối đa có trung vị là 13; có lead mở chồng hơn 100 vị thế cùng lúc.
  - Con số "7 bot DCA" là định nghĩa chặt: DCA kèm gồng lỗ.
  - Binance gộp các lần mở thêm vào cùng một vị thế, nên không đo được DCA trên Binance.
- **Lối chơi phổ biến nhất là đánh ngược đà:** 22/50 bot. Trung vị chỉ 43% số lệnh vào cùng chiều với biến động 24 giờ trước đó. 7 lead OKX có kiểu nhồi lệnh, gồng lỗ (DCA).
- **Tỷ lệ thắng cao, nhưng đuôi lỗ lớn:** tỷ lệ thắng trung vị 74% ở OKX và 85,5% ở Binance. Tuy vậy, 23/50 bot có lệnh lỗ cực lớn, và 24/50 bot có lãi dồn vào vài lệnh.
- **Lỗ treo (đo qua API vị thế đang mở của OKX):** 17/26 lead OKX đang lỗ chưa chốt, tổng −1,29M USDT. 8 lead có khoản lỗ này lớn so với lãi đã chốt, trong đó có lead mà 100% lệnh đã đóng là lệnh thắng.
- **TradFi chiếm khoảng 20% số lệnh** (OKX 22%, Binance 14%), phân loại theo `exchangeInfo` của Binance.
- **Khác biệt giữa hai sàn:** OKX nghiêng long (trung vị 73,5%) và giữ lệnh khoảng 21 giờ. Binance cân bằng long/short hơn (52%) và giữ lệnh khoảng 6,5 giờ. Đòn bẩy trung vị ở cả hai sàn là 10x.
- **Regime lúc vào lệnh:** 57% lệnh vào khi thị trường tăng, 35% khi đi ngang, 8% khi giảm. Thị trường trong giai đoạn khảo sát nghiêng tăng, nên một phần thành tích có thể là do thị trường chứ không phải kỹ năng.

**Giới hạn:**
- Chỉ thấy được lệnh, không thấy luật của bot. Mỗi lead lấy tối đa 1.000 lệnh.
- Tỷ lệ thắng OKX công bố là tỷ lệ *ngày* có lãi, không phải tỷ lệ lệnh thắng.
- Binance không công khai vị thế đang mở.

## 17. Ngách Signal, tách riêng khỏi Alpha (29/09/2026)

- **Signal** là tín hiệu vào lệnh cụ thể, được đẩy tới người theo; bot của người theo tự vào lệnh.
- **Alpha** là nghiên cứu, dữ liệu và insight, bán dưới dạng terminal, API hoặc feed.
- **OKX Signal Marketplace** có 31 kênh [58]:
  - 6 kênh top có tổng 86.375 người theo, nhưng AUM chỉ $258K, tức khoảng $3 mỗi người theo.
  - Tỷ lệ thắng thực của người theo có trung vị 51%.
  - Số người theo tương quan ngược chiều với APY (−0,83, trên 6 kênh).
  - Kênh tính phí theo 3 dạng: chia lợi nhuận, phí tháng hoặc miễn phí.
- **OKX.AI** có 8 gói thuê bao tháng, tất cả đều là tín hiệu (10–20 USDT) [1].
- **Trên OKX** đang chạy 75.460 signal bot [57].
- **Nhận định:** Signal là ngách có nhiều người dùng nhất và không cần tự bỏ vốn, nhưng tiền mỗi người dùng rất thấp.

## 18. Xu hướng phía người tạo agent (29/09/2026)

**Phương pháp:** so tỷ trọng ngách giữa listing fintech cũ trên OKX.AI (mã agent < 10.000, 48 listing) và listing mới (mã ≥ 10.000, 58 listing) [1].

**Kết quả:**
| Ngách | Listing cũ | Listing mới |
|---|---|---|
| Tín hiệu | 48% | 26% |
| Giao dịch | 6% | 17% |
| Cổ phiếu token hoá (xStocks) | 0% | 10% |
| Hạ tầng tin cậy | 12% | 14% |
| Rủi ro | 25% | 22% |

- Số gói thuê bao tăng từ 1 (listing cũ) lên 7 (listing mới).
- **Nhận định:** người tạo đang rời ngách tín hiệu (đã bão hoà) để chuyển sang giao dịch, xStocks và mô hình thuê bao. Trong khi đó, người dùng vẫn chủ yếu dùng tín hiệu và copy bot.

- **Cung và cầu lệch nhau trên OKX.AI** (106 agent fintech; cung = % số agent, cầu = % lượt dùng):
  - Rủi ro, hạ tầng tin cậy và xStocks có 45 agent, chiếm 42,5% nguồn cung, nhưng chỉ 0,4% lượt dùng.
  - Tín hiệu có cầu gấp 2,6 lần cung. Nếu bỏ TradeDesk ra thì chỉ còn 0,55 lần: cầu dồn vào một agent.
  - Khi bỏ TradeDesk, giao dịch có cầu gấp 2 lần cung, DeFi yield gấp 12,5 lần (DeFi yield chỉ có 4 agent, mẫu nhỏ).
  - Cầu copy-trade thật nằm trên chợ của sàn: một bot có 10.055 người copy, so với 198 lượt dùng của cả ngách giao dịch trên OKX.AI.

## 10. Kiểm chứng

10 nhận định trụ cột được kiểm tra độc lập (xem `digests/verify-r1-1.md`):
- **Verified (10):** [1] [2] [5] [12] [15] [18] [21] [27] [37] [43]. Riêng [12] do lead lấy lại trực tiếp từ API DefiLlama ngày 28/09; snapshot 08/08 cho GMGN thấp hơn (~$9,5M/30 ngày) vì GMGN tăng mạnh gần đây.
- **Disputed (4):** [14] mức giao dịch thật x402; [49] số liệu Bitget; bảng xếp hạng x402scan so với tổng on-chain; ngày ra mắt OKX.AI (lệch một ngày).
- **Kiểm tra trích dẫn (14 mẫu):** 8 khớp; 4 khớp một phần ([3] [4] [37] [43], đã sửa câu chữ và bổ sung nguồn gốc [55] [56]); 1 không khớp ([45], đã chuyển sang [53]); 1 không truy cập được ([21], đã được kiểm chứng độc lập).
- **Vòng Deepen (7 nhận định):** 3 khớp (Robinhood Gold 4,84M; Cleo $400M ARR; Predict.fun >$1,8B/130K người dùng); 2 khớp một phần (tỷ lệ chia lợi nhuận Binance/OKX); 2 chưa kiểm chứng (Composer $215M/ngày; thuật ngữ "lead bot"). Xem `digests/verify-r2-1.md`.
- **Unverified (1):** [8] doanh thu thật của Leo Labs (chỉ có một nguồn trải nghiệm trực tiếp).
- Không chạy red-team (validation = normal).

## 11. Bản đồ độ cũ số liệu

| Nhận định | Loại | Ngày số liệu | Kiểm tra lại | Đã cũ? |
|---|---|---|---|---|
| VN Resolution 05/2025 | regulatory | 2025-09 | 2026-03-01 | có |
| CoinGecko/Nansen x402 price | pricing | 2026-04 | 2026-07-01 | có |
| OKX.AI pricing 0.001-1 USDT, subs 10-20 USDT | pricing | 2026-09 | 2026-12-01 | chưa |
| McKinsey/MS forecasts | forecast | 2025-10 | 2027-04-01 | chưa |
| VC H1-2026 $510B | funding | 2026-07 | 2027-07-01 | chưa |
| OKX.AI live census 146/106 | metric | 2026-09 | 2027-09-01 | chưa |
| OKX.AI task volume $9,653 | metric | 2026-09 | 2027-09-01 | chưa |
| DefiLlama bot revenue 30d | metric | 2026-09 | 2027-09-01 | chưa |
| x402 cumulative $41-50M | metric | 2026-09 | 2027-09-01 | chưa |

Mốc kiểm tra lại sớm nhất: 2026-03-01 (đã quá hạn). Cần kiểm tra lại ngay tình trạng Nghị quyết 05/2025 và bảng giá x402 của Nansen. Bảng giá CoinGecko đã được xem trực tiếp ngày 28/09.
