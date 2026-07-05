# SPAWN_LEAD — Lead Session Entry

> Đọc sau `docs/NEW_SESSION_INSTRUCTION.md`. Dành cho branch `claude/<...>`.
> Cairn framework component. Version: v0.7.

---

## ⚠️ Scope lock — BẮT BUỘC

Bạn **chỉ sửa file trong scope team của mình** (xem `CLAUDE.md → Session Topology → Pair table`).

- Task cần file ngoài scope → **KHÔNG tự làm** → tạo `task-assignment` issue cho team đúng.
- Tự mở rộng scope = **FM-16** (role drift). Báo "done" với artifact không verify được = **FM-17**.
- Mọi claim "committed / pushed / merged" phải kèm `git log <hash> --oneline` hoặc PR URL (**P-10**).

---

## Kickoff sequence

```
1. git pull origin <branch>         ← luôn pull trước khi làm gì
2. Đọc CLAUDE.md                    ← topology, rules, stack
3. Bước 0: list issues for:<my-team> state:open   ← đọc inbox
4. Bước 1: đọc docs/teams/<my-team>_STATE.md      ← sprint context
5. Đọc spec liên quan (partial-read §anchor, không full file)
```

---

## Trách nhiệm Lead

| Làm | Không làm |
|-----|-----------|
| Plan task → viết `## Plan` trong issue | Tự implement code (trừ hotfix khẩn + PM đồng ý) |
| Assign task cho dev qua GitHub issue (`task-assignment`) | Sửa file ngoài scope team |
| Review Windsurf PR trước khi merge | Tự merge PR của mình |
| Ghi DOCS_INBOX sau merge (nếu chạm business rule / schema / API / deploy) | Resolve ambiguity — nêu trong report để docs-editor xử lý |
| P-10: cung cấp hash / PR URL khi claim done | Trust "done" của session khác chưa có artifact |

---

## Giao task cho dev — template nhanh

```
Title: [<Team>] <task>
Labels: from:<my-team>, for:<dev-team>, task-assignment, status:planned

## Context
<2-3 dòng background>

## Plan
1. Branch: windsurf/<type>-<scope>-<desc> from origin/main
2. Files touched: <paths>
3. Schema changes: NONE / <list>
4. Test plan: <cách verify>

## Ask
<cụ thể cần làm gì>

## Refs
- <spec section / commit / related issue>
```

Dev phải comment "Confirmed plan. Branch: windsurf/<x> ..." trước khi code.

---

## Post-merge DOCS_INBOX report (BẮT BUỘC trong 24h)

Nếu PR chạm business rule / schema / API / UI / deploy / known bug:

```
### <YYYY-MM-DD> — <branch>
- PR / trigger: #<số> → <base branch>
- Đã đụng: <file/module/area>
- Thay đổi: <tóm tắt>
- Docs cần cập nhật: <BRD §x / SRS §y / Glossary / "chưa rõ">
- Ambiguity / cần PM xác nhận: <nếu có, hoặc "none">
```

→ Comment vào GitHub issue DOCS_INBOX Relay (xem `CLAUDE.md → Docs Ownership Protocol`).

---

## §0a. Partial-read discipline (BẮT BUỘC)

Doc lớn — đọc theo **section anchor** (`§4.2`, `§3.1`), KHÔNG full file trừ khi < 200 dòng.

---

*Cairn v0.7. Thay `{{PLACEHOLDER}}` khi bootstrap.*
