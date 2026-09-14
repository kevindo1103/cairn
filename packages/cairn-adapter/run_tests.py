"""Run the isolated adapter suite against the sibling pinned ledger, without install."""

import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path[:0] = [str(root), str(root.parent / "communication-ledger")]

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(str(root / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() and not result.skipped else 1)
