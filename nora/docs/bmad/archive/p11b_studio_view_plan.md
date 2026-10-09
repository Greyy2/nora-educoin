# P11b — Đồng nhất view /alpha/create và /education (plan + todo)

Quyết định của anh (2026-10-08):
- Hai trang **cùng một view**: trái = code; phải = **chỉ 2 tab: "Mẫu" và "Kết quả"**.
- "Mẫu" giống hệt nhau (cùng component, cùng nguồn `GET /api/studio/education/samples`).
- Chạy cùng một engine, cùng đường chạy (`POST /custom/backtest` → job tạm → kết quả).
- Khác biệt duy nhất: ở /education, sau khi chạy xong, tab "Kết quả" có **highlight giải thích từng mục kết quả** (mỗi chỉ số / biểu đồ / bảng) — sinh từ chiến lược + số của chính lần chạy đó (backend, tất định).

## Hiện trạng (sau lượt sửa của công cụ khác)
- Bố cục 2 cột đã chung, nhưng cột phải có quá nhiều tab: results, explain, data, features, operators, samples (+ guide ở education) → bỏ bớt.
- Tab "explain" + `ResultExplain.jsx` dùng ngưỡng tự đặt trong JS → sai quy tắc (đang được sửa thành giải thích từ backend).
- Tra cứu dữ liệu/chỉ báo/toán tử: đã có trong trình soạn (gợi ý, hover, chip RUN/ADAPT/REJECT) → không cần tab riêng.

## Kiến trúc đích
```
StudioWorkspace (dùng chung)          props: mode = "create" | "education"
├─ Trái: EditorPane                    tab file, tên, chip trạng thái, RunSettings, Kiểm tra, Lưu, Chạy, CodeEditor (+assist)
└─ Phải: 2 tab
   ├─ "Mẫu":   SamplesPane             danh sách 50 mẫu (lọc nhóm/độ khó) → mở vào tab file mới
   └─ "Kết quả": CustomResult          giống hệt 2 trang
                 explain={mode==="education" ? notes : null}
                 → mỗi mục có ô highlight ghi chú (chỉ hiện khi có notes)
```
- `pages/CreateAlpha.jsx` = `<StudioWorkspace mode="create"/>`; `pages/Education.jsx` = `<StudioWorkspace mode="education"/>`. Mọi state (tab file, chạy, lưu, cảnh báo rời trang) nằm trong StudioWorkspace — một bản.
- Lưu chiến lược: cả hai trang dùng cùng SaveStrategyModal (lưu alpha kèm kết quả).

## Backend giải thích (tất định)
`POST /api/studio/strategies/explain` (mở rộng, không endpoint mới nếu đủ) nhận `{code, result_ref}` → trả `notes` gắn theo mục của kết quả:
`{summary, metrics:{sharpe, cagr, mdd_pct, win_rate_pct, profit_factor, trades,…}, equity, drawdown, trades, exits, per_symbol, yearly, stages:{train,test}}`.
Mỗi ghi chú = sự kiện đo được từ result (số, so sánh train/test, lý do thoát lệnh chiếm bao nhiêu %, tài sản/năm đóng góp) + liên hệ với logic code (điều kiện vào/ra/dừng đọc từ IR). Không có ngưỡng "tốt/xấu" tự đặt; không câu lý thuyết chung.

## TODO
1. [ ] (đang chạy) Backend: `notes` theo mục từ result + IR; test tất định (cùng code + result → cùng notes).
2. [ ] (đang chạy) `CustomResult` nhận prop `explain` → render highlight inline cạnh từng mục; bỏ tab/`ResultExplain` kiểu ngưỡng JS.
3. [ ] Tạo `components/studio/StudioWorkspace.jsx` gộp phần chung của CreateAlpha + Education; 2 page chỉ còn 1 dòng render.
4. [ ] Cột phải chỉ 2 tab "Mẫu" / "Kết quả"; xoá tab data/features/operators/explain/guide (nội dung tra cứu đã có trong assist của trình soạn; hướng dẫn ngắn → placeholder của editor khi trống).
5. [ ] `SamplesPane` dùng chung (nguồn API samples; lọc; mở mẫu vào tab file mới).
6. [ ] Education: sau khi chạy xong gọi explain → truyền notes vào CustomResult; Create: không gọi.
7. [ ] Giữ: cảnh báo rời trang khi chưa lưu, lưu phiên bản alpha (`alpha_id`), chip assist, Ctrl+Enter chạy.
8. [ ] Build + kiểm E2E (playwright): 2 trang cùng DOM cấu trúc trừ highlight; mở mẫu → chạy → kết quả; education có highlight từng mục; create không có.
