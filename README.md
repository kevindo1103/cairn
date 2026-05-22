# Cairn — Multi-Agent Orchestration Framework

> Điều phối một fleet AI coding agent (Claude Code, Windsurf, …) thành một software org có kỷ luật — dùng git + GitHub primitives, docs sống làm single source of truth. KHÔNG build infra mới, KHÔNG framework nặng.

**Version:** v0.6 · Extracted từ Bingxue ERP (validation N=1)

---

## File nào đọc trước

| Bạn là | Đọc |
|--------|-----|
| **Mới biết Cairn — muốn HIỂU** | `CAIRN_CONCEPTS.md` — mental model, 1 nền tảng + 5 mechanism, tại sao Cairn tồn tại |
| **Bootstrap dự án mới** | `CAIRN_CONCEPTS.md` → `CAIRN_SETUP.md` (L1/L2/L3 graduated init) |
| **Muốn lessons + failure modes** | `CAIRN_KNOWLEDGE.md` — patterns, failure modes, validation log |
| **AI session trong dự án đang chạy Cairn** | `docs/NEW_SESSION_INSTRUCTION.md` → `CLAUDE.md` |
| **docs-editor của một dự án adopt Cairn** | `docs/CAIRN.md` (pointer) + section "Contribute back" dưới đây |
| **Cairn root docs-editor — maintain repo này** | `ROOT_DOCS_EDITOR.md` |

**3 tầng tài liệu Cairn:** `CAIRN_CONCEPTS.md` (WHY — mental model) · `CAIRN_SETUP.md` (HOW — bootstrap) · `CAIRN_KNOWLEDGE.md` (LESSONS — accumulated wisdom).

---

## Cairn là gì — 60 giây

4 vấn đề khi chạy nhiều AI session song song:
1. **Docs drift** — nhiều agent sửa docs → spec lệch code.
2. **Coordination** — agent không biết agent khác làm gì → trùng file, conflict.
3. **Context loss** — session mới ramp up chậm.
4. **Relay overhead** — user truyền tin thủ công.

Cairn giải bằng:
- **Topology** — Lead/Dev pair, scope isolation, human-as-orchestrator.
- **Docs Ownership Protocol** — 1 docs-editor sở hữu canonical docs, others report qua DOCS_INBOX, fold theo cascade. (Mô hình CQRS.)
- **GitHub Issues bus + kanban** — cross-session message, không cần realtime infra.
- **Lessons-as-rules** — incident → rule vĩnh viễn agent đọc lại lúc spawn.

---

## Cấu trúc repo

```
README.md                 ← bạn đang đọc
CAIRN_CONCEPTS.md          ← mental model (WHY — 6 concept)
CAIRN_SETUP.md             ← bootstrap guide (HOW — L1/L2/L3)
CAIRN_KNOWLEDGE.md         ← knowledge tree (LESSONS — cross-project)
ROOT_DOCS_EDITOR.md        ← instruction cho session maintain repo này
CLAUDE.md                 ← master config template
.windsurf/rules.md        ← dev session rules
.claude/skills/           ← doc-fold-reflection skill
.github/                  ← CI workflows + issue templates
scripts/setup-labels.sh   ← GitHub label setup
docs/
  ├── CAIRN.md             ← pointer (giữ lại trong dự án bootstrap)
  ├── DOCS_INBOX.md       ← async handoff queue
  ├── SESSION_COMMS.md    ← Issues protocol
  ├── TEAM_STATE_PATTERN.md
  ├── NEW_SESSION_INSTRUCTION.md
  ├── WINDSURF_ONBOARDING.md
  └── _CANONICAL_DOCS_SKELETON.md
```

---

## Knowledge tree — Cairn tự học qua các dự án

Cairn v0.6 = validation N=1 (Bingxue ERP). Mỗi dự án adopt tiếp theo là một lần validate + nguồn learning mới.

**`CAIRN_KNOWLEDGE.md`** = knowledge tree canonical — patterns, failure modes, validation log. Sống trong **repo cairn này** (single source of truth, không copy-drift sang dự án).

### Contribute back (dự án Cairn → knowledge tree)

Khi docs-editor của một dự án Cairn phát hiện **framework-level learning** (không phải project-specific — vd: 1 failure mode mới, 1 pattern hiệu quả, 1 protocol cần sửa):

1. File issue **against repo cairn** với label `cairn-learning`.
2. Body theo template `## Context` / `## Learning` / `## Đề xuất sửa Cairn`.
3. Cairn maintainer (hoặc Cairn docs-editor session) fold vào `CAIRN_KNOWLEDGE.md` → bump Cairn version.

Đây là **DOCS_INBOX pattern áp dụng đệ quy** cho chính framework — Cairn-as-a-project có inbox riêng cho learnings từ các dự án dùng nó.

**Phân biệt:**
- Learning **project-specific** (vd bug logic của ERP) → DOCS_INBOX của dự án đó.
- Learning **framework-level** (vd "topology nên có rule X") → `cairn-learning` issue về cairn.

---

## Maturity & honest caveats

- **N=1 validation** — mới 1 dự án. Treat như "đang test framework".
- **TIER-3 gaps** — context/error/observability mới ở mức increment đầu. Xem `CAIRN_KNOWLEDGE.md §Open Gaps`.
- **Tied to tool limitations 2026** — nửa framework là workaround cho "agent không có realtime push / không nhớ giữa session". Sẽ evolve khi tool cải tiến.

---

*Cairn v0.6 — feedback qua `cairn-learning` issues.*
