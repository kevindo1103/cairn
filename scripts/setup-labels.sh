#!/usr/bin/env bash
# Cairn framework — GitHub label setup
# Tạo label taxonomy cho cross-session comms (SESSION_COMMS.md).
# Yêu cầu: gh CLI + gh auth login. Chạy từ repo root: bash scripts/setup-labels.sh
#
# Customize: sửa SENDER_TEAMS / RECIPIENT_TEAMS theo topology dự án.

set -euo pipefail

# ── Customize theo topology ──────────────────────────────────
TEAMS="docs-editor backend frontend infra qc"   # thêm/bớt team
# ─────────────────────────────────────────────────────────────

create() {
  # $1=name $2=color $3=description
  gh label create "$1" --color "$2" --description "$3" --force
}

echo "→ Sender labels (from:*)"
for t in $TEAMS pm; do
  create "from:$t" "1f77b4" "Sent by $t"
done

echo "→ Recipient labels (for:*)"
for t in $TEAMS pm; do
  create "for:$t" "2ca02c" "Routed to $t"
done

echo "→ Type labels"
create "task-assignment"  "e377c2" "Lead assigning task to dev"
create "review-request"   "ff7f0e" "PR ready for lead review"
create "spec-conflict"    "d62728" "Ambiguity in spec — PM decide"
create "relay"            "9467bd" "Lead to Lead cross-team message"
create "blocker:human-needed"       "d73a4a" "Stuck — needs user/PM intervene"
create "blocker:waiting-dependency" "fbca04" "Waiting upstream — track only"
create "question"         "bcbd22" "Needs clarification"
create "audit-finding"    "17becf" "Audit result"

echo "→ Status labels (kanban)"
create "status:planned"     "c5def5" "Lead wrote Plan, awaiting dev confirm"
create "status:in-progress" "fef2c0" "Dev coding"
create "status:review"      "d4c5f9" "PR opened, awaiting review"

echo "→ Cairn framework label"
create "cairn-learning"      "5319e7" "Framework-level learning to contribute back to Cairn"

echo "✓ Cairn labels created."
echo "Next: tạo GitHub Projects board (Backlog/Planned/In Progress/Review/Done)."
