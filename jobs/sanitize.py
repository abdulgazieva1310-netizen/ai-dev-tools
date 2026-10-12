"""Sanitizers that keep job payloads and error summaries small and non-sensitive.

Background jobs are durable rows that operators can read in the admin and in
logs, so anything stored on them is limited to record identifiers and to short,
redacted summaries. Media bytes, credentials and long free text never make it
into ``payload`` or ``error_summary``.

Redaction is applied to the *whole* ``name: value`` pair, never to the name
alone: redacting ``Authorization: Bearer`` and leaving ``sk-live-...`` behind is
how credentials used to leak. The same detector decides whether a payload string
value looks like a credential; those payloads are rejected rather than rewritten,
so a secret can never reach the durable row.
"""

import json
import re

MAX_PAYLOAD_BYTES = 4096
MAX_PAYLOAD_STRING_LENGTH = 200
MAX_PAYLOAD_SEQUENCE_ITEMS = 200
ERROR_SUMMARY_MAX_LENGTH = 200
REDACTED = "[redacted]"

# Substrings that make a key, header or parameter name credential bearing. They
# are matched inside a longer name as well, so ``client_secret``,
# ``aws_secret_access_key`` and ``Set-Cookie`` are all recognised.
_SENSITIVE_NAME_BODY = (
    r"pass(?:word|wd|phrase)"
    r"|secret(?:[_-]?key)?"
    r"|token"
    r"|credential"
    r"|authorization"
    r"|api[_-]?key|apikey"
    r"|access[_-]?key"
    r"|private[_-]?key"
    r"|cookie"
    r"|session[_-]?id|sessionid"
    r"|bearer"
)

# One sensitive name, allowing surrounding name characters (``x-api-key``,
# ``aws_secret_access_key``) but never crossing a word boundary.
_SENSITIVE_NAME = r"[A-Za-z0-9_.\-]*?(?:" + _SENSITIVE_NAME_BODY + r")[A-Za-z0-9_.\-]*"

# A quoted value, a single quoted value, or a bare value that runs to the end of
# the line without swallowing a clause separator (``sessionid=a; Path=/``).
_ASSIGNMENT_VALUE = (
    r"(?:"
    r"\"[^\"\r\n]*\""
    r"|'[^'\r\n]*'"
    r"|(?:(?![,;\r\n])[^\r\n])+"
    r")"
)

_ASSIGNMENT_REDACTION = re.compile(
    # ``Authorization: Bearer <token>``, ``client_secret: ...``, ``api_key=...``,
    # ``{"cookie": "..."}``: the value is consumed with the name, never orphaned.
    r"(?<![A-Za-z0-9])"
    r"(?P<name>" + _SENSITIVE_NAME + r")"
    r"[\"']?[ \t]*(?P<separator>[:=])[ \t]*"
    r"(?P<value>" + _ASSIGNMENT_VALUE + r")",
    re.IGNORECASE,
)

_REDACTIONS = (
    _ASSIGNMENT_REDACTION,
    # ``Bearer <token>`` / ``Basic <base64>`` with no name in front of them.
    re.compile(
        r"(?i)\b(?:bearer|basic|digest|negotiate|oauth|hmac|apikey)"
        r"\s+[A-Za-z0-9._~+/=\-]{6,}"
    ),
    # Known provider token prefixes, which are short and cannot be caught by a
    # length heuristic on their own.
    re.compile(
        r"(?i)(?<![A-Za-z0-9])(?:"
        r"github_pat_[A-Za-z0-9_]{8,}"
        r"|(?:sk|pk|rk|whsec|ghp|gho|ghu|ghs|glpat|xox[abopsr]|akia|asia|aiza"
        r"|ya29|eyj|sg)[-_][A-Za-z0-9_\-]{8,}"
        r")"
    ),
)

# Last resort: a long opaque run. This is a backstop, not the main defence,
# which is why it sits behind the named patterns above.
_OPAQUE_RUN = re.compile(r"[A-Za-z0-9+/=_\-]{24,}")

