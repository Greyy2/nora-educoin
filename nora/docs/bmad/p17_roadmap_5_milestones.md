# P17 — Lộ trình 5 tiến độ (2026-10-12)

Vai trò: **anh làm** từng tiến độ; **Opus** phân tích, viết brief, test cổng. Mỗi tiến độ xong = cổng xanh + commit.
Thứ tự: T1 dứt kiến trúc → T2+T3 Education hoàn chỉnh (ưu tiên sản phẩm) → T4 hybrid → T5 OKX.

## Lộ trình gốc → trạng thái
| # | Bước | Trạng thái |
|---|---|---|
| 1 | Hoàn thiện UI | ✅ (R4 badge/cảnh báo/Chuẩn-Nhanh, dọn Studio) |
| 2 | Đồng bộ tham số + code chiến lược chuẩn quốc tế / TradingView | ✅ (theo anh) |
| 3 | Kiến trúc cực gọn: Backtest → WFA → MC (giữ wfa/carlo), xoá funnel/search/tune, metrics = Nautilus PortfolioAnalyzer, dùng thẳng Nautilus | ◐ lõi xong (1 engine, 1 adapter, gỡ số giả). Còn lại → **T1** |
| 4 | Hybrid biên dịch: Education = Nora DSL; Chuyên gia = tự nhận code phức tạp → biên dịch Nautilus native | T4 |
| 5 | Paper/testnet OKX đồng bộ backtest | T5 |
| 6 | Home kiểu sova → 2 hệ thống song song Education / Coin | T2 |
| 7 | User: profile, chiến lược của mình, market theo user, 10 user × 50 mẫu, ẩn mẫu khi đã có chiến lược | T2–T3 |

## TODO tổng (tick khi Opus xác nhận cổng)
- [ ] **T1 Dứt kiến trúc** — chi tiết: `p17_t1_architecture_detail.md`
  - [ ] B0 baseline snapshot · [ ] B1 models/storage.py · [ ] B2 data/data.py (đọc) · [ ] B3 data/crawl.py (kéo + kiểm định + ghi) + job data_update · [ ] B4 cắt pkl + archive crawl/pkl · [ ] B5a jobs/ signal/ alpha/plan · [ ] B5b routes mỏng · [ ] B5c xoá funnel/search/tune (giữ wfa/carlo) + UI Funnel/Tune · [ ] B5d metrics = Nautilus PortfolioAnalyzer · [ ] B6 suite xanh + restart + education_warm
- [ ] **T2 Home + khung Education/Coin + User** — chi tiết: `p17_t2_*.md` (Opus viết khi T1 đạt)
  - [ ] users.py + routes/users + cookie · [ ] owner_id cho user alpha · [ ] Home (2 thẻ) · [ ] EduLayout / CoinLayout + redirect route cũ · [ ] chọn/tạo user, /edu/me
- [ ] **T3 Education hoàn chỉnh**
  - [ ] seed 10 user × 5 chiến lược · [ ] Market /edu · [ ] Profile /edu/u/:handle · [ ] Xem /edu/s/:id + fork · [ ] Studio Edu + luật ẩn mẫu · [ ] E2E e2e_edu.py
- [ ] **T4 Hybrid biên dịch**
  - [ ] alpha/route.classify + reasons · [ ] whitelist import native · [ ] badge Coin Studio · [ ] bộ 20 mẫu phân loại
- [ ] **T5 OKX paper/testnet**
  - [ ] SignalActor tăng dần (parity) · [ ] TradingNode demo · [ ] job live_paper/testnet · [ ] đối chiếu compare_events · [ ] UI /coin/live

## Mô hình sản phẩm
```
/                Home (preview 2 hệ thống: thẻ + số liệu thật + nút vào)
├── /edu/*       EDUCATION (layout + nav riêng)
│     /edu                 Market: lưới user (avatar, số chiến lược, lãi tốt nhất)
│     /edu/u/:handle       Profile user: chiến lược của user đó (thẻ: PnL/MDD/Sharpe thật)
│     /edu/s/:id           Xem chiến lược (code + kết quả), nút "Sao chép về của tôi"
│     /edu/studio          Viết/chạy/lưu (Nora DSL, form đơn giản)
│     /edu/me              Profile của tôi
└── /coin/*      COIN (Alpha catalog, Studio chuyên gia, Backtest → WFA → MC, Portfolio, History, Live)
```
Luật mẫu: user mới (0 chiến lược) → Studio mở sẵn mẫu, thấy danh sách mẫu; khi user có ≥1 chiến lược đã lưu → ẩn mục "Mẫu" (vẫn xem được chiến lược của user khác qua Market).

---

## T1 — Dứt kiến trúc: cực gọn, Backtest → WFA → MC (làm TRƯỚC)
Chi tiết từng bước + bảng file: **`p17_t1_architecture_detail.md`**. Tóm tắt:
- `backend/data/` thay `crawl/`: `crawl.py` (kéo về, kiểm định, chuẩn hoá, ghi catalog) + `data.py` (dùng cho backtest); catalog là nguồn duy nhất, bỏ pkl/funding/Binance/DEX.
- GIỮ `wfa/`, `carlo/` + luồng sổ Backtest → WFA → MC. Xoá `optimize/` (funnel, search, registry promote/revalidate/top_agents) + UI Funnel/Tune; phần còn dùng → `backend/strategies.py` (chiến lược hệ thống, user alpha, sample cache) và `jobs/tasks.py` (book backtest/WFA/MC).
- Metrics = Nautilus PortfolioAnalyzer; `metrics/report.py` chỉ ghép payload UI + MDD/CAGR/Calmar.
- Cây: `main.py data/{crawl,data}.py strategies.py jobs/ routes/ alpha/ signal/ nautilus/ metrics/ wfa/ carlo/ models/`; routes mỏng; chỉ `nautilus/` import nautilus_trader.
**Cổng**: snapshot engine + tín hiệu IDENTICAL; bảng so metrics cũ/mới giải thích được; grep sạch; full suite 0 failed; backend ≤ ~15k dòng; vite build sạch.

