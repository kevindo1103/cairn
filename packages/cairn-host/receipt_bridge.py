"""Fail-closed bridge from observed receipt to existing operator attestation."""
from observed_receipts import ReceiptRejected, validate_pair
import json
import hashlib
from pathlib import Path

def bridge(receipt, confirmation, command, command_digest, operator_key, stage, *,
           expected_turn=None):
    """Validate separate authority first; never construct a confirmation."""
    payload = validate_pair(receipt, confirmation, command, command_digest, operator_key,
                            stage, command["thread_id"], expected_turn)
    if not isinstance(payload, dict):
        raise ReceiptRejected("Observed payload is not an importer observation")
    # Existing importer accepts the observation only after its own receipt-path
    # and confirmation checks; this bridge never invents either artifact.
    return payload


def write_import_artifacts(root, receipt, confirmation, command, command_digest, operator_key,
                           stage, *, expected_turn=None):
    """Persist separately-authorized bridge inputs under a host evidence root."""
    payload = bridge(receipt, confirmation, command, command_digest, operator_key, stage,
                     expected_turn=expected_turn)
    root = Path(root).absolute()
    evidence = root / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    if any(part == ".." for part in evidence.parts) or evidence.is_symlink() or evidence.is_junction():
        raise ReceiptRejected("Unsafe evidence root")
    receipt_path = evidence / (receipt["receipt_digest"] + ".observed.json")
    confirmation_path = evidence / (receipt["receipt_digest"] + ".confirmation.json")
    for path, value in ((receipt_path, receipt), (confirmation_path, confirmation)):
        if path.exists():
            if path.read_bytes() != json.dumps(value, sort_keys=True, separators=(",", ":")).encode():
                raise ReceiptRejected("Immutable bridge artifact mutation")
        else:
            path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
    return dict(observation=payload, receipt_path=str(receipt_path),
                confirmation_path=str(confirmation_path))


def importer_receipt(receipt, flat_receipt):
    """Accept only a complete importer-shaped receipt supplied by host evidence."""
    required = {"event_id", "dedupe", "checkpoint", "thread_id", "turn_id", "action",
                "readback", "transport_ref", "stream_ref"}
    if not isinstance(flat_receipt, dict) or not required.issubset(flat_receipt):
        raise ReceiptRejected("Missing importer receipt provenance")
    if flat_receipt["event_id"] != receipt["event_id"] or flat_receipt["thread_id"] != receipt["thread_id"]:
        raise ReceiptRejected("Importer receipt binding mismatch")
    return flat_receipt


def resume_existing_importer(uat_root, observed, flat_receipt, confirmation, stage, *, receipt_journal=None):
    """Materialize a host-observed flat receipt then use existing operator_resume.

    Confirmation is the existing explicit PM confirmation schema; this bridge
    never creates or rewrites it.  Existing importer validation remains the
    sole authority for stage order and ledger transition.
    """
    if receipt_journal is not None:
        receipt_journal.persist_receipt(observed)
        receipt_journal.assert_unconsumed(observed)
    flat = importer_receipt(observed, flat_receipt)
    uat_root = Path(uat_root).absolute()
    evidence = uat_root / "evidence"
    encoded = json.dumps(flat, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path = evidence / ("bridge-" + digest + ".json")
    if path.exists() and path.read_bytes() != encoded:
        raise ReceiptRejected("Importer receipt artifact mutation")
    if not path.exists():
        path.write_bytes(encoded)
    import existing_task_uat
    result = existing_task_uat.operator_resume(
        uat_root, [dict(stage=stage, receipt_path=str(path), confirmation=confirmation)])
    if receipt_journal is not None:
        receipt_journal.consume(observed, confirmation)
    return result
