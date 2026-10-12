# P17 — Lộ trình 5 tiến độ (2026-10-12)

Vai trò: **anh làm** từng tiến độ; **Opus** phân tích, viết brief, test cổng. Mỗi tiến độ xong = cổng xanh + commit.
Ưu tiên số 1: **Education hoàn chỉnh** (T1+T2).

## Lộ trình gốc → trạng thái
| # | Bước | Trạng thái |
|---|---|---|
| 1 | Hoàn thiện UI | ✅ (R4 badge/cảnh báo/Chuẩn-Nhanh, dọn Studio) |
| 2 | Đồng bộ tham số + code chiến lược chuẩn quốc tế / TradingView | ✅ (theo anh) |
| 3 | Kiến trúc gọn chuẩn | ✅ lõi (1 engine Nautilus, 1 adapter kết quả, gỡ số giả). Phần còn lại → T4 |
| 4 | Hybrid biên dịch: Education = Nora DSL; Chuyên gia = tự nhận code phức tạp → biên dịch Nautilus native | T3 |
| 5 | Paper/testnet OKX đồng bộ backtest | T5 |
| 6 | Home kiểu sova → 2 hệ thống song song Education / Coin | T1 |
| 7 | User: profile, chiến lược của mình, market theo user, 10 user × 50 mẫu, ẩn mẫu khi đã có chiến lược | T1–T2 |

## Mô hình sản phẩm
```
/                Home (preview 2 hệ thống: thẻ + số liệu thật + nút vào)
├── /edu/*       EDUCATION (layout + nav riêng)
│     /edu                 Market: lưới user (avatar, số chiến lược, lãi tốt nhất)
│     /edu/u/:handle       Profile user: chiến lược của user đó (thẻ: PnL/MDD/Sharpe thật)
│     /edu/s/:id           Xem chiến lược (code + kết quả), nút "Sao chép về của tôi"
│     /edu/studio          Viết/chạy/lưu (Nora DSL, form đơn giản)
│     /edu/me              Profile của tôi
└── /coin/*      COIN (hệ thống hiện tại: Alpha, Funnel, Book, Backtest, Live…)
```
Luật mẫu: user mới (0 chiến lược) → Studio mở sẵn mẫu, thấy danh sách mẫu; khi user có ≥1 chiến lược đã lưu → ẩn mục "Mẫu" (vẫn xem được chiến lược của user khác qua Market).

---

## T1 — Home + khung Education + User (nền)
**Backend**
- `backend/users.py` (1 file): User {id, handle, display_name, avatar, bio, created_at}; lưu `data/users/<id>.json`; phiên đăng nhập đơn giản: cookie `nora_uid` ký HMAC (secret `~/.config/nora/app.env`), không mật khẩu ở bản đầu (chọn/tạo user). Routes `routes/users.py`: `GET/POST /api/users`, `GET /api/users/{handle}`, `GET/POST /api/me`, `PUT /api/me` (profile).
- User alpha có `owner_id`: sửa `optimize/book/registry.save_user_alpha/list_user_alphas` thêm `owner_id`, lọc theo owner; `GET /api/users/{handle}/strategies`.
- Fix suite: các test đang fail ở baseline (danh sách ở `scratchpad/baseline.log` — Opus gửi kèm brief).
**Frontend**
- `pages/Home.jsx` (tham chiếu sova `frontend/src/pages/Home`: tiêu đề, 2 thẻ hệ thống, số liệu thật từ API, nút vào). Route `/` = Home.
- Tách layout: `layout/EduLayout.jsx`, `layout/CoinLayout.jsx` (Shell hiện tại → Coin, mọi route cũ chuyển dưới `/coin/*`, redirect đường cũ).
- Chọn/tạo user (modal), avatar góc phải, `/edu/me`.
**Cổng (Opus test)**: full suite 0 failed; `/` render 2 thẻ; tạo user → cookie → `/api/me` đúng; route cũ redirect; vite build sạch.

## T2 — Education hoàn chỉnh (Market + seed + mẫu)
- Seed: script `test/scripts/seed_edu_users.py` tạo 10 user (tên/handle/avatar/bio tiếng Việt), chia 50 mẫu (5/user, trộn category/difficulty), lưu thành user alpha có owner.
- Kết quả THẬT: chạy job `education_warm` (mọi mẫu qua Nautilus) → cache; thẻ chỉ hiện số khi có cache (đã làm ở P16).
- Market `/edu`: lưới user (số chiến lược, best Sharpe/PnL thật); `/edu/u/:handle`: chiến lược của user; `/edu/s/:id`: code + CustomResult; "Sao chép về của tôi" (fork → owner = tôi, chạy lại).
- Studio Edu: form đơn giản (Nora DSL), lưu → owner = tôi; luật ẩn mẫu khi đã có ≥1 chiến lược.
- Quyền: chỉ owner sửa/xoá; người khác xem + fork.
**Cổng**: 10 user × 5 chiến lược hiển thị; mọi số trên thẻ = cache Nautilus thật (đối chiếu 3 mẫu bằng chạy lại); user mới thấy mẫu, sau khi lưu 1 chiến lược thì mẫu ẩn; fork chạy được; E2E script `test/scripts/e2e_edu.py` exit 0. → **Education DONE.**

## T3 — Hybrid biên dịch (chuyên gia)
- `alpha/route.py`: `classify(code) -> "dsl" | "native"`: native khi code là class kế thừa `nautilus_trader...Strategy`, hoặc dùng cấu trúc ngoài DSL (state machine nhiều lệnh, order book, nhiều instrument phụ thuộc nhau, quản lý lệnh tuỳ ý); DSL khi khớp hợp đồng DSL. Trả lý do (`reasons[]`) để UI hiện.
- Compile native: kiểm import whitelist (nautilus_trader, numpy, pandas, math…), cấm os/subprocess/socket/open; chạy trong job subprocess (run_limited). Lỗi rõ ràng.
- Coin Studio: badge "Biên dịch: Nora DSL / Nautilus native" + lý do; Education luôn DSL (code phức tạp → gợi ý chuyển sang Coin).
- Cùng hợp đồng kết quả (đã thống nhất ở P16: `nautilus/results.py`).
**Cổng**: bộ 20 mẫu phân loại đúng (10 DSL, 10 native, gồm ca biên); code cấm import bị chặn; native multi-order chạy ra kết quả + benchmark; test_nautilus_native xanh.

## T4 — Coin hoàn chỉnh + dứt kiến trúc
- Chuyển package theo cây đích (p16 §4): `optimize/process` → `jobs/`; `alpha/dsl` → `signal/` + `alpha/plan.py`; `metrics/regime` bỏ import nautilus.
- Routes mỏng: `post_mc` gate, `_nav`, `_build_meta` xuống module; meta thêm `engine.default_exec_mode`, `frames.defaults`; `BacktestRequest.run_frame`.
- `backend/data.py` thay `crawl/` (p16 §5: D1–D6): catalog là nguồn duy nhất, archive pkl.
**Cổng**: grep import cấm = 0; snapshot `p16_engine_snapshot --check` IDENTICAL; signal parity; full suite xanh; p9_ledger --dups sạch.

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
