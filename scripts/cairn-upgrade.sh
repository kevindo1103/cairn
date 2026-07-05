#!/usr/bin/env bash
# cairn-upgrade.sh — upgrade a Cairn-adopting project to the latest framework version.
#
# Run from the adopting project root:
#   bash scripts/cairn-upgrade.sh --local /path/to/cairn/clone
#   bash scripts/cairn-upgrade.sh --local /path/to/cairn/clone --dry-run
#
# Options:
#   --local PATH    Path to local Cairn framework clone (required for private repos)
#   --branch NAME   GitHub branch to fetch from via gh CLI (default: main)
#   --dry-run       Show what would change without writing anything
#
# Requirements: bash, git, python3.
# Optional:     gh CLI (for fetching from GitHub directly, without --local).

set -euo pipefail

CAIRN_REPO="kevindo1103/cairn"
CAIRN_BRANCH="main"
CAIRN_LOCAL=""
DRY_RUN=false
CAIRN_VERSION="v0.7"
BACKUP_DIR=".cairn-upgrade-backup"

# ── Colors ────────────────────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;34m'; R='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${G}✓${NC} $*"; }
warn() { echo -e "${Y}⚠${NC} $*"; }
info() { echo -e "${B}→${NC} $*"; }
err()  { echo -e "${R}✗${NC} $*" >&2; }
step() { echo ""; echo "── $* ──────────────────────────────────────────────"; }

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local)   CAIRN_LOCAL="$2"; shift 2 ;;
    --branch)  CAIRN_BRANCH="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    -h|--help)
      grep '^#' "$0" | head -20 | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) err "Unknown option: $1. Use --help."; exit 1 ;;
  esac
done

MANUAL_STEPS=()

# ── Header ────────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  cairn-upgrade.sh — target: Cairn ${CAIRN_VERSION}"
[[ "$DRY_RUN" == "true" ]] && echo "  MODE: DRY RUN — no writes, no git operations"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Safety checks ─────────────────────────────────────────────────────────────
if [[ ! -f "CLAUDE.md" ]]; then
  err "CLAUDE.md not found. Run this script from the adopting project root."
  exit 1
fi

if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
  err "Uncommitted changes detected. Commit or stash first: git stash -u"
  exit 1
fi

# ── fetch_cairn_file ──────────────────────────────────────────────────────────
# Copy a file from the Cairn source (local clone or GitHub via gh CLI).
fetch_cairn_file() {
  local src="$1"   # relative path in cairn repo
  local dest="$2"  # destination path in adopting project

  if [[ -n "$CAIRN_LOCAL" ]]; then
    [[ ! -f "${CAIRN_LOCAL}/${src}" ]] && { err "Not found in local cairn: ${CAIRN_LOCAL}/${src}"; return 1; }
    if [[ "$DRY_RUN" == "false" ]]; then
      mkdir -p "$(dirname "$dest")"
      cp "${CAIRN_LOCAL}/${src}" "$dest"
    fi
  elif command -v gh &>/dev/null; then
    if [[ "$DRY_RUN" == "false" ]]; then
      mkdir -p "$(dirname "$dest")"
      gh api "repos/${CAIRN_REPO}/contents/${src}?ref=${CAIRN_BRANCH}" \
        --jq '.content' | base64 -d > "$dest"
    fi
  else
    err "No fetch method available. Provide --local /path/to/cairn or install gh CLI."
    exit 1
  fi
}

# ── backup_file ───────────────────────────────────────────────────────────────
backup_file() {
  local f="$1"
  [[ -f "$f" && "$DRY_RUN" == "false" ]] && {
    mkdir -p "$BACKUP_DIR"
    cp "$f" "${BACKUP_DIR}/$(basename "$f").$(date +%Y%m%d).bak"
  }
}

# ═══════════════════════════════════════════════════════════════════════════════
step "Step 1: Spawn templates (docs/spawn/)"

for role in LEAD DEV DOCS_EDITOR; do
  dest="docs/spawn/SPAWN_${role}.md"
  if [[ -f "$dest" ]]; then
    warn "Exists: ${dest} — skipping (delete to force re-fetch)"
  else
    info "[DRY] Would add: ${dest}" && [[ "$DRY_RUN" == "true" ]] && continue || true
    fetch_cairn_file "docs/spawn/SPAWN_${role}.md" "$dest"
    ok "Added ${dest}"
    MANUAL_STEPS+=("Customize any {{PLACEHOLDER}} in docs/spawn/SPAWN_${role}.md")
  fi
done

# ═══════════════════════════════════════════════════════════════════════════════
step "Step 2: TEAM_STATE schema (docs/TEAM_STATE_SCHEMA.md)"

dest="docs/TEAM_STATE_SCHEMA.md"
if [[ -f "$dest" ]]; then
  warn "Exists: ${dest} — skipping"
