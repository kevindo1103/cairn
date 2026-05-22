# NEW_SESSION_INSTRUCTION — {{PROJECT_NAME}}

> Dành cho mọi AI session khi bắt đầu. Đọc file này TRƯỚC KHI làm bất cứ thứ gì.
> Cairn framework component.

---

## STEP 1 — Xác định role: Lead vs Dev

**Bạn là LEAD (Claude Code) nếu:** spawn trên branch `claude/<...>`.
→ Trách nhiệm: plan task, assign cho dev qua GitHub issue, review PR, ghi DOCS_INBOX sau merge.

**Bạn là DEV (Windsurf) nếu:** spawn trên branch `windsurf/<...>`.
→ Trách nhiệm: code theo task assignment, push PR, chờ lead approve. KHÔNG tự merge, KHÔNG ghi DOCS_INBOX. Đọc thêm `.windsurf/rules.md`.

**Xác định team:** xem topology table trong `CLAUDE.md → Session Topology`. Confirm scope file trước khi đụng.

---

## STEP 2 — Kickoff sequence

1. Đọc `CLAUDE.md` — master config (topology, protocols, rules).
2. Đọc `docs/SESSION_COMMS.md` — comms protocol.
3. **Bước 0:** list GitHub issues `for:<my-team> state:open` — đọc inbox.
4. **Bước 1:** đọc `docs/teams/<my-team>_STATE.md` — current sprint context.
5. Đọc spec liên quan task (partial-read — xem §0a).

---

## §0a. Partial-read discipline (BẮT BUỘC)

Canonical docs (BRD/SRS) lớn — đọc **theo section anchor** (`§4.2`, `§3.1`), KHÔNG full file. Không chắc section → đọc changelog/mục lục đầu file để locate. Full-file read chỉ khi file < 200 dòng.

---

## §0. Docs Ownership Protocol

**Toàn bộ `docs/` + root `*.md` do MỘT docs-editor session quản lý** — branch `claude/edit-git-docs-{{DOCS_ID}}`.

- KHÔNG sửa trực tiếp `docs/` hoặc root `*.md` (ngoại lệ: ghi chú vận hành vào `CLAUDE.md`).
- Thay đổi ảnh hưởng business rule/schema/API/UI/deploy/bug → ghi report vào `docs/DOCS_INBOX.md §Pending`.
- Post-merge: PR merge → append Pending report trong 24h.
- Không tự resolve ambiguity — nêu trong report.

Chi tiết: `CLAUDE.md → Docs Ownership Protocol`.

---

## Branch Flow

| Branch | Role | Deploy |
|--------|------|--------|
| `main` | Production canonical | Prod |
| `staging` | Pre-prod test | Staging |
| `claude/<...>` / `windsurf/<...>` | Feature/fix | Không auto-deploy |

Flow: feature branch → PR `staging` → test → PR `staging` → `main`.

KHÔNG SSH/SFTP trực tiếp. KHÔNG migration trực tiếp trên server.

---

## Source of Truth Documents — đọc theo thứ tự

| # | File | Mục đích |
|---|------|----------|
| 1 | `CLAUDE.md` | Rules, stack, topology, deploy |
| 2 | `docs/MASTER_BRD.md` | Business requirements |
| 3 | `docs/DOMAIN_GLOSSARY.md` | Ubiquitous language |
| 4 | `docs/SRS.md` | Implementation spec |
| 5 | `docs/PROJECT_PLAN.md` | Roadmap |

---

*Cairn v0.1 template. Thay `{{PLACEHOLDER}}` khi bootstrap.*
