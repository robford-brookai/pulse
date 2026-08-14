/**
 * The `define*` surface the app source is written against.
 *
 * `design/platform/pulse-app-scaffold.md` writes these imports as `twenty-sdk/define`. We
 * declare them here instead, for the same reason the artifact emitter is ours (design
 * Decision 1): no dev instance exists yet (DNA-909), and the SDK's shape is only provable
 * against a running server. Declaring the types locally keeps `tsc --noEmit` an honest check
 * of the model today — a field with options on a non-SELECT type, or a relation naming a
 * field that is not one, fails to compile — and keeps the swap to the real SDK a change of
 * import path rather than a rewrite. The names, keys, and value shapes mirror the documented
 * SDK so that swap stays mechanical.
 *
 * The functions are identity: they exist to name the entity kind for AST detection and to
 * apply the type. Nothing here reads a file, mints an identifier, or opens a socket.
 */

import type { GeneratedOption } from "../generated/options";

export const FieldType = {
  TEXT: "TEXT",
  FULL_NAME: "FULL_NAME",
  NUMBER: "NUMBER",
  DATE_TIME: "DATE_TIME",
  RAW_JSON: "RAW_JSON",
  SELECT: "SELECT",
  RELATION: "RELATION",
} as const;
export type FieldType = (typeof FieldType)[keyof typeof FieldType];

export const RelationType = {
  MANY_TO_ONE: "MANY_TO_ONE",
  ONE_TO_MANY: "ONE_TO_MANY",
} as const;
export type RelationType = (typeof RelationType)[keyof typeof RelationType];

/** A scalar field type: everything a SELECT's options and a RELATION's target do not apply to. */
export type ScalarFieldType = Exclude<FieldType, "SELECT" | "RELATION">;

export interface RelationDefinition {
  readonly type: RelationType;
  readonly targetObject: string;
  /** The field on `targetObject` facing back. Relations are declared from both sides. */
  readonly inverseField: string;
}

interface FieldCommon {
  readonly universalIdentifier: string;
  readonly name: string;
  readonly label: string;
  readonly description?: string;
  readonly isNullable?: boolean;
  readonly isUnique?: boolean;
  /**
   * A Twenty default is a literal expression inside a string, so a string default is doubly
   * quoted: `"'pending_start'"`. Same convention as `pulse_core.twenty_model`.
   */
  readonly defaultValue?: string;
}

export interface ScalarFieldDefinition extends FieldCommon {
  readonly type: ScalarFieldType;
}

export interface SelectFieldDefinition extends FieldCommon {
  readonly type: "SELECT";
  /**
   * Always an array imported from `generated/options.ts` (design Decision 3). The type says
   * `GeneratedOption` rather than a locally-shaped option so a hand-written literal has to
   * carry a `universalIdentifier` and a `position` it has no business minting.
   */
  readonly options: readonly GeneratedOption[];
}

export interface RelationFieldDefinition extends FieldCommon {
  readonly type: "RELATION";
  readonly relation: RelationDefinition;
}

export type FieldDefinition =
  | ScalarFieldDefinition
  | SelectFieldDefinition
  | RelationFieldDefinition;

export interface ObjectDefinition {
  readonly universalIdentifier: string;
  readonly nameSingular: string;
  readonly namePlural: string;
  readonly labelSingular: string;
  readonly labelPlural: string;
  readonly icon: string;
  readonly description?: string;
  readonly fields: readonly FieldDefinition[];
}

export interface ObjectPermission {
  readonly objectNameSingular: string;
  readonly canRead: boolean;
  readonly canCreate: boolean;
  readonly canUpdate: boolean;
  readonly canDelete: boolean;
}

export interface FieldPermission {
  readonly objectNameSingular: string;
  readonly fieldName: string;
  readonly canRead: boolean;
  readonly canUpdate: boolean;
}

export interface RoleDefinition {
  readonly name: string;
  readonly label: string;
  readonly description: string;
  readonly objectPermissions: readonly ObjectPermission[];
  readonly fieldPermissions: readonly FieldPermission[];
}

/**
 * Views, mirroring `twenty-shared/src/application/viewManifestType.ts` field for field.
 *
 * Two things about the real shape are worth stating, because the earlier local stand-in got
 * both wrong. A view carries a `universalIdentifier`, and so does every one of its fields,
 * filters, filter groups, sorts, groups, and field groups — each is a syncable entity in its
 * own right. And objects and fields are addressed by identifier, never by name:
 * `objectUniversalIdentifier` and `fieldMetadataUniversalIdentifier`. Name-based ergonomics
 * would have to be unwound on the day `twenty-sdk/define` replaces this file, which is exactly
 * what declaring the real shape here avoids.
 *
 * The deprecated `key` field (`ViewKey.INDEX`) is left out: the server reserves it for the
 * default views it provisions itself and ignores it on a manifest view.
 */

