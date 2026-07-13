# Cairn Security Baseline — SEC Rules

*Cairn v0.7 · Áp dụng cho MỌI project chạy Cairn framework · Last updated: 2026-07-13*

> **Mục đích:** Đảm bảo sản phẩm bàn giao đến tay khách hàng đáp ứng tiêu chuẩn bảo mật thị trường.
> File này là **canonical security standard** — project KHÔNG được hạ chuẩn, chỉ được thêm rule riêng.
> Mọi rule có mã `SEC-XX` để reference trong issue / PR review / DOCS_INBOX report.

---

## Chuẩn tham chiếu (market standards)

| Chuẩn | Áp dụng khi | Mức |
|-------|-------------|-----|
| **OWASP Top 10 (2021)** | Mọi project có web surface | BẮT BUỘC — baseline này cover toàn bộ 10 mục |
| **OWASP ASVS 4.0 Level 1** | Mọi project bàn giao khách hàng | BẮT BUỘC |
| **OWASP ASVS Level 2** | Project xử lý PII / tài chính / HR data | BẮT BUỘC khi có data nhạy cảm |
| **Nghị định 13/2023/NĐ-CP (PDPD VN)** | Project xử lý dữ liệu cá nhân người VN | BẮT BUỘC — khách hàng VN |
| **GDPR** | Có user EU | Khi hợp đồng yêu cầu |
| **CIS Benchmarks** | Hardening VPS/server tự quản | Khuyến nghị |

---

## 1. Authentication & Session (SEC-01 → SEC-06)

- **SEC-01** — Mọi endpoint đọc/ghi data phải có auth (`Depends(get_current_user)` hoặc tương đương). Endpoint public phải được liệt kê tường minh trong 1 whitelist duy nhất, có comment lý do.
- **SEC-02** — Password: hash bằng **bcrypt / argon2** (không MD5/SHA1/plaintext). Min length 8, không giới hạn max dưới 64. KHÔNG force đổi định kỳ nếu không có incident (theo NIST 800-63B).
- **SEC-03** — JWT: secret ≥ 256 bit từ env, KHÔNG hardcode. Access token TTL ≤ 24h (khuyến nghị ≤ 1h + refresh token). Thuật toán pin cứng (`HS256`/`RS256`) — reject `alg=none`.
- **SEC-04** — Token storage phía client: ưu tiên `httpOnly` cookie + `Secure` + `SameSite=Lax`. Nếu buộc dùng localStorage (SPA legacy) → PHẢI có CSP chặt (SEC-27) và ghi rõ trade-off trong SRS.
- **SEC-05** — Login: rate-limit (vd 5 lần sai / 15 phút / IP+username) + lockout tạm hoặc backoff. Message lỗi generic — KHÔNG tiết lộ "user tồn tại nhưng sai password".
- **SEC-06** — Logout phải vô hiệu hoá session/token phía server khi kiến trúc cho phép (denylist/rotate). Đổi password → revoke toàn bộ session cũ.

## 2. Authorization (SEC-07 → SEC-10)

- **SEC-07** — **IDOR guard:** mọi endpoint nhận `id` phải verify ownership/role trước khi trả data (vd staff chỉ xem record của chính mình: `employee_code == JWT.sub`). Đây là lỗi bị khai thác nhiều nhất — QC phải có test case riêng.
- **SEC-08** — Phân quyền theo role ở **backend** — frontend ẩn nút chỉ là UX, KHÔNG phải security control.
- **SEC-09** — Multi-tenant: mọi query PHẢI scope theo tenant (`get_tenant_session(tid)` pattern) — KHÔNG bao giờ query cross-tenant trừ admin endpoint có audit log.
- **SEC-10** — Deny by default: route mới chưa gắn permission → mặc định 403, không phải 200.

## 3. Input / Output (SEC-11 → SEC-15)

- **SEC-11** — SQL: **chỉ ORM / parameterized query**. KHÔNG raw SQL với f-string/concat. (OWASP A03 Injection)
- **SEC-12** — Validate input bằng schema layer (Pydantic/Zod/tương đương) trên MỌI endpoint — type, range, length, enum. Reject thừa field khi có thể (`extra=forbid`).
- **SEC-13** — Upload file: whitelist extension + MIME sniff + size limit + rename ngẫu nhiên + lưu ngoài web root. KHÔNG serve file upload với content-type thực thi được.
- **SEC-14** — Output encoding: frontend framework escape mặc định (React/Vue) — KHÔNG dùng `dangerouslySetInnerHTML` / `v-html` với data user trừ khi qua sanitizer (DOMPurify) + review.
- **SEC-15** — Path traversal: mọi thao tác file theo input user phải resolve + verify nằm trong thư mục cho phép.

## 4. Data Protection & PII (SEC-16 → SEC-20)

