"""Opt-in disposable Docker migration probe; never launch target code on the host."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import uuid
from importlib.resources import files
from pathlib import Path

from .common import Refused, finding, outside, parse_json, write_new
from .sourcechecks import migration_graph
from .coverage import inspect_model_scope, scope_findings
from .probe_protocol import validate_result


def export_probe(view, destination: Path) -> None:
    destination = outside(destination, view.root)
    if destination.exists():
        raise Refused("OUTPUT_EXISTS")
    selected = [p for p in view.entries if p.startswith("backend/") and
                p.endswith((".py", ".ini", ".txt", ".json")) and
                not any(x.startswith(".env") or x in {"tenants", "static", "uploads", "secrets", "credentials"}
                        for x in p.split("/"))]
    if not selected or "backend/requirements.txt" not in selected:
        raise Refused("PROBE_SOURCE_INCOMPLETE")
    view.preload(selected)
    for p in selected:
        write_new(destination / p, view.read(p))
    worker = files("iceflow_harness.data").joinpath("probe_worker.py.txt").read_bytes()
    write_new(destination / "probe_worker.py", worker)
    protocol = files("iceflow_harness").joinpath("probe_protocol.py").read_bytes()
    write_new(destination / "probe_protocol.py", protocol)
    dockerfile = b'''FROM python:3.11-slim
COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /work
USER 65534:65534
'''
    write_new(destination / "Dockerfile", dockerfile)
    write_new(destination / "SOURCE.json", json.dumps(view.source(), indent=2).encode())


def docker_command(image: str, source: Path, name: str) -> list[str]:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image):
        raise Refused("PROBE_IMAGE_DIGEST_REQUIRED")
    if "," in str(source) or not re.fullmatch(r"iceflow-probe-[0-9a-f]{32}", name):
        raise Refused("PROBE_ARGUMENT_INVALID")
    return ["docker", "run", "--rm", "--pull=never", "--name", name,
            "--label", "iceflow-harness.probe=true", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true", "--pids-limit=64", "--memory=2g", "--cpus=2",
            "--user=65534:65534", "--tmpfs", "/work:rw,exec,nosuid,nodev,size=1g,mode=1777",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777",
            "--mount", f"type=bind,src={source},dst=/src,readonly", image, "python", "/src/probe_worker.py"]


def run_probe(view, cfg: dict, image: str) -> list[dict]:
    expected, coverage = inspect_model_scope(view.read(cfg["model_path"]), cfg["model_classes"])
    if coverage["unsupported"]:
        return scope_findings(coverage)  # Refuse unsupported source before executing it.
    by_table = {item["table"]: item["model"] for item in coverage["resolved"]}
    migration_paths = [p for p in view.entries if p.startswith(cfg["migration_dir"] + "/") and p.endswith(".py")]
    graph = migration_graph({p: view.read(p) for p in migration_paths})
    env = {k: v for k, v in os.environ.items() if k not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    name = "iceflow-probe-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="iceflow-probe-") as temp:
        # Parent must be traversable by container non-root user; contains only exported source.
        os.chmod(temp, 0o755)
        target = Path(temp) / "snapshot"
        export_probe(view, target)
        command = docker_command(image, target, name)
        try:
            result = subprocess.run(command, capture_output=True, timeout=210, env=env, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Refused("DOCKER_PROBE_UNAVAILABLE_OR_TIMEOUT") from exc
        finally:
            # This exact random name belongs to this invocation, never a production container.
            try:
                cleanup = subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15, env=env, check=False)
                # The --rm container may already be gone. A remaining container is never hidden.
                if cleanup.returncode != 0:
                    remaining = subprocess.run(
                        ["docker", "container", "ls", "--all", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"],
                        capture_output=True, timeout=10, env=env, check=False)
                    if remaining.returncode != 0 or remaining.stdout.strip():
                        raise Refused("PROBE_CLEANUP_UNCONFIRMED")
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise Refused("PROBE_CLEANUP_UNCONFIRMED") from exc
        if result.returncode != 0 or len(result.stdout) > 2 * 1024 * 1024:
            raise Refused("DOCKER_PROBE_FAILED")
        try:
            value = validate_result(parse_json(result.stdout))
        except ValueError as exc:
            raise Refused("DOCKER_PROBE_RESULT_INVALID") from exc
        if value.get("status") != "MIGRATED":
            return [finding("K04B", "BLOCKED", "MIGRATION_SETUP_FAILED_NO_PARITY_VERDICT",
                            details={"image": image, "source_sha": view.sha,
                                     "bootstrap_mode": "EMPTY_DATABASE_REQUESTED",
                                     "auto_ddl_fallback": False, "parity_evaluated": False,
                                     "worker_status": value["status"],
                                     "diagnostic": value["diagnostic"],
                                     "host_database_access": False, "authority": "NONE"})]
        if not isinstance(value.get("tables"), dict) or value.get("revisions") != graph["heads"]:
            raise Refused("PROBE_REVISION_MISMATCH")
        output = [finding("K04", "PASS", "REVISION_MATCH",
                          details={"expected_revisions": graph["heads"],
                                   "observed_revisions": value["revisions"]})]
        for table, expected_columns in expected.items():
            actual = value["tables"].get(table, [])
            if not isinstance(actual, list) or not all(isinstance(x, str) for x in actual):
                raise Refused("PROBE_COLUMNS_INVALID")
            missing = sorted(set(expected_columns) - set(actual))
            output.append(finding("K04B", "FAIL" if missing else "PASS",
                                  "MODEL_MIGRATION_MISMATCH" if missing else "EMPTY_DB_MIGRATION_COLUMNS_PRESENT",
                                  details={"model": by_table[table], "table": table, "missing_columns": missing,
                                           "inspected_column_names": expected_columns, "image": image,
                                           "source_sha": view.sha, "revisions": graph["heads"],
                                           "host_database_access": False, "authority": "NONE",
                                           "source_code_executed_in_disposable_container": True,
                                           "types_constraints_indexes": "NOT_CHECKED",
                                           "adversarial_source_attestation": "NOT_PROVEN"}))
        output.extend(scope_findings(coverage))
        return output
