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

## Khi nào KHÔNG dùng GitHub Issues

- Long-running context lead-to-lead (architectural debate) → user relay.
- Binary attachments → upload qua chat.
- Realtime urgent → kênh khác (Telegram/phone).

---

*Cairn v0.1 template. Customize label list theo topology dự án.*
