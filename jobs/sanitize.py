"""Sanitizers that keep job payloads and error summaries small and non-sensitive.

Background jobs are durable rows that operators can read in the admin and in
logs, so anything stored on them is limited to record identifiers and to short,
redacted summaries. Media bytes, credentials and long free text never make it
into ``payload`` or ``error_summary``.
"""

import json
import re

MAX_PAYLOAD_BYTES = 4096
MAX_PAYLOAD_STRING_LENGTH = 200
MAX_PAYLOAD_SEQUENCE_ITEMS = 200
ERROR_SUMMARY_MAX_LENGTH = 200

_SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "authorization",
    "api_key",
    "apikey",
    "private_key",
    "cookie",
    "session_id",
)

_REDACTIONS = (
    re.compile(
        r"(?i)\b(password|passwd|secret|token|credential|authorization|api[_-]?key)"
        r"\b\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\bBearer\s+\S+"),
    re.compile(r"\b[A-Za-z0-9+/=_-]{32,}\b"),
)


def _fail(message):
    raise ValueError(f"Invalid job payload: {message}")


def _sanitize_value(value, *, path, depth=0):
    if depth > 3:
        _fail(f"{path} is nested too deeply (max depth 3).")
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        _fail(f"{path} must not be a float.")
    if isinstance(value, str):
        if len(value) > MAX_PAYLOAD_STRING_LENGTH:
            _fail(
                f"{path} is longer than {MAX_PAYLOAD_STRING_LENGTH} characters; "
                "store a record reference instead of content."
            )
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_PAYLOAD_SEQUENCE_ITEMS:
            _fail(f"{path} has more than {MAX_PAYLOAD_SEQUENCE_ITEMS} items.")
        return [
            _sanitize_value(item, path=f"{path}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        return _sanitize_mapping(value, path=path, depth=depth + 1)
    _fail(f"{path} has unsupported type {type(value).__name__}.")


def _sanitize_mapping(mapping, *, path, depth=0):
    cleaned = {}
    for key, value in mapping.items():
        if not isinstance(key, str):
            _fail(f"{path} has a non-string key {key!r}.")
        lowered = key.lower()
        if any(part in lowered for part in _SECRET_KEY_PARTS):
            _fail(f"{path} key {key!r} looks sensitive; never store credentials.")
        cleaned[key] = _sanitize_value(value, path=f"{path}.{key}", depth=depth)
    return cleaned


def sanitize_payload(payload) -> dict:
    """Return a validated, non-sensitive copy of a job payload."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        _fail("payload must be a mapping of record references.")
    cleaned = _sanitize_mapping(payload, path="payload")
    encoded = json.dumps(cleaned, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        _fail(f"payload is larger than {MAX_PAYLOAD_BYTES} bytes when encoded.")
    return cleaned


def sanitize_error_summary(summary) -> str:
    """Return a redacted, whitespace-collapsed, length-capped error summary."""
    text = "" if summary is None else str(summary)
    for pattern in _REDACTIONS:
        text = pattern.sub("[redacted]", text)
    text = " ".join(text.split())
    if len(text) > ERROR_SUMMARY_MAX_LENGTH:
        text = text[: ERROR_SUMMARY_MAX_LENGTH - 3].rstrip() + "..."
    return text
