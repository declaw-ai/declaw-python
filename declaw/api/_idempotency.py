"""Idempotency keys and retry pacing, shared by the sync and async clients.

Both clients implement the same retry loop twice. Anything that has to agree
between them lives here so the two cannot drift — they already had two copies of
a deterministic ``delay * (attempt + 1)`` backoff, and a fix applied to one and
not the other is the failure this module exists to prevent.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Optional

import httpx

# Machine-readable error codes returned by POST /sandboxes.
#
# Branch on these, never on the message. Messages are prose and change; codes are
# contract. It matters most where one status means several unrelated things: 409
# on this endpoint is either an in-progress original create or a template that
# needs rebuilding, and only the first is worth retrying.

#: 409 — the original create carrying this key is still running. Retrying the
#: IDENTICAL request is correct, and is how a caller recovers the sandbox ID
#: after a lost response. ``Retry-After`` is set.
CODE_IDEMPOTENCY_IN_PROGRESS = "idempotency_in_progress"

#: 422 — this key was already used with different parameters. Not retryable; the
#: caller must generate a fresh key per logical create.
CODE_IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"

#: 409 — unrelated to idempotency; the template needs a rebuild. Retrying the
#: request unchanged cannot fix it.
CODE_TEMPLATE_NOT_READY = "template_not_ready"

#: Never let a server pin a client for minutes on a Retry-After.
_MAX_RETRY_AFTER = 60.0


def new_idempotency_key() -> str:
    """Return a fresh random key for one *logical* create.

    Generate this ONCE per create and reuse it across that call's retries. A
    fresh key per attempt defeats the mechanism entirely: the server treats each
    retry as a new create, which is the duplicate-sandbox bug the key exists to
    prevent.

    ``uuid4`` draws from ``os.urandom`` (a CSPRNG), which is what this needs:
    a collision between two tenants' concurrent creates would return one caller
    the other's sandbox. Do not swap it for anything seeded from ``random``.
    """
    return str(uuid.uuid4())


def retry_jitter(delay: float, rng=None) -> float:
    """Spread a retry delay so clients that failed together do not return in step.

    Equal jitter: keep half the backoff to preserve growth, randomize the other
    half to break the lockstep. Without it, a blip that trips N clients produces
    N simultaneous retries, then N more — the server sees the same herd on every
    round instead of a spread.

    ``rng`` is injectable so tests can pin the draw.
    """
    if delay <= 0:
        return 0.0
    half = delay / 2
    draw = rng() if rng is not None else secrets.randbelow(10_000) / 10_000
    return half + half * draw


def retry_after(response: "httpx.Response") -> Optional[float]:
    """Read a ``Retry-After`` expressed in seconds.

    Returns ``None`` when the header is absent or unparseable, letting the caller
    fall back to its own backoff. The HTTP-date form is deliberately unsupported:
    parsing it correctly needs timezone handling for a case this API does not
    emit, and guessing wrong would sleep for hours.
    """
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        secs = float(raw)
    except (TypeError, ValueError):
        return None
    if secs < 0:
        return None
    return min(secs, _MAX_RETRY_AFTER)


def error_code(response: "httpx.Response") -> str:
    """Extract the machine-readable ``code`` from an error body, or ``""``."""
    try:
        body = response.json()
    except Exception:
        return ""
    if not isinstance(body, dict):
        return ""
    code = body.get("code")
    return code if isinstance(code, str) else ""


def should_retry_conflict(response: "httpx.Response") -> bool:
    """True when a 409 is the retryable kind.

    Branches on the code, never the status: 409 also means ``template_not_ready``
    on this endpoint, and retrying that burns the caller's budget waiting for
    something that will not change.
    """
    return response.status_code == 409 and error_code(response) == CODE_IDEMPOTENCY_IN_PROGRESS
