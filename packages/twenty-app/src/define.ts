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

export type ViewFilterOperand = "is" | "isNot" | "isEmpty" | "isNotEmpty";

export interface ViewFilter {
  readonly field: string;
  readonly operand: ViewFilterOperand;
  readonly value?: string;
}

export interface ViewSort {
  readonly field: string;
  readonly direction: "ASC" | "DESC";
}

export interface ViewDefinition {
  readonly name: string;
  readonly label: string;
  readonly icon: string;
  readonly objectNameSingular: string;
  readonly type: "TABLE" | "KANBAN";
  readonly visibleFields: readonly string[];
  readonly filters: readonly ViewFilter[];
  readonly sorts: readonly ViewSort[];
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
 * key the model never asks for) and the operation set has no logic-function operation to key —
 * the same reason the views carry none. Adding the field is a mint plus an artifact change,
 * proposed in HANDOFF.md rather than drifted into.
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
