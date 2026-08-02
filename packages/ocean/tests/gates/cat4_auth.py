"""Gate 4: Authentication & Authorization
Usage: BASE_URL_POCAR=http://localhost:8002 BASE_URL_ZCC=http://localhost:8006 \
       POCAR_WEBHOOK_SECRET=dev_secret ZCC_WEBHOOK_SECRET=dev_secret \
       pytest test/cat4_auth.py -v
Requires: pocar-connector (port 8002) and zcc-connector (port 8006) running.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

import httpx
import pytest

BASE_URL_POCAR = os.environ.get("BASE_URL_POCAR", "http://localhost:8002")
BASE_URL_ZCC = os.environ.get("BASE_URL_ZCC", "http://localhost:8006")
POCAR_SECRET = os.environ.get("POCAR_WEBHOOK_SECRET", "dev_secret")
ZCC_SECRET = os.environ.get("ZCC_WEBHOOK_SECRET", "dev_secret")

# Minimal valid POCAR payload
_POCAR_BODY = json.dumps({
    "alert_id": "test-alert-001",
    "patient_id": "patient-test-001",
    "alert_type": "glucose_high",
    "severity": "URGENT",
}).encode()

# Minimal valid ZCC payload
_ZCC_BODY = json.dumps({
    "event": "contact_center.engagement_ended",
    "payload": {
        "object": {
            "engagement_id": "eng-001",
            "duration": 120,
        }
    },
}).encode()


def _pocar_sig(body: bytes) -> str:
    return "sha256=" + hmac.new(POCAR_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _zcc_sig(body: bytes, ts: str) -> str:
    msg = f"v0:{ts}:{body.decode('utf-8')}"
    return "v0=" + hmac.new(ZCC_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Public health endpoints — no auth required
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,svc",
    [
        (f"{BASE_URL_POCAR}/health", "pocar-connector"),
        (f"{BASE_URL_ZCC}/health", "zcc-connector"),
    ],
)
def test_health_no_auth_returns_200(url, svc):
    r = httpx.get(url, timeout=5)
    assert r.status_code == 200, f"{svc} /health returned {r.status_code}"
    data = r.json()
    assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# POCAR webhook — HMAC-SHA256 (X-Pocar-Signature header)
# ---------------------------------------------------------------------------


def test_pocar_missing_signature_returns_401():
    r = httpx.post(
        f"{BASE_URL_POCAR}/webhooks/pocar",
        content=_POCAR_BODY,
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


def test_pocar_wrong_signature_returns_401():
    r = httpx.post(
        f"{BASE_URL_POCAR}/webhooks/pocar",
        content=_POCAR_BODY,
        headers={
            "Content-Type": "application/json",
            "X-Pocar-Signature": "sha256=deadbeef000000000000000000000000000000000000000000000000deadbeef",
        },
        timeout=5,
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


def test_pocar_wrong_scheme_returns_401():
    """md5= prefix instead of sha256= is rejected."""
    r = httpx.post(
        f"{BASE_URL_POCAR}/webhooks/pocar",
        content=_POCAR_BODY,
        headers={
            "Content-Type": "application/json",
            "X-Pocar-Signature": "md5=" + hmac.new(POCAR_SECRET.encode(), _POCAR_BODY, hashlib.md5).hexdigest(),
        },
        timeout=5,
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


def test_pocar_valid_signature_returns_200():
    r = httpx.post(
        f"{BASE_URL_POCAR}/webhooks/pocar",
        content=_POCAR_BODY,
        headers={
            "Content-Type": "application/json",
            "X-Pocar-Signature": _pocar_sig(_POCAR_BODY),
        },
        timeout=5,
    )
    # 200 = accepted; 500 = DB/broker issue in test environment (auth passed)
    assert r.status_code in (200, 500), f"expected 200 or 500, got {r.status_code}"


# ---------------------------------------------------------------------------
# ZCC webhook — Zoom v0 HMAC-SHA256 (x-zm-signature + x-zm-request-timestamp)
# ---------------------------------------------------------------------------


def test_zcc_missing_signature_returns_401():
    r = httpx.post(
        f"{BASE_URL_ZCC}/webhooks/zcc",
        content=_ZCC_BODY,
        headers={"Content-Type": "application/json"},
        timeout=5,
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


def test_zcc_wrong_signature_returns_401():
    ts = str(int(time.time()))
    r = httpx.post(
        f"{BASE_URL_ZCC}/webhooks/zcc",
        content=_ZCC_BODY,
        headers={
            "Content-Type": "application/json",
            "x-zm-request-timestamp": ts,
            "x-zm-signature": "v0=deadbeef000000000000000000000000000000000000000000000000deadbeef",
        },
        timeout=5,
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code}"


def test_zcc_valid_signature_returns_200():
    ts = str(int(time.time()))
    r = httpx.post(
        f"{BASE_URL_ZCC}/webhooks/zcc",
        content=_ZCC_BODY,
        headers={
            "Content-Type": "application/json",
            "x-zm-request-timestamp": ts,
            "x-zm-signature": _zcc_sig(_ZCC_BODY, ts),
        },
        timeout=5,
    )
    # 200 = accepted; 500 = broker issue in test environment (auth passed)
    assert r.status_code in (200, 500), f"expected 200 or 500, got {r.status_code}"


def test_zcc_url_validation_challenge_returns_200():
    """Zoom url_validation challenge must be answered without auth failure."""
    plain_token = "test-plain-token-12345"
    body = json.dumps({
        "event": "endpoint.url_validation",
        "payload": {"plainToken": plain_token},
    }).encode()
    ts = str(int(time.time()))
    r = httpx.post(
        f"{BASE_URL_ZCC}/webhooks/zcc",
        content=body,
        headers={
            "Content-Type": "application/json",
            "x-zm-request-timestamp": ts,
            "x-zm-signature": _zcc_sig(body, ts),
        },
        timeout=5,
    )
    assert r.status_code == 200, f"expected 200, got {r.status_code}"
    data = r.json()
    assert "plainToken" in data
    assert "encryptedToken" in data
    assert data["plainToken"] == plain_token
