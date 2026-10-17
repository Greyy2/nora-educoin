"""Seed Education: 10 tác giả x 5 chiến lược (50 mẫu) + 1 user mới không chiến lược.

Số liệu = kết quả Nautilus THẬT đã cache (alpha.store.sample_lookup); thiếu cache -> báo lỗi, không lưu bản không kết quả.
Idempotent: chạy lại không nhân đôi user/alpha (nhận diện bằng handle và sample_key).
Phân công tất định: sắp mẫu theo từng category (thứ tự trong samples.json, 10 mẫu/category); tác giả thứ i (0..9)
nhận mẫu thứ i của MỖI category -> mỗi người đúng 5 mẫu, đủ 5 category, độ khó trộn theo vị trí.

Chạy: ops/run_limited.sh --no-lock -- test/scripts/seed_edu_users.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from backend import users
from backend.alpha import store

# (handle, tên hiển thị, giới thiệu). Tác giả đầu là user thật đã có sẵn (tạo nếu chưa có).
AUTHORS = [
    ("vinh", "vinh", "trade"),
    ("trend_hunter", "Thợ săn xu hướng", "Đi theo xu hướng chính, cắt lỗ gọn."),
    ("mean_revert_mai", "Mai Hồi Quy", "Mua vùng quá bán, bán khi giá về trung bình."),
    ("breakout_nam", "Nam Bứt Phá", "Chờ giá phá vỡ vùng đi ngang rồi mới vào lệnh."),
    ("confluence_lan", "Lan Đa Chỉ Báo", "Chỉ vào lệnh khi nhiều chỉ báo cùng đồng thuận."),
    ("risk_guard_hung", "Hùng Quản Trị Rủi Ro", "Ưu tiên điểm thoát lệnh và kiểm soát sụt giảm."),
    ("quant_thao", "Thảo Định Lượng", "Thích thống kê: z-score, độ lệch chuẩn, hồi quy."),
    ("swing_minh", "Minh Lướt Sóng", "Bắt các nhịp sóng trung hạn trên khung ngày."),
    ("momentum_duc", "Đức Động Lượng", "Theo đà tăng giá và khối lượng."),
    ("calm_trader_an", "An Điềm Tĩnh", "Giao dịch ít, kỷ luật, đều tay."),
]
VIEWER = ("nguoi_xem", "Người xem", "")


def assignment(samples):
    """{handle: [sample, ...]} tất định: tác giả i nhận mẫu thứ i của mỗi category."""
    cats = {}
    for s in samples:
        cats.setdefault(s["category"], []).append(s)
    out = {h: [] for h, _, _ in AUTHORS}
    for lst in cats.values():
        for i, s in enumerate(lst):
            out[AUTHORS[i % len(AUTHORS)][0]].append(s)
    return out


def _ensure_user(handle, name, bio, role):
    u = users.get_by_handle(handle)
    return u or users.create_user(handle, name, bio=bio, role=role)


def seed(log=print):
    samples = store._education_samples()
    plan = assignment(samples)
    created_alphas = 0
    for handle, name, bio in AUTHORS:
        u = _ensure_user(handle, name, bio, "learner" if handle == "vinh" else "demo")
        have = {a.get("sample_key") for a in store.list_user_alphas(owner_id=u["id"]) if a.get("sample_key")}
        for s in plan[handle]:
            if s["key"] in have:
                continue
            result = store.sample_lookup(s)
            if result is None:
                raise SystemExit(f"Thiếu kết quả cache cho mẫu {s['key']}: chạy education_warm trước")
            store.save_user_alpha_from_result(u["id"], s["code"], s["name"], result, source="seed", sample_key=s["key"], note=s.get("summary", ""))
            created_alphas += 1
        log(f"@{handle}: {len(plan[handle])} mẫu")
    _ensure_user(*VIEWER, "learner")
    log(f"Đã thêm {created_alphas} alpha mới")
    return created_alphas


if __name__ == "__main__":
    seed()
