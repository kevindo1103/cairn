# TEAM_STATE Schema — Machine-Readable Format

> Cairn framework component. Version: v0.7.
> Mục đích: enable C-6 Tier-2 automation — cron script đọc state, surface cảnh báo mà không cần human parse markdown.

---

## Schema (YAML front-matter)

Mỗi `docs/teams/<team>_STATE.md` bắt đầu bằng YAML front-matter giữa `---`:

```yaml
---
# cairn-state — machine-readable. DO NOT remove block.
team: backend                     # tên team (khớp label from:/for:)
updated: "2026-05-29"            # ISO date, update sau mỗi merge
updated_by: "claude/feat-xyz"    # branch của session đã update
sprint_phase: "Phase 2F"         # current sprint label
active_count: 2                   # số task đang in_progress hoặc review
blocked_count: 1                  # số blocker mở
tasks:
  - issue: 145
    title: "Add checkout endpoint"
    status: in_progress           # planned|in_progress|review|blocked
    owner: windsurf               # lead|windsurf
    branch: "windsurf/feat-backend-checkout-api"
    blocked_by: null              # issue number nếu bị blocked, null nếu không
  - issue: 144
    title: "Fix auth middleware"
    status: blocked
    owner: windsurf
    branch: "windsurf/fix-backend-auth"
    blocked_by: 143
blockers:
  - issue: 144
    type: waiting_dependency      # human_needed|waiting_dependency
    description: "Chờ frontend confirm API contract"
---
```

Phần còn lại của file = markdown bình thường (human-readable). YAML front-matter không render trong GitHub UI (collapsed dưới `---`).

---

## Validation rules

- `status` enum: `planned` | `in_progress` | `review` | `blocked`
- `type` enum (blocker): `human_needed` | `waiting_dependency`
- `updated` format: `YYYY-MM-DD`
- **Consistency:** `active_count` = số task có `status: in_progress` hoặc `review`
- **Consistency:** `blocked_count` = số task có `status: blocked`
- Inconsistency giữa count và tasks list = update chưa đầy đủ.

---

## C-6 Tier-2 reference: cron automation

Script đọc tất cả `docs/teams/*_STATE.md`, parse YAML front-matter, report ngoại lệ:

```bash
#!/usr/bin/env bash
# surface-blockers.sh — C-6 Tier-2 Automated Signal example
# Trigger: cron hàng ngày. Action: human-act (không tự block).

for f in docs/teams/*_STATE.md; do
  python3 - << 'PY'
import sys, yaml, re
content = open("$f").read()
if not content.startswith('---'):
    sys.exit(0)
try:
    fm = yaml.safe_load(content.split('---')[1])
except:
    sys.exit(0)
for b in fm.get('blockers', []):
    emoji = '⚠️' if b['type'] == 'human_needed' else '⏳'
    print(f"{emoji}  [{fm['team']}] {b['description']} (issue #{b['issue']})"
PY
done
```

Output này post vào GitHub Issue tổng hoặc Slack digest. Đây là Tier-2 canonical example: máy phát hiện (✓), human-act (không auto-block — đúng với blocker type).

---

## Migration từ markdown-only STATE.md

1. Thêm YAML front-matter ở đầu file (trước hết mọi nội dung khác).
2. Giữ nguyên markdown bên dưới — không breaking với agent đọc markdown.
3. Update `active_count` + `blocked_count` + `tasks` list sau mỗi merge (cùng với bước refresh markdown bình thường).

**Adopt khi nào:** khi bạn có ≥3 team và muốn chạy automation script đọc cross-team blocker. L1/L2 nhỏ — markdown-only đủ.

---

*Cairn v0.7 template.*
