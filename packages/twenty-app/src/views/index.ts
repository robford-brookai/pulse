/**
 * Ops-facing saved views.
 *
 * Views carry a `universalIdentifier`, and so does every field, filter, sort, and group inside
 * one — `ViewManifestType` requires it, and objects and fields are addressed by identifier
 * rather than by name. The earlier claim that views carry none was never true of Twenty; it was
 * true only of this repo's artifact, whose operation set carries objects, fields, relations, and
 * roles and has no view operation to key.
 *
 * The identifiers are now minted. `pulse_core.twenty_model` declares the view keys (`ViewSpec`),
 * so `check_uid_map` accepts them, and every one resolves through `uid` — which throws naming the
 * key rather than minting. That pair is what holds the Python and TypeScript sides on the same
 * surface: a key one declares and the other never asks for fails on one side or the other.
 */

import type { ViewDefinition } from "../define";
import { DOMAIN_EVENT_LOG_VIEW } from "./domain-event-log.view";
import { DOMAIN_EVENT_ORPHANS_VIEW } from "./domain-event-orphans.view";
import { PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW } from "./patient-program-lifecycle-board.view";
import { PATIENT_PROGRAM_STATUS_BOARD_VIEW } from "./patient-program-status-board.view";

export {
  DOMAIN_EVENT_LOG_VIEW,
  DOMAIN_EVENT_ORPHANS_VIEW,
  PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW,
  PATIENT_PROGRAM_STATUS_BOARD_VIEW,
};

// Annotated rather than `as const` (unlike `ALL_OBJECTS`): most of `ViewDefinition` is optional,
// so the literal type of a TABLE view would not carry `mainGroupByFieldMetadata...` at all and a
// consumer walking the collection could not ask about it. The annotation is what makes this a
// list of views rather than a list of four particular shapes.
export const ALL_VIEWS: readonly ViewDefinition[] = [
  PATIENT_PROGRAM_STATUS_BOARD_VIEW,
  PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW,
  DOMAIN_EVENT_LOG_VIEW,
  DOMAIN_EVENT_ORPHANS_VIEW,
];
