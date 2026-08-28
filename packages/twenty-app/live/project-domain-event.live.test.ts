/**
 * The five projection cases, run against a live Twenty server (pulse-app-scaffold 4.2).
 *
 * This is the wave-3 half of `tests/project-domain-event.test.ts`. The unit suite runs the five
 * cases with a faked `CoreApiClient` and proves the *logic*; this file runs the same five cases
 * with the real one (`src/live/rest-core-api.ts`) and proves the logic still holds when the
 * client is a real server: real SELECT storage, real relation columns, real defaults, real
 * date-time round-tripping. The handler is imported, never restated — a live run that
 * reimplemented the semantics would verify a copy of them.
 *
 * **Not a server-side install.** The scaffold doc's dev loop installs the app and fires the
 * function from `domainEvent.created`; that path needs `twenty-sdk`, which this repo has not
 * adopted (evaluation and its cost are in HANDOFF.md, and adoption is twenty-dev-instance 6.3).
 * The task's own second option is what runs here: synthetic DomainEvent creates against the live
 * server, with the handler invoked in-process over the same records. Everything downstream of
 * "the trigger fired" is therefore live; the trigger itself is not, and that gap is the one thing
 * this file cannot close.
 *
 * **Cases build on one another** — the late-event case needs the state the first-event case set,
 * and the dimension-isolation case needs both. They run in declaration order in one file, and
 * `afterAll` removes every record the run created whether it passed or failed.
 *
 * Synthetic data only. The fixtures are a program code, a minted canonical identifier, and
 * catalog vocabulary — there is no patient-shaped value anywhere in this file, and the receipt it
 * prints carries case names, outcome statuses, and catalog values only: no record ids, no
 * response bodies, no credential.
 *
 * Run: task twenty:verify:live TARGET=dev   (needs PULSE_TWENTY_DEV_URL / _TOKEN)
 */

import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { PROJECTION_LOOKUP } from "../generated/projection-lookup";
import { foreignKey } from "../src/logic-functions/core-api";
import {
  handler,
  type DomainEventRecord,
  type ProjectionOutcome,
} from "../src/logic-functions/project-domain-event";
import {
  createRestCoreApiClient,
  type LiveCoreApiClient,
} from "../src/live/rest-core-api";

/** Target resolution mirrors `twenty_deploy.resolve_target`: environment, never code. */
const target = (process.env["PULSE_LIVE_TARGET"] ?? "dev").toUpperCase();
const baseUrl = process.env[`PULSE_TWENTY_${target}_URL`];
const token = process.env[`PULSE_TWENTY_${target}_TOKEN`];

if (
  baseUrl === undefined ||
  baseUrl === "" ||
  token === undefined ||
  token === ""
) {
  // An empty secret reaches a job as an empty string; treating that as configured would run the
  // suite against nothing and pass. Same refusal as `twenty_verify`: live-only, never an
  // empty-state pass.
  throw new Error(
    `target ${target.toLowerCase()} is not configured — set PULSE_TWENTY_${target}_URL and PULSE_TWENTY_${target}_TOKEN`,
  );
}

/** One run's fixture namespace. Every record this file creates carries it, and only those go. */
const RUN = randomUUID();
const PROGRAM_CODE = `PULSE-LIVE-${RUN.slice(0, 8)}`;
const CANONICAL_PATIENT_ID = randomUUID();
const UNRESOLVABLE_PATIENT_ID = randomUUID();

/** The three instants the guard cases turn on: T0 before T1, T2 after both. */
const T0 = "2026-01-10T00:00:00.000Z";
const T1 = "2026-02-20T00:00:00.000Z";
const T2 = "2026-03-30T00:00:00.000Z";

const client: LiveCoreApiClient = createRestCoreApiClient({ baseUrl, token });

/** Ids to remove in `afterAll`, newest first so a child never outlives its parent. */
const created: { object: string; id: string }[] = [];

const track = <T extends { id: string }>(object: string, record: T): T => {
  created.unshift({ object, id: record.id });
  return record;
};

/** The receipt this run prints: what was exercised and how it came out. No workspace content. */
const receipt: {
  case: string;
  spec: string;
  outcome: string;
  liveState: Record<string, string | null>;
}[] = [];

const record = (
  caseName: string,
  spec: string,
  outcome: ProjectionOutcome,
  liveState: Record<string, string | null>,
): void => {
  receipt.push({ case: caseName, spec, outcome: outcome.status, liveState });
};

/**
 * One synthetic DomainEvent, created live. `eventId` and `eventType` are the envelope's
 * NOT NULL pair; the rest is what the handler reads. `payload` and `evidence` stay unset —
 * the handler never reads them, so no producer-shaped blob is invented here either.
 */
