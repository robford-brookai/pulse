"""Unit tests for ocean_broker.config — BrokerConfig factory."""

from __future__ import annotations

from unittest.mock import patch

from ocean_broker.config import build_consumer_config, build_producer_config


class TestRedpandaMode:
    """Tests for plaintext Redpanda (local dev) mode."""

    def test_redpanda_producer_config(self, monkeypatch):
        monkeypatch.setenv("REDPANDA_BROKERS", "localhost:9092")
        monkeypatch.delenv("MSK_BOOTSTRAP_SERVERS", raising=False)

        cfg = build_producer_config()

        assert cfg["bootstrap.servers"] == "localhost:9092"
        assert "security.protocol" not in cfg
        assert "sasl.mechanism" not in cfg
        assert "oauth_cb" not in cfg


class TestMSKMode:
    """Tests for MSK Serverless (SASL_SSL + OAUTHBEARER) mode."""

    MSK_BROKERS = "boot-xyz.kafka.us-east-1.amazonaws.com:9098"

    def test_msk_producer_config(self, monkeypatch):
        monkeypatch.setenv("MSK_BOOTSTRAP_SERVERS", self.MSK_BROKERS)
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        cfg = build_producer_config()

        assert cfg["bootstrap.servers"] == self.MSK_BROKERS
        assert cfg["security.protocol"] == "SASL_SSL"
        assert cfg["sasl.mechanism"] == "OAUTHBEARER"
        assert callable(cfg["oauth_cb"])
        assert cfg["connections.max.idle.ms"] == 540_000

    def test_msk_consumer_config_includes_group_id(self, monkeypatch):
        monkeypatch.setenv("MSK_BOOTSTRAP_SERVERS", self.MSK_BROKERS)
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        cfg = build_consumer_config(group_id="test-group")

        assert cfg["group.id"] == "test-group"
        assert cfg["enable.auto.commit"] is False
        assert cfg["auto.offset.reset"] == "earliest"

    def test_oauth_cb_converts_expiry_to_seconds(self, monkeypatch):
        monkeypatch.setenv("MSK_BOOTSTRAP_SERVERS", self.MSK_BROKERS)
        monkeypatch.setenv("AWS_REGION", "us-east-1")

        fake_token = "eyJhbGciOiJIUzI1NiJ9.test"
        fake_expiry_ms = 900_000  # 900 seconds in ms

        cfg = build_producer_config()

        with patch(
            "ocean_broker.config.generate_auth_token",
            return_value=(fake_token, fake_expiry_ms),
            create=True,
        ):
            # Patch the lazy import target
            with patch(
                "aws_msk_iam_sasl_signer.MSKAuthTokenProvider.generate_auth_token",
                return_value=(fake_token, fake_expiry_ms),
            ):
                token, expiry_sec = cfg["oauth_cb"]("ignored-config-arg")

        assert token == fake_token
        assert expiry_sec == fake_expiry_ms / 1000  # 900.0 seconds, NOT ms


class TestOverrides:
    """Test that caller overrides are applied."""

    def test_overrides_applied(self, monkeypatch):
        monkeypatch.setenv("REDPANDA_BROKERS", "localhost:9092")
        monkeypatch.delenv("MSK_BOOTSTRAP_SERVERS", raising=False)

        cfg = build_producer_config(overrides={"linger.ms": 100})

        assert cfg["linger.ms"] == 100
        assert cfg["bootstrap.servers"] == "localhost:9092"
