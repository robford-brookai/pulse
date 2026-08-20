"""twenty-projection — the ledger-fed Twenty board projection.

Committed ledger events for board subjects upsert Twenty records through the core REST
surface, monotonically on ``(subject_id, ledger_seq)``, so the board is a view of the
ledger rather than a parallel store. Scaffold only today: the apply core and consumer
loop land in waves 1-2 of the twenty-projection change.
"""
