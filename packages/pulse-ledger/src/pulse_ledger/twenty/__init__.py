"""The Twenty webhook route's body: payload interpretation and the outbound comment adapter.

`pulse_ledger.api` keeps what it already owns — auth at the door, error → status mapping, response
shaping. This package owns everything behind that door (`twenty-kanban-webhook-ingress` design
decision 1), so a 200-line payload interpreter never grows inside the API module.
"""

from __future__ import annotations
