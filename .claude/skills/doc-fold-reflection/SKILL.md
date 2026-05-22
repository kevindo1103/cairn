---
name: doc-fold-reflection
description: Use before committing canonical doc changes (BRD, SRS, Glossary, DS, PROJECT_PLAN). Verifies cascade consistency, cross-references, version bumps, DOCS_INBOX hygiene. Invoke after Edit/Write to any canonical doc — BEFORE git commit.
---

# Doc Fold Reflection — Pre-commit consistency check

> Cairn framework component. Reflection pattern — catch cascade drift TRƯỚC commit, không để session sau phải fix.
> For docs-editor sessions khi fold cascade BRD → SRS → Glossary → Plan → Mockup.

## When to invoke

Sau Edit/Write vào canonical doc (`docs/MASTER_BRD.md`, `docs/SRS.md`, `docs/DOMAIN_GLOSSARY.md`, `docs/UI_UX_DESIGN_SYSTEM.md`, `docs/PROJECT_PLAN.md`), BEFORE `git commit`.

NOT needed cho: DOCS_INBOX entries, README, operational docs, mockup `.jsx`, BA draft.

## Reflection Checklist

Mỗi item: output ✅/❌ + 1-dòng evidence. Bất kỳ ❌ → fix trước commit.

### 1. Version + Date bump
- [ ] File header version tăng
- [ ] Last updated = today
- [ ] Changelog row mới với version + date + summary

### 2. Changelog summary quality
- [ ] Mô tả WHAT changed, không chỉ "bump version"
- [ ] Reference issue/PR/DOCS_INBOX source
- [ ] Mention breaking change / locked decision nếu có

### 3. Cross-reference integrity
- [ ] D-rule/business-rule added → grep SRS có reference không
- [ ] Schema added SRS → BRD screen inventory + GLOSSARY term defined
- [ ] Endpoint added → CLAUDE.md API section nếu frontend-relevant
- [ ] Term renamed GLOSSARY → grep ALL docs cho tên cũ
- [ ] Pattern added DS → CLAUDE.md cheat sheet nếu rule-level

### 4. Cascade order respected
- [ ] Changes follow BRD → SRS → GLOSSARY → DS → Mockup (no skip)
- [ ] SRS update mà không update BRD upstream → derivation (OK) hay drift (BAD)?

### 4b. Doc size threshold (Context L2 trigger)
- [ ] `wc -l` các canonical doc lớn sau fold
- [ ] Doc vượt ngưỡng navigability (~6000 dòng) → cân nhắc build SUMMARY layer (xem CAIRN_SETUP §TIER-3)
- [ ] Chưa vượt → ghi line count vào commit message để track trend

### 5. DOCS_INBOX hygiene
- [ ] Source DOCS_INBOX entry tồn tại
- [ ] Sau fold: move entry `## Pending` → `## Processed` với date + docs/versions

### 6. PROJECT_PLAN sync
- [ ] Sprint completed → mark `[DONE]` Phase Map + changelog row
- [ ] Status table doc versions khớp file hiện tại

### 7. CLAUDE.md sync
- [ ] Bug pattern mới → CLAUDE.md Common Bug Patterns
- [ ] D-rule change → CLAUDE.md business rules
- [ ] API field change → CLAUDE.md API section
- [ ] New canonical doc → CLAUDE.md source-of-truth list

## Output format

```
## Reflection Result
| # | Check | Status | Evidence/Action |
|---|-------|--------|-----------------|
| 1 | Version bump | ✅ | vX → vY |
| 3 | Cross-references | ❌ | <rule> mentioned BRD missing SRS reference |
...
## Actions needed before commit
1. <fix>
## Approved for commit? YES / NO
```

## Failure mode prevented

**Không có skill:** fold thiếu — BRD update rule mới nhưng SRS không reference → session sau ship broken feature. Class: cascade drift.

**Có skill:** catch trước commit, fix 5 phút, save 1-2h downstream debug.

---

*Cairn v0.1 template skill. Update checklist khi thêm doc type hoặc gặp failure mode mới.*
