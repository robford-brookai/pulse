"""ZCC HMAC signature validation.

Sourced from test/cat6_business_logic.py — unique tests not covered by
tests/requirements/. ZCC normalizer tests are intentionally omitted
(duplicated by tests/requirements/test_INGEST_02.py).
"""
from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi import HTTPException

from utils import setup_service

setup_service("zcc-connector")

from src.receiver import _validate_zoom_signature  # noqa: E402


def test_zcc_valid_hmac_does_not_raise():
    secret = "zoom-secret"
    ts = "1700000000"
    body = b'{"event":"test"}'
    msg = f"v0:{ts}:{body.decode()}"
    sig = "v0=" + hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    _validate_zoom_signature(body, ts, sig, secret)  # should not raise


def test_zcc_invalid_hmac_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        _validate_zoom_signature(b'{"event":"test"}', "1700000000", "v0=deadbeef", "zoom-secret")
    assert exc_info.value.status_code == 401
