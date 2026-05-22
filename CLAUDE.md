# {{PROJECT_NAME}} — Claude Code Context

*Cairn framework {{CAIRN_VERSION}} · Last updated: {{DATE}}*

> Đây là master config. Mọi Claude Code session đọc file này đầu tiên.
> Thay tất cả `{{PLACEHOLDER}}` khi bootstrap. Xem `CAIRN_SETUP.md`.
>
> **Dự án này chạy trên Cairn framework** — xem `docs/CAIRN.md` để biết framework knowledge tree + cách contribute learning ngược về Cairn.

---

## Project Identity

- **Product:** {{PROJECT_NAME}} — {{PROJECT_DESC}}
- **Stack:** {{STACK}}
- **Environments:** {{PROD_URL}} (prod) · {{STAGING_URL}} (staging)
- **Phase hiện tại:** {{CURRENT_PHASE}}

---

## Docs Ownership Protocol (BẮT BUỘC)

**Toàn bộ `docs/` + root `*.md` do MỘT session docs-editor quản lý** — branch `claude/edit-git-docs-{{DOCS_ID}}`.

### Mọi session KHÁC (không phải docs-editor)
- **KHÔNG sửa trực tiếp** file trong `docs/` hoặc root `*.md`.
  - Ngoại lệ: thêm ghi chú vận hành (bug pattern, fix mới) vào `CLAUDE.md`.
- Sau thay đổi ảnh hưởng **business rule / schema / API / UI / deploy / known bug** → ghi report vào `docs/DOCS_INBOX.md` mục `## Pending`.
- **Post-merge rule (BẮT BUỘC):** PR merge vào `main` (hoặc `staging` cho spec-impact) → MUST append 1 Pending report trong 24h.
- ⚠️ Chỉ MỘT `DOCS_INBOX.md` canonical — branch docs. Không tạo bản trên branch khác.
- Không tự resolve ambiguity — nêu trong report để docs-editor xử lý.

### Session docs-editor
- Fold report theo cascade: **BRD → SRS → Glossary → Plan → Mockup**.
- Cập nhật version + changelog mỗi file.
- Chuyển report `## Pending` → `## Processed`.
- **TRƯỚC `git commit`** docs lớn: invoke skill `/doc-fold-reflection`.
- **Weekly Review:** đầu mỗi session (Monday hoặc > 7 ngày từ review cuối) → chạy checklist trong `DOCS_INBOX.md §Weekly Review`.

---

## Session Topology

> Customize bảng dưới theo dự án. Xoá row team không cần. Xem `CAIRN_SETUP.md §Chọn topology size`.

### Pair table

| # | Lead (Claude Code) | Middle Dev (Windsurf) | Scope file |
|---|---|---|---|
| 1 | **{{PRE}}_Docs** (docs-editor) | — *(single-owner)* | `docs/**` + root `*.md` |
| 2 | **{{PRE}}_Backend** | **Windsurf_Backend** | `{{BACKEND_PATH}}` |
| 3 | **{{PRE}}_Frontend** | **Windsurf_Frontend** | `{{FRONTEND_PATH}}` |
| 4 | **{{PRE}}_infra** | — *(single-owner)* | `.github/workflows/**`, deploy, CI/CD |
| 5 | **{{PRE}}_QC** | **Windsurf_QC** | `{{TEST_PATH}}` |

### Lead/Dev workflow (BẮT BUỘC)

| Vai trò | Trách nhiệm |
|---|---|
| **Claude Code (lead)** | Plan task → assign cho Windsurf qua GitHub issue. Review PR. Ghi DOCS_INBOX sau merge. **KHÔNG tự implement code** — exception: hotfix khẩn cấp + PM đồng ý. |
| **Windsurf (dev)** | Code theo assignment. Push branch `windsurf/...`. Mở PR với lead reviewer. **KHÔNG tự merge**, **KHÔNG tự ghi DOCS_INBOX**. |

