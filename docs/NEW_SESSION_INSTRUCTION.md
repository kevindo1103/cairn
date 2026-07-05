# NEW_SESSION_INSTRUCTION — {{PROJECT_NAME}}

> Dành cho mọi AI session khi bắt đầu. Đọc file này TRƯỚC KHI làm bất cứ thứ gì.
> Cairn framework component. Version: v0.7.

---

## STEP 1 — Xác định role, rồi đọc file spawn tương ứng

| Branch hiện tại | Role | File cần đọc tiếp |
|-----------------|------|-------------------|
| `claude/edit-git-docs-<id>` | **Docs-Editor** | `docs/spawn/SPAWN_DOCS_EDITOR.md` |
| `claude/<...>` | **Lead** | `docs/spawn/SPAWN_LEAD.md` |
| `windsurf/<...>` | **Dev** | `docs/spawn/SPAWN_DEV.md` |

**Đọc file spawn tương ứng ngay sau này.** File spawn chứa kickoff sequence đầy đủ, scope lock, và do/don't table cho role của bạn.

Xác định team: xem topology table trong `CLAUDE.md → Session Topology`. Confirm scope file trước khi đụng bất kỳ file nào.

---

## ⚠️ Scope lock — BẮT BUỘC (tóm tắt — chi tiết trong file spawn)

**Hard scope-lock:** bạn chỉ sửa file trong scope của role được spawn.

- Nếu task cần file **ngoài scope** → **KHÔNG tự làm** → file task-assignment issue cho team đúng.
- Tự mở rộng scope = **FM-16** (role drift). Báo "done" với artifact không verify được = **FM-17** (hallucinated artifact).
- Với mọi claim "committed / pushed / merged": cung cấp `git log <hash> --oneline` hoặc PR URL để orchestrator verify (**P-10**).

---

## §0. Source of Truth Documents

| # | File | Mục đích |
|---|------|----------|
| 1 | `CLAUDE.md` | Rules, stack, topology, deploy |
| 2 | `docs/MASTER_BRD.md` | Business requirements |
| 3 | `docs/DOMAIN_GLOSSARY.md` | Ubiquitous language |
| 4 | `docs/SRS.md` | Implementation spec |
| 5 | `docs/PROJECT_PLAN.md` | Roadmap |

Đọc theo section anchor (`§4.2`, `§3.1`) — KHÔNG full file. Chi tiết: `CLAUDE.md → Partial-read discipline`.

---

## §1. Branch Flow

| Branch | Role | Deploy |
|--------|------|--------|
| `main` | Production canonical | Prod |
| `staging` | Pre-prod test | Staging |
| `claude/edit-git-docs-<id>` | Docs-Editor canonical lane | Không auto-deploy |
| `claude/<...>` / `windsurf/<...>` | Feature/fix | Không auto-deploy |

Flow: feature branch → PR `staging` → test → PR `staging` → `main`.

KHÔNG SSH/SFTP trực tiếp. KHÔNG migration trực tiếp trên server.

---

*Cairn v0.7 template. Thay `{{PLACEHOLDER}}` khi bootstrap.*