const createEvent = async (
  fields: Partial<DomainEventRecord> & { eventType: string },
): Promise<DomainEventRecord> => {
  const remote = track(
    "domainEvent",
    await client.create("domainEvent", {
      eventId: randomUUID(),
      entityType: "patient",
      entityRefSystem: "brook",
      entityRefId: CANONICAL_PATIENT_ID,
      programCode: PROGRAM_CODE,
      producer: "pulse-app-scaffold-4.2",
      ...fields,
    }),
  );
  return {
    id: remote.id,
    eventType: fields.eventType,
    entityType: fields.entityType ?? "patient",
    entityRefSystem: fields.entityRefSystem ?? "brook",
    entityRefId: fields.entityRefId ?? CANONICAL_PATIENT_ID,
    programCode: fields.programCode ?? PROGRAM_CODE,
    occurredAt: fields.occurredAt ?? null,
  };
};

let patientId = "";
let programId = "";

/** The pair row as the server currently holds it, or null when it does not exist. */
const readPair = async () =>
  client.findOne("patientProgram", {
    [foreignKey("patient")]: patientId,
    [foreignKey("program")]: programId,
  });

/**
 * The event as the server currently holds it — the relation binding is the assertion.
 *
 * By record id, not by the envelope's `eventId`: the handler binds the relation onto the record
 * it was handed, and reading back by the same identity is what makes "it bound *this* event" the
 * thing being asserted.
 */
const readEvent = async (recordId: string) =>
  client.findOne("domainEvent", { id: recordId });

beforeAll(async () => {
  const program = track(
    "program",
    await client.create("program", {
      code: PROGRAM_CODE,
      name: `Live verification ${RUN.slice(0, 8)}`,
    }),
  );
  programId = program.id;

  const patient = track(
    "patient",
    await client.create("patient", {
      canonicalPatientId: CANONICAL_PATIENT_ID,
    }),
  );
  patientId = patient.id;
}, 60_000);

afterAll(async () => {
  // The pair row is the handler's creation, not a tracked fixture, and it has to go first:
  // deleting a Patient or Program while a PatientProgram still points at it leaves an orphan row
  // with null relations behind in the workspace.
  const pair = programId === "" ? null : await readPair().catch(() => null);
  if (pair !== null) created.unshift({ object: "patientProgram", id: pair.id });

  // Best-effort teardown, in creation-reverse order. A failure to delete is reported and does
  // not mask the suite's verdict: the fixtures are namespaced by `RUN`, so a leftover is
  // identifiable rather than confusing.
  const failures: string[] = [];
  for (const { object, id } of created) {
    try {
      await client.deleteRecord(object, id);
    } catch {
      failures.push(object);
    }
  }
  // The receipt goes to stdout as one JSON document, not through a logger: it is the artifact
  // this run produces, attached to the change's Linear parent.
  process.stdout.write(
    `${JSON.stringify(
      {
        artifact: "pulse-app-scaffold 4.2 — live logic-function verification",
        target: target.toLowerCase(),
        run: RUN,
        counts: { cases: receipt.length, fixtures: created.length },
        cases: receipt,
        teardown:
          failures.length === 0 ? "clean" : `failed: ${failures.join(", ")}`,
        optionValueEncoding:
          "catalog value -> UPPER_SNAKE_CASE ('.' -> '_'), encoded and decoded at the client boundary",
        note: "handler invoked in-process over live records; the database-event trigger itself is not installed (see HANDOFF.md)",
      },
      null,
      2,
    )}\n`,
  );
}, 120_000);

describe("first event for a pair creates the PatientProgram row", () => {
  it("creates the pair on the live server and applies the looked-up status", async () => {
    expect(await readPair()).toBeNull();

    const event = await createEvent({
      eventType: "enrollment.active",
      occurredAt: T1,
    });
    const outcome = await handler({ record: event, client });

    expect(outcome.status).toBe("applied");
    if (outcome.status !== "applied") return;
    expect(outcome.createdTarget).toBe(true);
    expect(outcome.objectNameSingular).toBe("patientProgram");

    const pair = await readPair();
    expect(pair).not.toBeNull();
    // Catalog vocabulary, not the stored token: the client decoded `ACTIVE` on the way in.
    expect(pair?.["lifecycleStatus"]).toBe(
      PROJECTION_LOOKUP["enrollment.active"]?.value,
    );
    expect(Date.parse(String(pair?.["lifecycleStatusAsOf"]))).toBe(
      Date.parse(T1),
    );
    // The other dimension keeps the default the artifact declared — the apply is one dimension.
    expect(pair?.["qualificationStatus"]).toBe("open");

    const stored = await readEvent(event.id);
    expect(stored?.[foreignKey("patientProgram")]).toBe(pair?.id);

    record(
      "first-event-creates-pair",
      "First event for a pair creates the PatientProgram row",
      outcome,
      {
        lifecycleStatus: String(pair?.["lifecycleStatus"]),
        lifecycleStatusAsOf: T1,
      },
    );
  }, 60_000);
});

