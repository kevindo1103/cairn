# TEAM_STATE_SCHEMA — YAML Front-Matter Schema

> Schema cho `docs/teams/*_STATE.md`. Enables C-6 Tier-2 cron automation.
> Cairn framework component. Version: v0.7.

---

## Mục đích

`docs/teams/<team>_STATE.md` = current sprint context cho mỗi team.
- Human-readable phần body (free prose).
- Machine-readable phần YAML front-matter → cron script đọc → dashboard / alert.

---

## Schema (YAML front-matter)

```yaml
---
# cairn-state — machine-readable. DO NOT remove block.
team: backend                    # team name (lowercase, match label taxonomy)
updated: "2026-05-29"            # ISO date, update mỗi lần edit file
updated_by: "claude/feat-xyz"    # branch hoặc session ID
sprint_phase: "Phase 2F"         # tên phase / sprint hiện tại
active_count: 2                  # số task đang in-progress
blocked_count: 1                 # số task bị block

tasks:
  - issue: 145
    title: "Add checkout endpoint"
    status: in_progress          # planned | in_progress | review | blocked | done
    owner: windsurf              # claude | windsurf | external
    branch: "windsurf/feat-backend-checkout-api"
    blocked_by: null             # issue number hoặc null

  - issue: 148
    title: "Migrate handover template"
    status: planned
    owner: windsurf
    branch: null
    blocked_by: null

blockers:
  - issue: 144
    type: waiting_dependency     # human_needed | waiting_dependency
    description: "Chờ frontend confirm API contract"
---
```

## Field reference

| Field | Type | Mô tả |
|-------|------|-------|
| `team` | string | Tên team, lowercase. Match label taxonomy (`from:<team>`, `for:<team>`). |
| `updated` | ISO date | Ngày cập nhật STATE.md lần cuối. Cron alert nếu > 7 ngày stale. |
| `updated_by` | string | Branch hoặc session ID cập nhật. |
| `sprint_phase` | string | Phase / sprint hiện tại. Free text. |
| `active_count` | int | Số task `in_progress`. |
| `blocked_count` | int | Số task `blocked`. |
| `tasks[].issue` | int | GitHub issue number. |
| `tasks[].status` | enum | `planned` · `in_progress` · `review` · `blocked` · `done` |
| `tasks[].owner` | string | `claude` · `windsurf` · `external` |
| `tasks[].branch` | string \| null | Branch đang chạy. Null nếu chưa start. |
| `tasks[].blocked_by` | int \| null | Issue number gây block, hoặc null. |
| `blockers[].type` | enum | `human_needed` (cần user) · `waiting_dependency` (track only) |

---

## Cron script mẫu (C-6 Tier-2)

```bash
#!/usr/bin/env bash
# weekly-review.sh — check TEAM_STATE staleness + blocked count
# Run: bash .github/scripts/weekly-review.sh

set -euo pipefail
ALERT_DAYS=7
TODAY=$(date +%Y-%m-%d)

for state_file in docs/teams/*_STATE.md; do
  team=$(grep '^team:' "$state_file" | awk '{print $2}')
  updated=$(grep '^updated:' "$state_file" | awk '{print $2}' | tr -d '"')
  blocked=$(grep '^blocked_count:' "$state_file" | awk '{print $2}')

  # Check staleness
  days_old=$(( ($(date -d "$TODAY" +%s) - $(date -d "$updated" +%s)) / 86400 ))
  if (( days_old > ALERT_DAYS )); then
    echo "⚠ STALE: $team — last updated ${days_old}d ago ($updated)"
  fi

  # Check blocked
  if (( blocked > 0 )); then
    echo "🚧 BLOCKED: $team — ${blocked} task(s) blocked"
  fi
done
```

Dùng trong `.github/workflows/weekly-review.yml` (schedule: `0 2 * * 1` = Monday 02:00 UTC).

---

## Validation rules

- `status` enum: `planned` | `in_progress` | `review` | `blocked` | `done`
- `type` enum (blocker): `human_needed` | `waiting_dependency`
- `updated` format: `YYYY-MM-DD`
- **Consistency:** `active_count` = số task có `status: in_progress` hoặc `review`
- **Consistency:** `blocked_count` = số task có `status: blocked`
- Inconsistency giữa count và tasks list = file chưa update đầy đủ.

**Adopt khi nào:** ≥3 team và muốn chạy automation cross-team. L1/L2 nhỏ — markdown-only đủ.

---

## Migration guide (từ plain markdown STATE.md)

Nếu đã có `docs/teams/<team>_STATE.md` dạng free prose:

1. Thêm YAML block ở đầu file (trước mọi nội dung khác).
2. Điền `team`, `updated` (ngày hôm nay), `updated_by` (branch hiện tại).
3. Map tasks hiện tại → `tasks[]` array.
4. Giữ nguyên phần body bên dưới (free prose sprint notes).
5. Commit: `docs: add cairn-state YAML front-matter to <team>_STATE.md`

---

*Cairn v0.7. Schema có thể extend — thêm field vào cuối block, không xóa field hiện có.*
