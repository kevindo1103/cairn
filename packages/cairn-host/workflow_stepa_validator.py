"""Bounded offline validator for the ERP #1632 StepA workflow edit."""
from __future__ import annotations
import argparse, re, subprocess, tempfile
from pathlib import Path
import yaml

JOB = "backend-tests"
EXPECTED_IF = ("github.event_name == 'pull_request' && "
               "needs.branch-name.outputs.backend == 'true' && "
               "needs.branch-name.outputs.tier == 'full'")
EVENTS = ("pull_request", "push", "workflow_dispatch")
BACKENDS = ("true", "false")
TIERS = ("full", "smoke")

def _bash():
    if Path(r"C:\Program Files\Git\bin\bash.exe").exists():
        return r"C:\Program Files\Git\bin\bash.exe"
    return "bash"

def _workflow(path):
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), dict):
        raise ValueError("workflow has no jobs mapping")
    job = value["jobs"].get(JOB)
    if not isinstance(job, dict):
        raise ValueError(f"missing {JOB} job")
    return job

def _run_body(job):
    for step in job.get("steps", []):
        if (isinstance(step, dict) and isinstance(step.get("name"), str)
                and "compare failing set against base" in step["name"]):
            body = step.get("run")
            if not isinstance(body, str):
                raise ValueError("comparison step has no run body")
            return body
    raise ValueError("comparison step missing")

def _condition(value):
    if not isinstance(value, str):
        raise ValueError("backend-tests.if is not a string")
    atoms = [part.strip() for part in value.split("&&")]
    expected = [part.strip() for part in EXPECTED_IF.split("&&")]
    if atoms != expected:
        raise ValueError("backend-tests.if differs from approved StepA condition")
    return atoms

def _evaluate(atoms, event, backend, tier):
    values = {
        "github.event_name": event,
        "needs.branch-name.outputs.backend": backend,
        "needs.branch-name.outputs.tier": tier,
    }
    for atom in atoms:
        name, literal = [part.strip() for part in atom.split("==", 1)]
        if name not in values or literal not in {"'pull_request'", "'true'", "'full'"}:
            raise ValueError("unsupported condition atom")
        if values[name] != literal[1:-1]:
            return False
    return True

def _approved_body_delta(base, candidate):
    removed = re.compile(
        r"(^|\n)if \[ \"\$\{\{ github\.event_name \}\}\" != \"pull_request\" \]; then\n"
        r".*?\nfi\n\n?", re.DOTALL)
    expected = removed.sub(lambda match: match.group(1), base, count=1)
    if expected == base:
        raise ValueError("approved non-PR guard was not found in base run body")
    if candidate != expected:
        raise ValueError("comparison shell body has an unapproved change")

def validate(base_path, candidate_path):
    base_job, candidate_job = _workflow(base_path), _workflow(candidate_path)
    atoms = _condition(candidate_job.get("if"))
    _approved_body_delta(_run_body(base_job), _run_body(candidate_job))
    matrix = {f"{event}/{backend}/{tier}": _evaluate(atoms, event, backend, tier)
              for event in EVENTS for backend in BACKENDS for tier in TIERS}
    if sum(matrix.values()) != 1 or not matrix["pull_request/true/full"]:
        raise ValueError("event/backend/tier condition matrix mismatch")
    with tempfile.TemporaryDirectory(prefix="cairn-stepa-") as temp:
        shell = Path(temp) / "comparison.sh"
        shell.write_text(_run_body(candidate_job), encoding="utf-8")
        result = subprocess.run([_bash(), "-n", shell.name], cwd=temp,
                                capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise ValueError(f"bash -n rejected extracted run body: {result.stderr.strip()}")
    return {"job": JOB, "condition": EXPECTED_IF, "matrix": matrix,
            "shell_delta": "removed approved non-PR early-exit guard", "bash_n": "PASS"}

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    print(validate(args.base, args.candidate))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
