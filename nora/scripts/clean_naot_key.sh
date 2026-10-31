#!/usr/bin/env bash
# ============================================================
# clean_naot_key.sh
# Xóa dấu vết NAOT/Anthropic hardcode khỏi server
# Dùng cho: "all servers" theo yêu cầu của team
# Usage: bash clean_naot_key.sh [--dry-run]
# ============================================================
set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

log()  { echo "[INFO]  $*"; }
warn() { echo "[WARN]  $*"; }
ok()   { echo "[OK]    $*"; }

run() {
  if $DRY_RUN; then
    echo "[DRY-RUN] $*"
  else
    eval "$@"
  fi
}

echo "=========================================="
echo "  NAOT Key Cleanup Script"
echo "  Host: $(hostname)"
echo "  Time: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
$DRY_RUN && warn "DRY-RUN mode — khong thay doi thuc su"
echo "=========================================="
echo ""

# -----------------------------------------------------------
# 1. Xóa block hardcode khỏi shell config files
# -----------------------------------------------------------
log "Buoc 1: Don shell config files..."
SHELL_FILES=("$HOME/.bashrc" "$HOME/.profile" "$HOME/.bash_profile" "$HOME/.zshrc" "$HOME/.zprofile")

for f in "${SHELL_FILES[@]}"; do
  [[ -f "$f" ]] || continue
  if grep -qE "naot|ANTHROPIC_BASE_URL|ANTHROPIC_AUTH_TOKEN" "$f" 2>/dev/null; then
    warn "Tim thay config trong: $f"
    run "sed -i '/^# NAOT API Configuration/,/^export OPENAI_API_KEY=.*naot.*/d' '$f'"
    run "sed -i '/naot\\.me/d; /ANTHROPIC_BASE_URL.*naot/d; /ANTHROPIC_AUTH_TOKEN.*sk-naot/d; /sk-naot/d' '$f'"
    ok "Cleaned: $f"
  else
    ok "Clean (khong can xu ly): $f"
  fi
done

# -----------------------------------------------------------
# 2. Xóa backup files cũ có chứa key
# -----------------------------------------------------------
log ""
log "Buoc 2: Xoa backup files chua key..."
find "$HOME" -maxdepth 2 -name "*.bak" 2>/dev/null | while read -r bak; do
  if grep -qE "sk-naot|naot\.me" "$bak" 2>/dev/null; then
    warn "Xoa backup co key: $bak"
    run "rm -f '$bak'"
  fi
done
ok "Done"

# -----------------------------------------------------------
# 3. Clean bash_history
# -----------------------------------------------------------
log ""
log "Buoc 3: Lam sach bash_history..."
HIST="$HOME/.bash_history"
if [[ -f "$HIST" ]]; then
  BEFORE=$(wc -l < "$HIST")
  run "sed -i '/naot\|ANTHROPIC_BASE_URL\|ANTHROPIC_AUTH_TOKEN\|ANTHROPIC_API_KEY\|OPENAI_BASE_URL\|OPENAI_API_KEY\|sk-naot/Id' '$HIST'"
  AFTER=$(wc -l < "$HIST" 2>/dev/null || echo "$BEFORE")
  ok "bash_history: xoa $((BEFORE - AFTER)) dong nhay cam"
fi

# -----------------------------------------------------------
# 4. Unset ENV vars trong session hiện tại
# -----------------------------------------------------------
log ""
log "Buoc 4: Unset ENV vars..."
for v in ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY OPENAI_BASE_URL OPENAI_API_KEY; do
  if [[ -n "${!v:-}" ]]; then
    warn "Unsetting: $v"
    unset "$v" 2>/dev/null || true
  fi
done
ok "ENV vars cleared"

# -----------------------------------------------------------
# 5. Scan .env files trong project directories
# -----------------------------------------------------------
log ""
log "Buoc 5: Scan .env files trong projects..."
for dir in "$HOME" "/app" "/srv" "/opt/app" "/var/app"; do
  [[ -d "$dir" ]] || continue
  find "$dir" -maxdepth 5 \( -name ".env" -o -name ".env.*" -o -name "*.env" \) \
    ! -path "*/node_modules/*" ! -path "*/.git/*" 2>/dev/null | while read -r envfile; do
    if grep -qE "sk-naot|naot\.me|ANTHROPIC_BASE_URL.*naot" "$envfile" 2>/dev/null; then
      warn "Tim thay key trong: $envfile"
      run "sed -i 's|https://api\.naot\.me[^\"'\'']*|https://api.anthropic.com|g' '$envfile'"
      run "sed -i '/sk-naot/d' '$envfile'"
      ok "Patched: $envfile"
    fi
  done
done

# -----------------------------------------------------------
# 6. Scan Docker/systemd service files
# -----------------------------------------------------------
log ""
log "Buoc 6: Scan Docker/systemd configs..."
find "$HOME" /opt /srv -maxdepth 5 \
  \( -name "docker-compose*.yml" -o -name "docker-compose*.yaml" \) 2>/dev/null | while read -r dcf; do
  if grep -qE "sk-naot|naot\.me" "$dcf" 2>/dev/null; then
    warn "Tim thay key trong docker-compose: $dcf"
    warn "  -> Can xu ly thu cong: thay bang secret manager"
  fi
done

find /etc/systemd /lib/systemd -name "*.service" 2>/dev/null | \
  xargs grep -l "naot" 2>/dev/null | while read -r sf; do
  warn "Tim thay key trong systemd: $sf — can xu ly thu cong"
done

# -----------------------------------------------------------
# 7. AGY transcript logs (nếu có)
# -----------------------------------------------------------
log ""
log "Buoc 7: Redact AGY transcript logs..."
AGY_BRAIN="$HOME/.gemini/antigravity-ide/brain"
if [[ -d "$AGY_BRAIN" ]]; then
  COUNT=$(find "$AGY_BRAIN" -name "transcript*.jsonl" 2>/dev/null | \
    xargs grep -l "sk-naot\|naot\.me" 2>/dev/null | wc -l)
  if [[ "$COUNT" -gt 0 ]]; then
    warn "Tim thay $COUNT transcript files chua key -> redact..."
    find "$AGY_BRAIN" -name "transcript*.jsonl" | while read -r tf; do
      if grep -qE "sk-naot|naot\.me" "$tf" 2>/dev/null; then
        run "sed -i 's/sk-naot-[A-Za-z0-9_-]*/[REDACTED]/g; s/sk-naot/[REDACTED]/g; s/api\.naot\.me/[REDACTED-HOST]/g; s/naot\.me/[REDACTED-HOST]/g' '$tf'"
      fi
    done
    ok "AGY transcripts redacted"
  else
    ok "AGY transcripts: sach"
  fi
fi

# -----------------------------------------------------------
# Summary
# -----------------------------------------------------------
echo ""
echo "=========================================="
echo "  Cleanup hoan tat tren: $(hostname)"
echo ""
echo "  Viec can lam thu cong:"
echo "  1. Rotate/revoke key cu tren: https://naot.me/dashboard/api-keys"
echo "  2. Restart Docker containers / systemd services neu co"
echo "  3. Neu dung key moi -> luu vao secret manager"
echo "     KHONG hardcode lai vao shell files"
echo "=========================================="
