# Bộ tài liệu BMAD của Nora

Bộ tài liệu theo phương pháp BMAD (Business, Model, Architecture, Delivery): yêu cầu sản phẩm, kiến trúc và đặc tả kỹ thuật, epic, story có tiêu chí chấp nhận và bằng chứng.
Viết bằng tiếng Việt; tên kỹ thuật (file, hàm, tham số, trạng thái) giữ nguyên tiếng Anh. Khớp code tại commit `a3202c9` (nhánh `fix/pipeline-audit`), cập nhật 01/10/2026.

## Mục lục

| File | Nội dung | Khi nào đọc |
|---|---|---|
| [prd.md](prd.md) | Vấn đề, tầm nhìn, người dùng, mục tiêu và chỉ số, phạm vi, FR/NFR, ràng buộc, rủi ro và câu hỏi mở | Bắt đầu phiên làm việc; trước khi đề xuất tính năng |
| [architecture.md](architecture.md) | Sơ đồ ngữ cảnh, bản đồ package, đặc tả chính xác (dữ liệu, tín hiệu, engine, danh mục, WFA, Monte Carlo, đường ống alpha, job, API, UI, vận hành, test) | Trước khi sửa code; khi cần ngữ nghĩa chính xác |
| [epics.md](epics.md) | 11 epic, 70 story, bảng trạng thái tổng | Chọn việc tiếp theo |
| [sprint-status.yaml](sprint-status.yaml) | Trạng thái máy đọc được của epic và story | Công cụ, script, tác tử |
| [stories/](stories/) | Mỗi story một file `E<n>-S<m>-<slug>.md` | Làm hoặc xác minh một story |
| [legacy/](legacy/README.md) | Tài liệu BMAD giai đoạn DEX (01_ đến 04_, waves/), chỉ để tra cứu lịch sử | Chỉ khi cần lịch sử |

Tài liệu chuyên đề (ở `nora/docs/`): [ui_contract.md](../ui_contract.md) (hợp đồng API cho UI), [alpha_pipeline.md](../alpha_pipeline.md), [signals_strategies.md](../signals_strategies.md),
[data_layout.md](../data_layout.md), [knowledge_base/](../knowledge_base/) (luật thép và lý thuyết, còn hiệu lực).

## Quy ước trạng thái

Story và epic dùng cùng một bộ giá trị:

| Giá trị | Nghĩa |
|---|---|
| `backlog` | Chưa làm, chưa đủ điều kiện bắt đầu |
| `ready` | Đủ điều kiện bắt đầu (phụ thuộc đã xong, AC đã duyệt) |
| `in-progress` | Đang làm |
| `review` | Đã làm xong, chờ kiểm bằng chứng |
| `done` | Mọi AC đã kiểm (bằng test hoặc số đo) và có Evidence |

Trạng thái epic: `done` khi mọi story `done`; `in-progress` khi có story đang làm hoặc vừa có story `done` vừa có story `backlog`; `backlog` khi mọi story `backlog`.
Ký hiệu task trong story: `[x]` đã xong, `[ ]` chưa làm, `[>]` đã chuyển sang story khác (ghi rõ story nào), không chặn `done`.

Quy tắc về bằng chứng: story `done` phải có mục **Evidence** gồm commit (hash từ `git log`), test chứng minh (tên test hoặc file) và số đo (nguồn nằm trong repo, ví dụ `data/alphas/*.json`, `data/_cache/...`, message commit).
Số chưa đo ghi "chưa đo", không đoán. Không nới gate để story "đạt": nếu kết quả không đạt thì story `done` ở chỗ ghi nhận trung thực (xem E5-S5), việc cải thiện là story khác.

## Cách cập nhật khi xong một story

1. **File story:** đổi dòng `- **Trạng thái:**`, tick `[x]` các task, điền Evidence (commit, test, số đo), thêm dòng vào Change Log (ngày, thay đổi, commit).
   Đi `in-progress → review → done`; không nhảy từ `backlog` sang `done` mà không có Evidence.
