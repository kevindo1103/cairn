# SPAWN_DEV — Dev Session Entry

> Đọc sau `docs/NEW_SESSION_INSTRUCTION.md`. Dành cho branch `windsurf/<...>`.
> Cairn framework component. Version: v0.7.

---

## ⚠️ Scope lock — BẮT BUỘC

Bạn **chỉ sửa file trong scope team của mình** (xem `CLAUDE.md → Session Topology → Pair table`).

- Task cần file ngoài scope → **DỪNG** → báo lead qua comment trong issue.
- Tự mở rộng scope = **FM-16** (role drift). Báo "done" với artifact không tồn tại = **FM-17**.
- Mọi claim "pushed / opened PR" phải kèm PR URL hoặc branch link (**P-10**).

---

## Kickoff sequence

```
1. Xác nhận đang trên branch windsurf/<...>   ← KHÔNG code trên claude/ hoặc main
2. git pull origin main                        ← sync trước khi branch
3. Bước 0: list issues for:<my-team> state:open  ← đọc inbox
4. Đọc task-assignment issue được assign       ← confirm plan trước khi code
5. Comment "Confirmed plan. Branch: windsurf/<x> (forked from origin/main verified). ETA: <y>."
6. Code → test local → push PR
```

---

## NGHIÊM CẤM

| Không được | Lý do |
|------------|-------|
| Merge PR của mình | Lead phải review trước |
| Push lên `claude/<...>` hoặc `main` | Scope của lead / protected |
| Tự ghi vào `docs/DOCS_INBOX.md` | Lead ghi, dev báo lead biết |
| Code khi plan chưa confirmed | Plan-action decoupling → sai spec |
| Sửa file ngoài scope team | FM-16 |

---

## Local-first rule (~70-80% fix)

Sửa code → verify local TRƯỚC khi push PR. Staging chỉ cho integration test không thể local:
- Scheduler / cron jobs
- Multi-tenant / external service thật
- Environment-specific config

---

## Trách nhiệm Dev

| Làm | Không làm |
|-----|-----------|
| Code theo plan trong task-assignment issue | Tự quyết spec khi ambiguous — hỏi lead |
| Push branch `windsurf/...`, mở PR với lead as reviewer | Tự merge, tự approve |
| Báo lead khi xong để lead ghi DOCS_INBOX | Tự ghi DOCS_INBOX |
| Trước push: `git fetch origin && git log <file> --oneline -10` (check trùng file) | Assume không ai đang sửa cùng file |

---

## P-10 — khi report done

```
# Comment trong task issue:
Done. PR: https://github.com/<org>/<repo>/pull/<n>
Branch: windsurf/<x>
Tested: <how — local / staging URL>
```

---

## §0a. Partial-read discipline (BẮT BUỘC)

Doc lớn — đọc theo **section anchor** (`§4.2`, `§3.1`), KHÔNG full file trừ khi < 200 dòng.

---

*Cairn v0.7. Thay `{{PLACEHOLDER}}` khi bootstrap.*
