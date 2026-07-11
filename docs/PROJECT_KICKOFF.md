# Cairn Project Kickoff — Thứ Tự Spawn & First Steps

> Đọc file này ngay sau khi clone cairn template và chạy `cairn-init.sh`.
> PM (human) làm Phase 0 trước, rồi spawn sessions theo đúng thứ tự dưới đây.

---

## Tổng Quan Spawn Order

```
Phase 0 — PM (human)          Cấu hình repo, quyết định topology
    ↓
Phase 1 — Docs-editor         Tạo canonical docs skeleton + DOCS_INBOX relay
    ↓
Phase 2 — Infra               Setup CI/CD skeleton, branch protection, secrets
    ↓ (song song nhau)
Phase 3 — Lead sessions       Backend / Frontend / Designer — đọc spec, init structure
    ↓
Phase 4 — Dev sessions        Windsurf pairs nhận task từ leads
    ↓
Phase 5 — QC                  Sau khi first feature có thể test
```

**Quy tắc cứng:** Đừng spawn Lead trước khi Docs-editor xong canonical docs skeleton.
Leads cần spec để plan — không có spec = plan sai = work over.

---

## Phase 0 — PM (Human) · Trước khi spawn bất kỳ session nào

**Mục tiêu:** Repo sẵn sàng cho tất cả sessions.

```bash
# 1. Chạy init script — điền placeholders vào CLAUDE.md
bash scripts/cairn-init.sh

# 2. Push lên GitHub
git add CLAUDE.md && git commit -m "chore: init cairn config"
git push origin main
```

**Trên GitHub:**
- [ ] Actions → **"Cairn First-Time Setup"** → Run workflow (nhập `setup`) → labels tự tạo
- [ ] Settings → **"Template repository"** OFF (đây là project repo rồi, không phải template nữa)
- [ ] Settings → Branches → Add rule: protect `main` (require PR, no force push)

**Quyết định topology:**
- [ ] Xác định sessions cần thiết (xem bảng Pair table trong `CLAUDE.md`)
- [ ] Quyết định có staging branch không → ảnh hưởng Infra setup
- [ ] Quyết định hosting: static / VPS / Docker / serverless → báo cho Infra

**Tạo docs-editor branch:**
```bash
git checkout -b claude/edit-git-docs-<random-4-char>
git push origin claude/edit-git-docs-<random-4-char>
```
→ Ghi branch name vào `CLAUDE.md § Docs Ownership Protocol`.

**Tạo DOCS_INBOX relay issue:**
- Dùng label: `docs-inbox` · Title: `[DOCS_INBOX Relay] — gửi report vào đây`
- Pin issue này trên repo
- Ghi issue number vào `CLAUDE.md § Docs Ownership Protocol`

---

## Phase 1 — Docs-editor Session · Spawn đầu tiên

**Branch:** `claude/edit-git-docs-<id>` (branch PM vừa tạo)
**Đọc trước:** `docs/spawn/SPAWN_DOCS_EDITOR.md`

### First steps

**1. Tạo canonical docs skeleton**
```
docs/
├── BRD.md              ← Business Requirements Document
├── SRS.md              ← Software Requirements Spec
├── GLOSSARY.md         ← Domain terminology
├── PROJECT_PLAN.md     ← Milestones + sprint plan
└── teams/
    ├── backend_STATE.md
    ├── frontend_STATE.md
    └── (một file per team trong topology)
```
Dùng `docs/_CANONICAL_DOCS_SKELETON.md` làm base. Điền thông tin project thật — không để placeholder.

**2. Tạo team STATE files** (1 file per lead session)
- Copy schema từ `docs/TEAM_STATE_SCHEMA.md`
- Điền team name, sprint phase hiện tại, tasks = empty

**3. Tạo issue onboarding cho từng lead**
- Label: `task-assignment` + `for:<team>` + `status:planned`
- Title: `[Kickoff] <Team> — Day 1 setup`
- Body: link tới spec section liên quan + scope file cụ thể

**4. Brief PM**
- Comment vào DOCS_INBOX relay issue: "Docs skeleton ready. Leads có thể spawn."

**Done criteria:** BRD + SRS draft tồn tại, mỗi team có STATE file, mỗi team có kickoff issue.

---

## Phase 2 — Infra Session · Spawn song song với Docs

**Branch:** `claude/infra-setup-initial`
**Đọc trước:** `docs/spawn/SPAWN_LEAD.md` + `CLAUDE.md § Deploy`

### First steps

**1. Hỏi PM** (nếu chưa rõ) trước khi làm bất kỳ thứ gì:
- Frontend hosting provider?
- Backend: VPS / Docker / serverless / không có?
- Có staging branch không?

**2. Setup CI/CD dựa trên câu trả lời**

*Static frontend (Vercel/Netlify):*
```yaml
# Không cần deploy workflow — Vercel/Netlify tự pull từ git push
# Chỉ cần pr-quality-gate.yml (đã có)
# Config trên Vercel dashboard: root dir = portal/ hoặc frontend/dist
```