### Branch naming

- Lead: `claude/<type>-<scope>-<desc>[-<random>]`
- Dev: `windsurf/<type>-<scope>-<desc>[-<random>]`
- type: `feat` · `fix` · `chore` · `docs` · `infra` · `test` · `hotfix`
- Long-lived: `main`, `staging`, `claude/edit-git-docs-{{DOCS_ID}}`

### INC-01 prevention (lessons-as-rules)

> **INC-01** (canonical incident): 2 session cùng sửa 1 file schema, 1 symbol bị xoá trong cleanup commit → prod crash loop. Đây là failure mode "siloing" + "uncoordinated edit".

Mitigation:
- User assign task rõ ràng — không trùng file.
- Trước push: `git fetch` + `git log <file> --oneline -10` xem có session khác chạm không.
- Trùng → escalate user, KHÔNG tự merge.
- PR gate bắt cross-module ImportError (xem `## Deploy`).

### Cross-session communication

GitHub Issues + labels — sessions tự đọc inbox khi spawn. Chi tiết: `docs/SESSION_COMMS.md`.

- Lead giao task: issue `from:<lead>` + `for:<dev>` + `task-assignment` + `status:planned` + body có `## Plan`.
- Lead → Lead relay: `from:X` + `for:Y` + `relay`.
- Spec conflict → PM: `for:pm` + `spec-conflict`.
- Blocker: `blocker:human-needed` (cần user) vs `blocker:waiting-dependency` (track only).
- Status: `status:planned` → `in-progress` → `review` → close.
- **Bước 0 kickoff:** list issues `for:<my-team> state:open`.
- **Bước 1 kickoff:** đọc `docs/teams/<myteam>_STATE.md`.
- **BẮT BUỘC tạo issue khi:** user yêu cầu code change, lead giao task, spec conflict, audit finding.
- **KHÔNG cần issue khi:** câu hỏi logic/read-only/docs hiện có.

---

## Partial-read discipline (BẮT BUỘC)

Canonical docs lớn — đọc theo section anchor (`§4.2`, `§3.1`), KHÔNG đọc full file. Không chắc section → đọc changelog/mục lục đầu file để locate. Full-file read chỉ khi file < 200 dòng.

---

## Deploy

> Customize theo stack + infra dự án.

- Branch flow: feature → PR `staging` → test → PR `staging` → `main`.
- `main` → prod, `staging` → staging — auto-deploy qua `.github/workflows/`.
- **KHÔNG** SSH/SFTP trực tiếp — mọi deploy qua CI/CD.
- PR vào `main` chạy `pr-quality-gate.yml` — {{GATE_CHECKS}}.
- Migration chỉ chạy qua deploy workflow.

---

## Bug Fix Protocol

1. **Reproduce** trên staging trước.
2. **Locate root cause** — không fix symptom.
3. **Check impact scope** — schema/FK/routes dùng chung.
4. **Fix & verify locally**.
5. **Deploy** qua CI/CD.
6. **Confirm** trên staging.

### Common Bug Patterns

> Append mỗi khi gặp pattern mới — đây là lessons-as-rules.

| Pattern | Triệu chứng | Fix |
|---------|-------------|-----|
| {{vd: Wrong API field name}} | {{undefined trong UI}} | {{đọc schema → đúng field}} |

---

## Security Rules

- Auth bắt buộc trên mọi endpoint sửa data.
- KHÔNG log: passwords, secrets, tokens.
- KHÔNG commit credentials — dùng env / GitHub Secrets.
- SQL: chỉ ORM, không raw f-string.

---

## Anti-Patterns

- N+1 queries → eager load.
- Magic numbers → named constant.
- God files > 500 dòng → split.
- `console.log` / debug print trong production code.

---

*Cairn v0.6 master config template. Bug pattern + rule mới → append vào file này (lessons-as-rules).*
