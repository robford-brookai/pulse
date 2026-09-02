"""The engine's consume loop: fixture queue → `pulse_core.consume` → `PostgresFactStore` (task 3.2).

Same throwaway-cluster fixtures as `test_store.py`; the queue is a fake SQS client, same
`FixtureQueue` shape twenty-projection's `test_consumer.py` uses. Covers the wiring itself
(`resolve_config`, `run`) plus the redelivery scenario end to end through the real kit consume
loop, not just the store directly.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from billing import consumer
from billing.consumer import ConsumerConfig, ConsumerStartupError, resolve_config, run

INFRA_DIR = Path(__file__).resolve().parents[1] / "infra" / "postgres"
QUEUE_URL = "https://sqs.fixture/000000000000/billing-engine"


def _upgrade(database_url: str) -> None:
    cfg = Config(str(INFRA_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(INFRA_DIR))
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "0001")


class FixtureQueue:
    """A fake SQS client: scripted delivery batches, deletions recorded into a shared journal."""

    def __init__(self, deliveries: list[list[dict[str, Any]]], journal: list[tuple[str, str]]) -> None:
        self.deliveries = [list(batch) for batch in deliveries]
        self.journal = journal

    def receive_message(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["QueueUrl"] == QUEUE_URL
        batch = self.deliveries.pop(0) if self.deliveries else []
        return {"Messages": batch}

    def delete_message(self, **kwargs: Any) -> None:
        assert kwargs["QueueUrl"] == QUEUE_URL
        self.journal.append(("delete", kwargs["ReceiptHandle"]))


def envelope(
    *, event_id: str, effective_at: str, payload: dict[str, object], subject_key: str = "ep-1"
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "billing_episode.declared",
        "subject_type": "billing_episode",
        "subject_key": subject_key,
        "effective_at": effective_at,
        "payload": payload,
    }


def queue_message(env: dict[str, Any], *, receipt: str) -> dict[str, Any]:
    """An EventBridge-delivered message: the envelope rides whole inside `detail`."""
    return {"Body": json.dumps({"detail": env}), "ReceiptHandle": receipt}


def _facts(db: psycopg.Connection, subject_key: str = "ep-1") -> dict[str, object]:
    cur = db.execute("SELECT facts FROM billing_engine.subject_facts WHERE subject_key = %s", (subject_key,))
    (facts,) = cur.fetchone()  # type: ignore[misc]
    return facts


def test_a_committed_event_folds_from_the_queue_alone(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    journal: list[tuple[str, str]] = []
    event_id = str(uuid.uuid4())
    queue = FixtureQueue(
        [
            [
                queue_message(
                    envelope(
                        event_id=event_id, effective_at="2026-09-01T10:00:00+00:00", payload={"to_state": "qualified"}
                    ),
                    receipt="rh-1",
                )
            ]
        ],
        journal,
    )

    run(ConsumerConfig(database_url=database_url, queue_url=QUEUE_URL), conn=db, sqs_client=queue, iterations=1)

    assert _facts(db)["to_state"] == "qualified"
    assert journal == [("delete", "rh-1")]


def test_a_redelivered_event_folds_nothing_twice(database_url: str, db: psycopg.Connection) -> None:
    _upgrade(database_url)
    journal: list[tuple[str, str]] = []
    event_id = str(uuid.uuid4())
    message = queue_message(
        envelope(event_id=event_id, effective_at="2026-09-01T10:00:00+00:00", payload={"to_state": "qualified"}),
        receipt="rh-1",
    )
    queue = FixtureQueue([[message], [message]], journal)

    run(ConsumerConfig(database_url=database_url, queue_url=QUEUE_URL), conn=db, sqs_client=queue, iterations=2)

    cur = db.execute("SELECT count(*) FROM billing_engine.subject_facts")
    (count,) = cur.fetchone()  # type: ignore[misc]
    assert count == 1
    assert journal == [("delete", "rh-1"), ("delete", "rh-1")]


def test_resolve_config_reads_the_environment() -> None:
    env = {"BILLING_ENGINE_CREDENTIAL": "postgresql://x/y", "SQS_QUEUE_URL": QUEUE_URL}
    config = resolve_config(env)
    assert config == ConsumerConfig(database_url="postgresql://x/y", queue_url=QUEUE_URL)


@pytest.mark.parametrize("missing", ["BILLING_ENGINE_CREDENTIAL", "SQS_QUEUE_URL"])
def test_resolve_config_names_a_missing_variable(missing: str) -> None:
    env = {"BILLING_ENGINE_CREDENTIAL": "postgresql://x/y", "SQS_QUEUE_URL": QUEUE_URL}
    del env[missing]

    with pytest.raises(ConsumerStartupError, match=missing):
        resolve_config(env)


def test_main_fails_startup_by_name_without_crashing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("BILLING_ENGINE_CREDENTIAL", raising=False)
    monkeypatch.delenv("SQS_QUEUE_URL", raising=False)

    exit_code = consumer.main([])

    assert exit_code == 2
    assert "BILLING_ENGINE_CREDENTIAL" in capsys.readouterr().err
