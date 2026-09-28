from __future__ import annotations

import ast
import re
from pathlib import PurePosixPath

from .common import Refused, finding, parse_json
from .config import load_yaml


def tree_of(data: bytes) -> ast.Module:
    try:
        return ast.parse(data.decode("utf-8-sig"))
    except (SyntaxError, UnicodeError, RecursionError) as exc:
        raise Refused("PYTHON_SOURCE_INVALID") from exc


def assignments(body: list[ast.stmt]) -> dict[str, ast.expr]:
    result = {}
    for node in body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            result[node.target.id] = node.value
    return result


def called_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return called_name(node.value) + "." + node.attr
    return ""


def workflow_check(data: bytes, path: str) -> list[dict]:
    try:
        value = load_yaml(data)
        if not isinstance(value, dict) or not isinstance(value.get("jobs"), dict) or not value["jobs"]:
            return [finding("K01", "FAIL", "WORKFLOW_JOBS_MISSING", path=path)]
        if "on" not in value:
            return [finding("K01", "FAIL", "WORKFLOW_TRIGGER_MISSING", path=path)]
        # This is intentionally not actionlint or a full Actions expression validator.
        return [finding("K01", "PASS", "YAML_KEYS_AND_MINIMUM_SHAPE", path=path,
                        details={"jobs": len(value["jobs"]), "actions_semantics": "NOT_EVALUATED"})]
    except Refused as exc:
        return [finding("K01", "BLOCKED" if exc.code == "YAML_ALIAS_UNSUPPORTED" else "FAIL", exc.code, path=path)]


def test_import_check(data: bytes, path: str) -> list[dict]:
    tree = tree_of(data)
    result = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and any(x.startswith("test_") for x in (node.module or "").split(".")):
            for alias in node.names:
                if alias.name == "*" or alias.name[:1].isupper():
                    result.append(finding("K03", "WARN", "POSSIBLE_IMPORTED_TEST_CLASS", path=path, line=node.lineno,
                                          details={"collection_executed": False}))
    return result


def diagnostics_check(data: bytes, path: str) -> list[dict]:
    result = []
    for node in ast.walk(tree_of(data)):
        if not isinstance(node, ast.ExceptHandler):
            continue
        kind = called_name(node.type) if node.type is not None else "bare"
        if kind not in {"Exception", "BaseException", "bare"}:
            continue
        calls = [called_name(n.func) for statement in node.body for n in ast.walk(statement) if isinstance(n, ast.Call)]
        has_log = any(re.search(r"(?:^|\.)(?:log|logger|logging)\.(?:error|exception|warning|critical)$", c) or
                      c.endswith(".emit_safe_event") or c == "emit_safe_event" for c in calls)
        reraises = any(isinstance(n, ast.Raise) for statement in node.body for n in ast.walk(statement))
        if not has_log and not reraises:
            result.append(finding("K07", "WARN", "CATCH_ALL_WITHOUT_VISIBLE_DIAGNOSTIC", path=path, line=node.lineno,
                                  details={"ast_heuristic_only": True, "runtime_log_test": "NOT_RUN"}))
    return result


# Only these known SQLAlchemy symbols can prove a first positional argument is
# NOT an explicit SQL name. Unknown/custom expressions are BLOCKED, never guessed.
_SQL_NON_NAME_SYMBOLS = frozenset({
    "Integer", "INT", "INTEGER", "SmallInteger", "SMALLINT", "BigInteger", "BIGINT",
    "String", "VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "Text", "TEXT", "Unicode",
    "UnicodeText", "Boolean", "BOOLEAN", "Float", "FLOAT", "Double", "DOUBLE",
    "DoublePrecision", "Numeric", "NUMERIC", "DECIMAL", "REAL", "Date", "DATE",
    "DateTime", "DATETIME", "TIMESTAMP", "Time", "TIME", "Interval", "LargeBinary",
    "BINARY", "VARBINARY", "BLOB", "Enum", "JSON", "Uuid", "UUID", "ARRAY",
    "PickleType", "NullType", "ForeignKey", "Identity", "Sequence", "Computed",
})
_SQL_MODULES = frozenset({"sqlalchemy", "sqlalchemy.types", "sqlalchemy.sql.sqltypes",
                          "sqlalchemy.schema", "sqlalchemy.sql.schema"})


