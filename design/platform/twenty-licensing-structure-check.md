# Twenty Licensing Structure Check

| | |
|---|---|
| **Status** | Draft — pending counsel review |
| **Date** | 2026-07-28 |
| **Context** | PULSE (Patient Unified Ledger of State & Events) MVP on self-hosted Twenty CRM |
| **Decision owner** | Rob Ford |
| **Related** | Event-state platform MVP design; Twenty fit assessment |

> Not legal advice. Verify conclusions with counsel before committing.

## Deployment under evaluation

Self-hosted Twenty (unmodified core) as entity registry + declarative state store for Brook business objects (Patient, Provider, Clinic). Events ingested as an Event custom object via Twenty's REST API by external actors. Postgres backend replicated to Snowflake via CDC. No Twenty-based product offered to third parties.

## License structure

Twenty is dual-licensed in one monorepo:

- **Core**: AGPL-3.0. Free, no user caps, no feature gates when self-hosted.
- **`twenty-ee` package**: proprietary commercial license. Gates SSO (SAML/OIDC), advanced RBAC, lifecycle permissions — paid even when self-hosted.
- **Twenty Cloud**: $9/user/month hosted offering. Out of scope here (see HIPAA below).

## Findings by scenario

### 1. Self-hosted internal use, unmodified core — clean

AGPL §13 (network clause) obligates offering corresponding source to users who interact with the software over a network. With unmodified core, the obligation is satisfied by the publicly available upstream source. No cost, no action required.

### 2. External actors calling the API — clean

Clinics/services POSTing events are network users under §13, but the obligation remains "provide corresponding source of what is running." Unmodified core = already public. API consumption of a stock instance does not constitute building a derivative product on top of Twenty.

### 3. Custom objects, workflows, webhook configs — no copyleft exposure

Configuration and data, not code. Likewise event producers, projection workflows, and the Snowflake CDC pipeline are separate programs communicating across API boundaries — not derivative works.

### 4. Modifying core — the trap

Patching Twenty source triggers real AGPL obligations: modified source must be offered to every network user, including external API callers.

**Team rule: never patch core.** Extend only via API, workflows, and the v2.0 app platform. This also matches the maintenance budget of a three-person data team.

### 5. SSO — resolved, $0

Requirement: Microsoft SSO. Twenty **core** (AGPL, free) includes Microsoft OAuth login, configured via `AUTH_MICROSOFT_ENABLED`, `AUTH_MICROSOFT_CLIENT_ID`, `AUTH_MICROSOFT_CLIENT_SECRET`, and callback URL variables (env or admin panel). Entra ID enforces MFA and conditional access at the identity layer.

Caveats:

1. This is OAuth sign-in, not SAML — `twenty-ee` is required only if compliance specifically mandates SAML/generic OIDC.
2. No SCIM. Disabling an Entra account blocks login, but active sessions and API keys must be revoked manually — add to the offboarding runbook.
3. Callback URLs must match exactly between Entra app registration and Twenty config (common misconfiguration).

### 6. HIPAA posture

- Self-hosted: no vendor touches PHI → no BAA needed from Twenty. Deploy inside existing HIPAA-compliant infra.
- Twenty Cloud: would require a BAA that is almost certainly unavailable. Treat cloud as off the table.
- AGPL software carries no warranty. All compliance controls (encryption at rest/in transit, access logging, backups, audit) are Brook's responsibility.

## Net assessment

Zero license cost and zero copyleft exposure provided:

1. Core stays unmodified.
2. All extensions stay API-side (custom objects, workflows, apps platform).
3. Microsoft SSO uses core OAuth login; `twenty-ee` deferred unless SAML becomes a mandate.

## Decisions resolved (2026-07-28)

1. SSO: Microsoft — satisfied by core Microsoft OAuth login at $0. Re-open only if SAML is mandated.
2. Event volume: low thousands/day — well within Twenty REST API ingest capacity; no architectural impact.

## Sources

- [Twenty CRM pricing teardown (DEV, 2026)](https://dev.to/beton/twenty-crm-pricing-teardown-2026-c32)
- [Twenty CRM review (Toolworthy, 2026)](https://www.toolworthy.ai/tool/twenty)
- [OpenTechHub — Twenty strategic assessment](https://www.opentechhub.io/twenty/)
- [Twenty pricing, reviews, pros & cons (Prospeo)](https://prospeo.io/s/twenty-pricing-reviews-pros-and-cons)
- [Twenty webhooks documentation](https://docs.twenty.com/developers/api-and-webhooks/webhooks)
- [twentyhq/twenty discussion #8948 — custom timeline events gap](https://github.com/twentyhq/twenty/discussions/8948)
- [Twenty self-host setup docs](https://docs.twenty.com/developers/self-host/capabilities/setup)
