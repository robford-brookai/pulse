"""`pulse_ledger.twenty` — the Twenty kanban ingress surface (twenty-kanban-webhook-ingress).

Design decision 1 splits it in two: `mapping.py` owns payload interpretation (drag → typed
disposition, task 2.1); `client.py` owns the outbound comment adapter (task 2.2). `api.py` keeps
auth at the door and wires both behind `/webhooks/twenty` (wave 2).
"""
