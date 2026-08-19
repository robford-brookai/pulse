# twenty-webhook-auth Specification

## Purpose
Defines the authenticated door of the Twenty kanban ingress: HMAC signature verification with a
freshness window, dual-secret rotation per D15's quarterly cadence, and attribution — the event's
actor is the webhook credential's principal, never anything the payload claims.
## Requirements
### Requirement: Webhook requests are signature-verified before any processing

Every request to the Twenty webhook route SHALL be verified — HMAC over the message Twenty
actually signs, timestamp inside the freshness window, checked before the signature — before the
payload is parsed or any command is attempted. A request that fails verification SHALL be rejected
as unauthenticated with no ledger write, no comment, and no payload content in the rejection or
its log line.

The verified wire format SHALL be the one Twenty's sender produces, which is fixed in its server
code with no configuration hook, so this repo adapts rather than negotiating:

- The signature, timestamp, and nonce SHALL be read from `X-Twenty-Webhook-Signature`,
  `X-Twenty-Webhook-Timestamp`, and `X-Twenty-Webhook-Nonce`.
- The signed message SHALL be `{timestamp}:{body}` and the signature SHALL be its HMAC-SHA256 as
  bare lowercase hex, with no version prefix on either the message or the digest.
- The timestamp SHALL be interpreted as **milliseconds** since the epoch.

The signature SHALL be computed over the raw request bytes as received, never over a
re-serialization of a parsed body, so that verification survives any future middleware. Comparison
SHALL be constant-time.

The nonce SHALL NOT be treated as a replay guard or an idempotency key: Twenty regenerates it per
delivery attempt, so a redelivery of one write arrives with a fresh nonce.

#### Scenario: A validly signed request is processed

- **GIVEN** the webhook route is enabled with a configured secret
- **WHEN** a request arrives whose `X-Twenty-Webhook-Signature` is the bare hex HMAC-SHA256 of
  `{timestamp}:{body}` under that secret, with a millisecond timestamp inside the freshness window
- **THEN** the payload proceeds to drag mapping

#### Scenario: A millisecond timestamp is inside the window, not 55,000 years stale

- **GIVEN** a correctly signed request whose timestamp is the current time in milliseconds
- **WHEN** freshness is evaluated
- **THEN** the request is inside the window and is processed, rather than being rejected as stale
  by a seconds-based reading of the same value

#### Scenario: A tampered body is rejected without processing

- **GIVEN** the webhook route is enabled with a configured secret
- **WHEN** a request's body does not match its signature
- **THEN** the request is rejected as unauthenticated, no command is attempted, and neither the
  body nor the signature appears in the rejection or its log line

#### Scenario: A stale timestamp is rejected

- **GIVEN** the webhook route is enabled with a configured secret
- **WHEN** a correctly signed request arrives with a timestamp outside the freshness window
- **THEN** the request is rejected as unauthenticated and no command is attempted

#### Scenario: A signature in the retired affixed format no longer verifies

- **GIVEN** the webhook route is enabled with a configured secret
- **WHEN** a request arrives signed in the previous scheme — a `v1=` prefixed digest over a
  `v1:{timestamp}:` prefixed message, carried on `X-Pulse-Signature`
- **THEN** it is rejected as unauthenticated, because the route reads only Twenty's headers and
  message construction

### Requirement: Rotation accepts two secrets during the window

The webhook configuration SHALL accept an optional second secret, and a signature valid under
either SHALL verify — so the D15 quarterly rotation is: add the incoming secret, re-point Twenty,
remove the retired secret — with no interval in which correctly signed requests are rejected.
Secret values SHALL live in the environment (sourced from the platform secret store), never in
workflow config, code, or fixtures.

#### Scenario: A request signed with the incoming secret verifies during rotation

- **GIVEN** both the current and the incoming secret are configured
- **WHEN** requests arrive signed with either secret
- **THEN** both verify

#### Scenario: A retired secret stops verifying once removed

- **GIVEN** rotation has completed and only the new secret is configured
- **WHEN** a request arrives signed with the retired secret
- **THEN** it is rejected as unauthenticated

### Requirement: The webhook actor is the credential's principal, never a body field

Commands produced by the webhook path SHALL be attributed to the webhook credential's fixed
principal (D15: attribution is authentication; ADR-0003's spoof-rejection posture). The Twenty
workspace member who dragged the card SHALL travel as evidence provenance on the command — a
system actor carries evidence — and SHALL NOT populate any actor field, whatever the payload
claims.

#### Scenario: The dragging user is provenance, not actor

- **GIVEN** a validly signed drag payload naming the workspace member who moved the card
- **WHEN** the command is produced
- **THEN** its actor is the webhook principal, and the workspace member appears only in the
  command's evidence
