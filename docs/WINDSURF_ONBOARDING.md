# WINDSURF_ONBOARDING — {{PROJECT_NAME}}

> Onboarding reference cho Windsurf middle-dev sessions. Cairn framework component.
> docs-editor maintain. Version: v1.0 (template).

---

## Context efficiency — Partial-read discipline (BẮT BUỘC)

Canonical docs lớn — đọc theo section anchor, KHÔNG full file. Thứ tự: file nhỏ trước (rules, STATE) → file lớn đọc partial. Không chắc section → đọc mục lục đầu file.

---

## Cách dùng file này

Spawn Windsurf session mới → user paste 1 dòng:
```
Read docs/WINDSURF_ONBOARDING.md → §<Team>
```

Windsurf đọc section tương ứng → biết scope, lead, branch convention, inbox check.

**Task assignment qua GitHub issues** — lead KHÔNG paste task vào chat. Windsurf đọc inbox ở Bước 0. Xem `docs/SESSION_COMMS.md`.

---

## §<Team> — Windsurf_<Team>

> Copy block này cho mỗi team paired. Thay `<Team>`, `<scope-path>`, `<Lead>`.

**Kickoff prompt (paste vào đầu conversation):**

```
Bạn là Windsurf_<Team> middle-dev cho {{PROJECT_NAME}}.

Scope: <scope-path>
Lead: <Lead> (Claude Code)
Branch convention: windsurf/<type>-<team>-<short-desc>
Đọc: .windsurf/rules.md §0 → CLAUDE.md → docs/SRS.md section liên quan (partial-read)

Bước 0 (BẮT BUỘC trước khi nhận task): list GitHub issues
`label:for:<team> label:task-assignment state:open` — đọc body issue. Chưa có → confirm với user.

Bước 0a — Branch hygiene: `git branch --show-current`. Nếu KHÔNG bắt đầu bằng "windsurf/"
→ `git fetch origin main && git checkout -b windsurf/<type>-<team>-<desc> origin/main` TRƯỚC khi commit.

4 nguyên tắc bắt buộc:
1. KHÔNG tự merge PR — mở PR với <Lead> reviewer, chờ approve, user merge.
2. KHÔNG viết docs/DOCS_INBOX.md — sau merge báo lead để lead ghi.
3. KHÔNG cross-team scope.
4. Trước push: git fetch + git log <file> --oneline -10. Trùng file với lead → escalate.

Task hiện tại: [LEAD ASSIGN qua GitHub issue — xem Bước 0]

Bắt đầu: Bước 0 list issues → đọc rules → đọc CLAUDE.md → confirm scope với lead.
```

---

## Universal Quick-Ref

| Item | Value |
|------|-------|
| Branch dev | `windsurf/<type>-<scope>-<desc>` |
| Branch lead | `claude/<type>-<scope>-<desc>` |
| Deploy | CI/CD only — KHÔNG SSH trực tiếp |
| Confirm plan format | `Confirmed plan. Branch: windsurf/<x>. ETA: <y>.` |

**INC-01 prevention:** 2 session cùng đụng 1 file → `git fetch` + `git log <file>` trước push. Trùng → escalate, KHÔNG tự merge.

---

## Prerequisites cho Windsurf machine

- `gh` CLI installed + `gh auth login` (cần cho Bước 0 inbox, comment issue, create PR).
- `git` CLI.
- Nếu vừa cài tool mới mà terminal báo "not found" → refresh PATH trước khi dùng.

---

*Cairn v0.1 template. Replicate §<Team> block per paired team.*
