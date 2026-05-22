# TEAM STATE FILES — Per-team kickoff context

> Cairn framework component. Giảm "context loss between layers" — session mới ramp up nhanh.
> Mỗi lead maintain file team của mình.

---

## File structure

```
docs/teams/
  <team>_STATE.md      # vd backend_STATE.md, frontend_STATE.md
```

Tạo per team paired. Single-owner teams (docs-editor, infra) opt-out — state đã ở DOCS_INBOX/PROJECT_PLAN.

---

## Template

```markdown
# <TEAM>_STATE — Last updated YYYY-MM-DD by <session>

## Current sprint
- Phase: <...>
- Goal: <1 dòng>

## Active tasks
| Issue | Title | Owner | Status | Branch |
|-------|-------|-------|--------|--------|
| #N | ... | lead/dev | code/review/blocked | windsurf/... |

## Last 3 merges
| Date | PR | Summary | Impact |
|------|-----|---------|--------|

## Open blockers
- ⚠️ <blocker> (issue #N)

## Recent decisions affecting this team
- YYYY-MM-DD: <decision>

## Pinned references
- Spec: docs/...
```

---

## Workflow

**Lead update (sau mỗi merge):** refresh Last 3 merges (FIFO drop) + Active tasks + Blockers. Commit `chore(state): refresh <team>_STATE.md`.

**Session kickoff Bước 1:** đọc `docs/teams/<myteam>_STATE.md` → biết sprint + tasks + blockers.

---

## Maintenance rules

- File MAX 1 trang (đọc < 2 phút).
- Last 3 merges — FIFO, giữ 3.
- Active tasks — chỉ sprint hiện tại.
- Update sau MỖI merge, không batch.
- File > 1 trang → archive `docs/teams/archive/`.

---

## Vs DOCS_INBOX vs PROJECT_PLAN

| File | Scope | Update | Audience |
|------|-------|--------|----------|
| STATE.md | 1 team, current sprint | per merge | sessions team đó |
| DOCS_INBOX | cross-team post-merge reports | per merge | docs-editor |
| PROJECT_PLAN | toàn project roadmap | per sprint | all + PM |

STATE = operational layer. DOCS_INBOX = handoff layer. PROJECT_PLAN = strategic layer.

---

*Cairn v0.1 template.*
