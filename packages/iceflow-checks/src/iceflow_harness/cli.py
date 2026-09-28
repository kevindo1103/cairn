from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

from . import __version__
from .audio import inspect_audio
from .common import Refused, canonical, digest, finding, outside, parse_json, read_bytes, write_new
from .config import default_config, load_config
from .decisions import lint_document
from .gitview import GitView
from .github import ReadOnlyGitHub, render_pr_metadata
from .junit import inspect_junit
from .report import envelope, save_report
from .schema import check_database
from .sourcechecks import migration_graph, scan


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Iceflow Harness: executable checks, read-only observations; never authorization.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create external config; never touch the ERP tree")
    init.add_argument("--repo", type=Path, required=True)
    init.add_argument("--out", type=Path, default=Path("harness.local.yml"))
    for name in ["doctor", "scan", "pr", "schema", "audio", "export-probe", "schema-probe"]:
        q = sub.add_parser(name)
        q.add_argument("--config", type=Path, default=Path("harness.local.yml"))
        if name in {"scan", "schema", "audio", "export-probe", "schema-probe"}:
            q.add_argument("--ref", help="Read this commit/ref; does not checkout")
        if name == "pr":
            q.add_argument("--number", type=int, required=True)
        elif name == "schema":
            q.add_argument("--db", type=Path, required=True, help="Standalone offline copy, never a production path")
            q.add_argument("--offline-copy", action="store_true", required=True)
        elif name == "audio":
            q.add_argument("--asset-root", type=Path, required=True)
            q.add_argument("--binding", type=Path, required=True)
        elif name == "export-probe":
            q.add_argument("--out", type=Path, required=True)
        elif name == "schema-probe":
            q.add_argument("--image", required=True, help="Prebuilt local image, sha256:... only")
            q.add_argument("--allow-isolated-execution", action="store_true", required=True)
    junit = sub.add_parser("junit")
    junit.add_argument("--file", type=Path, required=True)
    junit.add_argument("--lane", required=True)
    junit.add_argument("--exit-code", type=int, required=True)
    junit.add_argument("--out", type=Path, default=Path("reports"))
    dec = sub.add_parser("decision-lint")
    dec.add_argument("--file", type=Path, required=True)
    dec.add_argument("--out", type=Path, default=Path("reports"))
    demo = sub.add_parser("demo")
    demo.add_argument("--out", type=Path, default=Path("demo-output"))
    return p


def run(args) -> int:
    if args.command == "init":
        view = GitView(args.repo)
        out = outside(args.out, view.root)
        cfg = default_config(view.root, out.parent / "reports")
        write_new(out, yaml.safe_dump(cfg, sort_keys=False).encode())
        print(json.dumps({"created": str(out), "mode": "observe", "source_sha": view.sha}))
        return 0
    if args.command == "demo":
        from .demo import run_demo
        print(json.dumps(run_demo(args.out), indent=2))
        return 0
    source, extra, target = None, None, None
    if args.command in {"junit", "decision-lint"}:
        output = args.out
        if args.command == "junit":
            findings = inspect_junit(args.file, args.lane, args.exit_code)
        else:
            findings = lint_document(read_bytes(args.file).decode("utf-8"))
    else:
        cfg = load_config(args.config)
        output, target = Path(cfg["output_dir"]), Path(cfg["repo_path"]).resolve()
        output = outside(output, target)
        if args.command == "pr":
            client = ReadOnlyGitHub(cfg["repository"], cfg["repository_id"], max_reads=cfg["max_api_reads"],
                                   deadline_seconds=cfg["api_deadline_seconds"])
            snapshot = client.pr_snapshot(args.number)
            extra = snapshot
            findings = [finding("K06", "PASS", "PR_METADATA_SNAPSHOT_COMPLETE",
                                details={"head_sha": snapshot["head_sha"], "changed_files": snapshot["changed_files"],
                                         "api_reads": snapshot["api_reads"], "ci_acceptance": "NOT_EVALUATED"})]
        else:
            view = GitView(target, getattr(args, "ref", None) or cfg["ref"])
            if args.command == "doctor":
                findings = [finding("DOCTOR", "PASS", "CONFIG_AND_COMMITTED_GIT_READABLE"),
                            finding("DOCTOR", "INFO", "READ_ONLY_COMMAND_SURFACE",
                                    details={"mode": "observe", "docker_available": shutil.which("docker") is not None,
                                             "token_effective_permissions": "NOT_ATTESTED"})]
            elif args.command == "scan":
                findings = scan(view, cfg)
            elif args.command == "schema":
                db = args.db.resolve()
                if any(db.is_relative_to(Path(p)) for p in ["/opt", "/var/lib", "/var/www"]) or db.is_relative_to(target):
                    raise Refused("LIVE_OR_REPO_DATABASE_REFUSED")
                migration_paths = [p for p in view.entries if p.startswith(cfg["migration_dir"] + "/") and p.endswith(".py")]
                graph = migration_graph({p: view.read(p) for p in migration_paths})
                findings = check_database(args.db, view.read(cfg["model_path"]), cfg["model_classes"], graph["heads"][0])
            elif args.command == "audio":
                findings = inspect_audio(args.asset_root, view.read("backend/modules/kds/tts.py"), parse_json(read_bytes(args.binding)))
            elif args.command == "export-probe":
                from .probe import export_probe
                export_probe(view, outside(args.out, target))
                print(json.dumps({"exported": str(args.out), "source_sha": view.sha, "executed": False}))
                return 0
            else:
                from .probe import run_probe
                findings = run_probe(view, cfg, args.image)
            source = view.source()
            if view.dirty:
                findings.append(finding("SOURCE", "WARN", "DIRTY_WORKTREE_EXCLUDED"))
    if source is not None:
        extra = dict(extra or {}, configuration_sha256=digest(canonical(cfg)),
                     candidate_coverage="COMMITTED_TREE_ONLY", test_execution="COMMAND_SPECIFIC")
    value = envelope(args.command, findings, source, extra)
    directory = save_report(value, output, target)
    if args.command == "pr":
        write_new(directory / "pr-metadata.md", render_pr_metadata(extra).encode())
    print(json.dumps({"outcome": value["outcome"], "authority": "NONE", "counts": value["counts"],
                      "report": str(directory / "report.html"), "json": str(directory / "report.json")}, ensure_ascii=True))
    if any(x["status"] == "FAIL" for x in findings):
        return 1
    if any(x["status"] == "BLOCKED" for x in findings):
        return 2
    return 0  # WARN/NOT_RUN remain explicit in JSON; never use this alone as an ERP gate.


def main(argv: list[str] | None = None) -> int:
    try:
        return run(parser().parse_args(argv))
    except Refused as exc:
        print(json.dumps({"outcome": "BLOCKED", "reason": exc.code, "authority": "NONE"}), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        print(json.dumps({"outcome": "BLOCKED", "reason": "INPUT_OR_ENVIRONMENT_ERROR", "authority": "NONE"}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"outcome": "BLOCKED", "reason": "INTERRUPTED", "authority": "NONE"}), file=sys.stderr)
        return 130
    except Exception:
        print(json.dumps({"outcome": "BLOCKED", "reason": "INTERNAL_CHECK_ERROR", "authority": "NONE"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
