"""PII redaction for logs and persistent memory.

Uses the Cloud DLP API when ``ENABLE_DLP_REDACTION=1`` and credentials are
available; otherwise falls back to a fast regex scrubber. Both paths return
the same shape so callers never branch.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(
    r"\b(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}\b"
)
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_STREET_RE = re.compile(
    r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive)\b"
)

_REPLACEMENTS = (
    (_EMAIL_RE, "[REDACTED_EMAIL]"),
    (_PHONE_RE, "[REDACTED_PHONE]"),
    (_CREDIT_CARD_RE, "[REDACTED_CC]"),
    (_SSN_RE, "[REDACTED_SSN]"),
    (_STREET_RE, "[REDACTED_ADDRESS]"),
)


def _redact_str(text: str) -> str:
    for pattern, replacement in _REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def _redact_with_dlp(text: str) -> str:  # pragma: no cover - network call
    try:
        from google.cloud import dlp_v2

        client = dlp_v2.DlpServiceClient()
        parent = f"projects/{os.environ.get('GOOGLE_CLOUD_PROJECT')}"
        info_types = [
            {"name": "EMAIL_ADDRESS"},
            {"name": "PHONE_NUMBER"},
            {"name": "CREDIT_CARD_NUMBER"},
            {"name": "STREET_ADDRESS"},
            {"name": "US_SOCIAL_SECURITY_NUMBER"},
            {"name": "PERSON_NAME"},
        ]
        inspect_config = {"info_types": info_types, "min_likelihood": "LIKELY"}
        deidentify_config = {
            "info_type_transformations": {
                "transformations": [
                    {"primitive_transformation": {"replace_with_info_type_config": {}}}
                ]
            }
        }
        response = client.deidentify_content(
            request={
                "parent": parent,
                "deidentify_config": deidentify_config,
                "inspect_config": inspect_config,
                "item": {"value": text},
            }
        )
        return response.item.value
    except Exception as exc:
        logger.warning("DLP redaction failed, using regex fallback: %s", exc)
        return _redact_str(text)


def redact_pii(value: Any) -> Any:
    """Recursively scrub PII from strings inside dicts / lists / tuples."""
    if isinstance(value, str):
        if os.environ.get("ENABLE_DLP_REDACTION", "").lower() in ("1", "true", "yes"):
            return _redact_with_dlp(value)
        return _redact_str(value)
    if isinstance(value, dict):
        return {k: redact_pii(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        cleaned = [redact_pii(v) for v in value]
        return type(value)(cleaned)
    return value
