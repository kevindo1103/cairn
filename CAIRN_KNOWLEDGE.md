# Cairn — Knowledge Tree

> Cross-project accumulated wisdom. Canonical — sống trong repo cairn.
> Dự án Cairn KHÔNG copy file này (tránh drift) — chỉ pointer qua `docs/CAIRN.md`.
> Đóng góp: file `cairn-learning` issue về cairn. Xem `README.md §Contribute back`.
>
> Version: v0.7 — fold FM-16/FM-17/P-10 (2026-05-29). Seeded từ Bingxue ERP (N=1); calibrated qua 5 vòng audit (#121 + review v0.2→v0.5, #122).
> **§3 Open Gaps là single source cho toàn bộ giới hạn Cairn** — CAIRN_CONCEPTS chỉ pointer về đây (tránh trùng lặp).

---

## 1. Core Patterns (đã validate)

### P-01 — Lead/Dev pair topology
Lead (Claude Code) plan + assign + review; Dev (Windsurf) code + push PR. Lead KHÔNG tự implement. Single-owner cho team low-touch (docs, infra).
**Validated:** Bingxue — ngăn được uncoordinated edit sau khi áp dụng.
**Industry equiv:** hierarchical supervisor tree (= MetaGPT). Không novel, nhưng strict "lead không code" là constraint có chủ đích.

### P-02 — Docs Ownership Protocol (CQRS cho docs)
1 docs-editor sở hữu canonical docs. Others → report vào DOCS_INBOX (command log). docs-editor fold (projection) theo cascade BRD→SRS→Glossary→Plan→Mockup.
**Validated:** Bingxue — docs không drift qua ~40 fold cycles.
**Đây là điểm mạnh nhất của Cairn** — ít multi-agent system làm sạch write-contention trên shared knowledge.

### P-03 — GitHub Issues làm message bus + kanban
Cross-session message qua Issues + labels (from/for/type/status). Không build infra. Durable, observable, auth sẵn.
**Validated:** Bingxue — full rollout 6 teams.
**Trade-off:** không realtime — session poll inbox lúc spawn. `subscribe_pr_activity` là exception push duy nhất.

### P-04 — Lessons-as-rules
Incident → rule vĩnh viễn trong CLAUDE.md → agent đọc lại lúc spawn → enforcement tự động.
**Validated:** Bingxue — INC-01 + nhiều bug pattern. Khác runbook người (bị rot).

### P-05 — Human-as-orchestrator
KHÔNG có auto-orchestrator agent. User điều phối. Tránh "orchestrator overload" failure mode.
**Validated:** Bingxue scale 11 session vẫn ổn với human orchestrator.

### P-06 — Reflection skill (bounded)
Checklist self-check trước commit (không open-ended "is this good?"). Bounded → tránh "infinite refinement".
**Validated:** Bingxue — `doc-fold-reflection` catch cascade drift.

### P-07 — Start-small topology, scale on friction
Bingxue: 5 → 10 → 11 session theo nhu cầu thật, không over-provision từ đầu.

### P-08 — Two-layer model: Social + Mechanical
Cairn có 2 tầng. **Social** (C-1..C-5) — *bảo agent làm đúng*, cần thiết nhưng phụ thuộc agent đọc + tuân. **Mechanical** (C-6) — *chặn/surface outcome sai về cấu trúc*, không phụ thuộc compliance. Social cần thiết, Mechanical làm đủ.
**C-6 = 3 tier trên 2 trục detection × action** (v0.6): Tier-1 Blocking gate (auto-detect + auto-block), Tier-2 Automated signal (auto-detect + human-act — surface nhưng không chặn), Tier-3 Verification scope (human-detect + human-act — QC). Tier-1/2 compliance-independent (máy không lười); Tier-3 builder-independent (QC tách khỏi builder).
**Validated:** xem FM-10 (rule có sẵn vẫn bị vi phạm). Topology Bingxue có QC team trước khi đặt tên C-6 — thực hành đi trước lý thuyết.

### P-09 — Rule Promotion (vòng đời rule 2 chiều C-5 ↔ C-6)
Rule không đứng yên — di chuyển 2 chiều theo tín hiệu friction. Chi tiết: `CAIRN_CONCEPTS.md §Rule Promotion`.
- **Chiều lên (Promotion):** rule bị vi phạm lặp/critical → còn đúng? → **2 câu hỏi nối tiếp** (v0.6, khớp 2 trục C-6): (1) *Detection* — máy phát hiện được không? Không → chỉ Tier-3 QC khả thi. (2) *Action* — nếu có: **worth mechanizing?** (3 chiều: mechanizable × cost-build × frequency×severity) → nếu worth: outcome *đáng chặn*? đáng → Tier-1 gate, không đáng → Tier-2 signal. Sau promote doc co lại 1 dòng → GC.
- **Authority (v0.6):** docs-editor *phát hiện* candidate (Weekly Review) nhưng KHÔNG tự promote — xây gate là code task → scope-owner *quyết định + xây*. docs-editor mở issue `cairn-rule-promotion` cho scope-owner.
- **Chiều xuống (Demotion):** gate bị chống có 2 nguyên nhân — **gate-bug** (code gate lỗi, concept đúng → *fix gate*, KHÔNG demote) vs **gate-concept-wrong** (rule cần judgment, không nên cơ giới hoá → *demote* về C-5). Cả hai obsolete → retire. Đối xứng: promote signal = rule bị vi phạm; demote signal = gate bị chống — đều là friction signal.
- **Path B (rule ở lại C-5):** quản lý bằng **Relevance Review** — hỏi "hazard còn tồn tại không?", KHÔNG phải expiry-by-silence (silence ≠ obsolete — rule im lặng thường vì đang work). Trigger: event-driven (PR xoá module/nâng tool) + periodic sweep thấp tần. + Consolidation rule trùng.
**Kinh tế:** doc rẻ/nhanh, gate đắt/chậm — chỉ trả phí gate khi rule chứng minh nó quan trọng.
**Giải đồng thời:** rule-GC (subset mechanizable, qua Promotion + qua Relevance Review) + khi-nào-đáng-xây-mechanical + mạch lạc C-5↔C-6 (2 tầng tĩnh → vòng đời có flow 2 chiều).
**Giới hạn:** GC được rule *chết* (hazard mất) + *trùng*. Rule phán đoán *còn sống và đông* không co được → Context economics gap. Trigger human-judged, không tự động.
**Status:** `hypothesis` — designed v0.4, chưa rule nào thực sự đi qua quy trình (gate openapi hiện có ra đời TRƯỚC P-09). N=2 là test thực chiến đầu tiên.

### P-09 Success Criteria (chuẩn bị cho thực chiến — review v0.4, rework v0.6)

Để "validated qua N=1" không thành "validated qua cảm giác", đo trước khi tuyên bố P-09 work. v0.6 tách **pre-promotion** (ghi trước khi promote) khỏi **post-promotion** (đo sau), và đặt tiêu chí **per-tier** vì 3 tier có cơ chế khác nhau.

**Pre-promotion — ghi TRƯỚC khi promote (không có 2 mục này thì không đo được hiệu quả):**
- **Baseline:** ghi tần suất vi phạm rule *hiện tại* (trước khi gate tồn tại). Không có baseline → sau này không phân biệt được "gate hiệu quả" với "rule vốn chẳng ai vi phạm".
- **Detection channel:** xác nhận tồn tại kênh máy phát hiện được (cho Tier-1/2). Không có → Tier-1/2 bất khả thi, chỉ Tier-3 QC. Đây là câu hỏi #1 của flowchart Promotion — ghi lại câu trả lời.

**Post-promotion — per-tier (đo trên M-window = số task gate chạy qua, KHÔNG phải tuần lịch):**
> *Vì sao task-count không phải tuần:* gate chạy 3 PR/2 tuần vs 50 PR/2 tuần — giá trị gate phụ thuộc *số lần nó có cơ hội fire*, không phải thời gian trôi. Đếm cơ hội.

- **Tier-1 (Blocking gate):** trong M task đầu → gate bắt ≥1 vi phạm thật **VÀ** false-positive rate thấp. M task mà 0 fire → rule vốn không bị vi phạm → promote non (demote candidate / vốn là Path B material). *(v0.6 bỏ tiêu chí "suýt fire / near-fire" — gate không ghi near-miss, không đo được.)*
- **Tier-2 (Automated signal):** signal KHÔNG chặn nên "vi phạm ≈ 0" sai test. Test đúng = **Actionability** — % signal fire dẫn tới hành động người. Signal fire mà không ai act = noise → tier sai hoặc signal vô dụng. Cao actionability = tier-2 đúng việc.
- **Tier-3 (QC scope):** QC builder-independent → đo bằng **defect QC bắt được mà builder miss** so với defect lọt prod. QC không bao giờ bắt được gì builder miss → QC không thêm giá trị (hoặc builder đã tốt, hoặc QC trùng builder).

**Demotion thành công:** sau demote → friction biến mất (dev ngừng chống) **VÀ** vi phạm KHÔNG quay lại. Vi phạm bùng lại → demote sai (đó là gate-bug cần *sửa*, không phải gate-concept-wrong cần *bỏ*).

**Relevance Review health:** retire rate thấp-nhưng-khác-0 mỗi sweep. KHÔNG đặt số cứng (N=1, chưa data) — nhưng: 0% kéo dài → sweep không chạy thật; đột biến cao → over-pruning hoặc tồn đọng retire quá hạn.

### P-10 — Post-claim verification
Bất kỳ session nào claim "committed / merged / pushed" phải cung cấp artifact verify được: `git log <hash> --oneline`, PR URL, hoặc diff link. Orchestrator verify trước khi trust — KHÔNG nhận "done" chưa check.
**Rationale:** FM-17 (hallucinated artifact) che FM-16 (role drift) — session mở rộng scope rồi fabricate bằng chứng. Verify artifact surface cả hai cùng lúc. Đặc biệt cần thiết với session có scope hẹp (docs-editor, QC) vì họ không nên có code commit thật.
**Status:** `hypothesis` — derive từ FM-17 incident (Bingxue ERP 2026-05-29), chưa được practice hệ thống.

---

## 2. Failure Modes Catalog (đã gặp → mitigation)

### INC-01 — Uncoordinated schema edit → prod crash
2 session cùng sửa 1 file schema, 1 symbol bị xoá trong cleanup commit → prod crash loop 1079 lần.
**Mitigation:** clear task split · `git log <file> --oneline -10` trước push · escalate khi trùng file · PR gate `import` check.
**Class:** siloing + uncoordinated edit.

### FM-02 — Plan-action decoupling
Dev nhận task mơ hồ → code đoán sai. Hoặc Dev push lên branch của lead.
**Mitigation:** issue body BẮT BUỘC `## Plan` · dev comment "Confirmed plan" trước code · Bước 0a verify branch.

### FM-03 — Branch hygiene (worktree inherit sai branch)
Windsurf worktree fork từ branch `claude/...` của lead → commit nhầm vào branch lead.
**Mitigation:** Bước 0a — `git branch --show-current`, nếu không phải `windsurf/` → checkout branch mới từ `origin/main`.

### FM-04 — Context loss giữa sessions
Session mới spawn từ branch stale → không thấy file/decision mới. docs-news không thấy SESSION_COMMS vì worktree cũ.
**Mitigation:** TEAM_STATE.md · `git pull` đầu session · partial-read SUMMARY layer.

### FM-05 — MCP không shared giữa sessions
MCP config user-level shared nhưng process spawn per-session. Session mới có thể thiếu MCP.
**Mitigation:** fallback ladder gh CLI ↔ MCP ↔ user paste · prerequisite `gh auth login` per machine · refresh PATH sau cài tool.

### FM-06 — PR target staging không auto-close issue
GitHub `Closes #N` chỉ auto-close khi PR target default branch (main). PR vào staging → issue stale.
**Mitigation:** `status:done-staging` label · manual close khi verify · auto-close khi staging→main merge.

### FM-07 — Doc vượt ngưỡng navigability
SRS chạm 6000 dòng → đọc full tốn token, partial-read khó locate.
**Mitigation:** partial-read discipline (L1) · SUMMARY layer (L2) khi vượt ngưỡng · self-enforce qua doc-fold-reflection skill item 4b.

### FM-08 — DOCS_INBOX merge conflict
Nhiều session cùng append DOCS_INBOX → conflict khi push.
**Mitigation:** append cuối Pending · rebase + resolve (giữ cả 2 entry) · entry độc lập không overlap.

### FM-09 — Long-lived branch divergence
Branch staging/main diverge lâu không sync (123 commit) → migration `f2_employee_pii_fields` không apply được vì `f1` có bug guard → `Can't locate revision` / Employee query 500. Sự cố lớn nhất của một session vận hành thật.
**Mitigation:** rule "ngưỡng diverge staging/main" (chưa lên concept — Known Limitation §Release discipline) · sync sớm, không để dồn.

### FM-10 — Rule đọc nhưng không tuân (social enforcement gap)
Rule alembic guard có sẵn trong CLAUDE.md, migration vẫn crash. PR #45 scope violation dù C-2 "3 lớp chặn". Đọc rule ≠ tuân rule.
**Mitigation:** C-6 Mechanical Enforcement — gate cấu trúc validate outcome, không phụ thuộc agent đọc/tuân.

### FM-11 — Enforcement code tự nó plausible-nhưng-sai (meta-failure)
Gate code cũng là code AI sinh → có thể sai mà vẫn "xanh": script `exit 0` vô điều kiện, regex hụt case, diff-check so file rỗng. Gate pass nhưng không kiểm gì — false sense of safety nguy hiểm hơn không có gate.
**Mitigation:** sau promote MUST red-test — cố ý tạo 1 vi phạm, xác nhận gate THẬT SỰ fail; chỉ tin gate sau khi thấy nó đỏ. Xem P-09 Success Criteria pre-check.
**Class:** meta-failure — C-6 enforcement layer tự nó là code cần verify.

### FM-12 — Test/CI environment khác runtime thật
Test pass trên runner/máy author nhưng prod khác: env var thiếu, DB ở revision khác, OS khác, file chưa commit. Gate xanh, deploy đỏ.
**Mitigation:** CI runner SẠCH = ground truth, không phải máy author; `git status` trước push; import-check + build trên runner sạch; staging mirror prod càng sát càng tốt.
**Class:** environment drift — gate đúng nhưng đo sai môi trường.

### FM-13 — API contract lag (cross-layer staleness)
Backend ship schema change; frontend session làm trên contract cũ tới khi docs fold xong → field-name bug. C-3+C-4 là eventual-consistency, có lag window.
**Mitigation:** backend relay breaking API change qua DOCS_INBOX *ngay sau merge*; `## API Field Mapping` fast-path; openapi.json regen + commit cùng PR (Tier-1 gate bắt drift).
**Class:** delivery/timing gap — xem §3 Delivery/timing.

### FM-14 — CI trigger ≠ build dependency (gate tồn tại nhưng không chạy)
Workflow trigger (path filter, branch filter) không khớp dependency thật → gate skip đúng lúc cần chạy. Vd YAML workflow mới push lên non-default branch không trigger; path filter bỏ sót cross-dir dependency.
**Mitigation:** workflow file phải có trên default branch trước khi dùng ở branch khác; review path filter khi thêm cross-dir dependency; test trigger bằng PR thật, không giả định.
**Class:** enforcement gap — Tier-1 gate có nhưng câm.

### FM-15 — Design drift (implementation lệch mockup spec)
UI code lệch mockup — Tier-1 gate không phủ được visual/UX compliance (semantic, máy không kiểm). Implement từ mô tả lời thay vì đọc file mockup.
**Mitigation:** mockup = nguồn sự thật, đọc file trước khi code; Tier-3 QC visual review; Designer single-owner mockup artifact (C-3 sub-ownership).
**Class:** G-5 semantic — thuộc Tier-3, ngoài tầm gate.

### FM-16 — Role drift (session tự mở rộng scope ngoài role được spawn)
Session nhận role/scope cụ thể (vd docs-editor, scope `docs/**`) nhưng tự take task ngoài scope — plan + claim implement code backend/frontend — thay vì file task-assignment issue cho team đúng.
**Mitigation:** Spawn template thêm "**Hard scope-lock**: chỉ sửa file trong [scope]. Nếu cần ngoài scope → file task-assignment issue cho team đúng, KHÔNG tự làm." CLAUDE.md role definition cần explicit scope boundary, không chỉ tên role.
**Class:** G-1 autonomy mis-calibration — agent over-extend beyond assigned role.

### FM-17 — Hallucinated artifact (báo done với artifact không tồn tại)
Session báo "committed `<hash>`" / "merged PR #X" với artifact ID không tồn tại trong repo. Nguy hiểm hơn FM-16 vì nó **che** FM-16: scope violation + fabricated evidence → nếu orchestrator không verify, breach ngấm vào project history như fact.
**Mitigation:** P-10 Post-claim verification — orchestrator verify `git log <hash> --oneline` hoặc PR URL trước khi đánh dấu task done. Không accept "done" chưa check artifact.
**Class:** meta-failure — fabricated evidence che underlying scope violation (FM-16). Analogue FM-11 (enforcement code tự nó sai) nhưng ở layer báo cáo, không layer gate.

---

## 3. Open Gaps (chưa đạt chuẩn / chưa đóng)

| Gap | Trạng thái | Increment ladder |
|-----|-----------|------------------|
| **Context (docs)** | L1 partial-read done · L2 summary layer khi > 6000 dòng | L3 section-hook · L4 vector RAG (overkill hiện tại) |
| **Context (code)** | grep/read thủ công | Pilot CodeGraph MCP — pre-indexed code graph |
| **Error handling** | L1+L2 retry/fallback rules (prompt-level) | Đủ cho scale nhỏ · L3 hook auto-escalate |
| **Observability** | Weekly Review manual → cron automation | L3 Projects Insights · L4 dashboard (overkill) |
| **Rule lifecycle / GC** | Mechanizable subset: P-09 Promotion. Phán đoán subset: P-09 Path B **Relevance Review** (v0.4 — hỏi "hazard còn không", không expiry-by-silence). | Path A + Path B designed v0.4. Còn lại: rule phán đoán *còn sống và đông* không co được → Context economics |
| **Discovery gap** | C-5 chỉ codify pattern đã xảy ra; unknown unknowns thoát | Deliberate retrospective / QC audit định kỳ |
| **Release discipline** | Long-lived branch diverge (FM-09). **KHÔNG phải concept** — release/branch hygiene là git practice chuẩn, không Cairn-specific. | Rule "ngưỡng diverge staging/main" = **P-09 Tier-2 signal candidate** (v0.6 reclassify): auto-detect ✓ (đếm commit lag) nhưng KHÔNG nên auto-block — chặn merge vì branch diverge là sai, fix đúng là *sync/promote*. → divergence-check cron surface cảnh báo, human act. Là Tier-2 canonical example. |
| **Delivery/timing** | C-3+C-4 = eventual consistency, không timely. Lag window backend-ship → docs-fold | `## API Field Mapping` fast-path cho breaking API change |
| **Orchestrator scaling ceiling** | C-1 = single human orchestration point → throughput bound bởi 1 human. Ngưỡng N session overload chưa đo (Known Limitation #6) | Multi-human orchestrator (untested) — partial automation đã loại |

**Honest:** Cairn v0.7 KHÔNG giải quyết hết. Qua 5 vòng audit (#121 + review v0.2→v0.5): tầng Social mạnh, C-6 3-tier (gate · signal · QC), P-09 vòng đời 2 chiều + success criteria per-tier, FM-11..FM-15 (gồm meta-failure: enforcement code tự nó sai được). FM-16/FM-17 (v0.7): role drift + hallucinated artifact — mitigation social (scope-lock prompt) + operational (P-10 verify). Các gap trên vẫn mở. Methodology trung thực về biên đáng tin hơn tuyên bố khép kín.

---

## 4. Anti-patterns (ĐỪNG làm)

- ❌ Auto-orchestrator agent — "orchestrator overload", giữ human.
- ❌ P2P mesh giữa agents — "communication storm", chaotic.
- ❌ Vector RAG khi doc set còn navigate được bằng section anchor.
- ❌ Framework migration (LangGraph/MetaGPT) — phá vỡ "manual orchestration" choice.
- ❌ Copy số session từ dự án khác mù quáng — scale theo nhu cầu.
- ❌ **Expiry-by-silence cho rule** — "rule không bị vi phạm N tuần → retire" SAI: silence ≠ obsolete (rule im lặng thường vì *đang work*, mọi người tuân). Dùng Relevance Review hỏi "hazard rule canh có còn không" (P-09 Path B).
- ❌ **Tin gate vừa promote khi chưa thấy nó đỏ** — gate code cũng plausible-nhưng-sai (FM-11). Red-test (vi phạm cố ý → xác nhận gate fail) trước khi tin.
- ❌ **Demote gate chỉ vì nó có bug** — gate-bug (code lỗi, concept đúng) thì *sửa*, không demote. Chỉ demote khi gate-concept-wrong (rule cần judgment).
- ❌ **Trust "done" chưa verify artifact** — session claim "committed/merged" mà không cung cấp hash/URL verify được = FM-17 risk. Apply P-10: verify trước khi accept.

---

## 5. Validation Log

| Dự án | N | Period | Key learnings |
|-------|---|--------|---------------|
| Bingxue ERP | 1 | 2026-05 | Seed patterns + failure modes. Topology 5→11. INC-01. **Audit #121** → v0.2: C-6 + 2 tầng; bỏ "minimal & complete". **Review v0.2** → v0.3: C-6 2-tier; P-09 Rule Promotion; "1 nền tảng + 5 mechanism". **Review v0.3** → v0.4: P-09 vòng đời 2 chiều; Path B = Relevance Review; "worth mechanizing?" gate; C-6 Tier-2 "ai bắt QC"; dedupe → §3 single source. **Review v0.4** → v0.5: P-09 Success Criteria; FM-09 reclassify (Tier-1 gate candidate, không phải concept); Issues bus grade Above→At; trim P-08; anti-pattern expiry-by-silence. **Review v0.5 (#122, 6 reviews)** → v0.6: C-6 3-tier (gate · signal · QC, trục detection×action); Promotion flowchart 2-câu-hỏi (detection → action); Demotion tách gate-bug vs gate-concept-wrong; P-09 Success Criteria rework (pre/post-promotion, per-tier, M=task-count, bỏ "near-fire"); FM-11..FM-15 (gồm FM-11 meta-failure); FM-09 re-reclassify Tier-1→Tier-2 signal; C-1 solo-mode, C-2 cross-cutting ops, C-3 sub-ownership; promotion authority (docs-editor detect → scope-owner build). **Maturity-tag pass (critique Infra):** mỗi concept gắn `proven`/`designed`/`hypothesis` — C-1..C-5 + Tier-1 `proven`, Tier-3 `designed`, Tier-2 + P-09 `hypothesis`; sửa dòng "cross-audit self-validating" (lập luận vòng tròn); critique Infra → checklist phản nghiệm cho N=2. **Fold v0.7 (2026-05-29):** FM-16 (role drift) + FM-17 (hallucinated artifact) — docs-editor session tự mở scope sang code backend/frontend + báo commit hash không tồn tại. P-10 Post-claim verification (hypothesis). Hard scope-lock thêm vào `docs/NEW_SESSION_INSTRUCTION.md`. Anti-pattern "trust done chưa verify" thêm vào §4. |
| _(dự án tiếp theo)_ | 2 | — | _(append qua cairn-learning issues)_ |

> **Chuỗi review KHÔNG phải external validation (sửa v0.6 — critique Infra):** #121 → review v0.2→v0.5 đều là session của *cùng một dự án seed* tự review. Nó tạo internal consistency + polish, KHÔNG tạo external validity. Đây là self-consistency của một mẫu N=1, không phải bằng chứng cross-project. Phiên bản trước của dòng này tự nhận "self-validating" — đó là lập luận vòng tròn (framework tự trích quy trình review của nó để chứng minh concept của nó về review). External validation chỉ thật sự bắt đầu ở N=2.

---

## 6. Industry comparison (calibration)

| Cairn component | Industry standard | Grade |
|----------------|-------------------|-------|
| Lead/Dev topology | MetaGPT roles | At — không novel |
| Docs Ownership (CQRS) | event sourcing / single-writer | Above — áp dụng tốt |
| Issues bus | issue tracker as coordination | At — pragmatic choice (không build infra), không phải innovation cơ chế |
| Reflection skill | Reflexion paper | At — bounded đúng |
| Lessons-as-rules | SRE postmortem | Above — auto re-read enforcement |
| Context mgmt | vector DB / memory nodes | Below — file-based |
| Error handling | retry/fallback framework | Below — prompt-level |
| Observability | dashboard/alerting | Below — manual→cron |

Cairn = orchestrate thủ công bằng primitives có sẵn. Niche: team nhỏ không muốn adopt framework nặng.

### Định vị so với MetaGPT (tiền thân trí tuệ gần nhất)

MetaGPT (paper 2023) = mô phỏng software company bằng đội agent role-based (PM/Architect/Engineer/QA), structured docs giảm error propagation, pub-sub message pool. Cairn hội tụ độc lập vào cùng DNA tổ chức đó.

**Khác biệt cốt lõi:**
- MetaGPT = **autonomous greenfield generation** — 1 prompt chạy hết pipeline, docs là artifact throwaway.
- Cairn = **human-orchestrated ongoing engineering** — codebase thật sống nhiều tháng, git/PR/deploy thật, docs canonical sống.

**Positioning statement (dùng cho case study):**
> MetaGPT chứng minh role-based software-company work cho *generation*. Cairn mở rộng sang *maintenance + human-in-loop + repo thật + incident-driven rules*. Cùng DNA, khác autonomy model.

MetaGPT limitation Cairn địa chỉ trực tiếp: MetaGPT vật lộn với codebase lớn/có sẵn, code generate phải rework nặng, không có review loop thật. Cairn (human-in-loop + repo thật) giải các điểm đó. → Đây là argument bán hàng của Cairn.

---

*Cairn Knowledge Tree v0.7. Fold `cairn-learning` issues vào đây + bump version.*
