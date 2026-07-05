#!/usr/bin/env bash
# cairn-init.sh — one-shot bootstrap for a new Cairn-adopting project.
#
# Run from the new project root (after "Use this template"):
#   bash scripts/cairn-init.sh
#
# What this does:
#   1. Creates docs/teams/, docs/spawn/ directories
#   2. Creates placeholder DOCS_INBOX.md with Pending/Processed/Weekly Review sections
#   3. Creates placeholder canonical doc stubs (BRD/SRS/Glossary/PROJECT_PLAN)
#   4. Creates .claude/settings.json with SessionStart hook skeleton
#   5. Runs scripts/setup-labels.sh if gh CLI is authenticated
#   6. Prints next steps including {{PLACEHOLDER}} fill + cleanup
#
# Requirements: bash, git.
# Optional:     gh CLI (for setup-labels.sh).

set -euo pipefail

G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${G}✓${NC} $*"; }
warn() { echo -e "${Y}⚠${NC} $*"; }
info() { echo -e "${B}→${NC} $*"; }

DOCS_ID=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 5 || echo "xxxxx")
DOCS_BRANCH="claude/edit-git-docs-${DOCS_ID}"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  cairn-init.sh — bootstrapping Cairn v0.7"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [[ ! -f "CLAUDE.md" ]]; then
  echo "✗ CLAUDE.md not found. Run from project root (after 'Use this template')."
  exit 1
fi

# ── Directories ───────────────────────────────────────────────────────────────
info "Creating directory structure..."
mkdir -p docs/teams docs/spawn .claude/skills/doc-fold-reflection scripts
ok "Directories created"

# ── DOCS_INBOX.md ─────────────────────────────────────────────────────────────
if [[ ! -f "docs/DOCS_INBOX.md" ]]; then
  info "Creating docs/DOCS_INBOX.md..."
  cat > docs/DOCS_INBOX.md << 'EOF'
# DOCS_INBOX — Cross-Session Report Queue

> Queue nhận report từ mọi session sau merge. Docs-editor fold vào canonical docs.
> Cairn framework component.

---

## Pending

*(Empty — append reports here)*

---

## Processed

*(Reports đã fold)*

---

## Weekly Review Log

> Docs-editor chạy checklist 8 items mỗi Monday (hoặc > 7 ngày từ review cuối).
> Append findings vào đây. Finding actionable → tạo issue tương ứng.

*(No reviews yet)*
EOF
  ok "Created docs/DOCS_INBOX.md"
else
  warn "docs/DOCS_INBOX.md already exists — skipping"
fi

# ── Canonical doc stubs ───────────────────────────────────────────────────────
for doc in MASTER_BRD DOMAIN_GLOSSARY SRS PROJECT_PLAN; do
  dest="docs/${doc}.md"
  if [[ ! -f "$dest" ]]; then
    info "Creating stub ${dest}..."
    cat > "$dest" << STUB
# ${doc} — {{PROJECT_NAME}}

> Version: v0.1 · Last updated: $(date +%Y-%m-%d)
> ⚠ Stub — viết nội dung thật trước khi spawn team sessions.

## Changelog

| Version | Date | Change |
|---------|------|--------|
| v0.1 | $(date +%Y-%m-%d) | Init stub via cairn-init.sh |
STUB
    ok "Created ${dest}"
  else
    warn "${dest} already exists — skipping"
  fi
done

# ── doc-fold-reflection skill ─────────────────────────────────────────────────
skill_file=".claude/skills/doc-fold-reflection/SKILL.md"
if [[ ! -f "$skill_file" ]]; then
  info "Creating doc-fold-reflection skill stub..."
  cat > "$skill_file" << 'EOF'
# doc-fold-reflection — Pre-commit Checklist for Docs Fold

> Invoke before committing BRD/SRS/Glossary/DS/PROJECT_PLAN changes.
> Docs-editor calls: /doc-fold-reflection

Run through these 7 items:

1. All cascade levels affected? (BRD change → SRS sections referencing it updated?)
2. Version number bumped in every modified file?
3. Changelog entry added with date + summary?
4. Cross-references still valid? (section numbers, glossary terms)
5. DOCS_INBOX reports moved from §Pending → §Processed?
6. Any ambiguity left unresolved? (nêu trong processed report — không tự quyết)
7. `git diff --stat` reviewed — no accidental code file in staged changes?
EOF
  ok "Created ${skill_file}"
else
  warn "${skill_file} already exists — skipping"
fi

# ── .claude/settings.json ─────────────────────────────────────────────────────
settings_file=".claude/settings.json"
if [[ ! -f "$settings_file" ]]; then
  info "Creating .claude/settings.json with SessionStart hook skeleton..."
  cat > "$settings_file" << EOF
{
  "hooks": {
    "SessionStart": [
      {
        "command": "echo '⚠ Customize: replace <TEAM> with your team label before using this hook.'"
      }
    ]
  }
}
EOF
  ok "Created ${settings_file} (customize SessionStart hook with your team label)"
else
  warn "${settings_file} already exists — skipping"
fi

# ── setup-labels.sh ───────────────────────────────────────────────────────────
echo ""
info "GitHub labels..."
if command -v gh &>/dev/null && gh auth status &>/dev/null 2>&1; then
  if [[ -f "scripts/setup-labels.sh" ]]; then
    bash scripts/setup-labels.sh && ok "Labels created via setup-labels.sh"
  else
    warn "scripts/setup-labels.sh not found — create labels manually"
  fi
else
  warn "gh CLI not authenticated — run 'bash scripts/setup-labels.sh' manually after gh auth login"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ cairn-init complete."
echo ""
echo "  📋 Next steps:"
echo "     1. Docs branch name for this project: ${DOCS_BRANCH}"
echo "        → git checkout -b ${DOCS_BRANCH} && git push -u origin ${DOCS_BRANCH}"
echo "     2. Fill CLAUDE.md — replace ALL {{PLACEHOLDER}} values"
echo "     3. Fill docs/spawn/SPAWN_*.md — replace {{PLACEHOLDER}} values"
echo "     4. Write canonical doc content in docs/ (BRD, SRS, Glossary, PROJECT_PLAN)"
echo "     5. Customize .claude/settings.json SessionStart hook with your team label"
echo "     6. Cleanup (remove framework-only files):"
echo "        rm README.md CAIRN_SETUP.md CAIRN_CONCEPTS.md CAIRN_KNOWLEDGE.md"
echo "        rm docs/_CANONICAL_DOCS_SKELETON.md"
echo "     7. Commit: git add -A && git commit -m 'chore: init Cairn v0.7'"
echo "     8. Spawn docs-editor session on ${DOCS_BRANCH}"
echo ""
echo "  Docs branch: ${DOCS_BRANCH}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
