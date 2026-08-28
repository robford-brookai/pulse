# Identity fixtures

Synthetic demographic cases (no PHI — every name, DOB, and identifier here is invented) used to
drive the identity package's decision core: `identity/normalize.py` (wave 1, task 2.1) and
`identity/matcher.py` (wave 2, task 3.1). `loader.py` loads and shape-validates each JSON file in
this directory; see `tests/test_fixtures.py`.

Each case is one JSON file, named after itself, with a `kind` field selecting its shape:

- `kind: decision` — a referral, a set of existing persons, and the expected match decision
  (`match` / `mint` / `ambiguous`) with its rule id.
- `kind: normalization_pairs` — demographic pairs expected to normalize to the identical composite
  match key.
- `kind: ambiguous_dob` — a demographic record whose DOB must be rejected, never guessed.

## Cases

- **`exact_identifier_hit`** — a referral carries an `ExternalIdentifier` already held by an
  existing person. The identifier tier matches that person outright, even though the referral's
  demographics would composite-match a second, unrelated decoy person. Proves the identifier tier
  short-circuits before the composite tier is ever consulted.

- **`composite_unique_hit`** — a referral carries no known identifier, but its composite match key
  resolves to exactly one existing person. The composite tier matches.

- **`mint_unknown_everything`** — a referral whose identifier and composite digest match nothing
  among existing persons. Nothing matches, so the decision mints a new person.

- **`two_candidate_ambiguity`** — a referral's composite digest resolves to two distinct existing
  persons. v1 is deterministic-only: it never auto-chooses between candidates, so the decision is
  ambiguous and both candidates are carried for human review.

- **`near_miss_different_dob`** — the must-not-match case: same name, different DOB. An existing
  person and the referral share the identical normalized name and sex, but the DOB differs, so the
  composite digest differs and the existing person is never a candidate. The decision mints
  instead of matching.

- **`suffix_casing_pairs`** — pairs of demographic records differing only in casing, punctuation,
  or a name suffix (`Jr.`/`Sr.`/`III`). Each pair must normalize to the identical composite match
  key.

- **`ambiguous_dob_format`** — a DOB in a slash-separated numeric format with no format contract
  (`03/04/1990`), where day and month cannot be distinguished. Normalization must reject this
  explicitly, naming the offending field, rather than guess.

## Adding a case

1. Pick the `kind` that matches the shape you need, or extend `loader.py`'s shape validation if
   none fits.
2. Write the JSON file, name it after its `case` field, and document it above.
3. Run `uv run pytest packages/identity/tests/test_fixtures.py` — the loader validates every file
   in this directory, so a malformed new case fails immediately with the file name and defect.
