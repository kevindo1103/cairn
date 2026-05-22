# CAIRN.md — Dự án này chạy trên Cairn framework

> File pointer — GIỮ LẠI trong dự án sau khi bootstrap. Mọi session đọc khi cần hiểu framework.

---

## Dự án này dùng Cairn

**Cairn** = framework điều phối multi-agent (Lead/Dev topology · Docs Ownership Protocol · GitHub Issues bus · lessons-as-rules).

- **Cairn version khi bootstrap:** `{{CAIRN_VERSION}}` (vd v0.1)
- **Cairn framework repo:** `{{CAIRN_STARTER_REPO_URL}}`
- **Framework knowledge tree:** `{{CAIRN_STARTER_REPO_URL}}/blob/main/CAIRN_KNOWLEDGE.md`

Cách Cairn vận hành trong dự án này: xem `CLAUDE.md` + `docs/NEW_SESSION_INSTRUCTION.md` + `docs/SESSION_COMMS.md`.

---

## Contribute learning ngược về Cairn

Khi bạn (đặc biệt docs-editor) phát hiện một **framework-level learning** trong lúc làm việc:

- 1 failure mode mới chưa có trong `CAIRN_KNOWLEDGE.md §2`
- 1 pattern hiệu quả đáng nhân rộng
- 1 chỗ protocol Cairn cần sửa / chưa rõ
- 1 gap TIER-3 có cách giải mới

→ **File issue against repo Cairn framework** (`{{CAIRN_STARTER_REPO_URL}}`):

```
Labels: cairn-learning
Title: [Cairn Learning] <short>
Body:
  ## Context
  <dự án nào, tình huống nào>

  ## Learning
  <điều rút ra — framework-level, không project-specific>

  ## Đề xuất sửa Cairn
  <pattern mới / failure mode mới / protocol fix — hoặc "chỉ ghi nhận">
```

Cairn maintainer fold vào `CAIRN_KNOWLEDGE.md` → bump Cairn version.

**Phân biệt quan trọng:**
- Learning **project-specific** (bug logic, schema dự án này) → `docs/DOCS_INBOX.md` của dự án.
- Learning **framework-level** (Cairn nên làm X) → `cairn-learning` issue về Cairn repo.

Nếu phân vân → mặc định project-specific. Chỉ escalate lên Cairn khi chắc chắn áp dụng được cho dự án khác.

---

## Cairn version của dự án này

Cairn là single-source-of-truth ở repo framework — dự án KHÔNG copy `CAIRN_KNOWLEDGE.md`. Khi Cairn ra version mới có pattern/fix đáng adopt → docs-editor quyết định pull update nào vào (CLAUDE.md, SESSION_COMMS, v.v.) + ghi vào DOCS_INBOX.

---

*Cairn pointer. Thay `{{CAIRN_VERSION}}` + `{{CAIRN_STARTER_REPO_URL}}` khi bootstrap.*