else
  info "[DRY] Would add: ${dest}" && [[ "$DRY_RUN" == "true" ]] && : || {
    fetch_cairn_file "docs/TEAM_STATE_SCHEMA.md" "$dest"
    ok "Added ${dest}"
  }
  MANUAL_STEPS+=("Add YAML front-matter to existing docs/teams/*_STATE.md (see docs/TEAM_STATE_SCHEMA.md §Migration guide)")
fi

# ═══════════════════════════════════════════════════════════════════════════════
step "Step 3: NEW_SESSION_INSTRUCTION.md → v0.7 dispatcher"

dest="docs/NEW_SESSION_INSTRUCTION.md"
if grep -q "docs/spawn/SPAWN_LEAD" "$dest" 2>/dev/null; then
  warn "${dest} already has dispatcher format — skipping"
else
  info "Replacing ${dest} with v0.7 dispatcher (backup kept)"
  if [[ "$DRY_RUN" == "false" ]]; then
    backup_file "$dest"
    fetch_cairn_file "docs/NEW_SESSION_INSTRUCTION.md" "$dest"
  fi
  ok "Updated ${dest}"
  warn "Review backup in ${BACKUP_DIR}/ for project-specific content to re-apply"
fi

# ═══════════════════════════════════════════════════════════════════════════════
step "Step 4: SESSION_COMMS.md → machine-readable convention"

dest="docs/SESSION_COMMS.md"
if grep -q "cairn-machine" "$dest" 2>/dev/null; then
  warn "${dest} already has machine-readable block — skipping"
elif [[ ! -f "$dest" ]]; then
  warn "${dest} not found — skipping (create it first from cairn template)"
else
  info "Inserting machine-readable section into ${dest}"
  if [[ "$DRY_RUN" == "false" ]]; then
    backup_file "$dest"
    # Fetch cairn SESSION_COMMS.md to temp, extract machine-readable section, insert into project file
    tmp_cairn=$(mktemp)
    fetch_cairn_file "docs/SESSION_COMMS.md" "$tmp_cairn"
    python3 - "$dest" "$tmp_cairn" << 'PYEOF'
import sys, re

project_path, cairn_path = sys.argv[1], sys.argv[2]

with open(project_path) as f:
    project = f.read()
with open(cairn_path) as f:
    cairn = f.read()

# Extract machine-readable section from cairn file
pattern = r'(## Machine-readable issue body convention.*?)(?=\n## Khi nào KHÔNG|\Z)'
match = re.search(pattern, cairn, re.DOTALL)
if not match:
    print("⚠ Could not find machine-readable section in cairn SOURCE — skipping")
    sys.exit(0)

new_section = match.group(1).rstrip()

# Insert before "## Khi nào KHÔNG dùng GitHub Issues"
marker = "## Khi nào KHÔNG dùng GitHub Issues"
if marker in project:
    project = project.replace(marker, new_section + "\n\n---\n\n" + marker)
    with open(project_path, 'w') as f:
        f.write(project)
    print("ok")
else:
    print("⚠ Marker '## Khi nào KHÔNG dùng GitHub Issues' not found in project file")
    print("  → Append manually from docs/SESSION_COMMS.md §Machine-readable")
PYEOF
    rm -f "$tmp_cairn"
  fi
  ok "Patched ${dest}"
fi

# ═══════════════════════════════════════════════════════════════════════════════
step "Step 5: .cairn-version tracking file"

if [[ "$DRY_RUN" == "false" ]]; then
  echo "${CAIRN_VERSION}" > .cairn-version
  ok "Wrote .cairn-version = ${CAIRN_VERSION}"
else
  info "[DRY] Would write .cairn-version = ${CAIRN_VERSION}"
fi

# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Automated steps done."
echo ""

# Add FM/P manual steps
MANUAL_STEPS+=(
  "CLAUDE.md §Cross-session rules — add if missing:"
  "  FM-16: session tự mở rộng scope ngoài role được spawn → report + fix, không trust"
  "  FM-17: session báo 'committed <hash>' với artifact không tồn tại → verify trước khi trust"
  "  P-10: mọi claim 'done' phải kèm git log <hash> hoặc PR URL"
  "Review ${BACKUP_DIR}/ cho project-specific content bị overwrite"
  "git add + commit: feat(cairn): upgrade to ${CAIRN_VERSION} — spawn templates + TEAM_STATE schema"
  "Push via PR to docs-editor branch (or feature branch) per project deploy flow"
)

echo "  📋 Manual steps:"
for i in "${!MANUAL_STEPS[@]}"; do
  echo "     $((i+1)). ${MANUAL_STEPS[$i]}"
done

[[ -d "$BACKUP_DIR" ]] && echo "" && echo "  Backups: ${BACKUP_DIR}/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
