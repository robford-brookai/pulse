"""Verify event-store consumer subscribes to all required Ocean topics."""

from __future__ import annotations

from utils import setup_service

setup_service("event-store")

from src.consumer import TOPICS


def test_logistics_topic_in_consumer():
    """ocean.logistics must be in the event-store consumer TOPICS list."""
    assert "ocean.logistics" in TOPICS


def test_ops_topic_in_consumer():
    """ocean.ops (heartbeats) must be in the event-store consumer TOPICS list."""
    assert "ocean.ops" in TOPICS
