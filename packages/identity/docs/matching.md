# Identity matching — normalization rules

Rules version: **v1**

This document is the published rule set behind `identity.normalize.composite_digest`. It exists so
a reviewer can take any two referrals, work the rules by hand, and say whether the matcher will
treat them as the same person — without reading the code and without access to the ledger.

Every worked example below is re-derived from the package in
`packages/identity/tests/test_matching_docs.py`. A rule change that does not update this table
fails the suite.

## Why the version number matters

The composite match key is hashed and registered in `ledger.person_match_keys`. Rows already
registered were derived under the rules in force at the time. Changing a rule changes composites,
therefore digests, therefore which candidates a lookup returns — so a rule change is a **breaking
change to the genesis contract**, requiring a re-registration plan and a version bump here, not a
patch release.

## The composite match key

Four normalized fields, joined with `:` in this order:

```
<last name>:<dob>:<sex>:<first initial>
```

The readable composite is PHI and never leaves `identity/normalize.py`. The only value any caller
receives is its sha256 hex digest, matching `[0-9a-f]{64}` — the check constraint
`ledger.person_match_keys` enforces.

## Rules

| Rule | Applies to | Description | Example |
| --- | --- | --- | --- |
| R1 | last name, first name | Unicode NFKD decomposition, combining marks dropped | `Martínez` → `martinez` |
| R2 | last name, first name, sex | Casefold | `MARTINEZ` → `martinez` |
| R3 | last name, first name | Split on anything outside `[a-z0-9]`, join the parts — apostrophes, hyphens, commas, periods and spaces disappear | `O'Brien-Walsh` → `obrienwalsh` |
| R4 | last name, first name | Drop generational suffix tokens: `jr` `jnr` `sr` `snr` `ii` `iii` `iv` `v` `vi` `vii` `viii` `2nd` `3rd` `4th`. Guard: if dropping them would leave nothing, the tokens are kept | `MARTINEZ, Jr.` → `martinez`; `Sr` → `sr` |
| R5 | first name | Reduce to the first character after R1–R4 | `Alexandra` → `a` |
| R6 | sex | Map an accepted spelling to one character: `m`/`male` → `m`, `f`/`female` → `f`, `o`/`other` → `o`, `u`/`unk`/`unknown` → `u`. Anything else is rejected | `female` → `f` |
| R7 | dob | Parse from unambiguous spellings only, emit ISO `YYYY-MM-DD`: ISO `YYYY-MM-DD`, compact `YYYYMMDD`, an alphabetic month name in either order (`4 Mar 1990`, `March 4, 1990`), or a `datetime.date`. Everything else is rejected | `04 Mar 1990` → `1990-03-04` |

### Why R7 rejects instead of guessing

`03/04/1990` carries no format contract: it is 4 March under one convention and 3 April under
another. Picking one registers a match key for a date the referral may not have meant, and a
wrong key silently attaches a person to the wrong record. The rejection names the `dob` field and
stops there — it never echoes the value, because the value is PHI and the rejection is logged.

## Rejection rule ids

| Rule id | Meaning |
| --- | --- |
| `ambiguous_dob` | The DOB's shape carries no format contract, or is not a date at all |
| `invalid_dob` | The shape was accepted but names a day the calendar does not have |
| `missing_field` | The field normalizes to nothing — empty, whitespace, or punctuation only |
| `unknown_sex` | The sex value is not one of R6's accepted spellings |

An error names the field and the rule id and carries no demographic value.

## Worked examples

All demographics below are synthetic. `A1`/`A2`/`A3` are the same person spelled three ways, as
are `B1`/`B2` — identical composites, identical digests.

| # | last_name | first_name | dob | sex | composite | digest |
| --- | --- | --- | --- | --- | --- | --- |
| A1 | `Martinez` | `Alex` | `1990-03-04` | `F` | `martinez:1990-03-04:f:a` | `37614efc61bd114484f8f413c94d203d2e191215bc0287257d053abb34c5045b` |
| A2 | `MARTINEZ, Jr.` | `ALEXANDRA` | `04 Mar 1990` | `female` | `martinez:1990-03-04:f:a` | `37614efc61bd114484f8f413c94d203d2e191215bc0287257d053abb34c5045b` |
| A3 | `Martínez` | `a.` | `19900304` | `f` | `martinez:1990-03-04:f:a` | `37614efc61bd114484f8f413c94d203d2e191215bc0287257d053abb34c5045b` |
| B1 | `O'Brien-Walsh` | `Sam` | `1982-11-30` | `M` | `obrienwalsh:1982-11-30:m:s` | `6c605716e1d83fc5c6b9ac07a3c306e7b9fdd27f1bae6e0b09d901cbebd38b4c` |
| B2 | `obrien walsh III` | `sam` | `November 30, 1982` | `male` | `obrienwalsh:1982-11-30:m:s` | `6c605716e1d83fc5c6b9ac07a3c306e7b9fdd27f1bae6e0b09d901cbebd38b4c` |
| C1 | `Nguyen` | `Jordan` | `2001-07-15` | `U` | `nguyen:2001-07-15:u:j` | `5ca421a5e156c2392623a7d9f28f55f11fe7241ec4a4c5a29a655d7b914cd008` |

To reproduce a digest by hand: `printf '%s' 'martinez:1990-03-04:f:a' | shasum -a 256`.

### Rejected inputs

| # | last_name | first_name | dob | sex | field | rule id |
| --- | --- | --- | --- | --- | --- | --- |
| R-1 | `Martinez` | `Alex` | `03/04/1990` | `F` | `dob` | `ambiguous_dob` |
| R-2 | `Martinez` | `Alex` | `04/03/90` | `F` | `dob` | `ambiguous_dob` |
| R-3 | `Martinez` | `Alex` | `1990-02-30` | `F` | `dob` | `invalid_dob` |
| R-4 | `Martinez` | `Alex` | `31 Feb 1990` | `F` | `dob` | `invalid_dob` |
| R-5 | `-` | `Alex` | `1990-03-04` | `F` | `last_name` | `missing_field` |
| R-6 | `Martinez` | `Alex` | `1990-03-04` | `yes` | `sex` | `unknown_sex` |

## What this document does not cover

Match *decisions* — the two-tier exact-identifier / composite trichotomy, evidence, and rule ids
like `composite_unique` — belong to `identity/matcher.py` and are documented with it.
