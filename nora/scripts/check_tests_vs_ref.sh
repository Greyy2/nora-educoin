#!/bin/bash
# Dùng: ./check_tests_vs_ref.sh <git-ref>
# Chạy test HIỆN TẠI trên code tại <git-ref> để xác nhận test bắt được lỗi cũ
# (lưu ý: sau khi tái cấu trúc package, import của test dùng đường dẫn mới nên <git-ref> phải từ commit tái cấu trúc trở đi)
set -e
REF=${1:?git ref required}
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${NORA_PYTHON:-/home/vmc03/.venvs/nora/bin/python}"
TMP=$(mktemp -d)

echo "[check_tests_vs_ref] REF=$REF TMP=$TMP"

# Extract backend code at the given ref
git -C "$ROOT" archive "$REF" nora/backend | tar -x -C "$TMP"

# Copy current tests (the new ones we want to verify catch old bugs)
cp -r "$ROOT/nora/test" "$TMP/nora/"
rm -rf "$TMP/nora/test/__pycache__"

# Use python3.11 with PYTHONPATH pointing to extracted code
cd "$TMP/nora"
PYTHONPATH=. "$PY" \
  -m pytest test -q -rA -p no:cacheprovider 2>&1 | grep -E "^(PASSED|FAILED|ERROR|test/)" || true

echo "[done] cleanup $TMP"
rm -rf "$TMP"
