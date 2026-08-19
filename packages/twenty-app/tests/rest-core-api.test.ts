/**
 * The live `CoreApiClient` adapter, unit-tested against a faked `fetch`.
 *
 * The adapter is what makes wave 3's live cases run the *same* handler the unit suite runs —
 * `core-api.ts` said the swap to a real client would be a change of import path, and this is
 * that client. It opens no socket here: `fetch` is injected, exactly the way the handler's
 * client is injected (design.md Decision 7 — two fakes, and this is the second one seen from
 * the other side).
 *
 * The properties worth pinning are the ones a live run would otherwise discover by writing
 * garbage into a workspace: the URL a singular object name resolves to, the transport-boundary
 * SELECT encoding (4.1's first-contact finding), and that a failure never carries a response
 * body out of the adapter.
 */

import { describe, expect, it } from "vitest";

import { OPTIONS_BY_FIELD } from "../generated/options";
import {
  CoreApiError,
  createRestCoreApiClient,
  decodeOptionValue,
  encodeOptionValue,
  restPlural,
} from "../src/live/rest-core-api";

/** A `fetch` that answers from a script and records what it was asked. */
const scriptedFetch = (
  responses: readonly { status: number; body: unknown }[],
): {
  fetch: typeof fetch;
  calls: { url: string; method: string; body: unknown; auth: string }[];
} => {
  const calls: { url: string; method: string; body: unknown; auth: string }[] =
    [];
  let index = 0;
  const fetchImpl = (async (url: string | URL, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    calls.push({
      url: String(url),
      method: init?.method ?? "GET",
      body:
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as unknown)
          : null,
      auth: headers.get("authorization") ?? "",
    });
    const scripted = responses[index++] ?? { status: 200, body: {} };
    return {
      ok: scripted.status < 400,
      status: scripted.status,
      json: async () => scripted.body,
      text: async () => JSON.stringify(scripted.body),
    } as Response;
  }) as unknown as typeof fetch;
  return { fetch: fetchImpl, calls };
};

const client = (responses: readonly { status: number; body: unknown }[]) => {
  const { fetch: fetchImpl, calls } = scriptedFetch(responses);
  return {
    api: createRestCoreApiClient({
      baseUrl: "https://twenty.example/",
      token: "test-token",
      fetchImpl,
    }),
    calls,
  };
};

describe("the singular-to-REST-path mapping", () => {
  it("routes every modeled object to the plural the model declares", () => {
    expect(restPlural("patientProgram")).toBe("patientPrograms");
    expect(restPlural("domainEvent")).toBe("domainEvents");
    expect(restPlural("patient")).toBe("patients");
  });

  it("refuses an object the model does not declare rather than guessing a plural", () => {
    expect(() => restPlural("invoice")).toThrow(/invoice/);
  });
});

describe("the SELECT transport encoding", () => {
  it("encodes a catalog value the way the live server stores it", () => {
    // 4.1 first contact: v2.30 stores option values UPPER_SNAKE, so the catalog's dotted
    // lowercase vocabulary is a transport-boundary translation, never a repo-side rename.
    expect(encodeOptionValue("referral.received")).toBe("REFERRAL_RECEIVED");
    expect(encodeOptionValue("active")).toBe("ACTIVE");
  });

  it("agrees with the encoding the generator emits, option for option", () => {
    // Two implementations of one rule: this client's, for values that need not be options, and
    // `pulse_core.twenty_model.encode_option_value`, whose result task 6.6 emits as
    // `encodedValue`. They must not drift — a kanban column keyed on `encodedValue` and a write
    // encoded here have to land on the same token, or a drag writes into no column at all.
    const options = Object.values(OPTIONS_BY_FIELD).flat();
    expect(options.length).toBeGreaterThan(0);
    for (const option of options) {
      expect(option.encodedValue, option.value).toBe(
        encodeOptionValue(option.value),
      );
    }
  });

  it("decodes a stored token back to the catalog value it came from", () => {
    expect(
      decodeOptionValue("domainEvent.eventType", "REFERRAL_RECEIVED"),
    ).toBe("referral.received");
    expect(
      decodeOptionValue("patientProgram.lifecycleStatus", "PENDING_START"),
    ).toBe("pending_start");
  });

  it("leaves a token no catalog option encodes to alone instead of guessing", () => {
    // `SOMETHING_ELSE` could be `something.else` or `something_else`; the encoding is not
    // injective in that direction, so an unknown token stays raw and an assertion fails
    // loudly rather than a wrong catalog value being invented.
    expect(decodeOptionValue("domainEvent.eventType", "SOMETHING_ELSE")).toBe(
      "SOMETHING_ELSE",
    );
  });

  it("encodes SELECT fields on write and leaves every other field untouched", async () => {
    const { api, calls } = client([
      {
        status: 200,
        body: {
          data: {
            updatePatientProgram: {
              id: "pp-1",
              lifecycleStatus: "ACTIVE",
              lifecycleStatusAsOf: "2026-03-01T00:00:00.000Z",
            },
          },
        },
      },
    ]);

    await api.update("patientProgram", "pp-1", {
      lifecycleStatus: "active",
      lifecycleStatusAsOf: "2026-03-01T00:00:00.000Z",
    });

    expect(calls[0]?.method).toBe("PATCH");
    expect(calls[0]?.url).toBe(
      "https://twenty.example/rest/patientPrograms/pp-1",
    );
    expect(calls[0]?.body).toEqual({
      lifecycleStatus: "ACTIVE",
      lifecycleStatusAsOf: "2026-03-01T00:00:00.000Z",
    });
  });

  it("decodes SELECT fields on read, so the handler compares catalog vocabulary", async () => {
    const { api } = client([
      {
        status: 200,
        body: {
          data: {
            patientPrograms: [
              {
                id: "pp-1",
                lifecycleStatus: "PENDING_START",
                programCode: "CCM",
              },
            ],
          },
        },
      },
    ]);

    const found = await api.findOne("patientProgram", { programCode: "CCM" });

    expect(found).toEqual({
      id: "pp-1",
      lifecycleStatus: "pending_start",
      programCode: "CCM",
    });
  });
});

