"""Script kiểm tra cổng chất lượng T6 cho Docs Education (check_edu_docs.py).

Kiểm tra:
1. 5 ví dụ code trong docs/education/viet-chien-luoc.md đều biên dịch thành công (compile_code).
2. Tài liệu API docs/education/api.md đầy đủ và đồng bộ.
3. Không có chữ 'sova' trong docs/education/.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from backend.alpha.compile import compile_code

DOCS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "education")
VIET_CHIEN_LUOC = os.path.join(DOCS_DIR, "viet-chien-luoc.md")
API_DOC = os.path.join(DOCS_DIR, "api.md")


def extract_python_blocks(md_path: str):
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
    pattern = r"```python\n(.*?)\n```"
    return re.findall(pattern, content, re.DOTALL)


def check_docs():
    print("=== KIỂM TRA CHẤT LƯỢNG DOCS EDUCATION (T6) ===")

    # 1. Trích xuất và kiểm tra biên dịch các khối code trong viet-chien-luoc.md
    assert os.path.isfile(VIET_CHIEN_LUOC), f"Thiếu file {VIET_CHIEN_LUOC}"
    blocks = extract_python_blocks(VIET_CHIEN_LUOC)
    print(f"1. Tìm thấy {len(blocks)} khối code trong viet-chien-luoc.md")
    assert len(blocks) >= 5, f"Phải có ít nhất 5 khối code ví dụ (hiện có {len(blocks)})"

    for idx, code in enumerate(blocks):
        try:
            prog = compile_code(code.strip())
            assert prog is not None
            print(f"   [PASS] Khối #{idx+1} ({code.strip().splitlines()[0]}) compile thành công")
        except Exception as e:
            print(f"   [FAIL] Khối #{idx+1} compile thất bại: {e}")
            raise

    # 2. Kiểm tra api.md
    assert os.path.isfile(API_DOC), f"Thiếu file {API_DOC}"
    with open(API_DOC, "r", encoding="utf-8") as f:
        api_content = f.read()
    assert len(api_content) > 500, "api.md quá ngắn"
    assert "/api/edu/market" in api_content
    print("2. [PASS] api.md đầy đủ và hợp lệ")

    # 3. Kiểm tra từ cấm 'sova'
    for root, _, files in os.walk(DOCS_DIR):
        for file in files:
            if file.endswith(".md"):
                fp = os.path.join(root, file)
                text = open(fp, "r", encoding="utf-8").read().lower()
                assert "sova" not in text, f"Phát hiện chữ 'sova' trong {fp}"
    print("3. [PASS] Không chứa chữ 'sova' trong docs/education/")

    print("=== TẤT CẢ TIÊU CHÍ CỔNG T6 ĐỀU ĐẠT CHUẨN! ===")


if __name__ == "__main__":
    check_docs()
