"""Verify a deployed Twenty artifact by schema read-back (pulse-app-scaffold 4.1).

Runs after `task twenty:deploy` and answers one question with a receipt: does the live target
carry what the artifact says it should? Two assertions, in order — spec: "Read-back matches the
artifact":

1. **Read-back.** Every artifact operation's target is present in the state the Metadata API
   reports, under its mapped `universalIdentifier` (roles under their `role:<name>` key — the
   same identities `twenty_deploy` plans on). Any absence is a mismatch, named in the receipt.
2. **Re-apply is all no-ops.** The same deploy path runs again against the live state and its
   receipt must report zero creates and zero updates — the live proof of the idempotence claim
   the scripted-transport tests pin. A matching target receives nothing: no-ops are never sent.

The re-apply is skipped when read-back already found something missing — a verification script
detects, it never repairs, and a re-apply over a hole would create records from a verify path.
A present-but-drifted record does re-apply (that is the deploy contract: converge, then the
nonzero exit and the receipt's update count report that verification failed).

Exit status is the assertion: zero iff both hold. The printed receipt is the artifact to attach —
operation names, counts, and the artifact checksum; never remote payloads, response bodies, or
credentials (same containment as `twenty_deploy`).

Verification is live-only: there is no offline mode, and a missing credential pair is an error
naming the variables, never an empty-state pass.

Run: uv run python -m pulse_core.twenty_verify --target dev   (task twenty:verify)
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pulse_core.twenty_deploy import (
    TARGET_NAMES,
    DeployError,
    MetadataApiTransport,
    Transport,
    artifact_checksum,
    deploy,
    operation_key,
    operation_name,
    resolve_target,
    validation_findings,
)
from pulse_core.twenty_metadata import ARTIFACT_PATH

#: Stated on every receipt so a raw read of the live schema is interpretable: SELECT option
#: values are stored encoded (see `twenty_validate.encode_option_value`), and 4.2's function
#: cases read the encoded tokens back, not the catalog vocabulary.
OPTION_VALUE_ENCODING = "catalog value -> UPPER_SNAKE_CASE ('.' -> '_'), e.g. referral.received -> REFERRAL_RECEIVED"


@dataclass(frozen=True)
class VerificationReceipt:
    """What a verification run is worth attaching: what was checked, and both verdicts.

    Names, counts, and the checksum. No payloads, no response bodies, no credential.
    `reapply` is the re-apply receipt's counts, or `None` when read-back failed and the
    re-apply was skipped.
    """

    target: str
    artifact: str
    checksum: str
    present: tuple[str, ...]
    missing: tuple[str, ...]
    reapply: Mapping[str, int] | None
    failure: str | None

    @property
    def ok(self) -> bool:
        """Both assertions hold: nothing missing, and the re-apply mutated nothing."""
        return (
            not self.missing
            and self.failure is None
            and self.reapply is not None
            and self.reapply.get("create") == 0
            and self.reapply.get("update") == 0
        )

    @property
    def counts(self) -> dict[str, int]:
        return {"present": len(self.present), "missing": len(self.missing)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "artifact": self.artifact,
            "checksum": self.checksum,
            "ok": self.ok,
            "counts": self.counts,
            "missing": list(self.missing),
            "reapply": None if self.reapply is None else dict(self.reapply),
            "failure": self.failure,
            "optionValueEncoding": OPTION_VALUE_ENCODING,
        }


def verify(target: str, artifact_path: Path, transport: Transport) -> VerificationReceipt:
    """Read the target back, assert every artifact operation present, then re-apply."""
    findings = validation_findings(artifact_path)
    if findings:
        msg = f"artifact {artifact_path} is not valid — refusing to verify against it:\n" + "\n".join(findings)
        raise DeployError(msg)

    operations = tuple(json.loads(artifact_path.read_text())["operations"])
    state = transport.read_state()
    present = tuple(operation_name(op) for op in operations if operation_key(op) in state)
    missing = tuple(operation_name(op) for op in operations if operation_key(op) not in state)

    reapply: Mapping[str, int] | None = None
    failure: str | None = None
    if not missing:
        reapply_receipt = deploy(target=target, artifact_path=artifact_path, transport=transport)
        reapply = reapply_receipt.counts
        failure = reapply_receipt.failure

    return VerificationReceipt(
        target=target,
        artifact=str(artifact_path),
        checksum=artifact_checksum(artifact_path),
        present=present,
        missing=missing,
        reapply=reapply,
        failure=failure,
    )


def main(
    argv: list[str] | None = None, env: Mapping[str, str] | None = None, transport: Transport | None = None
) -> int:
    """CLI entry point: verify one target, print the receipt, exit nonzero on any mismatch."""
    parser = argparse.ArgumentParser(description="Verify the deployed Twenty metadata artifact by read-back.")
    parser.add_argument("--target", required=True, choices=TARGET_NAMES, help="which instance to verify")
    parser.add_argument("--artifact", type=Path, default=ARTIFACT_PATH, help="artifact file to verify against")
    args = parser.parse_args(argv)

    environment = os.environ if env is None else env
    try:
        resolved_transport = (
            transport if transport is not None else MetadataApiTransport(resolve_target(args.target, environment))
        )
        receipt = verify(target=args.target, artifact_path=args.artifact, transport=resolved_transport)
    except DeployError as error:
        print(str(error))
        return 1

    print(json.dumps(receipt.to_dict(), indent=2, sort_keys=True))
    return 0 if receipt.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
