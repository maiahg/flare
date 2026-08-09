from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_VERSION = "v0"
# Reject requests whose timestamp is more than 5 minutes from now (replay guard).
MAX_TIMESTAMP_SKEW_SECONDS = 60 * 5


def compute_signature(signing_secret: str, timestamp: str, body: str) -> str:
    """Return the expected ``v0=...`` signature for a request."""
    basestring = f"{SIGNATURE_VERSION}:{timestamp}:{body}".encode()
    digest = hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def is_valid_signature(
    *,
    signing_secret: str,
    timestamp: str | None,
    body: str,
    signature: str | None,
    now: float | None = None,
    max_skew_seconds: int = MAX_TIMESTAMP_SKEW_SECONDS,
) -> bool:
    """Validate a Slack signature and timestamp freshness."""
    if not timestamp or not signature:
        return False

    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    current = time.time() if now is None else now
    if abs(current - ts) > max_skew_seconds:
        return False

    expected = compute_signature(signing_secret, timestamp, body)
    return hmac.compare_digest(expected, signature)