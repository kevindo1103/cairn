# Canonical Docs — Skeleton Guide

> Cairn cung cấp STRUCTURE; nội dung viết riêng per project. Tạo 4 file dưới đây trong `docs/`, xoá file `_CANONICAL_DOCS_SKELETON.md` này sau khi xong.

---

## docs/MASTER_BRD.md

```markdown
# {{PROJECT_NAME}} — Master BRD
**Version:** v1.0 · **Last updated:** {{DATE}}

## 1. Product Overview
## 2. Stakeholders & Roles
## 3. User Journeys
## 4. Functional Requirements
## 5. Business Rules (D-rules — locked decisions)
## 6. Screen Inventory
## Changelog
| Version | Date | Changes |
```

## docs/SRS.md

```markdown
# {{PROJECT_NAME}} — SRS
**Version:** v1.0 · **Last updated:** {{DATE}}

## 1. Architecture Overview
## 2. Data Model / Schema
## 3. API Endpoints
## 4. Module Specs
## 5. Auth & Security
## Changelog
```

## docs/DOMAIN_GLOSSARY.md

```markdown
# {{PROJECT_NAME}} — Domain Glossary
**Version:** v1.0

## Ubiquitous Language
| Term | UI label | DB name | API route | Definition |
## Changelog
```

## docs/PROJECT_PLAN.md

```markdown
# {{PROJECT_NAME}} — Project Plan
**Version:** v1.0 · **Last updated:** {{DATE}}

## Tổng quan dự án
## Trạng thái hiện tại
## Phase Map
## Decisions Log
| Date | Decision | Value | Owner |
## Changelog
```

---

## Cascade order (docs-editor fold)

**BRD → SRS → Glossary → PROJECT_PLAN → Mockup**

Thay đổi business → BRD trước. SRS derive từ BRD. Glossary sync term. PLAN track sprint. Mockup cuối.

---

*Cairn v0.1. Xoá file này sau khi tạo 4 canonical docs.*
