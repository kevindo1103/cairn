"""Standalone local communication ledger. No Codex or ERP side effects."""

__version__ = "0.1.0"

from .ledger import Ledger, LedgerError

__all__ = ["Ledger", "LedgerError"]
