# SESSION_COMMS — Cross-Session Communication via GitHub Issues

> Protocol để các AI session trao đổi message không cần user relay thủ công.
> Cairn framework component. Version: v1.0 (template).

---

## Tại sao

Nhiều session chạy song song → user phải relay tin thủ công, không scale. Giải pháp: **GitHub Issues làm message board** — session tự đọc inbox khi spawn, reply qua comment, close khi done.

**Hạn chế:** session là request-response, KHÔNG có background poller. Auto-check inbox chỉ xảy ra khi user spawn/wake session. PR webhook (`subscribe_pr_activity`) là exception realtime duy nhất.

---

## Label taxonomy

**Sender:** `from:docs-editor` · `from:backend` · `from:frontend` · `from:infra` · `from:qc` · `from:pm` *(thêm/bớt theo topology)*

**Recipient:** `for:docs-editor` · `for:backend` · `for:frontend` · `for:infra` · `for:qc` · `for:pm`

**Type:**

| Label | Khi nào |
|-------|---------|
| `task-assignment` | Lead giao task cho dev |
| `review-request` | PR ready cần review |
| `spec-conflict` | Ambiguity trong spec, cần PM decide |
| `relay` | Lead → Lead cross-team |
| `blocker:human-needed` | Stuck, cần user intervene — priority signal |
| `blocker:waiting-dependency` | Đợi team khác, track only |
| `question` | Cần clarification |
| `audit-finding` | Kết quả audit |

**Status (kanban):**

| Label | Column | Khi nào |
|-------|--------|---------|
| `status:planned` | Planned | Lead viết `## Plan`, chờ dev confirm |
| `status:in-progress` | In Progress | Dev confirm + bắt đầu code |
| `status:review` | Review | PR opened |
| *(closed)* | Done | Issue close |

---

## Issue creation rule

**BẮT BUỘC tạo issue khi:** user yêu cầu code change/feature, lead giao task dev, spec conflict, cross-team audit finding.

**KHÔNG cần issue khi:** câu hỏi logic/business rule, check code read-only, hỏi về docs hiện có, brainstorm chưa actionable.

---

## Workflow

### Sender
1. Title: `[<TEAM>] <short summary>`
2. Labels: 1 sender + 1+ recipient + 1-2 type (+ `status:planned` nếu task-assignment)
3. Body: `## Context` + `## Plan` (task-assignment) + `## Ask` + `## Refs`

### Recipient (Bước 0 kickoff)
List issues `for:<my-team> state:open`, đọc body từng issue. Sau đó:
- Đủ context → confirm plan → handle → comment progress → close.
- Ambiguous → comment hỏi, add `blocker:waiting-dependency`.
- Stuck sau 3 retry → add `blocker:human-needed`.
- Out of scope → redirect, remove `for:<my>` label.

---

## Pattern 1 — Lead → Dev task assignment

```
Title: [<Team>] <task>
Labels: from:<lead>, for:<dev>, task-assignment, status:planned
Body:
  ## Context
  <2-3 dòng background>

  ## Plan (lead viết — dev confirm trước khi code)
  1. Branch: windsurf/<type>-<scope>-<desc> from origin/main
  2. Files touched: <paths>
  3. Schema changes: <NONE / list>
  4. Test plan: <how to verify>

  ## Ask
  <cụ thể cần làm gì>

  ## Refs
  - <spec section / commit / related issue>
```

**Dev confirm step (BẮT BUỘC trước code):**
```
Confirmed plan. Branch: windsurf/<x> (forked from origin/main verified). ETA: <y>.
```
Plan ambiguous → hỏi lead, KHÔNG code đoán.

## Pattern 2 — Lead → Lead relay
Labels: `from:X` + `for:Y` + `relay`. Body: Context + Ask + Refs.

## Pattern 3 — Spec conflict → PM
Labels: `from:X` + `for:pm` + `spec-conflict`. Body: Context + 2 options + recommend.

