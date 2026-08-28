/**
 * The Core API boundary the projection handler is written against — the one fake on the
 * TypeScript side (`openspec/changes/pulse-app-scaffold/design.md`, Decision 7).
 *
 * The scaffold doc calls this `CoreApiClient` and notes it is generated from a live schema, so
 * entity lookups come back fully typed. No instance exists yet (DNA-909), so the shape is
 * declared here for the same reason `src/define.ts` declares the `define*` surface: a locally
 * declared boundary makes the handler unit-testable today and makes the swap to the generated
 * client a change of import path rather than a rewrite.
 *
 * Deliberately three methods. The handler reads by filter, creates the pair row on first
 * contact, and updates one record at a time; anything wider would be boundary surface no
 * behavior in `twenty-projection-apply` asks for.
 *
 * Nothing here opens a socket — this file is types plus one documented naming convention.
 */

/**
 * A record as the Core API returns it: the base `id` plus whatever fields were selected. Field
 * values stay `unknown` because the boundary is untyped until the generated client lands, and
 * an `unknown` forces the handler to narrow before it compares an `...AsOf` against an
 * `occurredAt` — which is exactly where a silent LWW bug would otherwise live.
 */
export interface CoreRecord {
  readonly id: string;
  readonly [field: string]: unknown;
}

/**
 * Filter and write shapes are keyed by field name, with one convention: a relation is
 * addressed by its foreign key, `<relationField>Id` (`patientId`, `programId`,
 * `patientProgramId`), never by a nested object. Twenty's REST surface names relation columns
 * that way, and keeping the convention in one place means the generated client swap touches
 * this file rather than the handler.
 */
export type CoreFilter = Readonly<Record<string, string>>;

export type CoreFields = Readonly<Record<string, unknown>>;

/** The foreign-key field name for a relation field: the boundary's one naming rule. */
export const foreignKey = (relationField: string): string =>
  `${relationField}Id`;

export interface CoreApiClient {
  /** The single record matching every filter entry, or `null` — never a throw on no match. */
  findOne(
    objectNameSingular: string,
    filter: CoreFilter,
  ): Promise<CoreRecord | null>;
  create(objectNameSingular: string, fields: CoreFields): Promise<CoreRecord>;
  update(
    objectNameSingular: string,
    recordId: string,
    fields: CoreFields,
  ): Promise<CoreRecord>;
}
