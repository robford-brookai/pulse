"""Source-inspection tests: verify ticket event types are wired in EVENT_HANDLERS."""

from __future__ import annotations


def test_ticket_create_requested_dispatches_to_handler():
    """EVENT_HANDLERS must map ticket.create.requested to handle_ticket_created."""
    from src.consumer import EVENT_HANDLERS
    from src.handlers.tickets import handle_ticket_created

    assert "ticket.create.requested" in EVENT_HANDLERS
    assert EVENT_HANDLERS["ticket.create.requested"] is handle_ticket_created


def test_ticket_update_requested_dispatches_to_handler():
    """EVENT_HANDLERS must map ticket.update.requested to handle_ticket_updated."""
    from src.consumer import EVENT_HANDLERS
    from src.handlers.tickets import handle_ticket_updated

    assert "ticket.update.requested" in EVENT_HANDLERS
    assert EVENT_HANDLERS["ticket.update.requested"] is handle_ticket_updated


def test_self_published_ticket_types_are_not_consumed():
    """`ticket.created` and `ticket.updated` must not be EVENT_HANDLERS keys (task 3.9).

    Control-plane is the only publisher of both — every other service sends the
    `*.requested` form — so these keys routed control-plane's own output back into its
    handlers. For `ticket.created` that echo minted a fresh `uuid4` and `human_id` per
    pass: one requested ticket became an unbounded stream of tickets.
    """
    from src.consumer import EVENT_HANDLERS

    assert "ticket.created" not in EVENT_HANDLERS
    assert "ticket.updated" not in EVENT_HANDLERS
