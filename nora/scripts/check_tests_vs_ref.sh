#!/bin/bash
# Dùng: ./check_tests_vs_ref.sh <git-ref>
# Chạy test HIỆN TẠI trên code tại <git-ref> để xác nhận test bắt được lỗi cũ
set -e
REF=${1:?git ref required}
ROOT=/home/ubuntu/norabt
TMP=$(mktemp -d)

echo "[check_tests_vs_ref] REF=$REF TMP=$TMP"

# Extract backend code at the given ref
git -C "$ROOT" archive "$REF" nora/backend | tar -x -C "$TMP"

# Copy current tests (the new ones we want to verify catch old bugs)
cp -r "$ROOT/nora/tests" "$TMP/nora/"
rm -rf "$TMP/nora/tests/__pycache__"

# Use python3.11 with PYTHONPATH pointing to extracted code
cd "$TMP/nora"
PYTHONPATH=. /home/ubuntu/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11 \
  -m pytest tests -q -rA -p no:cacheprovider 2>&1 | grep -E "^(PASSED|FAILED|ERROR|tests/)" || true

echo "[done] cleanup $TMP"
rm -rf "$TMP"
