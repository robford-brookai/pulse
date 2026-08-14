/**
 * The checked-in `universalIdentifier` map, read as data (design Decision 2).
 *
 * `uid` is the TypeScript twin of `pulse_core.twenty_model.require_uid`: a key the model needs
 * and the map lacks is an error naming the key, never a mint. Both sides read the same file, so
 * the hand-written object files and the generated artifact carry the same identifiers by
 * construction rather than by review.
 */

import uidMap from "../uid-map.json";

export const UID_MAP: Readonly<Record<string, string>> = uidMap;

/**
 * `<object>` / `<object>.<field>` / `<object>.<field>.<option>`. An option value may itself
 * contain a dot (`domainEvent.eventType.referral.received`) — keys are composed and looked up
 * whole, never split back apart.
 */
export const uid = (key: string): string => {
  const identifier = UID_MAP[key];
  if (identifier === undefined) {
    throw new Error(
      `universalIdentifier missing for '${key}': mint it into uid-map.json (never generated)`,
    );
  }
  return identifier;
};

/** The prefix a `pendingUid` placeholder carries. Never a UUID, so it cannot be mistaken for one. */
export const PENDING_UID_PREFIX = "pending:";

/**
 * A `universalIdentifier` the Twenty type requires and the map does not hold yet.
 *
 * Views are the only such surface today: `ViewManifestType` requires an identifier on the view
 * and on each field, filter, sort, and group, while `pulse_core.twenty_model` does not ask for
 * view keys yet and `check_uid_map` fails on any key the model never asks for. Minting first
 * would fail that check, so the call sites name the keys they will need and this returns a
 * visible placeholder until the model learns them (HANDOFF.md). On that day every one of these
 * becomes `uid` and this function goes away.
 */
export const pendingUid = (key: string): string =>
  UID_MAP[key] ?? `${PENDING_UID_PREFIX}${key}`;
