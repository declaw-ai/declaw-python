"""Idempotency key + retry pacing, for both the sync and async clients.

The two clients carry independent copies of the retry loop, so every behavioral
case here runs against BOTH. A fix applied to one and not the other is the exact
failure this file is built to catch.
"""

from __future__ import annotations

import re

import httpx
import pytest

from declaw.api._idempotency import (
    CODE_IDEMPOTENCY_IN_PROGRESS,
    CODE_IDEMPOTENCY_KEY_REUSED,
    CODE_TEMPLATE_NOT_READY,
    error_code,
    new_idempotency_key,
    retry_after,
    retry_jitter,
    should_retry_conflict,
)

UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _resp(status: int, body: dict | None = None, headers: dict | None = None):
    return httpx.Response(
        status,
        json=body if body is not None else {},
        headers=headers or {},
        request=httpx.Request("POST", "https://example.invalid/sandboxes"),
    )


class TestNewIdempotencyKey:
    def test_uuid4_shape(self):
        assert UUID4.match(new_idempotency_key())

    def test_unique(self):
        # A collision between two tenants' concurrent creates would hand one
        # caller the other's sandbox. Correctness boundary, not cosmetics.
        keys = {new_idempotency_key() for _ in range(10_000)}
        assert len(keys) == 10_000


class TestRetryJitter:
    def test_within_half_to_full(self):
        # Below d/2 would hammer the server harder than configured; above d
        # would stretch the caller's deadline past what max_retries implies.
        for _ in range(500):
            got = retry_jitter(0.4)
            assert 0.2 <= got <= 0.4

    def test_actually_varies(self):
        # The entire point: clients that fail together must not return in step.
        # A constant passes every bound check above.
        seen = {retry_jitter(1.0) for _ in range(200)}
        assert len(seen) > 10, "retries are still synchronised"

    def test_zero_stays_zero(self):
        assert retry_jitter(0) == 0.0
        assert retry_jitter(-1) == 0.0

    def test_rng_is_injectable(self):
        assert retry_jitter(1.0, rng=lambda: 0.0) == 0.5
        assert retry_jitter(1.0, rng=lambda: 1.0) == 1.0


class TestRetryAfter:
    @pytest.mark.parametrize(
        "hdr,want",
        [
            (None, None),
            ("2", 2.0),
            ("0", 0.0),
            ("-5", None),
            ("garbage", None),
            ("Wed, 21 Oct 2026 07:28:00 GMT", None),  # HTTP-date unsupported
            ("9999", 60.0),  # clamped; a server must not pin a client for hours
        ],
    )
    def test_parse(self, hdr, want):
        headers = {} if hdr is None else {"Retry-After": hdr}
        assert retry_after(_resp(409, {}, headers)) == want


class TestErrorCode:
    def test_extracts(self):
        assert error_code(_resp(422, {"code": CODE_IDEMPOTENCY_KEY_REUSED})) == (
            CODE_IDEMPOTENCY_KEY_REUSED
        )

    @pytest.mark.parametrize("body", [{}, {"code": None}, {"code": 7}, ["nope"]])
    def test_missing_or_wrong_type_is_empty(self, body):
        r = httpx.Response(409, json=body, request=httpx.Request("POST", "https://x.invalid/"))
        assert error_code(r) == ""

    def test_non_json_body_is_empty(self):
        r = httpx.Response(
            502,
            text="<html>bad gateway</html>",
            request=httpx.Request("POST", "https://x.invalid/"),
        )
        assert error_code(r) == ""


class TestShouldRetryConflict:
    """409 means two unrelated things; only one of them is retryable."""

    @pytest.mark.parametrize(
        "status,code,want",
        [
            (409, CODE_IDEMPOTENCY_IN_PROGRESS, True),
            (409, CODE_TEMPLATE_NOT_READY, False),
            (409, "", False),
            (422, CODE_IDEMPOTENCY_KEY_REUSED, False),
            (500, CODE_IDEMPOTENCY_IN_PROGRESS, False),  # code alone is not enough
        ],
    )
    def test_matrix(self, status, code, want):
        assert should_retry_conflict(_resp(status, {"code": code})) is want


# ── End-to-end through the real clients ──────────────────────────────────────
#
# Everything above tests helpers. These drive the actual retry loops, which is
# where the key has to survive a retry.


