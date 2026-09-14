"""Dependency-free CLI. JSON arguments come from stdin or a file."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .api import COMMANDS, execute
from .ledger import Ledger, LedgerError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Explicit local SQLite path")
    parser.add_argument("--pm-task", help="Required for first initialization; immutable thereafter")
    parser.add_argument("command", choices=("init",) + COMMANDS)
    parser.add_argument("--input", default="-", help="JSON argument file; default stdin (blank means {})")
    args = parser.parse_args(argv)
    try:
        ledger = Ledger(args.db, pm_task=args.pm_task)
        if args.command == "init":
            result = {"database": ledger.path, "automatic_wake": "NOT_IMPLEMENTED"}
        else:
            raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
            result = execute(ledger, args.command, json.loads(raw) if raw.strip() else {})
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (LedgerError, TypeError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
