from __future__ import annotations

import ast
import io
import re
import struct
import wave
from pathlib import Path

from .common import Refused, SHA256, digest, finding, no_symlinks, parse_json, read_bytes
from .sourcechecks import assignments, tree_of


def audio_policy(source: bytes) -> tuple[dict, dict, int]:
    values = assignments(tree_of(source).body)
    try:
        policies = ast.literal_eval(values["_MANIFEST_POLICIES"])
        audio = ast.literal_eval(values["_ASSET_AUDIO_POLICY"])
        count = ast.literal_eval(values["_ASSET_COUNT"])
    except (KeyError, ValueError, TypeError) as exc:
        raise Refused("AUDIO_SOURCE_POLICY_UNRESOLVED") from exc
    if not isinstance(policies, dict) or not isinstance(audio, dict) or type(count) is not int or not 1 <= count <= 1000:
        raise Refused("AUDIO_SOURCE_POLICY_UNRESOLVED")
    return policies, audio, count


def inspect_audio(root: Path, source: bytes, expected_binding: dict | None) -> list[dict]:
    """Bingxue static-audio profile. Missing expectation is refusal, never opt-out."""
    if not isinstance(expected_binding, dict) or set(expected_binding) != {"asset_id", "archive_sha256", "manifest_sha256"}:
        raise Refused("AUDIO_BINDING_REQUIRED")
    if (not isinstance(expected_binding["asset_id"], str) or not expected_binding["asset_id"].isdigit() or
        not all(isinstance(expected_binding[k], str) and SHA256.fullmatch(expected_binding[k])
                for k in ["archive_sha256", "manifest_sha256"])):
        raise Refused("AUDIO_BINDING_INVALID")
    root = no_symlinks(root)
    if not (root / "manifest.json").is_file():
        raise Refused("MANIFEST_MISSING")
    raw = read_bytes(root / "manifest.json", 2 * 1024 * 1024)
    if digest(raw) != expected_binding["manifest_sha256"]:
        raise Refused("MANIFEST_DIGEST_MISMATCH")
    marker = parse_json(read_bytes(root / "source-identity.json", 64 * 1024))
    if not isinstance(marker, dict) or any(marker.get(k) != v for k, v in expected_binding.items()):
        raise Refused("AUDIO_BINDING_MISMATCH")
    policies, audio, count = audio_policy(source)
    manifest = parse_json(raw)
    keys = {"schema", "version", "source", "locale", "range", "sentence_template", "template_sha256",
            "generator", "generator_sha256", "model", "codec", "codec_identity", "voice", "encoding", "container", "assets"}
    if not isinstance(manifest, dict) or set(manifest) != keys:
        raise Refused("MANIFEST_SHAPE")
    policy = policies.get(manifest["version"])
    if not isinstance(policy, dict) or any(manifest.get(k) != v for k, v in policy.items()):
        raise Refused("MANIFEST_POLICY_MISMATCH")
    if manifest["template_sha256"] != digest(manifest["sentence_template"].encode("utf-8")):
        raise Refused("MANIFEST_TEMPLATE_MISMATCH")
    assets = manifest["assets"]
    if not isinstance(assets, list) or len(assets) != count:
        raise Refused("ASSET_COUNT_MISMATCH")
    expected_keys = {"daily_seq", "filename", "sha256", "bytes", "duration_ms", "mime", "sample_rate", "channels", "sample_width"}
    seen = set()
    total_bytes = 0
    for item in assets:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise Refused("ASSET_SHAPE")
        seq = item["daily_seq"]
        if type(seq) is not int or seq in seen or not policy["range"]["min"] <= seq <= policy["range"]["max"]:
            raise Refused("ASSET_SEQUENCE_INVALID")
        seen.add(seq)
        # Version/path grammar is deliberately fixed for this Bingxue adapter.
        if manifest["version"] != "kds-ready-v1" or item["filename"] != f"kds-ready-v1/order-ready-{seq:04d}.wav":
            raise Refused("ASSET_PATH_INVALID")
        if (type(item["bytes"]) is not int or not 1 <= item["bytes"] <= 10 * 1024 * 1024 or
            type(item["duration_ms"]) is not int or not 1 <= item["duration_ms"] <= 120000 or
            not isinstance(item["sha256"], str) or not SHA256.fullmatch(item["sha256"]) or
            any(item.get(k) != v for k, v in audio.items())):
            raise Refused("ASSET_METADATA_INVALID")
        path = root / item["filename"]
        if not path.is_file():
            raise Refused("ASSET_MISSING")
        data = read_bytes(path, 10 * 1024 * 1024)
        total_bytes += len(data)
        if total_bytes > 512 * 1024 * 1024:
            raise Refused("AUDIO_BYTE_BUDGET")
        if len(data) != item["bytes"] or digest(data) != item["sha256"]:
            raise Refused("ASSET_DIGEST_MISMATCH")
        if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE" or struct.unpack_from("<I", data, 4)[0] != len(data) - 8:
            raise Refused("WAV_INVALID")
        try:
            with wave.open(io.BytesIO(data), "rb") as wav:
                if (wav.getcomptype() != "NONE" or wav.getnchannels() != audio["channels"] or
                    wav.getsampwidth() != audio["sample_width"] or wav.getframerate() != audio["sample_rate"] or
                    wav.getnframes() <= 0):
                    raise Refused("WAV_POLICY_MISMATCH")
                frames = wav.readframes(wav.getnframes())
                if len(frames) != wav.getnframes() * wav.getnchannels() * wav.getsampwidth():
                    raise Refused("WAV_TRUNCATED")
        except (wave.Error, EOFError, struct.error) as exc:
            raise Refused("WAV_INVALID") from exc
    if seen != set(range(policy["range"]["min"], policy["range"]["max"] + 1)):
        raise Refused("ASSET_SEQUENCE_INVALID")
    if read_bytes(root / "manifest.json", 2 * 1024 * 1024) != raw:
        raise Refused("AUDIO_CHANGED")
    return [finding("K05", "PASS", "STATIC_AUDIO_FILES_VERIFIED", details={
        "assets": count, "bytes": total_bytes, "manifest_sha256": digest(raw),
        "reader_policy_sha256": digest(source), "http_serving_test": "NOT_RUN",
        "archive_bytes_reverified": False, "official_reader_executed": False, "binding_authenticity": "CALLER_SUPPLIED_NOT_AUTHENTICATED",
        "not_a_runtime_lease": True})]
