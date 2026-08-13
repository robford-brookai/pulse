/**
 * Producer — the single MCP write path. Create-only on DomainEvent and nothing else.
 *
 * `canRead: false` is deliberate: a producer appends events and never queries the log, so the
 * write path holds no read capability over anyone's history.
 */

import { defineRole } from "../define";

export const PRODUCER_ROLE = defineRole({
  name: "producer",
  label: "Event Producer",
  description:
    "The single MCP write path. Creates DomainEvent rows and nothing else.",
  objectPermissions: [
    {
      objectNameSingular: "domainEvent",
      canRead: false,
      canCreate: true,
      canUpdate: false,
      canDelete: false,
    },
  ],
  fieldPermissions: [],
});

export default PRODUCER_ROLE;
