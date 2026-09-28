from __future__ import annotations

from pathlib import Path
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .common import Refused, digest, finding, read_bytes


def inspect_junit(path: Path, lane: str, exit_code: int) -> list[dict]:
    raw = read_bytes(path)
    try:
        root = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise Refused("JUNIT_INVALID") from exc
    if root.tag not in {"testsuite", "testsuites"}:
        raise Refused("JUNIT_ROOT_INVALID")
    cases = list(root.iter("testcase"))
    if not cases:
        return [finding("K02", "FAIL", "JUNIT_NO_TESTCASES", details={"lane": lane})]
    # A well-formed but truncated report must not turn 3 expected tests into 1 PASS.
    for suite in [root, *[s for s in root.iter("testsuite") if s is not root]]:
        descendants = list(suite.iter("testcase"))
        counts = {
            "tests": len(descendants),
            "failures": sum(any(n.tag == "failure" for n in c) for c in descendants),
            "errors": sum(any(n.tag == "error" for n in c) for c in descendants),
            "skipped": sum(any(n.tag == "skipped" for n in c) for c in descendants),
        }
        for key, observed in counts.items():
            declared = suite.get(key)
            if declared is not None:
                try:
                    if int(declared) != observed:
                        raise Refused("JUNIT_COUNTS_INCONSISTENT")
                except ValueError as exc:
                    raise Refused("JUNIT_COUNTS_INVALID") from exc
    failed, skipped, passed, ids = [], [], 0, set()
    for case in cases:
        name = case.get("name")
        if not name:
            raise Refused("JUNIT_TEST_NAME_MISSING")
        identity = (case.get("classname", ""), name)
        if identity in ids:
            raise Refused("JUNIT_DUPLICATE_TEST_ID")
        ids.add(identity)
        ref = "::".join(identity)
        nodes = list(case)
        bad = [n for n in nodes if n.tag in {"failure", "error"}]
        if bad and any(n.tag == "skipped" for n in nodes):
            raise Refused("JUNIT_CONTRADICTORY_TEST_RESULT")
        if bad:
            failed.append({"test_ref": ref, "phase": "error_or_fixture" if any(n.tag == "error" for n in bad) else "call"})
        elif any(n.tag == "skipped" for n in nodes):
            skipped.append(ref)
        else:
            passed += 1
    if failed or exit_code != 0:
        status, code = "FAIL", "TEST_FAILURE" if failed else "PROCESS_FAILURE_WITHOUT_NAMED_TEST_FAILURE"
    elif skipped:
        status, code = "WARN", "SKIPS_NOT_ALL_PASS"
    else:
        status, code = "PASS", "NAMED_TESTS_ALL_PASS"
    return [finding("K02", status, code, details={
        "lane": lane, "exit_code": exit_code, "collected": len(cases), "passed": passed,
        "failed": len(failed), "skipped": len(skipped), "failed_tests": failed, "skipped_tests": skipped,
        "junit_sha256": digest(raw), "source_binding": "CALLER_SUPPLIED_NOT_ATTESTED",
        "raw_failure_messages_included": False, "release_evidence": False})]