export const ViewType = {
  TABLE: "TABLE",
  LIST: "LIST",
  KANBAN: "KANBAN",
  CALENDAR: "CALENDAR",
} as const;
export type ViewType = (typeof ViewType)[keyof typeof ViewType];

export const ViewFilterOperand = {
  IS: "IS",
  IS_NOT: "IS_NOT",
  IS_NOT_NULL: "IS_NOT_NULL",
  LESS_THAN_OR_EQUAL: "LESS_THAN_OR_EQUAL",
  GREATER_THAN_OR_EQUAL: "GREATER_THAN_OR_EQUAL",
  IS_BEFORE: "IS_BEFORE",
  IS_AFTER: "IS_AFTER",
  CONTAINS: "CONTAINS",
  DOES_NOT_CONTAIN: "DOES_NOT_CONTAIN",
  IS_EMPTY: "IS_EMPTY",
  IS_NOT_EMPTY: "IS_NOT_EMPTY",
  IS_RELATIVE: "IS_RELATIVE",
  IS_IN_PAST: "IS_IN_PAST",
  IS_IN_FUTURE: "IS_IN_FUTURE",
  IS_TODAY: "IS_TODAY",
  VECTOR_SEARCH: "VECTOR_SEARCH",
} as const;
export type ViewFilterOperand =
  (typeof ViewFilterOperand)[keyof typeof ViewFilterOperand];

export const ViewFilterGroupLogicalOperator = {
  AND: "AND",
  OR: "OR",
  NOT: "NOT",
} as const;
export type ViewFilterGroupLogicalOperator =
  (typeof ViewFilterGroupLogicalOperator)[keyof typeof ViewFilterGroupLogicalOperator];

export const ViewSortDirection = {
  ASC: "ASC",
  DESC: "DESC",
} as const;
export type ViewSortDirection =
  (typeof ViewSortDirection)[keyof typeof ViewSortDirection];

export const ViewVisibility = {
  WORKSPACE: "WORKSPACE",
  UNLISTED: "UNLISTED",
} as const;
export type ViewVisibility =
  (typeof ViewVisibility)[keyof typeof ViewVisibility];

export const ViewOpenRecordIn = {
  SIDE_PANEL: "SIDE_PANEL",
  RECORD_PAGE: "RECORD_PAGE",
} as const;
export type ViewOpenRecordIn =
  (typeof ViewOpenRecordIn)[keyof typeof ViewOpenRecordIn];

export const ViewCalendarLayout = {
  DAY: "DAY",
  WEEK: "WEEK",
  MONTH: "MONTH",
} as const;
export type ViewCalendarLayout =
  (typeof ViewCalendarLayout)[keyof typeof ViewCalendarLayout];

export const AggregateOperations = {
  MIN: "MIN",
  MAX: "MAX",
  AVG: "AVG",
  SUM: "SUM",
  COUNT: "COUNT",
  COUNT_UNIQUE_VALUES: "COUNT_UNIQUE_VALUES",
  COUNT_EMPTY: "COUNT_EMPTY",
  COUNT_NOT_EMPTY: "COUNT_NOT_EMPTY",
  COUNT_TRUE: "COUNT_TRUE",
  COUNT_FALSE: "COUNT_FALSE",
  PERCENTAGE_EMPTY: "PERCENTAGE_EMPTY",
  PERCENTAGE_NOT_EMPTY: "PERCENTAGE_NOT_EMPTY",
} as const;
export type AggregateOperations =
  (typeof AggregateOperations)[keyof typeof AggregateOperations];

/** Every entity the manifest can sync carries its own identifier. */
export interface SyncableEntityOptions {
  readonly universalIdentifier: string;
}

export type ViewFilterValue =
  | string
  | readonly string[]
  | boolean
  | number
  | Record<string, unknown>;

export interface ViewFieldDefinition extends SyncableEntityOptions {
  readonly fieldMetadataUniversalIdentifier: string;
  readonly isVisible?: boolean;
  readonly size?: number;
  readonly position: number;
  readonly aggregateOperation?: AggregateOperations;
  readonly viewFieldGroupUniversalIdentifier?: string;
}

export interface ViewFilterDefinition extends SyncableEntityOptions {
  readonly fieldMetadataUniversalIdentifier: string;
  readonly operand: ViewFilterOperand;
  readonly value: ViewFilterValue;
  readonly subFieldName?: string;
  readonly viewFilterGroupUniversalIdentifier?: string;
  readonly positionInViewFilterGroup?: number;
}

