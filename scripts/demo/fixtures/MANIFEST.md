# Demo 5 fixture manifest

Generated once, hand-authored, and committed (`pulse-demo-closeout` design.md decision 3): a
`synthea-seed` overlay for one synthetic patient plus the raw landing/mart rows the demo's
consent-ingress and verdict-relay stages read through their real producer surfaces. None of
this is Synthea-generated FHIR output, so no Java is needed to regenerate or validate it
(`synthetic-population` spec, "Check stays Java-free") — it engineers state the same way every
other `synthea-seed` overlay does (`packages/synthea-seed/src/synthea_seed/overlays/`), pinned
against the population's committed seed for provenance:

- **Pinned population seed**: `20260809` (`packages/synthea-seed/src/synthea_seed/config/synthea-pin.yaml`)
- **Patient key**: `brook-fx-demo5-episode-0001` — the same identifier appears as the referral
  variants' resolved `person_id`, the consent export row's `subject_key`, and the verdict mart
  row's `subject_id`.

Re-authoring any file below is an explicit, reviewed edit; this table is the drift receipt —
regenerate it with `shasum -a 256 <file>` and diff.

| File | sha256 |
|---|---|
| `overlay.yaml` | `235a3a25a8fc4df356783796f6944d3bb2575e92785d5c35fe1762b46a67f337` |
| `referral_variants.json` | `b4349d9ff7d5e51f5b7ded5247d1187a7ddb82fe5a8eda112ce45024e6b2e02f` |
| `consent_export_row.json` | `4f7c4a703abf4c9878ccb1dbaf4f6f7bfa9bdf085166154e717c689060b5e3e2` |
| `verdict_mart_row.json` | `b1e97519c18258802207f2bce0d60e0713bfed9c9a93d05ffbb1ccbceb9f933b` |

## Contents

- `overlay.yaml` — the `synthea-seed/overlay@1` fixture (`fixture: demo5_end_to_end_episode`):
  an open, qualified billing episode, its positive verdict, and the granted consent, all on
  `brook-fx-demo5-episode-0001`.
- `referral_variants.json` — three referrals in `identity.matcher.resolve`'s input shape
  (`packages/identity/tests/fixtures/*.json` convention): `mint` (nothing matches, mints the
  patient), `exact_match` (the identifier the mint minted against, short-circuits to that
  person), `quarantine` (no identifier, two demographic-alike candidates, quarantined for
  human review).
- `consent_export_row.json` — one Customer.io consent export landing row on the pinned
  `CONTRACT_COLUMNS` (`packages/consent-ingress/src/consent_ingress/row_source.py`).
- `verdict_mart_row.json` — one verdict mart row on the pinned eight-column contract
  (`docs/contracts/consumes.md`), verdict type `billing_eligibility` (registered in
  `packages/verdict-relay/src/verdict_relay/config.py` against `billing_episode`).

All demographics and identifiers are invented; no PHI.