2. **`sprint-status.yaml`:** đổi giá trị của story đó, cập nhật `summary`, `last_updated`, `baseline_commit`.
3. **`epics.md`:** đổi dòng của story trong bảng epic, cập nhật cột "Story (done / tổng)" và dòng "Tổng"; nếu mọi story của epic `done` thì đổi trạng thái epic (ở bảng tổng, tiêu đề epic và `sprint-status.yaml`).
4. **`prd.md`:** nếu story đổi trạng thái một FR (cột TT) hoặc đóng một rủi ro/câu hỏi (mục 8), cập nhật tại đó.
5. **`architecture.md`:** nếu hành vi hoặc hằng số đổi, sửa phần đặc tả tương ứng; số test (mục 13) nếu đổi.
6. **Hợp đồng và test:** đổi payload API thì sửa `nora/docs/ui_contract.md` và test backend trước; đổi ngữ nghĩa engine thì golden phải đổi có chủ đích (E3-S8) và ghi lý do vào Change Log.
7. Chạy kiểm tra nhất quán (dưới đây) rồi mới coi là xong.

Thêm story mới: chọn epic, lấy số `S` kế tiếp, tạo `stories/E<n>-S<m>-<slug>.md` theo cấu trúc của các story hiện có (Story, Acceptance Criteria dạng Given/When/Then đánh số, Tasks, Dev Notes, Evidence, Change Log), thêm vào `epics.md` và `sprint-status.yaml`.

## Kiểm tra nhất quán

Chạy từ gốc repo; in lỗi nếu trạng thái trong file story, `sprint-status.yaml` và `epics.md` không khớp (cần PyYAML):

```bash
python3 - <<'PY'
import glob, os, re, yaml
base = "nora/docs/bmad"
y = yaml.safe_load(open(f"{base}/sprint-status.yaml", encoding="utf-8"))
epics_md = open(f"{base}/epics.md", encoding="utf-8").read()
bad, total = [], 0
for eid, e in y["epics"].items():
    for key, st in e["stories"].items():
        total += 1
        txt = open(f"{base}/stories/{key}.md", encoding="utf-8").read()
        m = re.search(r"^- \*\*Trạng thái:\*\* (\S+)", txt, re.M)
        if not m or m.group(1) != st: bad.append(f"{key}: file={m and m.group(1)} yaml={st}")
        if not re.search(rf"\(stories/{re.escape(key)}\.md\) \| .* \| {re.escape(st)} \|", epics_md):
            bad.append(f"{key}: epics.md không khớp {st}")
        if st == "done" and "## Evidence" not in txt: bad.append(f"{key}: thiếu Evidence")
files = {os.path.basename(p)[:-3] for p in glob.glob(f"{base}/stories/*.md")}
listed = {k for e in y["epics"].values() for k in e["stories"]}
bad += [f"file không có trong yaml: {k}" for k in sorted(files - listed)]
print(f"{total} story;", "OK" if not bad else "LỖI"); print("\n".join(bad))
PY
```

## Thứ tự đọc cho phiên làm việc mới

1. [prd.md](prd.md) mục 3, 7, 8 (mục tiêu, ràng buộc, rủi ro) và [knowledge_base/02_boss_mandates_and_rulebase.md](../knowledge_base/02_boss_mandates_and_rulebase.md).
2. [epics.md](epics.md) và [sprint-status.yaml](sprint-status.yaml): việc đang làm và việc kế tiếp.
3. [architecture.md](architecture.md) phần liên quan đến code sắp đụng; đặc biệt mục 12 (vận hành) trước khi chạy job nặng: **mọi lệnh nặng phải qua `backend/ops/run_limited.sh`**.
4. Story cần làm trong `stories/`.

Ràng buộc bất biến khi sửa: golden test phải giữ bit-identical (trừ khi chủ đích đổi ngữ nghĩa); không nới gate; không chạm `frontend/src/v2` khi tác tử UI đang làm E8-S6 mà không thống nhất.
