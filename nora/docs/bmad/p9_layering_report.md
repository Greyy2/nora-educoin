# P9 — báo cáo luật phụ thuộc (tự sinh bởi nora/test/test_layering.py, chế độ BÁO CÁO)

Không sửa tay. Sinh lại: `NORA_LAYERING_WRITE=1 PYTHONDONTWRITEBYTECODE=1 ops/run_limited.sh --no-lock -- -m pytest -q test/test_layering.py`.
Bật bắt buộc (P9.10): `NORA_LAYERING_STRICT=1`. Luật: ADR-P9 §2; ánh xạ đường dẫn hiện tại -> tầng đích: bảng `LAYER_RULES` trong test.

- Module backend: 58 · shim (`# P9-SHIM`, bỏ qua): 0 · chưa ánh xạ: 0
- **Vi phạm: 0**

## Tóm tắt theo luật

| Luật | Số vi phạm |
|---|---:|
| (không có) | 0 |

## Chi tiết
