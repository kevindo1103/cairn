"""Explicit direct-column coverage. This is not all-model discovery or authority.

One profile contract is shared by workflow acceptance and report validation.
Other inventory models, other source files, constraints and runtime mutations
remain outside this intentionally bounded movement/stock presence check.
"""
from __future__ import annotations

import ast
import re
from collections import Counter

from .common import Refused, digest, finding
from .sourcechecks import assignments, model_columns, tree_of

INVENTORY_COVERAGE_ID = "bingxue-movement-stock-v1"
_INVENTORY_MODELS = {"InventoryMovement": "inventory_movements",
                     "WarehouseStock": "warehouse_stocks"}
COVERAGE_SCOPE = "CONFIGURED_DIRECT_COLUMNS_ONLY"


def coverage_contract(name: str) -> dict[str, str]:
    if name != INVENTORY_COVERAGE_ID:
        raise Refused("MODEL_COVERAGE_CONTRACT_UNKNOWN")
    return dict(_INVENTORY_MODELS)


def inspect_model_scope(data: bytes, classes: list[str]) -> tuple[dict, dict]:
    """Resolve selected models or record explicit unsupported coverage.

    No module is imported/executed. `excluded` inventories only top-level class
    declarations in this file, not every runtime SQLAlchemy mapper in the app.
    """
    if (not classes or len(classes) != len(set(classes)) or
            any(not isinstance(n, str) or not re.fullmatch(r"[A-Za-z_]\w*", n)
                for n in classes)):
        raise Refused("CONFIG_MODELS")
    tree = tree_of(data)
    expected, resolved, unsupported, excluded = {}, [], [], []
    for name in sorted(classes):
        try:
            columns = model_columns(data, [name])
            table, names = next(iter(columns.items()))
            resolved.append({"model": name, "table": table, "columns": names})
        except Refused as exc:
            unsupported.append({"model": name, "reason": exc.code})
    counts = Counter(item["table"] for item in resolved)
    for item in resolved[:]:
        if counts[item["table"]] != 1:
            unsupported.append({"model": item["model"], "reason": "MODEL_TABLE_AMBIGUOUS"})
            resolved.remove(item)
        else:
            expected[item["table"]] = item["columns"]
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef) and cls.name not in classes:
            value = assignments(cls.body).get("__tablename__")
            table = value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None
            excluded.append({"model": cls.name, "table": table, "reason": "NOT_SELECTED"})
    scope = {"schema": "iceflow-model-coverage-v1", "scope": COVERAGE_SCOPE,
             "model_source_sha256": digest(data), "selected_models": sorted(classes),
             "resolved": resolved, "unsupported": unsupported, "excluded": excluded,
             "excluded_universe": "TOP_LEVEL_CLASS_DECLARATIONS_IN_MODEL_SOURCE_ONLY",
             "other_source_files_and_runtime_mappers": "NOT_DISCOVERED",
             "types_constraints_indexes": "NOT_CHECKED"}
    return expected, scope


def scope_findings(scope: dict) -> list[dict]:
    result = [finding("K04B", "BLOCKED", entry["reason"],
                      details={"model": entry["model"], "coverage": "UNSUPPORTED"})
              for entry in scope["unsupported"]]
    result.append(finding("K04B_COVERAGE", "BLOCKED" if scope["unsupported"] else "PASS",
                          "MODEL_COVERAGE_UNRESOLVED" if scope["unsupported"] else "MODEL_SCOPE_RECORDED",
                          details=scope))
    return result


def coverage_satisfied(findings: list[dict], contract_name: str) -> bool:
    """Validate report coverage, not the truth/authorship of arbitrary JSON."""
    required = coverage_contract(contract_name)
    records = [f for f in findings if f["check"] == "K04B_COVERAGE"]
    if len(records) != 1 or records[0]["status"] != "PASS":
        return False
    try:
        c = records[0]["details"]
        if (c["schema"] != "iceflow-model-coverage-v1" or c["scope"] != COVERAGE_SCOPE or
                c["unsupported"] != [] or not isinstance(c["excluded"], list) or
                not re.fullmatch(r"[0-9a-f]{64}", c["model_source_sha256"])):
            return False
        selected, resolved = c["selected_models"], c["resolved"]
        if (not isinstance(selected, list) or not isinstance(resolved, list) or
                len(selected) != len(set(selected)) or
                len(resolved) != len(selected)):
            return False
        models = {m["model"]: m for m in resolved}
        if (len(models) != len(resolved) or set(models) != set(selected) or
                len({m["table"] for m in resolved}) != len(resolved) or
                any(name not in models or models[name]["table"] != table
                    for name, table in required.items())):
            return False
        rows = [f for f in findings if f["check"] == "K04B"]
        if len(rows) != len(resolved):
            return False
        seen = set()
        for row in rows:
            d = row["details"]
            name = d["model"]
            if name in seen or name not in models:
                return False
            seen.add(name)
            columns = models[name]["columns"]
            if (not isinstance(columns, list) or not columns or
                    any(not isinstance(x, str) for x in columns) or
                    len(columns) != len(set(columns)) or row["status"] != "PASS" or
                    d["table"] != models[name]["table"] or d["missing_columns"] != [] or
                    d["inspected_column_names"] != columns):
                return False
        return seen == set(selected)
    except (KeyError, TypeError, ValueError):
        return False
