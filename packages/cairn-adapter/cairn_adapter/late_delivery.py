"""Fail-closed receipts for accepted transport whose dispatcher lease expired."""
import hashlib
import hmac
import math

from .store import Rejected, canonical, digest


AUTHORITY = "pilot operator confirmation authority"
OBSERVER = "CODEX_APP_TRANSPORT"
RECEIPT_FIELDS = {
    "schema", "event_id", "event_digest", "payload_digest", "target_thread_id",
    "target_turn_id", "stage", "observed_payload", "delivery_attempt", "delivery_token_digest",
    "platform_receipt_digest", "platform_receipt_ref", "observer", "accepted",
    "observed_at", "receipt_digest", "observer_signature",
}
CONFIRMATION_FIELDS = {
    "receipt_digest", "event_id", "event_digest", "payload_digest", "target_thread_id",
    "target_turn_id", "stage", "delivery_attempt", "operator_task", "operator_generation",
    "authority", "confirmed_at", "signature",
}


def _hmac(key, value):
    return hmac.new(bytes(key), canonical(value).encode("utf-8"), hashlib.sha256).hexdigest()


def _sha256_hex(value):
    return (isinstance(value, str) and len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value))


def observed_delivery_receipt(event, delivery_token, target_turn_id, platform_receipt_digest,
                              observer_key, *, observed_payload, observed_at):
    """Host observer creates this; the returned receipt contains no operator authorization."""
    if not isinstance(target_turn_id, str) or not target_turn_id.strip():
        raise Rejected("Exact platform turn id required")
    if not _sha256_hex(platform_receipt_digest):
        raise Rejected("Platform receipt must be pinned by SHA256")
    if not isinstance(observed_payload, str) or not observed_payload.strip():
        raise Rejected("Exact observed transport payload required")
    body = dict(schema="cairn-late-delivery-v1", event_id=event["id"],
                event_digest=event["digest"],
                payload_digest=hashlib.sha256(observed_payload.encode("utf-8")).hexdigest(),
                target_thread_id=event["target"], target_turn_id=target_turn_id,
                stage="SENT", observed_payload=observed_payload,
                delivery_attempt=event["attempts"],
                delivery_token_digest=hashlib.sha256(delivery_token.encode()).hexdigest(),
                platform_receipt_digest=platform_receipt_digest,
                platform_receipt_ref="artifact://sha256/" + platform_receipt_digest,
                observer=OBSERVER, accepted=True, observed_at=observed_at)
    if isinstance(observed_at, bool) or not isinstance(observed_at, (int, float)) or not math.isfinite(observed_at):
        raise Rejected("Invalid observer timestamp")
    body["receipt_digest"] = digest(body)
    body["observer_signature"] = _hmac(observer_key, body)
    return body


def operator_confirmation(receipt, operator_task, operator_generation, operator_key, *, confirmed_at):
    """Separate operator action; observer code must not receive the operator key."""
    body = {key: receipt[key] for key in (
        "receipt_digest", "event_id", "event_digest", "payload_digest", "target_thread_id",
        "target_turn_id", "stage", "delivery_attempt")}
    body.update(operator_task=operator_task, operator_generation=operator_generation,
                authority=AUTHORITY, confirmed_at=confirmed_at)
    body["signature"] = _hmac(operator_key, body)
    return body


