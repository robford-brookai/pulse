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
