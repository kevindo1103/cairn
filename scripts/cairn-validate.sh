#!/usr/bin/env bash
# cairn-validate.sh — Cairn docs reference checker (C-6 Tier-2 signal)
#
# Bắt broken cross-reference trong docs TRƯỚC khi drift tích luỹ —
# thay phần check thủ công tương ứng trong Weekly Review.
#
# Checks:
#   1. Markdown link trỏ tới file local không tồn tại (fail)
#   2. {{PLACEHOLDER}} còn sót trong *.md (warning; --strict → fail)
#      → Cairn template repo: placeholder là chủ đích, chạy KHÔNG --strict.
#      → Adopting project: PHẢI chạy --strict (sau bootstrap không được sót).
#
# Usage:
#   bash scripts/cairn-validate.sh            # cairn repo / dev check
#   bash scripts/cairn-validate.sh --strict   # adopting projects (CI khuyến nghị)
#
# Exit: 0 = pass · 1 = có lỗi

set -uo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

STRICT=0
[ "${1:-}" = "--strict" ] && STRICT=1

TMP_ERR=$(mktemp)
TMP_WARN=$(mktemp)
trap 'rm -f "$TMP_ERR" "$TMP_WARN"' EXIT

# ---------- 1. Broken local markdown links ----------
# Quét mọi *.md (trừ node_modules/venv). Link http/https/mailto/#anchor bỏ qua.
# Path resolve theo: (a) relative tới file chứa link, (b) relative tới repo root.
while IFS= read -r file; do
  dir=$(dirname "$file")
  grep -noE '\]\([^)]+\)' "$file" 2>/dev/null | while IFS=: read -r line raw; do
    target=${raw#*(}
    target=${target%)}
    case "$target" in
      http://*|https://*|mailto:*|\#*) continue ;;
    esac
    path=${target%%#*}   # bỏ phần #anchor
    path=${path%% *}     # bỏ title sau space: [x](file.md "title")
    [ -z "$path" ] && continue
    case "$path" in
      *'{{'*|*'<'*) continue ;;   # placeholder/ví dụ trong template — không check
    esac
    if [ ! -e "$dir/$path" ] && [ ! -e "$path" ]; then
      echo "  $file:$line → ($target)" >> "$TMP_ERR"
    fi
  done
done < <(find . \( -path ./node_modules -o -path ./venv -o -path ./.git \) -prune -o -name '*.md' -print)

# ---------- 2. Leftover {{PLACEHOLDER}} ----------
grep -rnoE '\{\{[A-Z][A-Z0-9_]*\}\}' --include='*.md' . 2>/dev/null \
  | grep -v -e node_modules -e '^\./venv' \
  | sed 's/^/  /' >> "$TMP_WARN" || true

# ---------- Report ----------
FAIL=0

if [ -s "$TMP_ERR" ]; then
  echo "✗ BROKEN LINKS ($(wc -l < "$TMP_ERR")):"
  cat "$TMP_ERR"
  FAIL=1
else
  echo "✓ Links: OK"
fi

if [ -s "$TMP_WARN" ]; then
  N=$(wc -l < "$TMP_WARN")
  if [ "$STRICT" = "1" ]; then
    echo "✗ PLACEHOLDERS còn sót ($N) — adopting project phải điền hết khi bootstrap:"
    cat "$TMP_WARN"
    FAIL=1
  else
    echo "⚠ Placeholders: $N (OK cho template repo; adopting project chạy --strict)"
  fi
else
  echo "✓ Placeholders: none"
fi

exit $FAIL