- **SEC-16** — TLS bắt buộc mọi môi trường public (prod + staging). HTTP → redirect HTTPS. HSTS bật trên prod.
- **SEC-17** — PII (họ tên, SĐT, email, địa chỉ, lương, chấm công...): liệt kê trong SRS mục "Data classification". Chỉ thu thập field thực sự cần (data minimization — NĐ 13/2023).
- **SEC-18** — **KHÔNG copy PII prod → staging/dev** mà chưa scrub/mask. Snapshot prod→staging phải có bước scrub PII, hoặc staging DB được đối xử như prod (access control tương đương) và ghi rõ trong CLAUDE.md là TODO.
- **SEC-19** — Backup: mã hoá at-rest, retention xác định, restore được test ít nhất 1 lần trước bàn giao.
- **SEC-20** — Xoá data: có cơ chế xoá/anonymize dữ liệu cá nhân khi khách hàng yêu cầu (right to erasure — NĐ 13/2023 & GDPR).

## 5. Secrets & Config (SEC-21 → SEC-24)

- **SEC-21** — KHÔNG commit secret vào repo: `.env` gitignored, chỉ commit `.env.example` (key, không value). CI dùng GitHub Secrets. Nhận secret qua issue/chat = vi phạm — PM nhập trực tiếp trên GitHub/hosting dashboard.
- **SEC-22** — Secret bị lộ (commit nhầm, log, screenshot) → **rotate ngay lập tức**, KHÔNG chỉ xoá commit (history còn). Ghi incident vào DOCS_INBOX.
- **SEC-23** — KHÔNG log: password, token, JWT, secret, số thẻ, OTP. Log PII ở mức tối thiểu (user id thay vì full profile).
- **SEC-24** — Debug mode / verbose error / swagger-ui: TẮT hoặc gate bằng auth trên prod. Error trả về client: generic message + request id; stack trace chỉ trong server log.

## 6. Dependencies & Supply Chain (SEC-25 → SEC-26)

- **SEC-25** — Lockfile bắt buộc (`package-lock.json` / `requirements.txt` pin version). Dependency mới phải qua PR review — không cài lib lạ ít maintainer cho việc trivial.
- **SEC-26** — Scan tự động trong PR gate: **Bandit** (Python) / **npm audit** (Node) + GitHub Dependabot alerts bật. Vuln HIGH/CRITICAL trong dependency đang dùng → fix trước khi bàn giao.

## 7. Frontend (SEC-27 → SEC-30)