def _transport(responses, seen):
    """Mock transport recording the Idempotency-Key of every attempt."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Idempotency-Key"))
        r = responses[min(len(seen) - 1, len(responses) - 1)]
        return httpx.Response(
            r[0],
            json=r[1],
            headers=r[2] if len(r) > 2 else {},
            request=request,
        )

    return httpx.MockTransport(handler)


class TestSyncClientRetries:
    def _client(self, responses, seen):
        from declaw.api.client import ApiClient
        from declaw.connection_config import ConnectionConfig

        c = ApiClient(ConnectionConfig(api_key="k", api_url="https://x.invalid"), retry_delay=0.001)
        c._client = httpx.Client(
            base_url="https://x.invalid", transport=_transport(responses, seen)
        )
        return c

    def test_reuses_one_key_across_retries(self):
        # THE CASE THE WHOLE CHANGE RESTS ON.
        seen: list = []
        c = self._client(
            [
                (500, {"message": "boom"}),
                (500, {"message": "boom"}),
                (200, {"sandbox_id": "sbx-1"}),
            ],
            seen,
        )
        c.post(
            "/sandboxes",
            json={"template": "base"},
            headers={"Idempotency-Key": new_idempotency_key()},
        )
        assert len(seen) >= 2, "no retry happened; test proves nothing"
        assert all(
            k == seen[0] and k for k in seen
        ), f"key changed across retries {seen} — every retry would create a new sandbox"

    def test_retries_in_progress_409(self):
        seen: list = []
        c = self._client(
            [
                (409, {"code": CODE_IDEMPOTENCY_IN_PROGRESS}, {"Retry-After": "0"}),
                (200, {"sandbox_id": "sbx-1"}),
            ],
            seen,
        )
        c.post("/sandboxes", json={}, headers={"Idempotency-Key": "k1"})
        assert len(seen) == 2, "in-progress 409 was not retried; caller never learns the sandbox ID"

    def test_does_not_retry_template_not_ready(self):
        from declaw.exceptions import ConflictError

        seen: list = []
        c = self._client([(409, {"code": CODE_TEMPLATE_NOT_READY})], seen)
        with pytest.raises(ConflictError) as ei:
            c.post("/sandboxes", json={}, headers={"Idempotency-Key": "k1"})
        assert len(seen) == 1, "retried something a retry cannot fix"
        assert ei.value.code == CODE_TEMPLATE_NOT_READY

    def test_exposes_code_on_exception(self):
        from declaw.exceptions import InvalidArgumentError

        seen: list = []
        c = self._client([(422, {"code": CODE_IDEMPOTENCY_KEY_REUSED, "message": "reused"})], seen)
        with pytest.raises(InvalidArgumentError) as ei:
            c.post("/sandboxes", json={}, headers={"Idempotency-Key": "k1"})
        assert ei.value.code == CODE_IDEMPOTENCY_KEY_REUSED


@pytest.mark.asyncio
class TestAsyncClientRetries:
    def _client(self, responses, seen):
        from declaw.api.async_client import AsyncApiClient
        from declaw.connection_config import ConnectionConfig

        c = AsyncApiClient(
            ConnectionConfig(api_key="k", api_url="https://x.invalid"), retry_delay=0.001
        )
        c._client = httpx.AsyncClient(
            base_url="https://x.invalid", transport=_transport(responses, seen)
        )
        return c

    async def test_reuses_one_key_across_retries(self):
        seen: list = []
        c = self._client(
            [
                (500, {"message": "boom"}),
                (500, {"message": "boom"}),
                (200, {"sandbox_id": "sbx-1"}),
            ],
            seen,
        )
        await c.post("/sandboxes", json={}, headers={"Idempotency-Key": new_idempotency_key()})
        assert len(seen) >= 2
        assert all(
            k == seen[0] and k for k in seen
        ), f"key changed across retries {seen} — every retry would create a new sandbox"

    async def test_retries_in_progress_409(self):
        seen: list = []
        c = self._client(
            [
                (409, {"code": CODE_IDEMPOTENCY_IN_PROGRESS}, {"Retry-After": "0"}),
                (200, {"sandbox_id": "sbx-1"}),
            ],
            seen,
        )
        await c.post("/sandboxes", json={}, headers={"Idempotency-Key": "k1"})
        assert len(seen) == 2

    async def test_does_not_retry_template_not_ready(self):
        from declaw.exceptions import ConflictError

        seen: list = []
        c = self._client([(409, {"code": CODE_TEMPLATE_NOT_READY})], seen)
        with pytest.raises(ConflictError) as ei:
            await c.post("/sandboxes", json={}, headers={"Idempotency-Key": "k1"})
        assert len(seen) == 1
        assert ei.value.code == CODE_TEMPLATE_NOT_READY


class TestCodeOnEveryException:
    """``.code`` must exist on EVERY exception, not just the generic path.

    The 429 and 402 branches build their own exception objects and return before
    the generic construction. An assignment placed only on the generic path left
    those two without the attribute at all, so ``except SandboxError as e:
    e.code`` raised AttributeError — for exactly the callers being careful enough
    to branch on it. The whole suite passed with that hole in it.
    """

    @pytest.mark.parametrize(
        "status,code",
        [
            (409, CODE_TEMPLATE_NOT_READY),
            (422, CODE_IDEMPOTENCY_KEY_REUSED),
            (429, "rate_limited"),
            (402, "insufficient_balance"),
            (404, "not_found"),
            (500, "internal"),
        ],
    )
    def test_sync(self, status, code):
        from declaw.api.client import ApiClient
        from declaw.connection_config import ConnectionConfig

        c = ApiClient(ConnectionConfig(api_key="k", api_url="https://x.invalid"))
        with pytest.raises(Exception) as ei:
            c._raise_for_status(_resp(status, {"message": "m", "code": code}))
        assert ei.value.code == code, f"{status} lost its code"

    def test_absent_code_is_empty_not_missing(self):
        from declaw.api.client import ApiClient
        from declaw.connection_config import ConnectionConfig

        c = ApiClient(ConnectionConfig(api_key="k", api_url="https://x.invalid"))
        with pytest.raises(Exception) as ei:
            c._raise_for_status(_resp(500, {"message": "boom"}))
        # Never AttributeError; callers can compare unconditionally.
        assert ei.value.code == ""

    def test_base_class_default(self):
        from declaw.exceptions import SandboxError

        assert SandboxError("x").code == ""
        assert SandboxError("x", code="abc").code == "abc"


class TestCreateWiring:
    """``Sandbox.create`` must actually SEND the header.

    Everything above drives ``client.post`` with a header supplied by the test,
    which proves the retry loop preserves a key but says nothing about whether
    create generates one. Dropping the header at the call site would leave every
    other test in this file green while restoring the original bug.
    """

    def test_sync_create_sends_key(self, monkeypatch):
        from declaw.api import client as client_mod
        from declaw.sandbox_sync.main import Sandbox

        captured = {}

        class FakePost:
            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        def fake_post(self, path, *, json=None, headers=None, **kw):
            captured["path"] = path
            captured["headers"] = headers or {}
            return FakePost({"sandbox_id": "sbx-1", "status": "running"})

        monkeypatch.setattr(client_mod.ApiClient, "post", fake_post)
        monkeypatch.setenv("DECLAW_API_KEY", "k")

        Sandbox.create(template="base")

        assert captured["path"] == "/sandboxes"
        key = captured["headers"].get("Idempotency-Key")
        assert key, "create sent no Idempotency-Key — the duplicate-sandbox bug is back"
        assert UUID4.match(key), f"key is not a v4 UUID: {key!r}"

    def test_two_creates_use_different_keys(self, monkeypatch):
        # Per LOGICAL create. Reusing one key across two separate creates would
        # make the second replay the first's response and return the wrong
        # sandbox — the opposite failure from reusing it across retries.
        from declaw.api import client as client_mod
        from declaw.sandbox_sync.main import Sandbox

        keys = []

        class FakePost:
            def json(self):
                return {"sandbox_id": "sbx-1", "status": "running"}

        def fake_post(self, path, *, json=None, headers=None, **kw):
            keys.append((headers or {}).get("Idempotency-Key"))
            return FakePost()

        monkeypatch.setattr(client_mod.ApiClient, "post", fake_post)
        monkeypatch.setenv("DECLAW_API_KEY", "k")

        Sandbox.create(template="base")
        Sandbox.create(template="base")

        assert len(keys) == 2 and all(keys)
        assert keys[0] != keys[1], "two separate creates shared one key"

    @pytest.mark.asyncio
    async def test_async_create_sends_key(self, monkeypatch):
        # A SEPARATE call site from the sync path. The two are edited
        # independently, so a header added to one and missed on the other is the
        # likely failure — cover both.
        from declaw.api import async_client as async_mod
        from declaw.sandbox_async.main import AsyncSandbox

        captured = {}

        class FakePost:
            def json(self):
                return {"sandbox_id": "sbx-1", "status": "running"}

        async def fake_post(self, path, *, json=None, headers=None, **kw):
            captured["headers"] = headers or {}
            return FakePost()

        monkeypatch.setattr(async_mod.AsyncApiClient, "post", fake_post)
        monkeypatch.setenv("DECLAW_API_KEY", "k")

        await AsyncSandbox.create(template="base")

        key = captured["headers"].get("Idempotency-Key")
        assert key, "async create sent no Idempotency-Key"
        assert UUID4.match(key)


def test_codes_are_importable_from_the_package_root():
    """The docs tell users to `from declaw import CODE_...`.

    They lived only in the private `declaw.api._idempotency` module, so the
    feature was unusable as documented — callers cannot branch on codes they
    cannot import. Found by writing the docs, not by any test.
    """
    import declaw

    for name in (
        "CODE_IDEMPOTENCY_IN_PROGRESS",
        "CODE_IDEMPOTENCY_KEY_REUSED",
        "CODE_TEMPLATE_NOT_READY",
    ):
        assert hasattr(declaw, name), f"declaw.{name} is not exported"
        assert name in declaw.__all__, f"{name} missing from __all__"