_SENSITIVE_NAME_RE = re.compile(_SENSITIVE_NAME, re.IGNORECASE)


def _redact_assignment(match) -> str:
    """Redact ``name: value`` as a unit, and stay stable when already redacted.

    The worker sanitizes a summary before logging it and the model sanitizes it
    again when the failure is recorded, so redaction has to be idempotent.
    """
    if match.group("value").lstrip().startswith(REDACTED):
        return match.group(0)
    return f"{match.group('name')}{match.group('separator')} {REDACTED}"


# Values that are unambiguously record references and must stay enqueueable even
# though they are long enough to look opaque.
_DIGITS_ONLY = re.compile(r"[0-9]+")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _fail(message):
    raise ValueError(f"Invalid job payload: {message}")


def _redact_opaque(match, *, strict: bool) -> str:
    """Redact a long opaque run.

    ``strict`` (payloads) redacts any long run, because a payload value should
    be a record reference. An error summary keeps letter-only runs such as
    ``listings_listings_display_name_key``, which are identifiers and not
    credentials, but still redacts anything that mixes letters and digits.
    """
    span = match.group(0)
    if not strict and not any(character.isdigit() for character in span):
        return span
    return REDACTED


def redact_secrets(text: str, *, strict: bool = False) -> str:
    """Replace every credential-shaped span of ``text`` with ``[redacted]``."""
    text = _ASSIGNMENT_REDACTION.sub(_redact_assignment, text)
    for pattern in _REDACTIONS[1:]:
        text = pattern.sub(REDACTED, text)
    text = _OPAQUE_RUN.sub(lambda match: _redact_opaque(match, strict=strict), text)
    return text


def _looks_like_secret(text: str, *, strict: bool = False) -> bool:
    """True when redaction would change ``text``."""
    return redact_secrets(text, strict=strict) != text


def _looks_like_record_reference(value: str) -> bool:
    return bool(_DIGITS_ONLY.fullmatch(value) or _UUID.fullmatch(value))


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
        if not _looks_like_record_reference(value) and _looks_like_secret(
            value, strict=True
        ):
            _fail(
                f"{path} contains a value that looks like a credential; "
                "store a record reference instead."
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
        if _SENSITIVE_NAME_RE.search(key):
            _fail(f"{path} key {key!r} looks sensitive; never store credentials.")
        cleaned[key] = _sanitize_value(value, path=f"{path}.{key}", depth=depth)
    return cleaned


def _encoded_length(payload) -> int:
    try:
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        )
    except (TypeError, ValueError):  # pragma: no cover - default=str covers these
        return 0
    return len(encoded.encode("utf-8"))


def sanitize_payload(payload) -> dict:
    """Return a validated, non-sensitive copy of a job payload.

    Keys that look sensitive are rejected, and so are string *values* that look
    like credentials: silently rewriting a payload would hide a caller bug, so
    the payload is refused with a :class:`ValueError` instead.
    """
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        _fail("payload must be a mapping of record references.")
    # Size is checked first so an oversized payload is reported as oversized
    # rather than tripping the per-value credential check on the way there.
    if _encoded_length(payload) > MAX_PAYLOAD_BYTES:
        _fail(f"payload is larger than {MAX_PAYLOAD_BYTES} bytes when encoded.")
    cleaned = _sanitize_mapping(payload, path="payload")
    if _encoded_length(cleaned) > MAX_PAYLOAD_BYTES:
        _fail(f"payload is larger than {MAX_PAYLOAD_BYTES} bytes when encoded.")
    return cleaned


def sanitize_error_summary(summary) -> str:
    """Return a redacted, whitespace-collapsed, length-capped error summary."""
    text = "" if summary is None else str(summary)
    text = redact_secrets(text)
    text = " ".join(text.split())
    if len(text) > ERROR_SUMMARY_MAX_LENGTH:
        text = text[: ERROR_SUMMARY_MAX_LENGTH - 3].rstrip() + "..."
    return text
