"""Sinh tài liệu docs/education/api.md tự động từ FastAPI app OpenAPI schema.

Đảm bảo bảng API luôn khớp 100% với code thật, không lệch schema hay tham số.
Chạy: ops/run_limited.sh --no-lock -- test/scripts/gen_edu_api_doc.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from backend.main import app

TARGET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "education", "api.md")

# Các nhóm endpoint liên quan mật thiết tới Education & Studio
EDU_TAGS = {"edu", "users", "custom", "alphas", "live"}
EDU_PREFIXES = ("/api/edu", "/api/users", "/api/me", "/api/studio/custom", "/api/studio/alphas", "/api/studio/live", "/api/studio/strategies/compile")


def generate():
    schema = app.openapi()
    paths = schema.get("paths", {})
    
    rows = []
    for path, methods in sorted(paths.items()):
        if not any(path.startswith(prefix) for prefix in EDU_PREFIXES):
            continue
        for method, spec in methods.items():
            method_upper = method.upper()
            summary = spec.get("summary") or spec.get("description") or "—"
            summary_clean = summary.split("\n")[0].strip()
            tags = ", ".join(spec.get("tags", []))
            
            # Tham số / body
            has_body = "requestBody" in spec
            responses = ", ".join(sorted(spec.get("responses", {}).keys()))
            
            rows.append({
                "method": method_upper,
                "path": path,
                "summary": summary_clean,
                "has_body": "Có" if has_body else "Không",
                "responses": responses,
            })

    content = [
        "# Danh Mục API Hệ Thống Education & Studio",
        "",
        "> **Lưu ý**: Tài liệu này được sinh tự động từ lược đồ OpenAPI (`/openapi.json`) của backend FastAPI.",
        "",
        "## Bảng Endpoint Cốt Lõi",
        "",
        "| Phương thức | Đường dẫn (Path) | Mô tả chức năng | Request Body | Mã phản hồi |",
        "|:---:|---|---|:---:|:---:|",
    ]

    for r in rows:
        content.append(f"| `{r['method']}` | `{r['path']}` | {r['summary']} | {r['has_body']} | `{r['responses']}` |")

    content.extend([
        "",
        "## Hướng Dẫn Xác Thực (Authentication)",
        "",
        "- Hệ thống sử dụng cookie định danh `nora_uid` được ký số bởi máy chủ.",
        "- Khi gọi `POST /api/users` hoặc `POST /api/me/login`, cookie `nora_uid` sẽ được thiết lập tự động trong phản hồi (`Set-Cookie`).",
        "- Các endpoint tạo mới hoặc sao chép chiến lược (`/fork`, `/user`) yêu cầu gửi kèm cookie này.",
        "",
    ])

    os.makedirs(os.path.dirname(TARGET_FILE), exist_ok=True)
    with open(TARGET_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(content))

    print(f"Đã sinh {len(rows)} endpoint vào {TARGET_FILE}")


if __name__ == "__main__":
    generate()