- **SEC-27** — Security headers trên prod: `Content-Security-Policy` (tối thiểu chặn inline-script lạ), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` (hoặc CSP frame-ancestors), `Referrer-Policy: strict-origin-when-cross-origin`.
- **SEC-28** — CORS: whitelist origin cụ thể — KHÔNG `*` khi có credentials.
- **SEC-29** — localStorage/sessionStorage: chỉ draft/UI state — KHÔNG lưu PII nhạy cảm, KHÔNG lưu token nếu đã có httpOnly cookie option (xem SEC-04).
- **SEC-30** — Form nhận input → CSRF protection khi dùng cookie auth (SameSite + CSRF token cho state-changing request).

## 8. Infra & Deploy (SEC-31 → SEC-35)

- **SEC-31** — Deploy CHỈ qua CI/CD — KHÔNG SSH/SFTP thủ công (bypass quality gate = bypass security gate). Provisioning lần đầu là exception duy nhất.
- **SEC-32** — VPS hardening tối thiểu: SSH key-only (tắt password auth), firewall chỉ mở port cần (80/443 + SSH), fail2ban hoặc tương đương, auto security updates.
- **SEC-33** — Service chạy user riêng non-root, quyền file tối thiểu. DB không expose ra internet (bind localhost / private network).
- **SEC-34** — GitHub repo: branch protection trên `main`, secret scanning + push protection bật, Actions permissions read-only mặc định.
- **SEC-35** — Audit log cho thao tác nhạy cảm (login, đổi quyền, xoá data, export PII) — ai, làm gì, khi nào. Immutable (append-only) khi kiến trúc cho phép.

---

## Trách nhiệm theo Cairn role

| Role | Chịu trách nhiệm SEC |
|------|---------------------|
| **Backend lead** | SEC-01→15, 23-24, 35 — review mọi Windsurf PR theo checklist này |
| **Frontend lead** | SEC-04, 14, 27→30 |
| **Infra** | SEC-16, 21-22, 26, 31→34 — owner của PR gate security steps |
| **QC** | Test case cho SEC-05, 07, 08, 09 (IDOR/authz là bắt buộc) + verify Pre-Delivery Checklist |
| **Docs-editor** | Giữ file này sync với Cairn upstream; fold security incident vào Common Bug Patterns |
| **PM (human)** | Approve exception (xem §Exception), nhập secrets, quyết định data classification |

## Enforcement mapping (C-6 · 3-tier)

| Tier | Cơ chế | Cover |
|------|--------|-------|
| **Tier 1 — Gate (tự động, chặn merge)** | Bandit / npm audit / secret scanning trong `pr-quality-gate.yml` | SEC-11 (một phần), 21, 26 |
| **Tier 2 — Signal (tự động, cảnh báo)** | Dependabot alerts, GitHub secret scanning alerts | SEC-22, 26 |
| **Tier 3 — QC (con người/session review)** | Lead PR review + QC test + Pre-Delivery Checklist | Toàn bộ còn lại — đặc biệt SEC-07 IDOR không tool nào bắt được |

---

## Pre-Delivery Security Checklist (BẮT BUỘC trước bàn giao khách hàng)

> QC session chạy checklist này → kết quả ghi vào issue `[Security Sign-off] <release>` label `for:pm` + `blocker:human-needed`.
> PM ký duyệt issue đó = sản phẩm được phép bàn giao. **Không có sign-off issue = không bàn giao.**

### Auth & Access
- [ ] Quét toàn bộ router: không endpoint ghi data nào thiếu auth (SEC-01)
- [ ] Test IDOR: user A không đọc/sửa được resource của user B qua đổi id (SEC-07)
- [ ] Test role bypass: gọi thẳng API admin bằng token staff → 403 (SEC-08)
- [ ] Rate-limit login hoạt động (SEC-05)
- [ ] Tài khoản test/demo/seed đã xoá hoặc đổi password mạnh

### Data & Secrets
- [ ] `git log` không chứa secret (chạy secret scan toàn history) (SEC-21/22)
- [ ] Prod `.env` không nằm trong repo/backup public
- [ ] TLS + HSTS hoạt động, HTTP redirect (SEC-16)
- [ ] Staging/dev không còn PII thật chưa scrub (SEC-18)
- [ ] Backup chạy + restore test OK (SEC-19)

### Code & Dependencies
- [ ] Bandit / npm audit: 0 HIGH/CRITICAL chưa xử lý (SEC-26)
- [ ] Không raw SQL f-string (grep audit) (SEC-11)
- [ ] Debug mode / verbose error tắt trên prod (SEC-24)
- [ ] Security headers trả về đúng (check bằng curl hoặc securityheaders.com) (SEC-27)
- [ ] CORS không wildcard với credentials (SEC-28)

### Infra
- [ ] SSH key-only, firewall đúng port (SEC-32)
- [ ] DB không truy cập được từ internet (SEC-33)
- [ ] Branch protection + secret scanning bật trên repo (SEC-34)
- [ ] Audit log ghi nhận login + thao tác nhạy cảm (SEC-35)

### Bàn giao
- [ ] Tài liệu bàn giao có mục "Security notes": data classification, secrets nào khách phải rotate khi nhận, hướng dẫn cấp/thu hồi tài khoản
- [ ] Toàn bộ credentials tạm của team dev bị thu hồi / rotate sau bàn giao
- [ ] Khách hàng nhận danh sách known limitations + TODO security (nếu có exception)

---

## Exception process

Không đáp ứng được 1 rule (deadline, legacy constraint):

1. Tạo issue `security-exception` + `for:pm` + `blocker:human-needed` — ghi rõ: rule nào (SEC-XX), lý do, rủi ro, mitigation tạm, deadline fix.
2. **PM approve tường minh trong issue** — session KHÔNG tự quyết.
3. Exception được list trong tài liệu bàn giao (khách hàng biết) + ghi vào `CLAUDE.md §Security Rules` project như known limitation.
4. Exception có deadline — quá hạn → escalate lại PM.

---

## Incident response (tối thiểu)

1. **Phát hiện** (log, alert, khách báo) → tạo issue `security-incident` + `blocker:human-needed` NGAY — không chờ điều tra xong.
2. **Contain:** rotate secret liên quan, revoke session, chặn IP nếu cần.
3. **Điều tra:** root cause theo Bug Fix Protocol — xác định data nào bị ảnh hưởng.
4. **Thông báo:** PM quyết định thông báo khách hàng; nếu lộ dữ liệu cá nhân người VN → nghĩa vụ thông báo theo NĐ 13/2023 (72h).
5. **Hậu kiểm:** fold lesson vào Common Bug Patterns + đề xuất rule SEC mới lên Cairn upstream (cairn-learning issue).

---

## Cách project adopt file này

1. Copy `docs/SECURITY_BASELINE.md` vào repo project (cairn template đã kèm sẵn).
2. `CLAUDE.md §Security Rules` của project chỉ giữ 4-5 rule tóm tắt + pointer tới file này.
3. Project có rule riêng (vd HIPAA, PCI-DSS) → thêm section `## Project-specific` cuối file, KHÔNG sửa SEC-XX gốc.
4. Cairn upstream update baseline → docs-editor project fold diff về (xem `docs/CAIRN.md`).

---

*Cairn v0.7 · SEC rule mới từ incident thực tế → contribute ngược về `kevindo1103/cairn` qua cairn-learning issue.*