## T2 — Home + khung Education + User (nền)
**Backend**
- `backend/users.py` (1 file): User {id, handle, display_name, avatar, bio, created_at}; lưu `data/users/<id>.json`; phiên đăng nhập đơn giản: cookie `nora_uid` ký HMAC (secret `~/.config/nora/app.env`), không mật khẩu ở bản đầu (chọn/tạo user). Routes `routes/users.py`: `GET/POST /api/users`, `GET /api/users/{handle}`, `GET/POST /api/me`, `PUT /api/me` (profile).
- User alpha có `owner_id`: sửa `optimize/book/registry.save_user_alpha/list_user_alphas` thêm `owner_id`, lọc theo owner; `GET /api/users/{handle}/strategies`.
**Frontend**
- `pages/Home.jsx` (tham chiếu sova `frontend/src/pages/Home`: tiêu đề, 2 thẻ hệ thống, số liệu thật từ API, nút vào). Route `/` = Home.
- Tách layout: `layout/EduLayout.jsx`, `layout/CoinLayout.jsx` (Shell hiện tại → Coin, mọi route cũ chuyển dưới `/coin/*`, redirect đường cũ).
- Chọn/tạo user (modal), avatar góc phải, `/edu/me`.
**Cổng (Opus test)**: full suite 0 failed; `/` render 2 thẻ; tạo user → cookie → `/api/me` đúng; route cũ redirect; vite build sạch.

## T3 — Education hoàn chỉnh (Market + seed + mẫu)
- Seed: script `test/scripts/seed_edu_users.py` tạo 10 user (tên/handle/avatar/bio tiếng Việt), chia 50 mẫu (5/user, trộn category/difficulty), lưu thành user alpha có owner.
- Kết quả THẬT: chạy job `education_warm` (mọi mẫu qua Nautilus) → cache; thẻ chỉ hiện số khi có cache (đã làm ở P16).
- Market `/edu`: lưới user (số chiến lược, best Sharpe/PnL thật); `/edu/u/:handle`: chiến lược của user; `/edu/s/:id`: code + CustomResult; "Sao chép về của tôi" (fork → owner = tôi, chạy lại).
- Studio Edu: form đơn giản (Nora DSL), lưu → owner = tôi; luật ẩn mẫu khi đã có ≥1 chiến lược.
- Quyền: chỉ owner sửa/xoá; người khác xem + fork.
**Cổng**: 10 user × 5 chiến lược hiển thị; mọi số trên thẻ = cache Nautilus thật (đối chiếu 3 mẫu bằng chạy lại); user mới thấy mẫu, sau khi lưu 1 chiến lược thì mẫu ẩn; fork chạy được; E2E script `test/scripts/e2e_edu.py` exit 0. → **Education DONE.**

## T4 — Hybrid biên dịch (chuyên gia)
- `alpha/route.py`: `classify(code) -> "dsl" | "native"`: native khi code là class kế thừa `nautilus_trader...Strategy`, hoặc dùng cấu trúc ngoài DSL (state machine nhiều lệnh, order book, nhiều instrument phụ thuộc nhau, quản lý lệnh tuỳ ý); DSL khi khớp hợp đồng DSL. Trả lý do (`reasons[]`) để UI hiện.
- Compile native: kiểm import whitelist (nautilus_trader, numpy, pandas, math…), cấm os/subprocess/socket/open; chạy trong job subprocess (run_limited). Lỗi rõ ràng.
- Coin Studio: badge "Biên dịch: Nora DSL / Nautilus native" + lý do; Education luôn DSL (code phức tạp → gợi ý chuyển sang Coin).
- Cùng hợp đồng kết quả (đã thống nhất ở P16: `nautilus/results.py`).
**Cổng**: bộ 20 mẫu phân loại đúng (10 DSL, 10 native, gồm ca biên); code cấm import bị chặn; native multi-order chạy ra kết quả + benchmark; test_nautilus_native xanh.

## T5 — Paper/testnet OKX đồng bộ backtest
- `nautilus/live.py`: TradingNode + OKX adapter (demo), chạy CHÍNH các Strategy class của backtest; tín hiệu tăng dần (`SignalActor` gọi lại `signal/`) — cùng một định nghĩa với backtest.
- Job `live_paper` / `live_testnet` (keys `~/.config/nora/okx.env`), trạng thái + lệnh ghi `data/live/<mode>/`.
- Đối chiếu: replay cùng khoảng thời gian bằng backtest → `compare_events` (đã có ở metrics/trades) → báo cáo lệch (giá khớp bps, thời điểm, lệnh thiếu/thừa).
- UI Coin `/coin/live`: trạng thái bot, PnL thật vs backtest.
**Cổng**: tín hiệu tăng dần == tín hiệu cả mảng (bit-identical); ≥30 cặp lệnh demo, lệch giá trung vị ≤ ngưỡng (chốt khi xem dữ liệu), 0 lệnh thiếu/thừa không giải thích được. Cần anh duyệt trước khi bật demo.

---
## Quy trình mỗi tiến độ
1. Opus gửi brief (file, việc, tiêu chí) đầu tiến độ.
2. Anh làm → báo xong.
3. Opus chạy cổng (test nhắm đích + 1 full suite cuối tiến độ) → báo đạt / lỗi cụ thể.
4. Commit.