describe("a late event is a no-op on state", () => {
  it("leaves the live status and stamp alone, and still logs the event bound to the pair", async () => {
    const before = await readPair();

    const event = await createEvent({
      eventType: "enrollment.on_hold",
      occurredAt: T0,
    });
    const outcome = await handler({ record: event, client });

    expect(outcome.status).toBe("late");

    const after = await readPair();
    expect(after?.["lifecycleStatus"]).toBe(before?.["lifecycleStatus"]);
    expect(after?.["lifecycleStatusAsOf"]).toBe(
      before?.["lifecycleStatusAsOf"],
    );

    // Logged, not lost: the event is bound to the pair even though it changed no state.
    const stored = await readEvent(event.id);
    expect(stored?.[foreignKey("patientProgram")]).toBe(after?.id);

    record("late-event-no-op", "A late event is a no-op on state", outcome, {
      lifecycleStatus: String(after?.["lifecycleStatus"]),
      lifecycleStatusAsOf: String(after?.["lifecycleStatusAsOf"]),
    });
  }, 60_000);
});

describe("dimensions are isolated", () => {
  it("applies a qualification event older than the lifecycle stamp, touching only its own pair", async () => {
    const before = await readPair();

    // T0 is before the lifecycle stamp set at T1. If the guard read the wrong dimension's
    // `...AsOf`, this event would be judged late and nothing would move.
    const event = await createEvent({
      eventType: "billing_episode.qualified",
      occurredAt: T0,
    });
    const outcome = await handler({ record: event, client });

    expect(outcome.status).toBe("applied");
    if (outcome.status !== "applied") return;
    expect(outcome.statusField).toBe("qualificationStatus");
    expect(outcome.createdTarget).toBe(false);

    const after = await readPair();
    expect(after?.["qualificationStatus"]).toBe(
      PROJECTION_LOOKUP["billing_episode.qualified"]?.value,
    );
    expect(Date.parse(String(after?.["qualificationStatusAsOf"]))).toBe(
      Date.parse(T0),
    );
    // The lifecycle dimension is untouched, value and stamp both.
    expect(after?.["lifecycleStatus"]).toBe(before?.["lifecycleStatus"]);
    expect(after?.["lifecycleStatusAsOf"]).toBe(
      before?.["lifecycleStatusAsOf"],
    );

    record("dimensions-isolated", "Dimensions are isolated", outcome, {
      qualificationStatus: String(after?.["qualificationStatus"]),
      lifecycleStatus: String(after?.["lifecycleStatus"]),
    });
  }, 60_000);
});

describe("an unresolvable ref stops cleanly", () => {
  it("writes no state and leaves the live event's relations empty", async () => {
    const before = await readPair();

    const event = await createEvent({
      eventType: "enrollment.ended",
      entityRefId: UNRESOLVABLE_PATIENT_ID,
      occurredAt: T2,
    });
    const outcome = await handler({ record: event, client });

    expect(outcome.status).toBe("unresolved");
    if (outcome.status !== "unresolved") return;
    expect(outcome.reason).toBe("entity-not-found");

    // No crash, no state write, and the event sits in the orphan view rather than being lost.
    const stored = await readEvent(event.id);
    expect(stored?.[foreignKey("patientProgram")]).toBeNull();
    expect(stored?.[foreignKey("provider")]).toBeNull();
    expect(stored?.[foreignKey("clinic")]).toBeNull();

    const after = await readPair();
    expect(after?.["lifecycleStatus"]).toBe(before?.["lifecycleStatus"]);
    expect(after?.["lifecycleStatusAsOf"]).toBe(
      before?.["lifecycleStatusAsOf"],
    );

    record(
      "unresolved-ref-stops",
      "An unresolvable ref stops cleanly",
      outcome,
      {
        lifecycleStatus: String(after?.["lifecycleStatus"]),
      },
    );
  }, 60_000);
});

describe("a lookup miss is a no-op", () => {
  it("binds the registry-anchor event to the pair and writes no state", async () => {
    const before = await readPair();
    expect(PROJECTION_LOOKUP["referral.received"]).toBeUndefined();

    const event = await createEvent({
      eventType: "referral.received",
      occurredAt: T2,
    });
    const outcome = await handler({ record: event, client });

    expect(outcome.status).toBe("no-lookup-row");

    // Bound, because an anchor event belongs to its pair — leaving it unbound would report a
    // crosswalk gap that does not exist.
    const stored = await readEvent(event.id);
    expect(stored?.[foreignKey("patientProgram")]).toBe(before?.id);

    const after = await readPair();
    expect(after?.["lifecycleStatus"]).toBe(before?.["lifecycleStatus"]);
    expect(after?.["lifecycleStatusAsOf"]).toBe(
      before?.["lifecycleStatusAsOf"],
    );
    expect(after?.["qualificationStatus"]).toBe(
      before?.["qualificationStatus"],
    );

    record("lookup-miss-no-op", "A lookup miss is a no-op", outcome, {
      lifecycleStatus: String(after?.["lifecycleStatus"]),
      qualificationStatus: String(after?.["qualificationStatus"]),
    });
  }, 60_000);
});
