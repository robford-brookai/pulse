import { execFileSync } from "node:child_process";
import { readFileSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";

import CLINIC from "../src/objects/clinic.object";
import DOMAIN_EVENT from "../src/objects/domain-event.object";
import PATIENT_PROGRAM from "../src/objects/patient-program.object";
import PATIENT from "../src/objects/patient.object";
import PROGRAM from "../src/objects/program.object";
import PROVIDER from "../src/objects/provider.object";
import APP_ROLE from "../src/roles/app.role";
import PRODUCER_ROLE from "../src/roles/producer.role";
import STAFF_ROLE from "../src/roles/staff.role";
import DOMAIN_EVENT_LOG_VIEW from "../src/views/domain-event-log.view";
import DOMAIN_EVENT_ORPHANS_VIEW from "../src/views/domain-event-orphans.view";
import PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW from "../src/views/patient-program-lifecycle-board.view";
import PATIENT_PROGRAM_STATUS_BOARD_VIEW from "../src/views/patient-program-status-board.view";

// The manifest smoke test task 6.4 asks for: `twenty dev:build` (the local bin, never `npx
// twenty` — the npm name is squatted) exits 0 offline and emits a manifest whose objects,
// roles, and views are the app source's, matched by universalIdentifier. This is the check
// 7.2's first live publish had to discover the hard way: the CLI detects entities
// syntactically (`export default define*({...})` inline), so a port that typechecks can still
// build an empty manifest. The identifiers pin content, not just success.

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const manifestPath = `${packageRoot}.twenty/output/manifest.json`;

interface ManifestEntity {
  readonly universalIdentifier: string;
  readonly [key: string]: unknown;
}

interface Manifest {
  readonly application?: ManifestEntity;
  readonly objects?: readonly ManifestEntity[];
  readonly roles?: readonly ManifestEntity[];
  readonly views?: readonly ManifestEntity[];
  readonly navigationMenuItems?: readonly ManifestEntity[];
  readonly logicFunctions?: readonly ManifestEntity[];
}

let manifest: Manifest;

beforeAll(() => {
  // A stale output directory would let a broken build pass on the previous build's manifest.
  rmSync(`${packageRoot}.twenty/output`, { recursive: true, force: true });
  // The local bin, resolved from the workspace root — `npx twenty` resolves to a squatted npm
  // package (an IP-geolocation tool) whenever the local install is missing.
  execFileSync(
    `${packageRoot}../../node_modules/.bin/twenty`,
    ["dev:build", "."],
    {
      cwd: packageRoot,
      // The CLI resolves the app's tsconfig against INIT_CWD when npm has set it. Under
      // `npm run test --workspace=@pulse/twenty-app` (what `task twenty:test` runs) INIT_CWD is
      // the repo root, which sends the build after a tsconfig two directories above the app.
      // Pin it to the app so the build sees the same world as a direct CLI invocation.
      env: { ...process.env, INIT_CWD: packageRoot },
      stdio: "pipe",
      timeout: 180_000,
    },
  );
  manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Manifest;
}, 200_000);

const identifiers = (
  entities: readonly ManifestEntity[] | undefined,
): readonly string[] =>
  (entities ?? []).map((entity) => entity.universalIdentifier).toSorted();

describe("twenty dev:build manifest", () => {
  it("carries every object the source defines, by identifier", () => {
    expect(identifiers(manifest.objects)).toStrictEqual(
      [PATIENT, PROGRAM, PATIENT_PROGRAM, PROVIDER, CLINIC, DOMAIN_EVENT]
        .map((object) => object.config.universalIdentifier)
        .toSorted(),
    );
  });

  it("carries every role the source defines, by identifier", () => {
    expect(identifiers(manifest.roles)).toStrictEqual(
      [PRODUCER_ROLE, STAFF_ROLE, APP_ROLE]
        .map((role) => role.config.universalIdentifier)
        .toSorted(),
    );
  });

  it("carries every view the source defines, by identifier", () => {
    expect(identifiers(manifest.views)).toStrictEqual(
      [
        PATIENT_PROGRAM_STATUS_BOARD_VIEW,
        PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW,
        DOMAIN_EVENT_LOG_VIEW,
        DOMAIN_EVENT_ORPHANS_VIEW,
      ]
        .map((view) => view.config.universalIdentifier)
        .toSorted(),
    );
  });
});