export interface ViewFilterGroupDefinition extends SyncableEntityOptions {
  readonly logicalOperator: ViewFilterGroupLogicalOperator;
  readonly parentViewFilterGroupUniversalIdentifier?: string;
  readonly positionInViewFilterGroup?: number;
}

export interface ViewGroupDefinition extends SyncableEntityOptions {
  readonly fieldValue: string;
  readonly isVisible?: boolean;
  readonly position: number;
}

export interface ViewFieldGroupDefinition extends SyncableEntityOptions {
  readonly name?: string;
  readonly position: number;
  readonly isVisible?: boolean;
}

export interface ViewSortDefinition extends SyncableEntityOptions {
  readonly fieldMetadataUniversalIdentifier: string;
  readonly direction: ViewSortDirection;
  readonly subFieldName?: string;
}

export interface ViewDefinition extends SyncableEntityOptions {
  readonly name: string;
  readonly objectUniversalIdentifier: string;
  readonly type?: ViewType;
  readonly icon?: string;
  /**
   * Optional upstream, required here. A view without a position is ordered by whatever the
   * server picks, which makes the ops sidebar's order a deploy-time accident. Requiring it is
   * strictly narrower than the SDK type, so the literals stay assignable on the swap.
   */
  readonly position: number;
  readonly isCompact?: boolean;
  readonly visibility?: ViewVisibility;
  readonly openRecordIn?: ViewOpenRecordIn;
  readonly mainGroupByFieldMetadataUniversalIdentifier?: string;
  readonly shouldHideEmptyGroups?: boolean;
  readonly anyFieldFilterValue?: string | null;
  readonly kanbanColumnWidth?: number | null;
  readonly kanbanAggregateOperation?: AggregateOperations;
  readonly kanbanAggregateOperationFieldMetadataUniversalIdentifier?: string;
  readonly calendarLayout?: ViewCalendarLayout;
  readonly calendarFieldMetadataUniversalIdentifier?: string;
  readonly calendarEndFieldMetadataUniversalIdentifier?: string;
  readonly fields?: readonly ViewFieldDefinition[];
  readonly filters?: readonly ViewFilterDefinition[];
  readonly filterGroups?: readonly ViewFilterGroupDefinition[];
  readonly groups?: readonly ViewGroupDefinition[];
  readonly fieldGroups?: readonly ViewFieldGroupDefinition[];
  readonly sorts?: readonly ViewSortDefinition[];
}

/**
 * What fires a logic function. Only the database-event trigger is declared, because it is the
 * only one the projection uses: `domainEvent.created` (`design/platform/pulse-app-scaffold.md`).
 */
export interface DatabaseEventTriggerSettings {
  readonly eventName: string;
}

/**
 * A logic function carries no `universalIdentifier` here. The scaffold doc's sketch shows one,
 * but the UID map is exactly the surface the artifact serializes (`uid_map_diff` fails on any
 * key the model never asks for) and the operation set has no logic-function operation to key.
 * Adding the field is a mint plus an artifact change, proposed in HANDOFF.md rather than
 * drifted into. Views are the opposite case and were wrong here before: Twenty genuinely
 * requires an identifier on a view and on each of its parts, so the type declares one and the
 * map has to learn the keys (HANDOFF.md).
 */
export interface LogicFunctionDefinition<TInput, TOutput> {
  readonly name: string;
  readonly timeoutSeconds: number;
  readonly handler: (input: TInput) => Promise<TOutput>;
  readonly databaseEventTriggerSettings: DatabaseEventTriggerSettings;
}

/** Any logic function, seen from the application config, which never calls one. */
export type AnyLogicFunctionDefinition = LogicFunctionDefinition<
  never,
  unknown
>;

export interface ApplicationDefinition {
  readonly name: string;
  readonly label: string;
  readonly description: string;
  /** The role a newly-provisioned member gets. Names a role in `roles`. */
  readonly defaultRole: string;
  readonly objects: readonly ObjectDefinition[];
  readonly roles: readonly RoleDefinition[];
  readonly views: readonly ViewDefinition[];
  readonly logicFunctions: readonly AnyLogicFunctionDefinition[];
}

export const defineObject = <T extends ObjectDefinition>(definition: T): T =>
  definition;
export const defineRole = <T extends RoleDefinition>(definition: T): T =>
  definition;
export const defineView = <T extends ViewDefinition>(definition: T): T =>
  definition;
export const defineApplication = <T extends ApplicationDefinition>(
  definition: T,
): T => definition;
export const defineLogicFunction = <TInput, TOutput>(
  definition: LogicFunctionDefinition<TInput, TOutput>,
): LogicFunctionDefinition<TInput, TOutput> => definition;
