/**
 * The live `CoreApiClient` — the projection handler's boundary, spoken over Twenty's core REST
 * API (pulse-app-scaffold 4.2).
 *
 * `core-api.ts` declared the boundary and promised that swapping the fake for a real client
 * would be a change of import path rather than a rewrite. This is the real client, and it holds
 * that promise: it implements the same three methods against `/rest`, so wave 3's live cases run
 * the *same handler* the unit suite runs, with nothing about the projection logic reimplemented
 * for the live path. A live run that re-stated the semantics would verify a copy.
 *
 * Three things are this file's own, and each one is a live-contact finding rather than a design
 * choice:
 *
 * 1. **The SELECT transport encoding.** v2.30 stores option values UPPER_SNAKE
 *    (`referral.received` → `REFERRAL_RECEIVED`, 4.1 first contact). The catalog stays the only
 *    vocabulary: values encode on the way out and decode on the way in, here at the boundary, so
 *    the handler compares and writes catalog values and never learns the wire spelling. Decoding
 *    is table-driven from `generated/options.ts` because the encoding is not injective in
 *    reverse (`A_B` could be `a.b` or `a_b`) — a token no option encodes to is left raw.
 * 2. **Plurals come from the model.** The REST collection for `patientProgram` is
 *    `patientPrograms` because `PATIENT_PROGRAM.namePlural` says so, not because of a string
 *    rule. An object the model does not declare is an error, not a guessed URL.
 * 3. **Failures carry a status, never a body.** Same containment as `twenty_deploy`: a rejected
 *    write's response body can quote the record value that was rejected, and this client is used
 *    where receipts get attached to tickets.
 *
 * `fetch` is injected so the adapter is unit-testable with no socket; the live runner passes the
 * global one. Nothing here reads a credential from the environment — the caller resolves it, the
 * same posture `twenty_deploy.resolve_target` sets on the Python side.
 */

import { OPTIONS_BY_FIELD } from "../../generated/options";
import type {
  CoreApiClient,
  CoreFields,
  CoreFilter,
  CoreRecord,
} from "../logic-functions/core-api";
import CLINIC from "../objects/clinic.object";
import DOMAIN_EVENT from "../objects/domain-event.object";
import PATIENT_PROGRAM from "../objects/patient-program.object";
import PATIENT from "../objects/patient.object";
import PROGRAM from "../objects/program.object";
import PROVIDER from "../objects/provider.object";

const REST_ROOT = "rest";

/** Object name → REST collection, read off the model rather than pluralized by rule. */
const PLURALS: ReadonlyMap<string, string> = new Map(
  [PATIENT, PROGRAM, PATIENT_PROGRAM, PROVIDER, CLINIC, DOMAIN_EVENT].map(
    ({ config }) => [config.nameSingular, config.namePlural],
  ),
);

/** The REST collection one modeled object lives in. An unmodeled name is an error. */
export const restPlural = (objectNameSingular: string): string => {
  const plural = PLURALS.get(objectNameSingular);
  if (plural === undefined) {
    throw new CoreApiError(
      `object ${objectNameSingular} is not in the model — no REST collection to address`,
    );
  }
  return plural;
};

/** A catalog option value as the live server stores it (`twenty_validate.encode_option_value`). */
export const encodeOptionValue = (value: string): string =>
  value.toUpperCase().replaceAll(".", "_");

/** `<object>.<field>` → stored token → catalog value, built once from the generated options. */
const DECODERS: ReadonlyMap<string, ReadonlyMap<string, string>> = new Map(
  Object.entries(OPTIONS_BY_FIELD).map(([key, options]) => [
    key,
    new Map(
      options.map((option) => [encodeOptionValue(option.value), option.value]),
    ),
  ]),
);

/** True when `<object>.<field>` is a SELECT the catalog owns the vocabulary of. */
const isOptionField = (objectNameSingular: string, field: string): boolean =>
  DECODERS.has(`${objectNameSingular}.${field}`);

/**
 * A stored token back to its catalog value, or the token unchanged when no option encodes to it.
 *
 * Leaving it raw is deliberate: the encoding collapses `.` and `_`, so reversing it by rule would
 * invent a value. A raw token reaching an assertion fails visibly; a guessed one passes wrongly.
 */
export const decodeOptionValue = (fieldKey: string, stored: string): string =>
  DECODERS.get(fieldKey)?.get(stored) ?? stored;

/** A transport or protocol failure. Carries what to fix, never what the server echoed back. */
export class CoreApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CoreApiError";
  }
}

const encodeFields = (
  objectNameSingular: string,
  fields: CoreFields,
): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(fields).map(([name, value]) => [
      name,
      isOptionField(objectNameSingular, name) && typeof value === "string"
        ? encodeOptionValue(value)
        : value,
    ]),
  );