## Pattern 4 — Audit finding
Labels: `from:X` + `for:<teams>` + `audit-finding`. Body: findings + per-team action.

---

## Error handling — Retry & Fallback

Agent KHÔNG có try/catch. Error handling = decision rules.

**Retry protocol:**
- Tool fail transient → retry max 3 lần, mỗi lần reasoning + đổi cách. KHÔNG retry y hệt.
- Vẫn fail → dừng, comment error nguyên văn + `blocker:human-needed`.
- Task ambiguous → KHÔNG code đoán, hỏi + `blocker:waiting-dependency`.
- `git push` network fail → retry 4× exponential backoff.

**Fallback per task type:**
- CI fail 2× → DỪNG push, mở issue kèm log. KHÔNG push-loop.
- Merge conflict → resolve đúng cách. KHÔNG `--force`/`checkout --theirs` mù.
- Scope boundary hit → tạo `relay` issue, KHÔNG tự sửa.
- Tool/MCP unavailable → fallback path, báo user. KHÔNG block hẳn.

**Anti-patterns NGHIÊM CẤM:** im lặng bỏ qua lỗi · retry vô hạn (loop) · destructive command để mask lỗi · code đoán khi ambiguous.

---

## SessionStart hook (Claude Code)

`.claude/settings.json`:
```json
{
  "hooks": {
    "SessionStart": [{
      "command": "gh issue list --label \"for:<TEAM>\" --state open --json number,title --limit 20"
    }]
  }
}
```

Windsurf không có hook — kickoff prompt phải có Bước 0 list issues.

---

## Machine-readable issue body convention (C-6 Tier-2)

> Dùng khi muốn cron automation hoặc bot đọc trạng thái issue mà không parse free-text.

Thêm HTML comment block vào **cuối body** của bất kỳ issue nào cần machine-readability:

```html
<!-- cairn-machine
status: blocked
type: waiting_dependency
waiting_for: "#123"
scope: backend
priority: high
-->
```

**Fields:**

| Field | Values | Mô tả |
|-------|--------|-------|
| `status` | `planned` · `in_progress` · `review` · `blocked` · `done` | Mirror label kanban |
| `type` | `task` · `relay` · `spec_conflict` · `blocker` · `question` | Mirror type label |
| `waiting_for` | `"#<issue>"` · `"<branch>"` · `"<team>"` | Dependency cụ thể |
| `scope` | team name (`backend`, `frontend`, …) | Ai xử lý |
| `priority` | `low` · `normal` · `high` · `critical` | Độ ưu tiên |

**Rules:**
- Block nằm **cuối body**, sau mọi nội dung human-readable.
- Không bắt buộc — thêm khi cần automation. Thiếu block = human-only issue.
- Khi update trạng thái: edit comment block, không tạo mới.
- Cron script đọc block này → update TEAM_STATE YAML → dashboard (xem `docs/TEAM_STATE_SCHEMA.md`).

**Ví dụ issue đầy đủ:**

```
Title: [Backend] Add checkout API endpoint
Labels: from:frontend, for:backend, task-assignment, status:planned

## Context
Frontend ShiftReview cần POST /operations/checkout endpoint...

## Plan
1. Branch: windsurf/feat-backend-checkout-api from origin/main
2. Files: backend/modules/operations/router.py, service.py, schemas.py
3. Schema: CheckoutIn {ws_id, actual_end_time}, CheckoutOut {id, status}
4. Test: curl POST /operations/checkout {ws_id: 1}

## Ask
Implement checkout endpoint per SRS §4.12.3

## Refs
- SRS §4.12.3
- Issue #89 (EOS prefill context)

<!-- cairn-machine
status: planned
type: task
scope: backend
priority: normal
-->
```

---

## Khi nào KHÔNG dùng GitHub Issues

- Long-running context lead-to-lead (architectural debate) → user relay.
- Binary attachments → upload qua chat.
- Realtime urgent → kênh khác (Telegram/phone).

---

*Cairn v0.7 template. Customize label list theo topology dự án.*
