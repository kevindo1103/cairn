#!/usr/bin/env bash
# cairn-init.sh — Bootstrap Cairn for a new project
# Usage: bash scripts/cairn-init.sh
# Run from project root after cloning the Cairn template repo.
# Cairn v0.7

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[cairn]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC}  $1"; }

echo ""
info "Cairn v0.7 init starting..."
echo ""

# ──────────────────────────────────────────────
# 1. Directory structure
# ──────────────────────────────────────────────
info "Creating directory structure..."
mkdir -p docs/teams docs/spawn .claude/skills/doc-fold-reflection

# ──────────────────────────────────────────────
# 2. DOCS_INBOX placeholder
# ──────────────────────────────────────────────
if [ ! -f docs/DOCS_INBOX.md ]; then
  info "Creating docs/DOCS_INBOX.md..."
  cat > docs/DOCS_INBOX.md << 'INBOX'
# DOCS_INBOX

> Cairn C-3 async report queue. Sessions ghi Pending; docs-editor fold → Processed.
> Canonical chỉ trên branch docs-editor. Không tạo bản copy trên branch khác.

---

## Pending

*(chưa có report)*

---

## Processed

*(chưa có)*

---

## Weekly Review Log

| Date | Reviewer | Findings | Actions |
|------|----------|----------|---------|
| *(chưa có)* | | | |
INBOX
else
  warn "docs/DOCS_INBOX.md already exists — skipping."
fi

# ──────────────────────────────────────────────
# 3. Canonical docs skeleton placeholders
# ──────────────────────────────────────────────
for doc in MASTER_BRD DOMAIN_GLOSSARY SRS PROJECT_PLAN; do
  if [ ! -f "docs/${doc}.md" ]; then
    info "Creating placeholder docs/${doc}.md..."
    printf '# %s\n\n> Placeholder — docs-editor viết nội dung per project.\n' "${doc}" > "docs/${doc}.md"
  else
    warn "docs/${doc}.md already exists — skipping."
  fi
done

# ──────────────────────────────────────────────
# 4. SessionStart hook (.claude/settings.json)
# ──────────────────────────────────────────────
if [ ! -f .claude/settings.json ]; then
  info "Creating .claude/settings.json with SessionStart hook placeholder..."
  cat > .claude/settings.json << 'SETTINGS'
{
  "hooks": {
    "SessionStart": [{
      "command": "echo '=== Cairn inbox ===' && gh issue list --label 'for:{{MY_TEAM}}' --state open --json number,title --limit 20 2>/dev/null || echo '(gh not configured — run gh auth login)'"
    }]
  }
}
SETTINGS
  warn "Edit .claude/settings.json — replace for:{{MY_TEAM}} with your team label."
else
  warn ".claude/settings.json already exists — skipping."
fi

# ──────────────────────────────────────────────
# 5. GitHub labels
# ──────────────────────────────────────────────
if command -v gh &> /dev/null && gh auth status &> /dev/null 2>&1; then
  info "Setting up GitHub labels..."
  bash scripts/setup-labels.sh || warn "Labels setup had errors — check output above."
else
  warn "gh CLI not found or not authenticated. Run manually: bash scripts/setup-labels.sh"
fi

# ──────────────────────────────────────────────
# 6. Docs branch helper
# ──────────────────────────────────────────────
DOCS_ID=$(openssl rand -hex 3 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null | tr -d '-' | head -c 6 || echo "aabbcc")
info "Docs branch name suggestion: claude/edit-git-docs-${DOCS_ID}"

# ──────────────────────────────────────────────
# Done
# ──────────────────────────────────────────────
echo ""
info "Bootstrap complete! Next steps:"
echo ""
echo "  1. Edit CLAUDE.md — replace all {{PLACEHOLDER}} with project values."
echo "  2. Edit .claude/settings.json — set correct team label in SessionStart hook."
echo "  3. Create docs branch:"
echo "       git checkout -b claude/edit-git-docs-${DOCS_ID}"
echo "       git push -u origin claude/edit-git-docs-${DOCS_ID}"
echo "  4. Spawn docs-editor session on that branch."
echo "  5. Write initial BRD/SRS content in docs/."
echo "  6. Cleanup (after docs ready):"
echo "       rm README.md CAIRN_SETUP.md CAIRN_CONCEPTS.md CAIRN_KNOWLEDGE.md docs/_CANONICAL_DOCS_SKELETON.md"
echo ""
info "Cairn v0.7 initialized. Good luck!"
