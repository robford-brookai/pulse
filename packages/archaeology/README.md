# archaeology

Read-only access seam to the legacy Mongo cluster (BF-0a). Every backfill discovery and
extraction flow goes through this package — BF-0b's discovery session first, the BF-5 bulk
extraction later.

## Inherited connection pattern

The connection posture is inherited from `brookai/streamline`'s Mongo CDC service, at
`repos/dacorom/mongo-stream/src/config.py` and `repos/dacorom/mongo-stream/src/watcher.py` in
that repo — not invented here:

- driver: sync `pymongo` (`>=4.8`), `MongoClient`;
- bounded network waits so a black-holed Atlas connection raises instead of wedging:
  `serverSelectionTimeoutMS` 30000, `connectTimeoutMS` 20000, `socketTimeoutMS` 600000
  (streamline's defaults, env-tunable here as there);
- TLS on by default (Atlas);
- env-sourced configuration that fails fast naming the missing variable names.

Divergences are deliberate and recorded in `docs/contracts/consumes.md`: credentials arrive as a
secret-store reference (never a literal connection string), and `retryWrites` is off because this
seam never writes.
