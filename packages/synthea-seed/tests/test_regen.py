"""Task 2.1 — verification against fixture trees only; no generation run, no Java.

Covers the spec scenarios "Two consecutive generations match" and "Drift is a failure, not a
refresh" through injected fake runners that materialize fixture trees deterministically.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest
from synthea_seed.pin import PinConfig
from synthea_seed.regen import (
    GenerationFailedError,
    JarChecksumError,
    ManifestMissingError,
    ensure_jar,
    generation_command,
    main,
    regenerate,
    write_properties,
)

JAR_BYTES = b"synthetic-jar-bytes"
JAR_SHA = hashlib.sha256(JAR_BYTES).hexdigest()


def _pin() -> PinConfig:
    return PinConfig.model_validate({
        "jar": {"version": "v3.3.0", "url": "https://example.invalid/synthea.jar", "sha256": JAR_SHA},
        "seed": 20260809,
        "clinician_seed": 20260809,
        "reference_date": "20260809",
        "properties": {"exporter.fhir.export": "true"},
        "profiles": {
            "dev": {"population": 500, "state": "Massachusetts", "manifest": "manifests/dev.manifest.json"},
            "staging": {
                "population": 50000,
                "state": "Massachusetts",
                "manifest": "manifests/staging.manifest.json",
            },
        },
    })


def _fake_downloader(url: str, dest: Path) -> None:
    dest.write_bytes(JAR_BYTES)


class FixtureTreeRunner:
    """Stands in for the Synthea process: writes a fixture tree into the -c properties' baseDirectory."""

    def __init__(self, files: dict[str, str], returncode: int = 0) -> None:
        self.files = files
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def __call__(self, command: Sequence[str]) -> int:
        self.commands.append(list(command))
        properties = Path(command[command.index("-c") + 1]).read_text()
        base_line = next(line for line in properties.splitlines() if line.startswith("exporter.baseDirectory"))
        output_dir = Path(base_line.split("=", 1)[1].strip())
        for rel_path, content in self.files.items():
            target = output_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        return self.returncode


def _regen(package_root: Path, runner: FixtureTreeRunner, **kwargs: Any) -> int:
    logs: list[str] = kwargs.pop("logs", [])
    return regenerate(
        "dev",
        pin=_pin(),
        package_root=package_root,
        runner=runner,
        downloader=_fake_downloader,
        log=logs.append,
        **kwargs,
    )


class TestJarPinning:
    def test_downloaded_jar_matching_checksum_is_accepted(self, tmp_path: Path) -> None:
        jar = ensure_jar(_pin(), tmp_path / ".jars", _fake_downloader)
        assert jar.read_bytes() == JAR_BYTES
        assert jar.name == "synthea-v3.3.0.jar"

    def test_checksum_mismatch_refuses_to_generate(self, tmp_path: Path) -> None:
        def wrong_bytes(url: str, dest: Path) -> None:
            dest.write_bytes(b"tampered")

        with pytest.raises(JarChecksumError, match="does not match pinned"):
            ensure_jar(_pin(), tmp_path / ".jars", wrong_bytes)

    def test_cached_jar_is_reverified_not_redownloaded(self, tmp_path: Path) -> None:
        cache = tmp_path / ".jars"
        ensure_jar(_pin(), cache, _fake_downloader)

        def must_not_download(url: str, dest: Path) -> None:  # pragma: no cover — failure path
            pytest.fail("jar was already cached; downloader must not run")

        assert ensure_jar(_pin(), cache, must_not_download).exists()


class TestGenerationCommand:
    def test_command_carries_every_pinned_input(self, tmp_path: Path) -> None:
        pin = _pin()
        properties = write_properties(pin, tmp_path / "output" / "dev", tmp_path / "dev.properties")
        command = generation_command(tmp_path / "synthea.jar", pin, pin.profile("dev"), properties)
        assert command[:3] == ["java", "-jar", str(tmp_path / "synthea.jar")]
        for flag, value in (
            ("-s", "20260809"),
            ("-cs", "20260809"),
            ("-r", "20260809"),
            ("-p", "500"),
            ("-c", str(properties)),
        ):
            assert command[command.index(flag) + 1] == value
        assert command[-1] == "Massachusetts"

    def test_properties_file_is_sorted_and_pins_base_directory(self, tmp_path: Path) -> None:
        pin = _pin()
        dest = write_properties(pin, tmp_path / "out", tmp_path / "p.properties")
        lines = dest.read_text().splitlines()
        assert lines == sorted(lines)
        assert f"exporter.baseDirectory = {tmp_path / 'out'}" in lines