describe("reading one record", () => {
  it("asks for the filtered collection with the bearer credential", async () => {
    const { api, calls } = client([
      { status: 200, body: { data: { patients: [{ id: "p-1" }] } } },
    ]);

    await api.findOne("patient", { canonicalPatientId: "syn-1" });

    expect(calls[0]?.method).toBe("GET");
    expect(calls[0]?.url).toBe(
      "https://twenty.example/rest/patients?filter=canonicalPatientId%5Beq%5D%3Asyn-1&limit=2",
    );
    expect(calls[0]?.auth).toBe("Bearer test-token");
  });

  it("ands every filter entry, in sorted order so the request is reproducible", async () => {
    const { api, calls } = client([
      { status: 200, body: { data: { patientPrograms: [] } } },
    ]);

    await api.findOne("patientProgram", {
      programId: "pr-1",
      patientId: "p-1",
    });

    expect(decodeURIComponent(calls[0]?.url ?? "")).toBe(
      "https://twenty.example/rest/patientPrograms?filter=patientId[eq]:p-1,programId[eq]:pr-1&limit=2",
    );
  });

  it("answers null for no match rather than throwing", async () => {
    const { api } = client([{ status: 200, body: { data: { patients: [] } } }]);

    expect(await api.findOne("patient", { mrn: "syn-none" })).toBeNull();
  });

  it("refuses an ambiguous match instead of picking one", async () => {
    // Two rows for a (patient, program) pair is a real defect — the pair is supposed to be
    // unique. Silently taking the first would project onto an arbitrary one of them.
    const { api } = client([
      {
        status: 200,
        body: { data: { patientPrograms: [{ id: "pp-1" }, { id: "pp-2" }] } },
      },
    ]);

    await expect(
      api.findOne("patientProgram", { patientId: "p-1" }),
    ).rejects.toThrow(CoreApiError);
  });

  it("refuses a filter value carrying the syntax's own separators", async () => {
    const { api } = client([]);

    await expect(
      api.findOne("patient", { canonicalPatientId: "syn,1" }),
    ).rejects.toThrow(/canonicalPatientId/);
  });
});

describe("containment on failure", () => {
  it("names the object and status but never carries the response body out", async () => {
    const { api } = client([
      {
        status: 400,
        body: {
          messages: ["mrn 'SYNTH-0001' is invalid"],
          error: "Bad Request",
        },
      },
    ]);

    const failure = await api
      .create("patient", { canonicalPatientId: "syn-1" })
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(CoreApiError);
    const message = String((failure as CoreApiError).message);
    expect(message).toContain("patient");
    expect(message).toContain("400");
    expect(message).not.toContain("SYNTH-0001");
    expect(JSON.stringify(failure)).not.toContain("SYNTH-0001");
  });
});

describe("creating and deleting a record", () => {
  it("posts to the collection and returns the created record", async () => {
    const { api, calls } = client([
      {
        status: 201,
        body: {
          data: { createPatient: { id: "p-1", canonicalPatientId: "syn-1" } },
        },
      },
    ]);

    const created = await api.create("patient", {
      canonicalPatientId: "syn-1",
    });

    expect(calls[0]?.method).toBe("POST");
    expect(calls[0]?.url).toBe("https://twenty.example/rest/patients");
    expect(created).toEqual({ id: "p-1", canonicalPatientId: "syn-1" });
  });

  it("deletes by id — the verb the fixtures need and the handler never has", async () => {
    const { api, calls } = client([
      { status: 200, body: { data: { deletePatient: { id: "p-1" } } } },
    ]);

    await api.deleteRecord("patient", "p-1");

    expect(calls[0]?.method).toBe("DELETE");
    expect(calls[0]?.url).toBe("https://twenty.example/rest/patients/p-1");
  });
});
