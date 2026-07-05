# SPAWN_DOCS_EDITOR — Docs-Editor Session Entry

> Đọc sau `docs/NEW_SESSION_INSTRUCTION.md`. Dành cho branch `claude/edit-git-docs-<id>`.
> Cairn framework component. Version: v0.7.

---

## ⚠️ Scope lock — BẮT BUỘC

Bạn **chỉ sửa `docs/**` + root `*.md`**. KHÔNG sửa code, KHÔNG sửa `.github/workflows/`.

- FM-16 từng xảy ra thật: docs-editor session mở rộng scope sang backend/frontend code.
- Nếu fold task cần thay đổi code → file task-assignment issue cho team đúng, KHÔNG tự làm.
- Mọi commit phải kèm `git log <hash> --oneline` hoặc diff link (**P-10**).

---

## Kickoff sequence

```
1. Đọc CLAUDE.md                          ← topology, protocols, rules
2. Check Weekly Review (xem §Weekly Review bên dưới)
3. Bước 0: list issues for:docs-editor state:open   ← đọc inbox report
4. Đọc docs/DOCS_INBOX.md §Pending        ← queue report cần fold
5. Fold theo cascade (xem §Fold workflow)
```

---

## §Weekly Review — BẮT BUỘC

Đầu mỗi session docs-editor, check xem last review > 7 ngày hoặc hôm nay là Monday.
Nếu có → chạy checklist 8 items TRƯỚC khi fold task khác:

1. Tất cả Pending reports trong DOCS_INBOX đã có plan xử lý chưa?
2. TEAM_STATE files của tất cả teams có được update gần đây không?
3. Canonical docs (BRD/SRS/Glossary) có version lag so với code đã merge không?
4. Issue kanban có issue nào stuck ở `status:in-progress` quá 5 ngày không?
5. Có `cairn-learning` issue nào chưa fold vào CAIRN_KNOWLEDGE.md không? (framework repo)
6. Có pattern lặp lại trong reports → candidate cho `Common Bug Patterns` trong CLAUDE.md?
7. Post-merge rule violation: có PR merge mà không có DOCS_INBOX report trong 24h không?
8. Danh sách docs bị ảnh hưởng: có gì cần update mà chưa vào queue không?

Append findings vào `## Weekly Review Log` trong `docs/DOCS_INBOX.md`. Finding actionable → tạo issue.

---

## §Fold workflow

**Cascade order (BẮT BUỘC):** BRD → SRS → Glossary → PROJECT_PLAN → Mockup

```
1. Đọc report trong DOCS_INBOX §Pending
2. Locate section cần update (partial-read — xem §anchor, không full file)
3. Fold nội dung: update canonical doc, bump version + append changelog entry
4. Chuyển report từ §Pending → §Processed (kèm version docs kết quả)
5. TRƯỚC git commit: invoke skill /doc-fold-reflection (checklist 7 items)
6. Commit + push
7. Reply issue DOCS_INBOX Relay: "✅ Folded — <docs/version>"
```

---

## Trách nhiệm Docs-Editor

| Làm | Không làm |
|-----|-----------|
| Fold report từ DOCS_INBOX vào canonical docs | Sửa code / .github/workflows |
| Bump version + changelog mỗi file bị ảnh hưởng | Self-decide ambiguity — nêu trong processed report |
| Move report Pending → Processed | Merge PR của session khác |
| Chạy `/doc-fold-reflection` trước mỗi commit docs lớn | Tạo DOCS_INBOX.md trên branch khác |
| Reply issue DOCS_INBOX Relay sau fold | Resolve conflict code — escalate lead |

---

## DOCS_INBOX report template (để nhận từ các session khác)

```
### <YYYY-MM-DD> — <session / branch>
- PR / trigger: #<số> → <base branch>
- Đã đụng: <file / module / area>
- Thay đổi: <tóm tắt>
- Docs cần cập nhật: <BRD §x / SRS §y / Glossary / PROJECT_PLAN / CLAUDE.md / "chưa rõ">
- Ambiguity / cần PM xác nhận: <nếu có, hoặc "none">
```

---

*Cairn v0.7. Thay `{{PLACEHOLDER}}` khi bootstrap.*
