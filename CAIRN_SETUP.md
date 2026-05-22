# Cairn — Setup Guide

> **Cairn** = framework điều phối một fleet AI coding agent thành một software org có kỷ luật, dùng git + GitHub làm substrate, docs sống làm single source of truth.
>
> Tên: **Cairn** = đống đá xếp chồng đánh dấu đường mòn — mỗi người đi qua đặt thêm một viên để người sau không lạc. Mỗi session đóng góp một "viên đá" (doc fold, lesson-as-rule); canonical docs là cọc tiêu; docs-editor giữ cọc tiêu thẳng hàng.
>
> Version: v0.6 — extracted từ Bingxue ERP (validation N=1). Dự án adopt tiếp theo là lần validate N=2 — ghi lại friction để cải tiến.

---

## Cairn giải quyết gì

Khi chạy nhiều AI coding session song song (Claude Code, Windsurf, …), 4 vấn đề luôn xuất hiện:

1. **Docs drift** — nhiều agent sửa docs → cross-reference stale, spec không khớp code.
2. **Coordination** — agent này không biết agent kia làm gì → trùng file, conflict (xem INC-01 dưới).
3. **Context loss** — session mới không biết tình trạng hiện tại → ramp up chậm hoặc làm sai.
4. **Relay overhead** — user phải truyền tin thủ công giữa các session.

Cairn = bộ protocol + template + workflow giải quyết 4 cái trên bằng primitives có sẵn (git, GitHub Issues, Claude Code skills/hooks). KHÔNG build infra mới, KHÔNG dùng framework nặng (LangGraph/MetaGPT).

---

## Cairn gồm gì

| Component | File | Vai trò |
|-----------|------|---------|
| **Front door** | `README.md` | Entry point — đọc trước (framework repo only) |
| **Mental model** | `CAIRN_CONCEPTS.md` | WHY — 1 nền tảng + 5 mechanism, 2 tầng (framework repo only) |
| **Bootstrap guide** | `CAIRN_SETUP.md` | File này — HOW, init L1/L2/L3 (framework repo only) |
| **Knowledge tree** | `CAIRN_KNOWLEDGE.md` | LESSONS — cross-project patterns + failure modes (framework repo only) |
| **Cairn pointer** | `docs/CAIRN.md` | GIỮ trong dự án bootstrap — cách contribute learning về Cairn |
| **Master config** | `CLAUDE.md` | Topology, protocols, rules — agent đọc đầu tiên |
| **Async handoff** | `docs/DOCS_INBOX.md` | Queue report cross-session + Weekly Review |
| **Comms protocol** | `docs/SESSION_COMMS.md` | GitHub Issues labels + kanban + error handling |
| **Team state** | `docs/TEAM_STATE_PATTERN.md` + `docs/teams/` | Per-team current-state files |
| **Session entry** | `docs/NEW_SESSION_INSTRUCTION.md` | Mọi session đọc khi spawn |
| **Dev onboarding** | `docs/WINDSURF_ONBOARDING.md` | Kickoff prompt cho dev session |
| **Dev rules** | `.windsurf/rules.md` | Rule cho middle-dev session |
| **Reflection skill** | `.claude/skills/doc-fold-reflection/` | Self-check trước commit docs |
| **CI gate** | `.github/workflows/pr-quality-gate.yml` | Quality gate per PR |
| **Observability** | `.github/workflows/weekly-review.yml` | Cron audit kanban health |
| **Issue templates** | `.github/ISSUE_TEMPLATE/` | 4 template khớp Cairn comms pattern |
| **Labels** | `scripts/setup-labels.sh` | GitHub labels (gồm `cairn-learning`) |

**Canonical docs** (BRD/SRS/Glossary/PROJECT_PLAN) — Cairn cung cấp skeleton, **nội dung viết riêng per project**.

**Framework-repo-only files** (`README.md`, `CAIRN_CONCEPTS.md`, `CAIRN_SETUP.md`, `CAIRN_KNOWLEDGE.md`, `docs/_CANONICAL_DOCS_SKELETON.md`) — XOÁ khỏi dự án sau bootstrap (xem §Cleanup).

---

## Core concepts

Cairn = **1 nền tảng (C-1) + 5 mechanism (C-2..C-6)**, chia 2 tầng (Social/Mechanical), nối bởi Rule Promotion. **Đọc `CAIRN_CONCEPTS.md` trước** để hiểu mental model (WHY). Tóm tắt:

| Concept | Loại | Đóng giới hạn |
|---------|------|---------------|
| C-1 Human-as-Orchestrator | nền tảng | Công việc thật cần judgment + accountability |
| C-2 Lead/Dev Topology + Scope Isolation | mechanism (Social) | N agent đụng 1 codebase → collision |
| C-3 Docs Ownership Protocol | mechanism (Social) | Session stateless → không domain memory |
| C-4 GitHub Issues Bus | mechanism (Social) | Session không kênh coordination realtime |
| C-5 Lessons-as-Rules | mechanism (Social) | Session stateless → không process memory |
| C-6 Enforcement Layer (3 tier: gate · signal · QC) | mechanism (Mechanical) | Code plausible-sai lọt; đọc rule ≠ tuân rule |

`CAIRN_SETUP.md` (file này) = tầng HOW. `CAIRN_CONCEPTS.md` = tầng WHY. `CAIRN_KNOWLEDGE.md` = tầng lessons.

---

## Bootstrap theo cấp độ — L1 → L2 → L3

Cairn adopt theo **learning curve 3 cấp**, KHÔNG bê hết một lúc. Mỗi cấp tự đứng được — leo cấp tiếp theo khi friction thật xuất hiện (pattern P-07).

### Bước chung (mọi cấp)

1. **Tạo repo** — "Use this template" → repo mới.
2. **Branches** — `main` + `claude/edit-git-docs-<random-id>` (docs lane). `staging` thêm ở L3 nếu cần.
3. **Customize `CLAUDE.md`** — thay `{{PLACEHOLDER}}` (project name, stack, env). Topology table chỉnh theo cấp đang dùng.

---

### L1 — Minimal Cairn · concepts C-1 + C-3 + C-5

**Khi nào:** solo / MVP / 1-2 người. Bắt đầu ở đây.

**Setup:**
- Canonical docs skeleton — viết nội dung sơ bộ BRD/SRS/Glossary/PLAN (theo `docs/_CANONICAL_DOCS_SKELETON.md`).
- `docs/DOCS_INBOX.md` — async handoff queue.
- `.claude/skills/doc-fold-reflection/` — reflection skill.
- Sessions: 1 docs-editor + 1-2 builder.

**SKIP ở L1:** GitHub Issues bus, labels, kanban, lead/dev pair, Windsurf, weekly review.

**Coordination:** user relay trực tiếp (chỉ 1-2 session — đủ).

**Giá trị:** docs không bao giờ drift · incident → rule · accountability rõ. Đủ cho dự án nhỏ vận hành nhiều tháng.

---

### L2 — Coordinated Cairn · thêm C-4

**Trigger leo từ L1:** ≥3-4 session / ≥2 team → user relay thành bottleneck.

**Thêm:**
- `bash scripts/setup-labels.sh` → GitHub labels.
- GitHub Projects board (cột Backlog / Planned / In Progress / Review / Done).
- Issue templates (`.github/ISSUE_TEMPLATE/`).
- `docs/SESSION_COMMS.md` + `docs/NEW_SESSION_INSTRUCTION.md` áp dụng đầy đủ.
- `docs/TEAM_STATE_PATTERN.md` + `docs/teams/` per team.

**Giá trị:** cross-session coordination tự chạy qua Issues — user không relay từng tin.

---

### L3 — Full Cairn · thêm C-2 đầy đủ (Lead/Dev pair)

**Trigger leo từ L2:** cần dev throughput cao / scale nhiều team.

**Thêm:**
- Windsurf middle-dev pair cho team chính.
- `docs/WINDSURF_ONBOARDING.md` + `.windsurf/rules.md`.
- `staging` branch + `.github/workflows/pr-quality-gate.yml`.
- `.github/workflows/weekly-review.yml` (observability cron).
- Error handling rules + partial-read discipline enforce đầy đủ.

**Topology size ở L3:**

| Quy mô | Sessions |
|--------|----------|
| Vừa | 5-6: lead + Windsurf pair cho team chính + infra |
| Lớn | 10-11: full lead/dev pairs + QC + designer |

**Giá trị:** fleet AI agent đầy đủ kỷ luật — plan/review/dev tách bạch, observability tự động.

---

### Chi phí mỗi cấp (adoption cost)

> **Honest (N=1):** ROI định lượng — token/effort tiết kiệm bao nhiêu % — **CHƯA đo**. Đây là cost định tính: leo mỗi nấc *thêm việc gì, ai gánh*.

