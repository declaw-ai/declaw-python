"""Client-side PII anonymization and deanonymization.

Anonymization is delegated to the guardrails-service via HTTP.
Deanonymization runs entirely client-side using the redaction map
returned by the scan call -- no server round-trip on the response path.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple

import httpx

_INCOMPLETE_REDACTION_RE = re.compile(
    r"(?:R|RE|RED|REDA|REDAC|REDACT|REDACTE|REDACTED)" r"(?:_[A-Z0-9_]*(?:_\d*)?)?$"
)

RedactionMap = Dict[str, str]


# ---------------------------------------------------------------------------
# Guardrails HTTP client
# ---------------------------------------------------------------------------


class GuardrailsClient:
    """Thin HTTP client for the guardrails-service REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url or os.environ.get("GUARDRAILS_URL", "") or "http://localhost:8000"
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )

    def scan_pii(
        self,
        texts: List[str],
        confidence_threshold: float = 0.7,
        entities: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """POST /api/v1/scan with pii_scanner. Returns raw JSON response."""
        pii_spec: Dict[str, Any] = {
            "confidence_threshold": confidence_threshold,
        }
        if entities:
            pii_spec["entities"] = entities

        body = {
            "prompts": texts,
            "scanners": [
                {
                    "scanner_type": "pii_scanner",
                    "pii_scanner": pii_spec,
                }
            ],
        }
        resp = self._client.post("/api/v1/scan", json=body)
        resp.raise_for_status()
        data: Dict[str, Any] = resp.json()
        return data

    def health(self) -> Dict[str, Any]:
        resp = self._client.get("/health")
        resp.raise_for_status()
        data: Dict[str, Any] = resp.json()
        return data

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GuardrailsClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Scan-response helpers
# ---------------------------------------------------------------------------


def _extract_pii_response(scan_resp: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull the pii_scanner_response out of a ScanResponse dict."""
    for sr in scan_resp.get("scanner_responses", []):
        if sr.get("scanner_type") == "pii_scanner":
            pii: Optional[Dict[str, Any]] = sr.get("pii_scanner_response")
            return pii
    return None


def _build_redaction_map(pii_resp: Dict[str, Any]) -> RedactionMap:
    """Build {masked_value: entity_value} from entity_details."""
    rmap: RedactionMap = {}
    for detail in pii_resp.get("entity_details", []):
        masked = detail.get("masked_value", "")
        original = detail.get("entity_value", "")
        if masked and original:
            rmap[masked] = original
    return rmap


# ---------------------------------------------------------------------------
# PIIHandler -- the main public API
# ---------------------------------------------------------------------------


@dataclass
class PIIHandler:
    """Client-side PII anonymization and deanonymization.

    Usage::

        handler = PIIHandler(guardrails_url="http://guardrails:8000")

        # Anonymize
        anon_texts, rmap = handler.anonymize(["John Doe, SSN 123-45-6789"])
        # anon_texts = ["REDACTED_PERSON_1, SSN REDACTED_US_SSN_1"]
        # rmap = {"REDACTED_PERSON_1": "John Doe", "REDACTED_US_SSN_1": "123-45-6789"}

        # ... send anon_texts to LLM, get response ...

        # Deanonymize (non-streaming)
        restored = handler.deanonymize(response_text, rmap)

        # Deanonymize (streaming)
        for chunk in handler.deanonymize_stream(sse_text_chunks, rmap):
            print(chunk, end="", flush=True)
    """

    guardrails_url: Optional[str] = None
    confidence_threshold: float = 0.7
    entities: Optional[List[str]] = None
    _client: Optional[GuardrailsClient] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._client is None:
            self._client = GuardrailsClient(base_url=self.guardrails_url)

    # -- Anonymize (calls guardrails-service) ---------------------------------

    def anonymize(
        self,
        texts: List[str],
        confidence_threshold: Optional[float] = None,
        entities: Optional[List[str]] = None,
    ) -> Tuple[List[str], RedactionMap]:
        """Anonymize PII in *texts* via the guardrails-service.

        Returns (anonymized_texts, redaction_map).
        The redaction_map is ``{masked_token: original_value}`` and should
        be passed to :meth:`deanonymize` or :meth:`deanonymize_stream`.
        """
        assert self._client is not None
        scan_resp = self._client.scan_pii(
            texts,
            confidence_threshold=confidence_threshold or self.confidence_threshold,
            entities=entities or self.entities,
        )
        pii_resp = _extract_pii_response(scan_resp)
        if pii_resp is None:
            return texts, {}

        redaction_map = _build_redaction_map(pii_resp)
        sanitized = pii_resp.get("sanitized_response", "")

        if sanitized:
            anon_texts = [sanitized]
            if len(texts) > 1:
                anon_texts = [sanitized] + texts[1:]
        else:
            anon_texts = list(texts)

        return anon_texts, redaction_map

    # -- Deanonymize (fully client-side) --------------------------------------

    @staticmethod
    def deanonymize(text: str, redaction_map: RedactionMap) -> str:
        """Replace REDACTED_* tokens with original values.

        Longest tokens are replaced first to prevent partial matches
        (e.g. REDACTED_PERSON_10 before REDACTED_PERSON_1).
        """
        result = text
        for token, original in sorted(redaction_map.items(), key=lambda x: len(x[0]), reverse=True):
            if token in result:
                result = result.replace(token, original)
        return result

    # -- Streaming deanonymize (fully client-side) ----------------------------

    @staticmethod
    def deanonymize_stream(
        chunks: Iterable[str],
        redaction_map: RedactionMap,
    ) -> Generator[str, None, None]:
        """Yield deanonymized text chunks in real-time.

        Mirrors the buffering strategy from ``dlp_interceptor.py``:
        incoming chunks accumulate in a buffer.  After each chunk the
        buffer tail is checked for an incomplete ``REDACTED_*`` token.

        * **Incomplete token detected** -- hold the *entire* buffer
          (don't emit anything).  This avoids splitting context around
          a partially-received token.
        * **No incomplete token** -- deanonymize and yield the full
          buffer, then clear it.

        At EOF, whatever remains in the buffer is flushed with a final
        deanonymize pass.

        *chunks* is any iterable of text strings (e.g. extracted from
        SSE ``data:`` fields by the caller -- this method is
        provider-agnostic).
        """
        buf = ""

        for chunk in chunks:
            buf += chunk

            if _INCOMPLETE_REDACTION_RE.search(buf) is not None:
                continue

            yield PIIHandler.deanonymize(buf, redaction_map)
            buf = ""

        if buf:
            yield PIIHandler.deanonymize(buf, redaction_map)

    # -- Lifecycle ------------------------------------------------------------

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def __enter__(self) -> PIIHandler:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
