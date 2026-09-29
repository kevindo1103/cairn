from __future__ import annotations

import html
import json
import uuid
from collections import Counter
from pathlib import Path

from . import __version__
from .common import canonical, digest, outside, utc_now, write_new

OWNERS = {"F00": "ERP_Docs", "K01": "ERP_Infra", "K02": "QC + ERP_Infra", "K03": "Test owner + QC",
          "K04": "Backend + ERP_Infra", "K04B": "Backend + QC", "K04_GRAPH": "Backend",
          "K05": "ERP_Infra + KDS", "K05_SOURCE": "ERP_Infra", "K06": "PR owner", "K07": "Backend", "K08": "Frontend + QC"}


def envelope(command: str, findings: list[dict], source: dict | None = None, extra: dict | None = None) -> dict:
    counts = dict(Counter(f["status"] for f in findings))
    if counts.get("FAIL"):
        outcome = "FAIL"
    elif counts.get("BLOCKED"):
        outcome = "BLOCKED"
    elif counts.get("NOT_RUN") or counts.get("WARN"):
        outcome = "PARTIAL"
    else:
        outcome = "CHECKED_SCOPE_ONLY"
    value = {"schema": "iceflow-harness-report-v1", "version": __version__, "command": command,
             "created_at": utc_now(), "mode": "observe", "authority": "NONE", "outcome": outcome,
             "counts": counts, "source": source, "findings": findings,
             "release_ready": "NOT_EVALUATED", "effective_permissions": [],
             "notices": ["Report only: no source edits, GitHub writes or release permission.",
                         "Static heuristics and supplied evidence do not prove runtime health."]}
    if extra:
        value["extra"] = extra
    value["report_digest_sha256"] = digest(canonical(value))
    return value


def render_markdown(value: dict) -> str:
    lines = ["# Iceflow Harness — " + value["outcome"], "", "Mode: observe · Authority: NONE · Release: NOT_EVALUATED", "",
             "```json", json.dumps(value.get("source"), indent=2), "```", "", "## Findings", ""]
    for item in value["findings"]:
        location = item.get("path", "") + (":" + str(item["line"]) if "line" in item else "")
        lines += [f"### {item['check']} / {item['status']} / {item['code']}",
                  "Location: " + json.dumps(location, ensure_ascii=True),
                  "Owner suggestion: " + OWNERS.get(item["check"], "Existing task owner"), ""]
        if "details" in item:
            lines += ["```json", json.dumps(item["details"], indent=2, ensure_ascii=True), "```", ""]
    return "\n".join(lines)


def render_html(value: dict) -> str:
    # No JS, network requests, remote font/CDN, unsafe HTML or arbitrary links.
    cards = []
    for f in value["findings"]:
        details = json.dumps(f.get("details", {}), indent=2, ensure_ascii=False)
        cards.append(f'<article><span class="tag">{html.escape(f["status"])}</span><h3>{html.escape(f["check"])} · {html.escape(f["code"])}</h3>'
                     f'<p>{html.escape(f.get("path", ""))} {f.get("line", "")}</p><details><summary>Evidence / limits</summary><pre>{html.escape(details)}</pre></details></article>')
    sha = (value.get("source") or {}).get("commit_sha", "Input evidence")
    return '<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' \
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">' \
        '<title>Iceflow Harness report</title><style>body{font:16px system-ui;background:#f1f5f9;color:#142330;max-width:1050px;margin:40px auto;padding:20px}header,article{background:white;border:1px solid #d9e2ec;border-radius:16px;padding:24px;margin:14px 0}h1{font-size:36px;margin:8px 0}h3{overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f8fa;padding:18px;border-radius:10px}.tag{float:right;background:#e5edf6;padding:6px 12px;border-radius:20px}small{color:#526576}</style>' \
        f'<header><small>ICEFLOW / ENGINEERING HARNESS v{__version__}</small><h1>{html.escape(value["outcome"])}</h1><p>Chỉ quan sát · Không cấp quyền · Không phải release gate</p><pre>{html.escape(str(sha))}</pre><p>{html.escape(json.dumps(value["counts"]))}</p></header>' + "".join(cards) + '</html>'


def save_report(value: dict, output: Path, repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        output = outside(output, repo_root)
    directory = output / (value["command"] + "-" + uuid.uuid4().hex[:12])
    write_new(directory / "report.json", json.dumps(value, indent=2, ensure_ascii=False).encode())
    write_new(directory / "summary.md", render_markdown(value).encode())
    write_new(directory / "report.html", render_html(value).encode())
    return directory