def validate_late_delivery(receipt, confirmation, event, delivery_token, operator_task,
                           operator_generation, operator_key, observer_key,
                           expected_payload_digest):
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise Rejected("Malformed late-delivery receipt")
    unsigned_receipt = {k: v for k, v in receipt.items() if k not in {"receipt_digest", "observer_signature"}}
    if receipt["receipt_digest"] != digest(unsigned_receipt):
        raise Rejected("Late-delivery receipt digest mismatch")
    signed_receipt = {k: v for k, v in receipt.items() if k != "observer_signature"}
    if not hmac.compare_digest(receipt["observer_signature"], _hmac(observer_key, signed_receipt)):
        raise Rejected("Late-delivery receipt was not issued by the host observer")
    if (receipt["schema"] != "cairn-late-delivery-v1" or receipt["observer"] != OBSERVER
            or receipt["accepted"] is not True or receipt["stage"] != "SENT"
            or receipt["event_id"] != event["id"]
            or receipt["event_digest"] != event["digest"]
            or not isinstance(receipt["observed_payload"], str)
            or receipt["payload_digest"] != hashlib.sha256(receipt["observed_payload"].encode("utf-8")).hexdigest()
            or receipt["payload_digest"] != expected_payload_digest
            or receipt["target_thread_id"] != event["target"]
            or not isinstance(receipt["target_turn_id"], str) or not receipt["target_turn_id"].strip()
            or type(receipt["delivery_attempt"]) is not int or receipt["delivery_attempt"] != event["attempts"]
            or receipt["delivery_token_digest"] != hashlib.sha256(delivery_token.encode()).hexdigest()
            or not _sha256_hex(receipt["platform_receipt_digest"])
            or receipt["platform_receipt_ref"] != "artifact://sha256/" + receipt["platform_receipt_digest"]
            or isinstance(receipt["observed_at"], bool)
            or not isinstance(receipt["observed_at"], (int, float))
            or not math.isfinite(receipt["observed_at"])):
        raise Rejected("Late-delivery receipt binding mismatch")
    if not isinstance(confirmation, dict) or set(confirmation) != CONFIRMATION_FIELDS:
        raise Rejected("Independent operator confirmation required")
    signature = confirmation["signature"]
    unsigned_confirmation = {k: v for k, v in confirmation.items() if k != "signature"}
    if not isinstance(signature, str) or not hmac.compare_digest(signature, _hmac(operator_key, unsigned_confirmation)):
        raise Rejected("Operator confirmation signature mismatch")
    expected = {key: receipt[key] for key in (
        "receipt_digest", "event_id", "event_digest", "payload_digest", "target_thread_id",
        "target_turn_id", "stage", "delivery_attempt")}
    if any(confirmation[key] != value for key, value in expected.items()):
        raise Rejected("Operator confirmation does not bind the exact receipt")
    if (confirmation["operator_task"] != operator_task
            or type(confirmation["operator_generation"]) is not int
            or confirmation["operator_generation"] != operator_generation
            or confirmation["authority"] != AUTHORITY
            or isinstance(confirmation["confirmed_at"], bool)
            or not isinstance(confirmation["confirmed_at"], (int, float))
            or not math.isfinite(confirmation["confirmed_at"])):
        raise Rejected("Operator confirmation principal/stage mismatch")
    return digest(unsigned_confirmation)


class LateDeliveryAuthority:
    """Host-only verifier; keys and operator identity never arrive in command input."""
    def __init__(self, observer_key, operator_key, operator_task, operator_generation,
                 expected_payload_digests):
        if not operator_task or type(operator_generation) is not int or operator_generation < 1:
            raise Rejected("Invalid pilot operator principal")
        self._observer_key = bytes(observer_key)
        self._operator_key = bytes(operator_key)
        self._operator_task = operator_task
        self._operator_generation = operator_generation
        if not isinstance(expected_payload_digests, dict) or any(
                not isinstance(event_id, str) or not _sha256_hex(value)
                for event_id, value in expected_payload_digests.items()):
            raise Rejected("Host command journal payload bindings are malformed")
        self._expected_payload_digests = dict(expected_payload_digests)

    def validate(self, receipt, confirmation, event, delivery_token, principal):
        if principal.get("task_id") != self._operator_task or principal.get("generation") != self._operator_generation:
            raise Rejected("Current PM principal is not the confirmed pilot operator")
        expected_payload_digest = self._expected_payload_digests.get(event["id"])
        if expected_payload_digest is None:
            raise Rejected("No durable host dispatch payload binding for this event")
        return validate_late_delivery(receipt, confirmation, event, delivery_token,
                                      self._operator_task, self._operator_generation,
                                      self._operator_key, self._observer_key,
                                      expected_payload_digest)