*Full-stack VPS:*
```yaml
# .github/workflows/deploy.yml
# Cần: SSH_HOST, SSH_USER, SSH_PRIVATE_KEY trong GitHub Secrets
# Tham khảo pattern trong CAIRN_KNOWLEDGE.md § Deploy
```

*Staging branch:*
```bash
git checkout -b staging
git push origin staging
# Tạo thêm deploy-staging.yml mirror deploy.yml
```

**3. Customize `pr-quality-gate.yml`** (đã có skeleton)
- Thêm đúng lint/build command cho stack của project
- Xoá steps không dùng

**4. Setup GitHub Secrets** (hướng dẫn PM tự nhập)
- Tạo issue `for:pm` liệt kê tên secrets cần thiết, PM nhập value trên GitHub
- KHÔNG nhận secret value qua issue/chat

**5. Test gate bằng dummy PR**
- Branch `claude/infra-gate-test` → đổi 1 dòng README → PR → confirm workflow chạy xanh

**Done criteria:** PR gate chạy xanh. Deploy workflow tồn tại (dù chưa có server thật). PM biết secrets cần nhập.

---

## Phase 3 — Lead Sessions · Sau khi Docs-editor done

**Đọc trước:** `docs/spawn/SPAWN_LEAD.md` + kickoff issue của team mình

### Backend Lead — First steps

- [ ] Đọc BRD + SRS section liên quan đến backend scope
- [ ] Init project structure: `backend/modules/`, `backend/core/`, `alembic/`
- [ ] Tạo `.env.example` với tất cả env vars cần thiết (không có value thật)
- [ ] Viết `README` ngắn trong `backend/`: setup local dev (venv, seed, run)
- [ ] Assign task đầu tiên cho Windsurf_Backend qua GitHub issue:
  - Thường là: auth module / session management / first domain endpoint
- [ ] Regen `docs/openapi.json` ngay khi có endpoint đầu tiên

### Frontend Lead — First steps

- [ ] Đọc BRD + SRS section liên quan + design system docs
- [ ] Init project structure: `portal/` hoặc `frontend/src/`
- [ ] Cài Tailwind + font + color token theo Design System
- [ ] Build "Hello World" màn hình đầu tiên đúng design → confirm với PM
- [ ] Assign task đầu tiên cho Windsurf_Frontend:
  - Thường là: layout shell / navigation / first screen
- [ ] Đọc `docs/openapi.json` trước khi implement bất kỳ API call nào

### Designer — First steps *(nếu có trong topology)*

- [ ] Đọc BRD + module content files (source of truth)
- [ ] Tạo mockup màn hình đầu tiên trong `design_v2/` hoặc `docs/mockup_*.jsx`
- [ ] KHÔNG implement code — output là file mockup
- [ ] Nếu design decision ảnh hưởng spec → comment DOCS_INBOX relay issue

---

## Phase 4 — Dev Sessions (Windsurf) · Sau khi Lead assign task

**Đọc trước:** `docs/spawn/SPAWN_DEV.md` + issue được assign

### First steps (áp dụng cho mọi Windsurf dev)

- [ ] Đọc kickoff issue: `## Plan` section — confirm "Confirmed plan" trong comment trước khi code
- [ ] Setup local dev theo hướng dẫn trong `backend/README` hoặc `frontend/README`
- [ ] `git checkout -b windsurf/<type>-<scope>-<desc>`
- [ ] Code → verify local → push → mở PR với lead là reviewer
- [ ] KHÔNG tự merge

---

## Phase 5 — QC Session · Sau first feature

**Đọc trước:** `docs/spawn/SPAWN_LEAD.md` + SRS test acceptance criteria

### First steps

- [ ] Đọc SRS — xác định acceptance criteria cho features đã build
- [ ] Setup test framework:
  - Backend: `pytest` + fixtures
  - Frontend/e2e: Playwright
- [ ] Viết test cho auth flow + first happy path
- [ ] Assign test tasks cho Windsurf_QC
- [ ] Đặt convention: `@pytest.mark.skip(reason="waiting: <branch>")` cho tests chờ dependency

---

## "Week 1 Done" Criteria

Project được coi là past kickoff khi:

- [ ] Tất cả sessions đã spawn ít nhất 1 lần
- [ ] Canonical docs (BRD + SRS draft) tồn tại và leads đã đọc
- [ ] CI/CD: PR gate chạy xanh trên ít nhất 1 real PR
- [ ] Mỗi team có ít nhất 1 issue `status:in-progress`
- [ ] DOCS_INBOX relay issue tồn tại và được pin
- [ ] Không còn `{{PLACEHOLDER}}` nào trong `CLAUDE.md`

---

*Cairn v0.7 · Đọc `CAIRN_SETUP.md` cho full onboarding checklist.*
