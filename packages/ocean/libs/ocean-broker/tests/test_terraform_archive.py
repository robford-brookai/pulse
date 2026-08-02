"""Structural tests for the bus archive (task 6.4).

Same placement and rationale as `test_terraform_bus.py`: `packages/ocean/libs` is
what `task test` collects, and the archive is the other half of the replay story
the consumers' idempotency guards assume.

The property that matters most here is boundedness. An `aws_cloudwatch_event_archive`
with `retention_days` omitted (or 0) retains events indefinitely — which would quietly
turn the convenience-replay archive into a second durable record. The spec is explicit
that the record is `audit_log`; the design's Open Questions bound retention to 30-90
days. These tests hold that line.
"""

from __future__ import annotations

import re
from pathlib import Path

#: `packages/ocean`, from `packages/ocean/libs/ocean-broker/tests/`.
_REPO_OCEAN = Path(__file__).resolve().parents[3]
_BUS_MODULE = _REPO_OCEAN / "infra" / "terraform" / "modules" / "eventbridge-ocean"


def _tf_text(name: str) -> str:
    return (_BUS_MODULE / name).read_text()


def _code_only(text: str) -> str:
    """Drop comment lines, so prose about the design is not read as configuration."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _block(text: str, header: str) -> str:
    """Return the body of the first brace-balanced block whose header line matches."""
    start = text.index(header)
    depth = 0
    for offset in range(start, len(text)):
        if text[offset] == "{":
            depth += 1
        elif text[offset] == "}":
            depth -= 1
            if depth == 0:
                return text[start : offset + 1]
    raise AssertionError(f"unterminated block for {header!r}")


class TestArchiveShape:
    """The archive exists, in its own file, attached to the OCEAN bus."""

    def test_archive_file_exists(self):
        assert (_BUS_MODULE / "archive.tf").is_file()

    def test_declares_exactly_one_archive(self):
        assert _tf_text("archive.tf").count('resource "aws_cloudwatch_event_archive"') == 1

    def test_archive_sources_from_the_ocean_bus(self):
        archive = _block(_tf_text("archive.tf"), 'resource "aws_cloudwatch_event_archive"')

        assert re.search(
            r"^\s*event_source_arn\s*=\s*aws_cloudwatch_event_bus\.ocean\.arn\s*$",
            archive,
            re.MULTILINE,
        )


class TestRetentionIsBounded:
    """Omitted retention means indefinite retention; the spec says bounded."""

    def test_retention_comes_from_the_variable(self):
        archive = _block(_tf_text("archive.tf"), 'resource "aws_cloudwatch_event_archive"')

        assert re.search(
            r"^\s*retention_days\s*=\s*var\.archive_retention_days\s*$",
            archive,
            re.MULTILINE,
        )

    def test_default_is_within_the_design_window(self):
        variable = _block(_tf_text("variables.tf"), 'variable "archive_retention_days"')
        default = re.search(r"^\s*default\s*=\s*(\d+)\s*$", variable, re.MULTILINE)

        assert default is not None, "archive_retention_days must state a default"
        assert 30 <= int(default.group(1)) <= 90

    def test_variable_validates_the_30_to_90_window(self):
        """0 disables the bound and anything above 90 creeps toward a second record."""
        variable = _block(_tf_text("variables.tf"), 'variable "archive_retention_days"')
        validation = _block(variable, "validation")

        assert "30" in validation and "90" in validation


class TestArchiveIsPassive:
    """The archive replays on demand; it must not filter or transform on the way in."""

    def test_archive_writes_no_event_pattern(self):
        """A pattern here would silently drop events from the replay window.

        The bus is dedicated to OCEAN, so everything on it belongs in the archive;
        filtering is the rules' job (task 6.2), driven by the generated catalog.
        """
        assert "event_pattern" not in _code_only(_tf_text("archive.tf"))

    def test_archive_name_is_exposed(self):
        assert 'output "archive_name"' in _tf_text("outputs.tf")
