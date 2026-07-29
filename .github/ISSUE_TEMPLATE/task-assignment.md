---
name: Task Assignment
about: Lead giao task cho dev session (Cairn comms Pattern 1)
title: "[<Team>] "
labels: task-assignment, status:planned
---

## Context
<2-3 dòng background — tại sao task này cần làm>

## Plan (lead viết — dev confirm trước khi code)
1. Branch: `<type>-<scope>-<desc>` from `origin/main`
2. Files touched: <paths>
3. Schema changes: <NONE / list>
4. Test plan: <cách verify>

## Acceptance Criteria (định nghĩa "done" — lead viết, PR review đối chiếu từng dòng)
- [ ] <criterion đo được — vd: POST /x trả 200 với payload hợp lệ, 403 khi sai role>
- [ ] <criterion — vd: UI khớp mockup §Y, mobile 375px không vỡ layout>
- [ ] Không regression: <screen/endpoint liên quan vẫn hoạt động>

## Ask
<cụ thể cần làm gì>

## Refs
- <spec section / commit / related issue>

<!-- Labels: thêm 1 from:<lead> + 1 for:<dev> theo topology dự án. -->
<!-- Dev BẮT BUỘC confirm trước khi code: -->
<!-- "Confirmed plan + AC. Branch: <x> (forked from origin/main verified). ETA: <y>." -->
<!-- Plan/AC ambiguous → hỏi lead, KHÔNG code đoán. -->
<!-- Lead review PR: đối chiếu TỪNG AC, tick hết mới merge. AC không đạt được → dev comment đề xuất sửa AC, KHÔNG tự nới. -->
