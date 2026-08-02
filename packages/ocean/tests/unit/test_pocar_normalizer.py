"""POCAR normalizer and HMAC signature validation.

Sourced from test/cat6_business_logic.py — unique tests not covered by
tests/requirements/.
"""
from __future__ import annotations

import hashlib
import hmac

import pytest
from fastapi import HTTPException

from utils import setup_service

setup_service("pocar-connector")

from src.normalizer import normalize_pocar_payload  # noqa: E402
from src.receiver import _validate_signature  # noqa: E402


def test_pocar_normalizer_produces_ocean_event():
    raw = {
        "alert_id": "alert-abc",
        "patient_id": "pt-xyz",
        "alert_type": "glucose_high",
        "severity": "URGENT",
        "clinic_id": "clinic-001",
        "triggered_at": "2026-03-06T07:00:00Z",
    }
    event = normalize_pocar_payload(raw)
    assert event.event_type == "alert.created"
    assert event.source_system == "pocar"
    assert event.entity_type == "alert"
    assert event.entity_id == "alert-abc"


def test_pocar_valid_hmac_does_not_raise(monkeypatch):
    monkeypatch.setenv("POCAR_WEBHOOK_SECRET", "test-secret-key")
    body = b'{"test": "payload"}'
    sig = "sha256=" + hmac.new(b"test-secret-key", body, hashlib.sha256).hexdigest()
    _validate_signature(body, sig)  # should not raise


def test_pocar_invalid_hmac_raises_401(monkeypatch):
    monkeypatch.setenv("POCAR_WEBHOOK_SECRET", "test-secret-key")
    with pytest.raises(HTTPException) as exc_info:
        _validate_signature(b'{"test": "payload"}', "sha256=deadbeef")
    assert exc_info.value.status_code == 401