| Cấp | Effort thêm | Ai gánh | Overhead chính |
|-----|-------------|---------|----------------|
| **L1** | Viết + maintain canonical docs; fold DOCS_INBOX | docs-editor (1 session chuyên trách) | docs-editor là vai trò cố định, không code feature — chi phí "thuế" cho mọi cấp |
| **L2** | Tạo issue per task; check inbox mỗi kickoff; maintain TEAM_STATE | Mỗi lead | ~1 issue + vài comment / task; Weekly Review (~15-30 phút/tuần) |
| **L3** | Lead review PR; Windsurf onboard; QC scope; vận hành Rule Promotion | Lead + QC team | QC = 1 scope riêng (không code feature); review PR là throughput tax đổi lấy chất lượng |

**Quy tắc:** đừng leo cấp nếu chưa thấy friction của cấp dưới — overhead cấp trên chỉ đáng khi đã chạm trần cấp dưới (P-07). L1 đủ cho nhiều dự án nhỏ cả vòng đời.

---

### Cleanup sau bootstrap (mọi cấp)

1. **Điền `docs/CAIRN.md`** — thay `{{CAIRN_VERSION}}` + `{{CAIRN_STARTER_REPO_URL}}`. GIỮ file này.
2. **Xoá** file chỉ dùng ở framework repo:
   ```
   rm README.md CAIRN_SETUP.md CAIRN_CONCEPTS.md CAIRN_KNOWLEDGE.md docs/_CANONICAL_DOCS_SKELETON.md
   ```
3. Lý do: `CAIRN_KNOWLEDGE.md` là single-source-of-truth ở framework repo — dự án KHÔNG copy (tránh drift), chỉ pointer qua `docs/CAIRN.md`.

---

## Vận hành

1. Spawn **docs-editor đầu tiên** → fold BRD/SRS ban đầu, setup canonical docs.
2. Spawn **team leads** theo nhu cầu — mỗi lead đọc `NEW_SESSION_INSTRUCTION.md` → `CLAUDE.md` → inbox.
3. User giao task → lead tạo issue (`task-assignment` + `## Plan` + `status:planned`).
4. Dev session đọc inbox → confirm plan → code → PR.
5. Lead review → user merge → lead ghi DOCS_INBOX.
6. docs-editor fold → cascade canonical docs.
7. docs-editor chạy Weekly Review mỗi Monday.

---

## TIER-3 known gaps (honest)

Cairn v0.6 CHƯA giải quyết hết — biết trước:

| Gap | Mitigation hiện có | Increment |
|-----|--------------------|-----------| 
| Context (code) | grep/read thủ công | Pilot CodeGraph MCP |
| Context (docs) | partial-read discipline | Summary layer khi docs > 6000 dòng |
| Error handling | retry/fallback rules (prompt-level) | — đủ cho scale nhỏ |
| Observability | Weekly Review cron | — đủ cho scale nhỏ |

Dự án mới: bake-in partial-read + error rules từ ngày 1 (free). Weekly cron + CodeGraph add khi cần.

---

## Checklist init nhanh

**Bước chung + L1 (tối thiểu):**
- [ ] Repo từ template
- [ ] Branch: main + docs lane
- [ ] CLAUDE.md — thay hết `{{PLACEHOLDER}}`
- [ ] Canonical docs skeleton có nội dung sơ bộ
- [ ] DOCS_INBOX + reflection skill sẵn sàng
- [ ] docs-editor session đầu tiên spawn

**L2 (khi ≥3-4 session):**
- [ ] `setup-labels.sh` chạy xong
- [ ] Projects board + issue templates
- [ ] TEAM_STATE files per team

**L3 (khi scale dev throughput):**
- [ ] Windsurf pair + WINDSURF_ONBOARDING + .windsurf/rules.md
- [ ] staging branch + pr-quality-gate + weekly-review cron

**Cleanup (mọi cấp):**
- [ ] `docs/CAIRN.md` — điền version + framework repo URL
- [ ] Xoá README/CAIRN_SETUP/CAIRN_CONCEPTS/CAIRN_KNOWLEDGE/_CANONICAL_DOCS_SKELETON

---

## Cairn learning loop

Dự án dùng Cairn → phát hiện friction framework-level → file `cairn-learning` issue về Cairn repo → maintainer fold vào `CAIRN_KNOWLEDGE.md`. Mỗi dự án là 1 lần validate. Xem `docs/CAIRN.md` + `README.md §Contribute back`.

---

*Cairn v0.6 — feedback + friction từ dự án adopt → cải tiến cho v0.7.*
