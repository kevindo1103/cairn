# DOCS_INBOX — Pending Doc Updates

> **Mục đích:** Hàng đợi để các session báo cáo thay đổi cần phản ánh vào canonical docs.
> Toàn bộ `docs/` + root `*.md` do **một session docs-editor** quản lý (branch `claude/edit-git-docs-{{DOCS_ID}}`).
> Xem `CLAUDE.md → Docs Ownership Protocol`.

---

## Quy tắc

**Session khác (không phải docs-editor):**
- KHÔNG sửa trực tiếp `docs/` hoặc root `*.md`.
- Sau thay đổi ảnh hưởng business rule / schema / API / UI / deploy / known bug → thêm 1 report vào `## Pending`.
- **POST-MERGE RULE:** PR merge `main` (hoặc `staging` cho spec-impact) → MUST append 1 Pending report trong 24h.
- Mỗi report là 1 entry độc lập, append cuối `## Pending`.
- ⚠️ Chỉ MỘT `DOCS_INBOX.md` canonical — branch docs. Không tạo bản trên branch khác.

**Session docs-editor:**
- Fold từng report → canonical docs theo cascade BRD → SRS → Glossary → Plan → Mockup.
- Cập nhật version + changelog.
- Chuyển report đã xử lý xuống `## Processed`.

---

## Report template

```
### <YYYY-MM-DD> — <session / branch>
- **Đã đụng:** <file / module / area>
- **Thay đổi:** <tóm tắt cái gì + tại sao>
- **Docs cần cập nhật:** <BRD §x / SRS §y / Glossary / ... — hoặc "chưa rõ">
- **Ambiguity / cần PM xác nhận:** <nếu có, hoặc "none">
```

---

## Weekly Review (BẮT BUỘC — docs-editor own)

> **Mục đích:** Catch friction từ kanban workflow trước khi tích lũy. Run mỗi **Monday** (hoặc đầu session docs-editor nếu > 7 ngày từ review cuối, hoặc chưa có log nào).
>
> **Owner:** docs-editor session. Run TRƯỚC khi fold task khác.
>
> **Format:** Append vào `## Weekly Review Log`. Mỗi finding actionable → tạo issue.

### Checklist (9 items)

1. **Stale `status:planned`** > 3 ngày untouched → ping lead.
2. **`task-assignment` thiếu `## Plan`** → request lead bổ sung.
3. **`blocker:human-needed`** > 24h → highlight cho user.
4. **PR merged staging mà issue chưa close** → manual close (`Closes #N` chỉ auto khi target main).
5. **STATE.md stale** > 7 ngày (khi team có PR trong tuần) → ping lead.
6. **DOCS_INBOX Pending** > 7 ngày unfolded → force fold hoặc ping reporter.
7. **Pair scope violation** — commit ngoài team scope → log incident.
8. **`for:*` label routing mismatch** → relabel.
9. **Rule Promotion candidates (P-09)** — scan rule vi phạm tuần này: rule nào vi phạm lặp lại HOẶC gây critical incident → đánh giá promote C-5→C-6 (mechanizable → file task xây gate; không-mechanizable-critical → QC scope; rule sai → retire). Rule thuần phán đoán bloat → consolidate/retire (Path B).

### Weekly Review Log

```markdown
### YYYY-MM-DD — docs-editor weekly review
**Findings:** ✅ items clean / ⚠️ item N: <detail>
**Actions:** <closed #M / pinged X / created #Y>
**Trend:** <pattern nếu có>
```

---

## Pending

_(report append bên dưới)_

---

## Processed

| Ngày xử lý | Report (ngày — session) | Docs đã cập nhật | Ghi chú |
|------------|-------------------------|------------------|---------|
| — | — | — | _(khởi tạo Cairn template)_ |
