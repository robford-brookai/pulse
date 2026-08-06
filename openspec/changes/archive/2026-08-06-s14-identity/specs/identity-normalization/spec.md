## Purpose

Defines the deterministic demographic normalization that produces the composite match key, the
rejection of ambiguous inputs, and the PHI boundary: the readable composite exists only inside
the identity package, and the ledger receives nothing but its sha256 digest.

## ADDED Requirements

### Requirement: Normalization is deterministic and documented

Demographic normalization SHALL be deterministic: casefold, strip punctuation, strip name
suffixes (Jr/Sr/III), and reduce the first name to its first initial, producing the composite
match key (last name + DOB + sex + first-initial). The same input SHALL always yield the same
composite. The rules SHALL be documented as a table of rules with examples, published with the
package, so a reviewer can reproduce any composite by hand.

#### Scenario: Suffix and casing variants normalize identically

- **GIVEN** two demographic records that differ only in casing, punctuation, or a name suffix
  (e.g. `MARTINEZ, Jr.` vs `martinez`)
- **WHEN** each is normalized
- **THEN** both yield the identical composite match key

#### Scenario: Normalization rules are published

- **GIVEN** the built package documentation
- **WHEN** a reviewer consults the matching rules document
- **THEN** every normalization rule appears with at least one worked example, and the documented
  rules reproduce the package's actual output for those examples

### Requirement: Ambiguous DOB formats are rejected, never guessed

DOB parsing SHALL accept only unambiguous formats. An input whose day and month cannot be
distinguished (e.g. `03/04/1990` with no format contract) SHALL be rejected explicitly — the
record does not enter matching with a guessed date, and the rejection names the offending field.

#### Scenario: Ambiguous DOB is rejected

- **GIVEN** a referral whose DOB is in an ambiguous day/month format
- **WHEN** normalization runs
- **THEN** the record is rejected with an error naming the DOB field and no composite is produced

### Requirement: The ledger never receives demographics

The readable composite is PHI and SHALL NOT leave the identity package. Only the composite's
sha256 hex digest (matching `[0-9a-f]{64}`, the `ledger.person_match_keys` check constraint)
SHALL be sent to the ledger. No demographic field or readable composite SHALL appear in any
command payload, log line, or error message emitted by the package.

#### Scenario: Only the digest reaches the ledger

- **GIVEN** a normalized composite for a referral
- **WHEN** the package interacts with the ledger for the composite tier
- **THEN** the value transmitted is the sha256 hex digest of the composite, matching
  `[0-9a-f]{64}`, and the readable composite appears nowhere in the request

#### Scenario: Demographics never reach logs or errors

- **GIVEN** any resolution path, including rejections and failures
- **WHEN** the package logs or raises
- **THEN** log lines and error messages carry subject keys and rule ids, never names, DOBs, sex,
  or the readable composite