const decodeRecord = (
  objectNameSingular: string,
  record: Record<string, unknown>,
): CoreRecord => {
  const decoded = Object.fromEntries(
    Object.entries(record).map(([name, value]) => [
      name,
      isOptionField(objectNameSingular, name) && typeof value === "string"
        ? decodeOptionValue(`${objectNameSingular}.${name}`, value)
        : value,
    ]),
  );
  const id = decoded["id"];
  if (typeof id !== "string") {
    throw new CoreApiError(
      `a ${objectNameSingular} record came back without an id`,
    );
  }
  return { ...decoded, id };
};

/**
 * The filter query one lookup sends: `field[eq]:value`, comma-joined (AND), sorted by field so
 * the same lookup produces the same URL twice.
 *
 * A value containing the syntax's own separators is refused rather than escaped: Twenty's filter
 * grammar has no quoting, so a comma in a value silently becomes a second predicate.
 */
const filterQuery = (filter: CoreFilter): string => {
  const predicates = Object.entries(filter)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([field, value]) => {
      if (/[,:[\]()]/.test(value)) {
        throw new CoreApiError(
          `filter value for ${field} contains a character the filter grammar reserves`,
        );
      }
      return `${field}[eq]:${value}`;
    });
  return predicates.join(",");
};

/** The mutation key Twenty wraps a single-record response in: `create` + `PatientProgram`. */
const mutationKey = (verb: string, objectNameSingular: string): string =>
  `${verb}${objectNameSingular.charAt(0).toUpperCase()}${objectNameSingular.slice(1)}`;

export interface LiveCoreApiClient extends CoreApiClient {
  /**
   * Delete one record by id — the verb the fixtures a live run creates need to clean up after
   * themselves. Deliberately not on `CoreApiClient`: the projection never deletes anything, and
   * widening the handler's boundary to give a test harness a verb would be the wrong trade.
   */
  deleteRecord(objectNameSingular: string, recordId: string): Promise<void>;
}

export interface RestCoreApiOptions {
  readonly baseUrl: string;
  readonly token: string;
  readonly fetchImpl?: typeof fetch;
}

export const createRestCoreApiClient = ({
  baseUrl,
  token,
  fetchImpl = fetch,
}: RestCoreApiOptions): LiveCoreApiClient => {
  const root = baseUrl.replace(/\/+$/, "");

  const request = async (
    method: string,
    path: string,
    body?: unknown,
  ): Promise<Record<string, unknown>> => {
    const response = await fetchImpl(`${root}/${path}`, {
      method,
      headers: {
        authorization: `Bearer ${token}`,
        "content-type": "application/json",
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) {
      // The body is never read. A rejected write quotes the value it rejected, and a receipt
      // built from this error is attached to tickets (`twenty_deploy`'s `TransportError`).
      throw new CoreApiError(
        `${method} ${path} failed with status ${response.status}`,
      );
    }
    const payload = (await response.json()) as {
      data?: Record<string, unknown>;
    };
    return payload.data ?? {};
  };

  const findOne = async (
    objectNameSingular: string,
    filter: CoreFilter,
  ): Promise<CoreRecord | null> => {
    const plural = restPlural(objectNameSingular);
    // limit=2 rather than 1: one extra row is what proves the match unambiguous.
    const query = `filter=${encodeURIComponent(filterQuery(filter))}&limit=2`;
    const data = await request("GET", `${REST_ROOT}/${plural}?${query}`);
    const records = data[plural];
    if (!Array.isArray(records)) {
      throw new CoreApiError(
        `the ${plural} listing came back without a ${plural} collection`,
      );
    }
    if (records.length > 1) {
      throw new CoreApiError(
        `${records.length} ${plural} records match one lookup — the filter names a key that is not unique`,
      );
    }
    const [record] = records as Record<string, unknown>[];
    return record === undefined
      ? null
      : decodeRecord(objectNameSingular, record);
  };

  const single = (
    verb: string,
    objectNameSingular: string,
    data: Record<string, unknown>,
  ): CoreRecord => {
    const record = data[mutationKey(verb, objectNameSingular)];
    if (record === null || typeof record !== "object") {
      throw new CoreApiError(
        `the ${verb} of a ${objectNameSingular} returned no record`,
      );
    }
    return decodeRecord(objectNameSingular, record as Record<string, unknown>);
  };

  return {
    findOne,

    async create(
      objectNameSingular: string,
      fields: CoreFields,
    ): Promise<CoreRecord> {
      const data = await request(
        "POST",
        `${REST_ROOT}/${restPlural(objectNameSingular)}`,
        encodeFields(objectNameSingular, fields),
      );
      return single("create", objectNameSingular, data);
    },

    async update(
      objectNameSingular: string,
      recordId: string,
      fields: CoreFields,
    ): Promise<CoreRecord> {
      const data = await request(
        "PATCH",
        `${REST_ROOT}/${restPlural(objectNameSingular)}/${recordId}`,
        encodeFields(objectNameSingular, fields),
      );
      return single("update", objectNameSingular, data);
    },

    async deleteRecord(
      objectNameSingular: string,
      recordId: string,
    ): Promise<void> {
      await request(
        "DELETE",
        `${REST_ROOT}/${restPlural(objectNameSingular)}/${recordId}`,
      );
    },
  };
};
