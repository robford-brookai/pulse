"""Source-inspection test: verify ticket.create.requested is wired in EVENT_HANDLERS."""
from __future__ import annotations


def test_ticket_create_requested_dispatches_to_handler():
    """EVENT_HANDLERS must map ticket.create.requested to handle_ticket_created."""
    from src.consumer import EVENT_HANDLERS
    from src.handlers.tickets import handle_ticket_created

    assert "ticket.create.requested" in EVENT_HANDLERS
    assert EVENT_HANDLERS["ticket.create.requested"] is handle_ticket_created
