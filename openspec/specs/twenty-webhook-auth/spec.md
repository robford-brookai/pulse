# twenty-webhook-auth Specification

## Purpose
Defines the authenticated door of the Twenty kanban ingress: HMAC signature verification with a
freshness window, dual-secret rotation per D15's quarterly cadence, and attribution — the event's
actor is the webhook credential's principal, never anything the payload claims.
## Requirements
### Requirement: Webhook requests are signature-verified before any processing

Every request to the Twenty webhook route SHALL be verified — HMAC over the versioned
timestamp-and-body message, timestamp inside the freshness window, checked before the signature —
before the payload is parsed or any command is attempted. A request that fails verification SHALL
be rejected as unauthenticated with no ledger write, no comment, and no payload content in the
rejection or its log line (S1.1's shipped middleware behavior, consumed unchanged; the requirement
here is that the enabled route puts nothing in front of it).

#### Scenario: A validly signed request is processed

- **GIVEN** the webhook route is enabled with a configured secret
- **WHEN** a request arrives signed with that secret and a timestamp inside the freshness window
- **THEN** the payload proceeds to drag mapping

#### Scenario: A tampered body is rejected without processing

- **WHEN** a request's body does not match its signature
- **THEN** the request is rejected as unauthenticated, no command is attempted, and neither the
  body nor the signature appears in the rejection or its log line

#### Scenario: A stale timestamp is rejected

- **WHEN** a correctly signed request arrives with a timestamp outside the freshness window
- **THEN** the request is rejected as unauthenticated and no command is attempted

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