class _ColumnNames:
    """Small, deliberately conservative static binding resolver; never imports ERP.

    Supports a unique direct module/class string literal assigned before use.
    Calls, imported string constants, reassignment, conditional bindings and
    custom type factories are unresolved. This is not a Python interpreter.
    """
    def __init__(self, tree: ast.Module, cls: ast.ClassDef):
        from collections import Counter
        self.cls = cls
        self.stores = Counter(n.id for n in ast.walk(tree)
                              if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)))
        self.imports = Counter()
        self.symbols = {}
        self.modules = {}
        self.module_literals = {}
        self.class_literals = {}
        self.class_fields = assignments(cls.body)
        for node in ast.walk(tree):
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                for alias in node.names:
                    self.imports[alias.asname or alias.name.split('.')[0]] += 1
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
                root = called_name(node).split('.')[0]
                self.stores[root] += 1
            # These binding forms do not have a Name(Store) AST node.
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.stores[node.name] += 1
            elif isinstance(node, ast.ExceptHandler) and node.name:
                self.stores[node.name] += 1
            elif isinstance(node, ast.arg):
                self.stores[node.arg] += 1
            elif isinstance(node, ast.MatchAs) and node.name:
                self.stores[node.name] += 1
        for node in tree.body:
            if node.lineno >= cls.lineno:
                break
            if isinstance(node, ast.ImportFrom) and node.module in _SQL_MODULES:
                for alias in node.names:
                    if alias.name in _SQL_NON_NAME_SYMBOLS:
                        self.symbols[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _SQL_MODULES:
                        self.modules[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else 'sqlalchemy'
            self._literal(node, self.module_literals)
        for node in cls.body:
            self._literal(node, self.class_literals)

    def _literal(self, node, output):
        name, value = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        if name is not None and isinstance(value, ast.Constant) and isinstance(value.value, str):
            if self.stores[name] == 1 and self.imports[name] == 0:
                output[name] = (value.value, node.lineno)

    def string(self, expr):
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return expr.value
        if isinstance(expr, ast.Name):
            # A class binding shadows a module binding, even when unresolved.
            known = self.class_literals if expr.id in self.class_fields else self.module_literals
            item = known.get(expr.id)
            if item is not None and item[1] < expr.lineno:
                return item[0]
        raise Refused("MODEL_COLUMN_UNRESOLVED")

    def non_name(self, expr):
        if isinstance(expr, ast.Constant) and expr.value is None:
            return True  # Optional name placeholder: Column(None, Integer).
        base = expr.func if isinstance(expr, ast.Call) else expr
        if isinstance(base, ast.Name):
            return (base.id in self.symbols and self.imports[base.id] == 1
                    and self.stores[base.id] == 0 and base.id not in self.class_fields)
        if isinstance(base, ast.Attribute):
            # Accept e.g. sa.Integer and sqlalchemy.types.String, only with an
            # unshadowed, explicit import. Unrecognized suffixes fail closed.
            parts = called_name(base).split('.')
            module = self.modules.get(parts[0])
            if not module or self.imports[parts[0]] != 1 or self.stores[parts[0]] != 0 or parts[0] in self.class_fields:
                return False
            full = module + '.' + '.'.join(parts[1:])
            parent, _, symbol = full.rpartition('.')
            return parent in _SQL_MODULES and symbol in _SQL_NON_NAME_SYMBOLS
        return False

    def physical_name(self, attribute: str, call: ast.Call) -> str:
        if any(isinstance(arg, ast.Starred) for arg in call.args) or any(kw.arg is None for kw in call.keywords):
            raise Refused("MODEL_COLUMN_UNRESOLVED")
        explicit = [kw for kw in call.keywords if kw.arg in {"name", "_name", "__name_pos"}]
        if len(explicit) > 1:
            raise Refused("MODEL_COLUMN_UNRESOLVED")
        positional = None
        if call.args and not self.non_name(call.args[0]):
            positional = self.string(call.args[0])
        if explicit:
            if positional is not None:
                raise Refused("MODEL_COLUMN_UNRESOLVED")  # Conflicting positional/keyword names.
            return self.string(explicit[0].value)
        return positional if positional is not None else attribute


def model_columns(data: bytes, class_names: list[str]) -> dict[str, list[str]]:
    tree = tree_of(data)
    result = {}
    column_aliases = {"Column", "mapped_column"}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy"):
            for alias in node.names:
                if alias.name in column_aliases:
                    column_aliases.add(alias.asname or alias.name)
    # Wildcard imports can rebind ANY SQLAlchemy constructor/type/name, even
    # when the '*' itself is the only literal name in the AST. Do not execute
    # imports or guess their exports. Explicit literal-only files remain usable.
    if any(isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
           for n in ast.walk(tree)):
        raise Refused("MODEL_COLUMN_UNRESOLVED")
    found = set()
    for cls in tree.body:
        if not isinstance(cls, ast.ClassDef) or cls.name not in class_names:
            continue
        found.add(cls.name)
        fields = assignments(cls.body)
        try:
            table = ast.literal_eval(fields["__tablename__"])
        except (KeyError, ValueError, TypeError) as exc:
            raise Refused("MODEL_TABLE_UNRESOLVED") from exc
        if not isinstance(table, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise Refused("MODEL_TABLE_UNRESOLVED")
        columns = []
        names = _ColumnNames(tree, cls)
        for name, value in fields.items():
            if isinstance(value, ast.Call) and called_name(value.func).split(".")[-1] in column_aliases:
                column = names.physical_name(name, value)
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column):
                    raise Refused("MODEL_COLUMN_UNRESOLVED")
                columns.append(column)
        for node in cls.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                "declared_attr" in called_name(d) for d in node.decorator_list
            ):
                raise Refused("MODEL_DECLARED_ATTR_UNSUPPORTED")
        # Inheritance/mixins cannot be silently treated as fully understood.
        if any(called_name(base).split(".")[-1] not in {"Base", "DeclarativeBase"} for base in cls.bases):
            raise Refused("MODEL_INHERITANCE_UNSUPPORTED")
        if not columns or table in result:
            raise Refused("MODEL_COLUMNS_UNRESOLVED")
        if any(isinstance(n, ast.AnnAssign) and n.value is None for n in cls.body):
            raise Refused("MODEL_ANNOTATION_ONLY_UNSUPPORTED")
        result[table] = sorted(set(columns))
    if found != set(class_names):
        raise Refused("MODEL_CLASS_MISSING")
    return result


def migration_graph(sources: dict[str, bytes]) -> dict:
    parents = {}
    for path, data in sources.items():
        if PurePosixPath(path).name == "__init__.py":
            continue
        values = assignments(tree_of(data).body)
        try:
            revision = ast.literal_eval(values["revision"])
            parent = ast.literal_eval(values["down_revision"])
            dependency = ast.literal_eval(values["depends_on"]) if "depends_on" in values else None
            if dependency is not None:
                raise Refused("MIGRATION_DEPENDENCIES_UNSUPPORTED")
        except (KeyError, ValueError, TypeError) as exc:
            raise Refused("MIGRATION_REVISION_UNRESOLVED") from exc
        if not isinstance(revision, str) or not revision or revision in parents:
            raise Refused("MIGRATION_REVISION_DUPLICATE_OR_INVALID")
        ps = [] if parent is None else [parent] if isinstance(parent, str) else list(parent) if isinstance(parent, (list, tuple)) else None
        if ps is None or not all(isinstance(p, str) and p for p in ps):
            raise Refused("MIGRATION_PARENT_INVALID")
        parents[revision] = ps
    if not parents or any(p not in parents for ps in parents.values() for p in ps):
        raise Refused("MIGRATION_PARENT_MISSING")
    visiting, done = set(), set()
    def visit(n):
        if n in visiting:
            raise Refused("MIGRATION_CYCLE")
        if n not in done:
            visiting.add(n)
            for p in parents[n]:
                visit(p)
            visiting.remove(n)
            done.add(n)
    try:
        for n in parents:
            visit(n)
    except RecursionError as exc:
        raise Refused("MIGRATION_GRAPH_LIMIT") from exc
    heads = sorted(set(parents) - {p for ps in parents.values() for p in ps})
    if len(heads) != 1:
        raise Refused("MIGRATION_MULTIPLE_HEADS")
    return {"heads": heads, "revisions": len(parents), "parity": "NOT_RUN"}


def scan(view, cfg: dict) -> list[dict]:
    findings = []
    paths = list(view.entries)
    workflows = [p for p in paths if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))]
    testfiles = [p for p in paths if p.endswith(".py") and PurePosixPath(p).name.startswith("test_")]
    migrations = [p for p in paths if p.startswith(cfg["migration_dir"] + "/") and p.endswith(".py")]
    extra = [cfg["model_path"], cfg["canonical_router"], cfg["compatibility_router"],
             "backend/modules/chat_ops/router.py", "backend/modules/kds/tts.py",
             "infra/release_v2/bundle.py", "frontend/package.json"]
    view.preload(workflows + testfiles + migrations + [p for p in extra if p in view.entries])
    if not workflows:
        findings.append(finding("K01", "BLOCKED", "NO_WORKFLOWS_DISCOVERED"))
    for path in workflows:
        findings.extend(workflow_check(view.read(path), path))
    if not testfiles:
        findings.append(finding("K03", "NOT_RUN", "NO_PYTHON_TESTS_DISCOVERED"))
    else:
        k03 = []
        for path in testfiles:
            try:
                k03.extend(test_import_check(view.read(path), path))
            except Refused as exc:
                k03.append(finding("K03", "BLOCKED", exc.code, path=path))
        findings.extend(k03 or [finding("K03", "PASS", "NO_DIRECT_TEST_CLASS_IMPORT_CANDIDATES",
                                       details={"files_scanned": len(testfiles), "collection_executed": False})])
    for path in ["backend/modules/chat_ops/router.py", "backend/modules/kds/tts.py"]:
        if path in view.entries:
            try:
                issues = diagnostics_check(view.read(path), path)
                findings.extend(issues or [finding("K07", "INFO", "AST_DIAGNOSTIC_SCAN_ONLY", path=path)])
            except Refused as exc:
                findings.append(finding("K07", "BLOCKED", exc.code, path=path))
    canonical = cfg["canonical_router"]
    compatibility = cfg["compatibility_router"]
    if canonical not in view.entries:
        findings.append(finding("F00", "FAIL", "CANONICAL_ROUTER_MISSING", path=canonical))
    elif compatibility not in view.entries:
        findings.append(finding("F00", "INFO", "NO_COMPATIBILITY_ROUTER", path=canonical))
    else:
        pointer = canonical in view.read(compatibility).decode("utf-8", "replace")
        findings.append(finding("F00", "INFO" if pointer else "WARN",
                                "ROUTER_REFERENCE_PRESENT_NOT_RUNTIME_PROOF" if pointer else "ROUTER_REFERENCE_MISSING",
                                path=compatibility))
    try:
        graph = migration_graph({p: view.read(p) for p in migrations})
        columns = model_columns(view.read(cfg["model_path"]), cfg["model_classes"])
        findings.append(finding("K04_GRAPH", "PASS", "SINGLE_SOURCE_MIGRATION_HEAD", details=graph))
        findings.append(finding("K04B", "NOT_RUN", "MIGRATED_DATABASE_REQUIRED", details={"model_columns": columns}))
    except Refused as exc:
        findings.append(finding("K04_GRAPH", "BLOCKED", exc.code))
    audio_wf = ".github/workflows/release-v2-ci.yml"
    if cfg["audio_required"] and audio_wf in view.entries:
        try:
            y = load_yaml(view.read(audio_wf))
            inputs = y.get("on", {}).get("workflow_dispatch", {}).get("inputs", {})
            if inputs.get("kds_audio_asset_id", {}).get("required") is not True:
                findings.append(finding("K05_SOURCE", "WARN", "OPTIONAL_AUDIO_INPUT_REQUIRES_SEMANTIC_GUARD", path=audio_wf))
        except (Refused, AttributeError):
            findings.append(finding("K05_SOURCE", "BLOCKED", "AUDIO_WORKFLOW_UNRESOLVED", path=audio_wf))
    findings.append(finding("K05", "NOT_RUN", "AUDIO_ASSET_DIRECTORY_REQUIRED"))
    package = "frontend/package.json"
    if package in view.entries:
        try:
            scripts = parse_json(view.read(package)).get("scripts", {})
            names = sorted(k for k in scripts if k == "test" or k.startswith("test:"))
            findings.append(finding("K08", "INFO", "TEST_SCRIPT_INVENTORY_ONLY", path=package,
                                    details={"scripts": names, "ci_reachability": "NOT_PROVEN", "execution": "NOT_RUN"}))
        except (Refused, AttributeError):
            findings.append(finding("K08", "BLOCKED", "PACKAGE_SCRIPTS_INVALID", path=package))
    findings.append(finding("K02", "NOT_RUN", "JUNIT_INPUT_REQUIRED"))
    findings.append(finding("K06", "NOT_RUN", "GITHUB_PR_SNAPSHOT_REQUIRED"))
    return findings
