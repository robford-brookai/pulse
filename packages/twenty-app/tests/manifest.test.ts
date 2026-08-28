import { execFileSync } from "node:child_process";
import { readFileSync, readdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";

import CLINIC from "../../twenty-model/objects/clinic.object";
import DOMAIN_EVENT from "../../twenty-model/objects/domain-event.object";
import PATIENT_PROGRAM from "../../twenty-model/objects/patient-program.object";
import PATIENT from "../../twenty-model/objects/patient.object";
import PROGRAM from "../../twenty-model/objects/program.object";
import PROVIDER from "../../twenty-model/objects/provider.object";
import APP_ROLE from "../../twenty-model/roles/app.role";
import PRODUCER_ROLE from "../../twenty-model/roles/producer.role";
import STAFF_ROLE from "../../twenty-model/roles/staff.role";
import APPLICATION from "../src/application-config";
import PROJECT_DOMAIN_EVENT from "../src/logic-functions/project-domain-event";
import PATIENT_PROGRAM_BOARD_NAV_ITEM from "../src/navigation/patient-program-board.nav";
import APP_DEFAULT_ROLE from "../src/roles/app-default.role";
import DOMAIN_EVENT_LOG_VIEW from "../src/views/domain-event-log.view";
import DOMAIN_EVENT_ORPHANS_VIEW from "../src/views/domain-event-orphans.view";
import PATIENT_PROGRAM_LIFECYCLE_BOARD_VIEW from "../src/views/patient-program-lifecycle-board.view";
import PATIENT_PROGRAM_STATUS_BOARD_VIEW from "../src/views/patient-program-status-board.view";

// The manifest smoke test task 6.4 asks for: `twenty dev:build` (the local bin, never `npx
// twenty` — the npm name is squatted) exits 0 offline and emits a manifest whose contents are
// the app source's, matched by universalIdentifier. This is the check 7.2's first live publish
// had to discover the hard way: the CLI detects entities syntactically (`export default
// define*({...})` inline), so a port that typechecks can still build an empty manifest. The
// identifiers pin content, not just success.
//
// Since task 6.6 the manifest is also pinned by what it does *not* carry. 7.2's live install
// settled it: a full-model install collides wholesale with the artifact-applied workspace
// metadata (45 ENTITY_ALREADY_EXISTS / 40 FIELD_ALREADY_EXISTS — an app cannot adopt
// workspace-owned entities), while a views-only package installs cleanly and binds its views to
// workspace-owned objects and fields. So the packaged surface is disjoint from the artifact's:
// views, navigation, the logic function, and one placeholder default role the SDK requires —
// objects and every real role stay artifact-owned. The mechanism is the file tree, because the
// CLI derives entities from it: the object and role sources live in `packages/twenty-model/`,
// outside the app path the CLI globs. Both halves are asserted here, because the exclusion is
// only as good as the tree, and a file moved back would publish a colliding model.

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

  it("carries the navigation item and the logic function", () => {
    // Without the nav item the board is URL-only (task 6.2); the logic function is the
    // projection handler, and it is app-owned because nothing in the artifact can express it.
    expect(identifiers(manifest.navigationMenuItems)).toStrictEqual([
      PATIENT_PROGRAM_BOARD_NAV_ITEM.config.universalIdentifier,
    ]);
    expect(identifiers(manifest.logicFunctions)).toStrictEqual([
      PROJECT_DOMAIN_EVENT.config.universalIdentifier,
    ]);
  });

  it("carries the placeholder default role and no other", () => {
    // The SDK requires exactly one `defineApplicationRole`; the artifact's roles are label-keyed
    // live with no identifier a manifest could reference. So the app declares one role that
    // grants nothing, and any real role appearing here would collide on install.
    expect(identifiers(manifest.roles)).toStrictEqual([
      APP_DEFAULT_ROLE.config.universalIdentifier,
    ]);
    expect(manifest.application?.defaultRoleUniversalIdentifier).toBe(
      APP_DEFAULT_ROLE.config.universalIdentifier,
    );
    expect(manifest.application?.universalIdentifier).toBe(
      APPLICATION.config.universalIdentifier,
    );
  });

  it("carries no object, and none of the artifact-owned roles", () => {
    // The exclusion 7.2's live install forced: an app cannot adopt workspace-owned entities, so
    // the packaged surface has to be disjoint from the artifact's. Asserted by identifier rather
    // than by count — a manifest that grew one object is the failing install, not a style drift.
    expect(identifiers(manifest.objects)).toStrictEqual([]);
    const artifactOwned = [PRODUCER_ROLE, STAFF_ROLE, APP_ROLE].map(
      (role) => role.config.universalIdentifier,
    );
    const objectsAndRoles = [
      ...identifiers(manifest.objects),
      ...identifiers(manifest.roles),
    ];
    for (const identifier of [
      ...artifactOwned,
      ...[
        PATIENT,
        PROGRAM,
        PATIENT_PROGRAM,
        PROVIDER,
        CLINIC,
        DOMAIN_EVENT,
      ].map((object) => object.config.universalIdentifier),
    ]) {
      expect(objectsAndRoles, identifier).not.toContain(identifier);
    }
  });

  it("keeps the model sources outside the path the CLI globs", () => {
    // The mechanism behind the assertions above, pinned directly: the CLI globs `**/*.ts` under
    // the app path, so exclusion *is* the file tree. A model file moved back under
    // `packages/twenty-app/` would silently rejoin the manifest.
    const sources = readdirSync(packageRoot, {
      recursive: true,
      withFileTypes: true,
    })
      .filter(
        (entry) =>
          entry.isFile() &&
          entry.name.endsWith(".ts") &&
          !entry.parentPath.includes("node_modules") &&
          !entry.parentPath.includes(".twenty"),
      )
      .map((entry) => `${entry.parentPath}/${entry.name}`);
    expect(sources.length).toBeGreaterThan(0);

    const modelEntities = sources.filter((path) =>
      /^export default define(Object|Role)\(\{$/m.test(
        readFileSync(path, "utf8"),
      ),
    );
    expect(modelEntities).toStrictEqual([]);
  });
});
