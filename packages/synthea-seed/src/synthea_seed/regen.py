"""Generation wrapper: shell out to the pinned JAR, verify the output against the manifest.

`task synthea:regen PROFILE=<p>` lands here. The JAR is fetched once into a local cache and
checksum-verified against the pin before every run — a wrong JAR never generates. After
generation the output tree is verified against the profile's committed manifest; divergence
exits nonzero naming every diverging file. Re-pinning the manifest is explicit (`REPIN=1`),
never automatic. Java is a prerequisite of this entry point only — nothing here runs inside
`task check`, and the unit tests exercise verification logic through injected fakes.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from .manifest import build_manifest, read_manifest, verify_tree, write_manifest
from .pin import PinConfig, Profile, load_pin

#: packages/synthea-seed — manifests, the JAR cache, and output trees live under here.
PACKAGE_ROOT = Path(__file__).resolve().parents[2]

Runner = Callable[[Sequence[str]], int]
Downloader = Callable[[str, Path], None]


class RegenError(RuntimeError):
    """Any failure of the regen pipeline; message is the operator-facing diagnosis."""


class JarChecksumError(RegenError):
    """The cached or downloaded JAR does not match the pinned sha256."""


class GenerationFailedError(RegenError):
    """The Synthea process exited nonzero."""


class ManifestMissingError(RegenError):
    """No committed manifest for the profile — re-pin is explicit, never implied."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _urllib_download(url: str, dest: Path) -> None:  # pragma: no cover — live-network path
    with urllib.request.urlopen(url) as response, dest.open("wb") as out:  # noqa: S310 — pin validates https
        shutil.copyfileobj(response, out)


def _subprocess_runner(command: Sequence[str]) -> int:  # pragma: no cover — spawns Java
    return subprocess.run(list(command), check=False).returncode  # noqa: S603 — argv built from the validated pin


def ensure_jar(pin: PinConfig, cache_dir: Path, downloader: Downloader = _urllib_download) -> Path:
    """The pinned JAR, downloaded if absent and checksum-verified on every call."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    jar = cache_dir / f"synthea-{pin.jar.version}.jar"
    if not jar.exists():
        partial = jar.with_suffix(".part")
        downloader(pin.jar.url, partial)
        partial.replace(jar)
    actual = _sha256(jar)
    if actual != pin.jar.sha256:
        jar_name = jar.name
        msg = f"{jar_name}: sha256 {actual} does not match pinned {pin.jar.sha256}; refusing to generate"
        raise JarChecksumError(msg)
    return jar


def write_properties(pin: PinConfig, output_dir: Path, dest: Path) -> Path:
    """The pinned module configuration as a Synthea properties file, sorted for determinism."""
    merged = {**pin.properties, "exporter.baseDirectory": str(output_dir)}
    lines = [f"{key} = {value}" for key, value in sorted(merged.items())]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n")
    return dest


def generation_command(jar: Path, pin: PinConfig, profile: Profile, properties_file: Path) -> list[str]:
    """The exact argv for a deterministic run: seeds, reference date, population, config, state."""
    return [
        "java",
        "-jar",
        str(jar),
        "-s",
        str(pin.seed),
        "-cs",
        str(pin.clinician_seed),
        "-r",
        pin.reference_date,
        "-p",
        str(profile.population),
        "-c",
        str(properties_file),
        profile.state,
    ]


def regenerate(
    profile_name: str,
    *,
    repin: bool = False,
    pin: PinConfig | None = None,
    package_root: Path | None = None,
    runner: Runner | None = None,
    downloader: Downloader | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Generate the profile's population and verify (or, with repin, author) its manifest.

    Returns 0 on a clean verification or an explicit re-pin; 1 when the output diverges from
    the committed manifest, after logging every diverging file by name. The None defaults
    resolve to the module-level implementations at call time, so tests inject fakes either
    way — as arguments or by patching the module attributes.
    """
    root = package_root if package_root is not None else PACKAGE_ROOT
    run = runner if runner is not None else _subprocess_runner
    download = downloader if downloader is not None else _urllib_download
    resolved_pin = pin if pin is not None else load_pin()
    profile = resolved_pin.profile(profile_name)

    jar = ensure_jar(resolved_pin, root / ".jars", download)

    output_dir = root / "output" / profile_name
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    properties_file = write_properties(resolved_pin, output_dir, root / "output" / f"{profile_name}.properties")

    command = generation_command(jar, resolved_pin, profile, properties_file)
    returncode = run(command)
    if returncode != 0:
        msg = f"synthea generation for profile {profile_name!r} exited {returncode}"
        raise GenerationFailedError(msg)

    manifest_path = root / profile.manifest
    if repin:
        manifest = build_manifest(
            output_dir, profile=profile_name, synthea_version=resolved_pin.jar.version, seed=resolved_pin.seed
        )
        write_manifest(manifest, manifest_path)
        log(f"re-pinned {profile.manifest}: {len(manifest.files)} files, top_hash {manifest.top_hash}")
        return 0

    if not manifest_path.exists():
        msg = (
            f"no committed manifest at {profile.manifest} for profile {profile_name!r}; "
            "re-pin is explicit — rerun with REPIN=1 and review the manifest diff"
        )
        raise ManifestMissingError(msg)

    divergence = verify_tree(output_dir, read_manifest(manifest_path))
    if not divergence.ok:
        log(f"output for profile {profile_name!r} diverges from {profile.manifest}:")
        log(divergence.describe())
        log("re-pin is explicit — rerun with REPIN=1 only if the divergence is intended and reviewed")
        return 1
    log(f"profile {profile_name!r} verified byte-identical against {profile.manifest}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="synthea_seed.regen",
        description="Regenerate a pinned synthetic population and verify its checksum manifest.",
    )
    parser.add_argument("--profile", required=True, help="population profile (dev, staging)")
    parser.add_argument(
        "--repin", action="store_true", help="author the manifest from this run instead of verifying (explicit re-pin)"
    )
    args = parser.parse_args(argv)
    try:
        return regenerate(args.profile, repin=args.repin)
    except (RegenError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
