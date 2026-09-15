"""Read-only candidate inventory. Never constructs a Store or issues a task command."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path[:0] = [str(root), str(root.parent / "communication-ledger")]
from cairn_adapter.governance import preparation_snapshot

if __name__ == "__main__":
    candidates = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(preparation_snapshot(candidates), ensure_ascii=False, indent=2))
