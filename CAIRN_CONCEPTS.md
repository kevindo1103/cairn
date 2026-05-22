# Cairn — Concepts (Mental Model)

> Đọc file này là "hiểu Cairn". Không cần đọc hết template trước.
> Cấu trúc: **1 nền tảng (C-1) + 5 mechanism (C-2..C-6)**, chia 2 tầng — Social/Knowledge + Mechanical — nối bởi **Rule Promotion**.
> Version: v0.6 — calibrated qua 5 vòng multi-session audit (#121 + review v0.2→v0.5).

---

## Tại sao Cairn tồn tại

### Câu hỏi MetaGPT đã trả lời

MetaGPT (2023) hỏi: *"AI agent role-based có BUILD được phần mềm không?"* → có, cho greenfield, tự động hoàn toàn (PM/Architect/Engineer/QA, 1 prompt → pipeline ra code).

### Câu hỏi MetaGPT KHÔNG trả lời — và Cairn trả lời

> *"Làm sao áp dụng nhiều AI agent vào THỰC TẾ kỹ thuật phần mềm ĐANG DIỄN RA — codebase sống, qua nhiều tháng, có sự cố, nơi agent stateless, không nói chuyện trực tiếp được, sinh code plausible-nhưng-sai, và công việc cần con người chịu trách nhiệm?"*

MetaGPT **bỏ con người** (autonomy). Cairn **giữ con người** — câu hỏi thứ hai cần judgment mà autonomy không cung cấp được: greenfield generation khác hẳn maintenance + incident + multi-month evolution.

**Cairn = kế thừa DNA tổ chức của MetaGPT, re-target sang "human-orchestrated ongoing engineering".**

---

## Giới hạn của AI coding agent (2026)

| # | Giới hạn | Hệ quả nếu bỏ mặc |
|---|----------|-------------------|
| **G-1** | Autonomy không đủ cho công việc thật | Code sai hướng, không ai chịu trách nhiệm |
| **G-2** | Concurrency không có coordination — N agent đụng 1 codebase | Collision, uncoordinated edit (INC-01: prod crash) |
| **G-3a** | Stateless — không domain memory ("hệ thống phải là gì") | Spec drift |
| **G-3b** | Stateless — không process memory ("đã sai gì") | Lặp lỗi cũ |
| **G-4** | Không kênh inter-agent realtime | User relay thủ công |
| **G-5** | Agent sinh code plausible-nhưng-sai; đọc rule ≠ tuân rule | Code sai trông hợp lý lọt qua; rule có sẵn vẫn bị vi phạm |

> G-3a/G-3b cùng gốc statelessness nhưng cần **remedy khác nhau** (canonical docs vs rules) — nên tách.

---

## Hai tầng của Cairn

```
┌─ TẦNG SOCIAL / KNOWLEDGE ─────────────────────────────┐
│  C-1 Human-as-Orchestrator (nền tảng)                 │
│  C-2 Topology · C-3 Docs Ownership                    │
│  C-4 Issues Bus · C-5 Lessons-as-Rules                │
│  → BẢO agent làm đúng. Cần thiết, NHƯNG chưa đủ.       │
└───────────────────────────────────────────────────────┘
            ↕  Rule Promotion (rule chảy C-5 → C-6)
┌─ TẦNG MECHANICAL ─────────────────────────────────────┐
│  C-6 Enforcement Layer (3 tier: gate · signal · QC)   │
│  → CHẶN/SURFACE kết quả sai, bất kể compliance.       │
└───────────────────────────────────────────────────────┘
```

Social tạo *knowledge + coordination* nhưng phụ thuộc agent đọc + tuân. Mechanical *không phụ thuộc compliance*. **Social làm Cairn cần thiết; Mechanical làm Cairn đủ.** Hai tầng KHÔNG tĩnh — **Rule Promotion** làm rule di chuyển giữa chúng (mục riêng dưới).

---

## Độ chín mỗi concept — đọc tag trước khi tin

Cairn là **N=1**: phần lõi đã chạy thật, phần mới phần lớn còn là thiết kế. Mỗi concept dưới đây gắn 1 tag cho biết tin được tới đâu — tông giọng tự tin của một methodology doc KHÔNG được phép xoá ranh giới này.

- **`proven`** — đã vận hành ở dự án seed (Bingxue ERP), có bằng chứng cụ thể (incident / cycle thật).
- **`designed`** — cơ chế thiết kế xong và tồn tại, nhưng chưa có dữ liệu vận hành.
- **`hypothesis`** — giả thuyết hợp lý, chưa chạy lần nào. Đối xử như điều cần kiểm, không phải điều đã biết.

⚠️ Bản thân các tag này là **tự-chấm N=1** — chưa qua external validation. Dự án adopt thứ 2 (N=2) là bài test thật đầu tiên cho cả tag lẫn concept.

---

## Cấu trúc: 1 nền tảng + 5 mechanism

C-1 khác category với C-2..C-6: nó là **operating-mode** (chọn human-orchestrated thay vì autonomous), không phải mechanism. C-2..C-6 là 5 **mechanism** dựng trên nền đó.

### C-1 · Human-as-Orchestrator — nền tảng — đóng G-1 · `proven`

Con người là orchestrator. KHÔNG có auto-orchestrator agent.

**Tại sao:** Công việc thật cần judgment + accountability. Auto-orchestrator scale nhiều agent gây "orchestrator overload". Con người giữ phán đoán; agent là worker.

**Hệ quả:** Lead plan + assign + review, KHÔNG tự code. User spawn session, duyệt PR, merge.

**Solo mode (L1):** khi chưa có Windsurf Dev (L1 Minimal — solo/MVP), Lead **tự code** — pair constraint "lead không code" chỉ apply từ L3 (khi có Dev). L1 = single agent operating, không có collision risk. "Lead không tự code" là rule của *pair topology*, không phải rule tuyệt đối.

**Giới hạn:** xem Known Limitations (CAIRN_KNOWLEDGE §3) — chính C-1 là trần scale của Cairn.

### C-2 · Lead/Dev Topology + Scope Isolation — đóng G-2 · `proven`

Tổ chức role-based: Lead (plan/review) ↔ Dev (code). Mỗi team có **scope** riêng.

**Tại sao:** N agent đụng 1 file = collision. Chia scope = blast-radius containment.

**Bằng chứng:** INC-01 — 2 session cùng sửa 1 file schema → prod crash loop 1079 lần.

**Lưu ý:** scope định nghĩa bằng **feature domain + file path**, không chỉ path — một feature có thể trải nhiều path.

**Cross-cutting operations** — C-2 scope (feature/path) KHÔNG phân loại được các thao tác chạm-mọi-team: **release/promote** (staging→main), dependency upgrade, repo-wide refactor. Đây không phải edit feature — là branch operation. Cần gán **owner chỉ định** (thường infra). Bằng chứng: promote 123-commit chạm 52 file mọi team — không scope nào "sở hữu". Release KHÔNG phải concept riêng (nó là git practice), nhưng *quyền sở hữu thao tác release* là câu hỏi topology — C-2 phải trả lời.

### C-3 · Docs Ownership Protocol — đóng G-3a (domain memory) · `proven`

MỘT docs-editor sở hữu canonical docs. Session khác report qua DOCS_INBOX; docs-editor fold theo cascade.

**Tại sao:** Session stateless → cần bộ nhớ chung bền vững về domain. Single-writer + async inbox + cascade = giải write-contention. (CQRS: DOCS_INBOX = command log, docs = read model, docs-editor = projection.)

**Điểm mạnh nhất của Cairn.**

**Sub-ownership theo artifact type:** C-3 nói "1 docs-editor sở hữu `docs/`" — nhưng `docs/` có thể chứa artifact không thuộc write-flow cascade của docs-editor (vd `mockup_*.jsx` do Designer sửa trực tiếp theo task, không qua DOCS_INBOX). Ownership đúng = theo **artifact type / write-flow**, không theo directory: docs-editor sở hữu *canonical spec* (BRD/SRS/Glossary — cascade fold); Designer sở hữu *design artifact* (mockup). Cùng nằm `docs/` không có nghĩa cùng 1 owner.

### C-4 · GitHub Issues Bus — đóng MỘT PHẦN G-4 · `proven`

Cross-session message qua GitHub Issues + labels + kanban.

**Tại sao:** Session không có kênh realtime. Cần substrate coordination bền vững, không build infra.

**Giới hạn:** C-4 cho **durable bus**, KHÔNG cho **delivery**. Tin nằm trong bus nhưng không tự đến đúng session — user vẫn là router. Đóng ~70% G-4.

### C-5 · Lessons-as-Rules — đóng G-3b (process memory) · `proven`

Mỗi sự cố/bài học → rule trong CLAUDE.md. Agent đọc lại lúc spawn.

**Tại sao:** Session stateless → hệ thống không tự học trừ khi bài học ghi vào nơi agent tương lai chắc chắn đọc.

**Giới hạn:**
- C-5 là **knowledge layer, KHÔNG phải compliance layer** — đọc rule ≠ tuân rule (bằng chứng: rule alembic guard có sẵn, migration vẫn crash). Enforcement thật cần C-6.
- **Discovery gap:** C-5 chỉ codify pattern đã xảy ra. Unknown unknowns cần retrospective/QC audit để surface.
- **Lifecycle:** C-5 không tự GC — giải bằng Rule Promotion (mục riêng).

### C-6 · Enforcement Layer — đóng G-5 · maturity theo tier (xem bảng)

**WHY** — Tầng Social không đóng được G-5: (1) agent sinh code plausible-nhưng-sai; (2) đọc rule ≠ tuân rule (rule alembic có sẵn vẫn crash; PR #45 scope violation dù C-2 "3 lớp chặn"). Thêm docs/rule không giải được — cần lớp khác.

**HOW — 3 tier trên 2 trục: detection (ai phát hiện) × action (ai xử lý).** KHÔNG phải thang sức mạnh tuyến tính — 3 cơ chế bù nhau.

| Tier | Detection × Action | Độ chín | Cơ chế | Đóng được gì |
|------|--------------------|---------|--------|--------------|
| **Tier-1 — Blocking gate** | auto-detect + **auto-block** | `proven` — import + build gate đang chạy, bắt bug thật. ⚠️ gate openapi false-fire ngay lần đầu (FM-11) | CI gate, CODEOWNERS, branch protection, openapi diff. Block merge/deploy khi fail. | Outcome máy kiểm được + đáng *chặn*: build, schema, import |
| **Tier-2 — Automated signal** | auto-detect + **human-act** | `hypothesis` — divergence-check chưa xây, weekly-review chưa cron-hoá | Cron/check tự động *surface* vấn đề nhưng KHÔNG block (weekly-review digest, divergence-check). | Outcome máy kiểm được nhưng *không nên chặn* — vd branch divergence (fix bằng promote, không bằng dừng merge) |
| **Tier-3 — Verification scope** | **human-detect** + human-act | `designed` — vai QC tồn tại trong topology; giá trị "bắt blind spot builder" chưa đo | QC team — scope chuyên trách verify. | Semantic / business-logic / UX — máy không kiểm được |

- Tier-1 mạnh nhất ở *chặn*; Tier-3 rộng nhất ở *phủ semantic*; Tier-2 lấp ô "máy phát hiện được nhưng không nên auto-block".
- Tier-1+2 **compliance-independent** (máy không lười). Tier-3 **builder-independent** (QC tách khỏi builder — vẫn lười/miss được, nhưng bắt blind spot builder).

**WHAT:** Tier-1 = CI quality gate (openapi diff PR #114 bắt drift không rule nào bắt) · CODEOWNERS · branch protection. Tier-2 = weekly-review cron · staging/main divergence-check. Tier-3 = **QC team** — biểu hiện rõ nhất: QC tồn tại CHÍNH VÌ G-5, topology đi trước concept model.

**Giới hạn Tier-3 — ai bắt blind spot của QC?** QC builder-independent → bắt blind spot builder. Nhưng QC cũng có blind spot riêng — giới hạn cơ bản của *mọi* human verification layer. Câu trả lời một phần **đã có trong thực hành**: **cross-audit loop** — peer session audit lẫn nhau (issue #121 + các review v0.x). Mitigation: rotation reviewer + cross-audit định kỳ; Tier-1/2 (máy) không có vấn đề này.

---

## Rule Promotion — vòng đời rule giữa C-5 ↔ C-6 (P-09) · `hypothesis`

> ⚠️ `hypothesis` — **chưa rule nào thực sự đi qua quy trình này.** Toàn bộ mục dưới là *thiết kế*, không phải mô tả thực hành. Gate openapi hiện có ra đời TRƯỚC P-09, không qua promotion. Đọc như đề xuất cần N=2 kiểm — đây là phần "mới và hay nhưng chưa validated" mà critique đã chỉ ra.

Cơ chế nối 2 tầng. Rule **không đứng yên** — di chuyển **2 chiều** theo tín hiệu friction.

### Chiều lên — Promotion (C-5 → C-6)

```
Bài học → [C-5] Rule trong docs (rẻ, nhanh, advisory)
              │ tín hiệu: vi phạm lặp lại HOẶC critical incident
              ▼
        Rule còn ĐÚNG? ── sai → RETIRE
              │ đúng
              ▼
   Máy phát hiện được vi phạm? (detection channel)
        │ CÓ — auto-detect            │ KHÔNG — chỉ human-detect
        ▼                             ▼
   Worth mechanizing?            Critical / semantic?
   (cost vs freq×severity)       │ có            │ không
        │ có        │ không      ▼                ▼
        ▼            ▼      [C-6 Tier-3]     ở lại [C-5]
   Nên BLOCK     ở lại [C-5]  QC scope       (Path B)
   outcome?      (Path B)
   │ có    │ không
   ▼        ▼
[C-6     [C-6
 Tier-1]  Tier-2]
 gate     signal
```

Routing 3 tier dựa **2 câu hỏi nối tiếp**, khớp đúng 2 trục của C-6:
1. **Detection** — máy phát hiện được vi phạm không? Không → chỉ Tier-3 (human-detect) khả thi.
2. **Action** — nếu máy phát hiện được: outcome có *đáng chặn* merge/deploy không? Đáng → Tier-1 (block). Không đáng (vd branch divergence — fix bằng promote, chặn merge sẽ sai) → Tier-2 (signal).

Sau promote: C-5 doc co lại 1 dòng pointer → GC context cost.

**Trigger (human-judged, KHÔNG phải counter tự động):** docs-editor đánh giá trong Weekly Review. Critical incident → promote ngay (N=1, như INC-01). Moderate → vi phạm lặp lại (~3 lần). Cosmetic → không promote.

**Authority — phát hiện ≠ quyết định ≠ xây (Theme E):** docs-editor *phát hiện* candidate trong Weekly Review (nó thấy friction signal), nhưng KHÔNG tự promote. Xây gate là **code task** → thuộc scope-owner của vùng đó (vd openapi gate → infra; import-check → backend). docs-editor mở issue `cairn-rule-promotion` cho scope-owner; scope-owner *quyết định* worth-it và *xây*. Tách vai tránh docs-editor (không sở hữu CI code) ôm việc ngoài scope.

**"Worth mechanizing?" — quyết định 3 chiều** (W2): `mechanizable × cost-to-build × frequency×severity`. Mechanizable KHÔNG đủ — custom linter 2 ngày cho vi phạm 2×/năm = không worth. Mechanizable-nhưng-không-worth → ở lại C-5 (Path B).

**Sau promote phải kiểm gate có thật sự chạy** — gate code cũng là code AI sinh, plausible-nhưng-sai (FM-11): gate pass vô điều kiện, hoặc trigger nhầm event. Success criteria + cách verify mỗi tier: `CAIRN_KNOWLEDGE.md §P-09 Success Criteria`.

**Tại sao kinh tế:** doc rẻ/nhanh; gate đắt/chậm. Chỉ trả chi phí gate khi rule *chứng minh* nó quan trọng. Tránh cả no-gate (chaos) lẫn gate-mọi-thứ (over-engineer).

### Chiều xuống — Demotion (C-6 → C-5 / retire)

Gate không bất tử. Tín hiệu demote = **gate bị chống**: false-positive cao, dev bypass thường xuyên. Nhưng "gate bị chống" có **2 nguyên nhân khác nhau — xử lý khác nhau**:

| Nguyên nhân | Bản chất | Xử lý |
|-------------|----------|-------|
| **Gate-bug** — gate code sai (regex hụt, trigger nhầm event) | Concept đúng, *implementation* lỗi | **Fix gate, KHÔNG demote.** Outcome vẫn đáng mechanize. |
| **Gate-concept-wrong** — rule bản chất cần judgment, không nên cơ giới hoá | Mechanizable đánh giá sai từ đầu | **Demote về C-5.** Rule còn đúng nhưng thuộc tầng advisory. |
| **Obsolete** — rule + gate đều hết thời | Hazard biến mất | **Retire** cả hai. |

Phân biệt gate-bug vs gate-concept-wrong là then chốt: demote một gate chỉ vì nó *có bug* = vứt bỏ enforcement còn giá trị. Hỏi: "sửa được để hết false-positive mà vẫn giữ ý nghĩa không?" — được → bug; không → concept sai.

Đối xứng: Promotion signal = rule *bị vi phạm* (Social fail). Demotion signal = gate *bị chống* (Mechanical over-reach). Cả hai là **friction signal**.

### Path B — rule ở lại C-5 (Relevance Review)

Rule không-critical + không-worth-mechanizing ở lại C-5 mãi — phần lớn là rule phán đoán ("hỏi product trước khi refactor schema"). Không quản lý → CLAUDE.md bloat.

**Cơ chế = Relevance Review, KHÔNG phải expiry-by-silence:**
> ⚠️ Rule im lặng thường vì nó *đang work* (mọi người tuân, 0 vi phạm). "Im lặng N tuần → retire" sẽ xoá đúng rule thành công nhất. **Silence ≠ obsolete.**

Relevance Review hỏi **"mối nguy rule này canh có còn tồn tại không?"** — không phải "có bị vi phạm không".
- Hazard còn → GIỮ, bất kể im lặng.
- Hazard mất (tool đã fix / code path đã xoá / đã có gate thay) → RETIRE.

2 trigger:
- **Event-driven (chính):** PR xoá module / nâng tool / ship gate mới → docs-editor check "rule C-5 nào canh thứ vừa đổi?" → retire/update. Rẻ, chính xác, nối post-merge DOCS_INBOX flow.
- **Periodic sweep (lưới an toàn):** relevance pass toàn bộ định kỳ thấp (quý, không phải tuần) — bắt rule mà hazard biến mất không qua PR rõ ràng.

Đồng thời **Consolidation:** 2 rule gần trùng → gộp.

**Giới hạn thành thật:** Relevance Review GC được rule *chết* (hazard mất) + *trùng*. Rule phán đoán *còn sống và đông* thì không co được — số rule hợp lệ tự nó quá lớn cho context là **Context economics gap** (khác), không phải Path B giải.

---

## Quan hệ giữa các concept

```
            C-1 Human-as-Orchestrator  (nền tảng — operating mode)
                        │
            C-2 Lead/Dev Topology
                  │              │
   C-3 Docs Ownership      C-4 Issues Bus
   (domain memory)         (coordination, delivery một phần)
                  │              │
            C-5 Lessons-as-Rules  (process memory — knowledge)
                        ↕
                        ↕  Rule Promotion (P-09) — 2 chiều
                        ↕
            C-6 Enforcement Layer  (3 tier: gate · signal · QC)
            (enforce/surface bất kể compliance)
```

- C-1 nền tảng. C-2 cấu trúc. C-3+C-4 hai trụ giao tiếp. C-5 process memory — *biết* đúng, không *bắt* đúng.
- C-6 đóng khoảng hở "biết ≠ làm". Rule Promotion là vòng đời 2 chiều nối C-5 ↔ C-6.

---

## Về số lượng concept — KHÔNG claim "complete"

6 concept (1 nền tảng + 5 mechanism) là **core**, KHÔNG phải tập đóng kín. Bỏ cái nào → một giới hạn hở:

| Bỏ | Giới hạn hở | Failure mode |
|----|-------------|--------------|
| C-1 | G-1 | Code sai hướng, không accountability |
| C-2 | G-2 | Collision — INC-01 lặp lại |
| C-3 | G-3a | Spec drift |
| C-4 | G-4 (phần) | User relay thủ công — không scale |
| C-5 | G-3b | Lặp lỗi cũ |
| C-6 | G-5 | Code plausible-sai lọt; rule bị phớt lờ |

Cairn **tự nhận có giới hạn ngoài 6 concept**.

---

## Giới hạn — Cairn tự nhận chưa đóng

Cairn KHÔNG khép kín. Danh sách giới hạn đầy đủ + hướng xử lý: **`CAIRN_KNOWLEDGE.md §3 Open Gaps`** — single source, tránh trùng lặp giữa 2 file (chính nguyên tắc C-3).

Tóm tắt nhanh: delivery/timing · rule lifecycle phần phán đoán (Path B) · discovery gap · release discipline · context economics · orchestrator scaling ceiling (C-1 là trần throughput).

---

## Cairn KHÔNG phải là gì

- **Không phải library code** (≠ LangGraph, CrewAI, AutoGen) — Cairn là operating model.
- **Không phải autonomous pipeline** (≠ MetaGPT, ChatDev) — giữ con người có chủ đích.
- **Không phải SWE agent product** (≠ Devin, OpenHands) — Cairn điều phối các product đó.
- **Không phải tool quản lý session** (≠ Conductor, vibe-kanban) — Cairn là protocol chạy trên chúng.
- **Tầng Social KHÔNG phải enforcement** — docs/rule cho knowledge. Compliance thật ở C-6.

Cairn = **methodology + scaffolding** vận hành fleet AI coding agent như software org có kỷ luật, dùng primitives có sẵn.

---

## Học Cairn theo cấp độ

- **L1 Minimal** — C-1 + C-3 + C-5. Drift + accountability + learning. Solo / MVP.
- **L2 Coordinated** — thêm C-4 + C-6 Tier-1 cơ bản (CI gate tối thiểu). Khi ≥2 team.
- **L3 Full** — thêm C-2 đầy đủ + C-6 đầy đủ (CODEOWNERS, branch protection, QC team) + Rule Promotion vận hành. Khi scale.

Leo từng nấc khi friction xuất hiện — pattern P-07.

**Cảm quan chi phí** (định tính — định lượng CHƯA đo, N=1):
- **L1:** docs-editor là *vai trò chuyên trách* (không code feature) + nhịp fold DOCS_INBOX.
- **L2:** += nhịp tạo issue/kanban per task + Weekly Review hàng tuần.
- **L3:** += review PR (throughput tax đổi chất lượng) + QC là *scope riêng không code feature*.

docs-editor và QC = "thuế kỷ luật" — scope không sinh feature. Đó là chi phí cố hữu của Cairn. Chi tiết per-cấp: `CAIRN_SETUP.md §Chi phí mỗi cấp`.

---

*Cairn Concepts v0.6. Tầng WHY. HOW ở `CAIRN_SETUP.md`, lessons + giới hạn ở `CAIRN_KNOWLEDGE.md`. Calibrated per audit #121 + review v0.2→v0.5 (#122).*