class TestVerification:
    FILES: ClassVar[dict[str, str]] = {
        "fhir/patient-0001.json": '{"id": "synthetic-0001"}',
        "fhir/patient-0002.json": '{"id": "s-0002"}',
    }

    def test_repin_then_identical_rerun_verifies_clean(self, tmp_path: Path) -> None:
        assert _regen(tmp_path, FixtureTreeRunner(self.FILES), repin=True) == 0
        assert (tmp_path / "manifests/dev.manifest.json").exists()
        logs: list[str] = []
        assert _regen(tmp_path, FixtureTreeRunner(self.FILES), logs=logs) == 0
        assert any("byte-identical" in line for line in logs)

    def test_divergence_exits_nonzero_naming_the_files(self, tmp_path: Path) -> None:
        assert _regen(tmp_path, FixtureTreeRunner(self.FILES), repin=True) == 0
        drifted = {
            "fhir/patient-0001.json": '{"id": "mutated"}',
            "fhir/patient-0003.json": "{}",
        }
        logs: list[str] = []
        assert _regen(tmp_path, FixtureTreeRunner(drifted), logs=logs) == 1
        report = "\n".join(logs)
        assert "changed: fhir/patient-0001.json" in report
        assert "missing: fhir/patient-0002.json" in report
        assert "unexpected: fhir/patient-0003.json" in report

    def test_divergence_does_not_touch_the_manifest(self, tmp_path: Path) -> None:
        assert _regen(tmp_path, FixtureTreeRunner(self.FILES), repin=True) == 0
        manifest_path = tmp_path / "manifests/dev.manifest.json"
        before = manifest_path.read_text()
        assert _regen(tmp_path, FixtureTreeRunner({"fhir/patient-0001.json": "{}"})) == 1
        assert manifest_path.read_text() == before

    def test_missing_manifest_demands_explicit_repin(self, tmp_path: Path) -> None:
        with pytest.raises(ManifestMissingError, match="REPIN=1"):
            _regen(tmp_path, FixtureTreeRunner(self.FILES))

    def test_stale_output_from_a_prior_run_is_cleared(self, tmp_path: Path) -> None:
        assert _regen(tmp_path, FixtureTreeRunner(self.FILES), repin=True) == 0
        stale = tmp_path / "output" / "dev" / "fhir" / "leftover.json"
        stale.write_text("{}")
        assert _regen(tmp_path, FixtureTreeRunner(self.FILES)) == 0

    def test_failed_generation_raises_with_the_exit_code(self, tmp_path: Path) -> None:
        with pytest.raises(GenerationFailedError, match="exited 3"):
            _regen(tmp_path, FixtureTreeRunner(self.FILES, returncode=3))


class TestCli:
    def test_unknown_profile_is_an_error_not_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("synthea_seed.regen.load_pin", _pin)
        monkeypatch.setattr("synthea_seed.regen.PACKAGE_ROOT", tmp_path)
        assert main(["--profile", "prod"]) == 2
        assert "unknown profile 'prod'" in capsys.readouterr().err

    def test_cli_verifies_through_the_same_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("synthea_seed.regen.load_pin", _pin)
        monkeypatch.setattr("synthea_seed.regen._urllib_download", _fake_downloader)
        monkeypatch.setattr("synthea_seed.regen._subprocess_runner", FixtureTreeRunner(TestVerification.FILES))
        monkeypatch.setattr("synthea_seed.regen.PACKAGE_ROOT", tmp_path)
        assert main(["--profile", "dev", "--repin"]) == 0
        assert main(["--profile", "dev"]) == 0
