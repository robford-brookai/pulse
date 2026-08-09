"""Pinned generation inputs: the determinism contract (design.md decisions 1, 2, 4).

Everything a generation depends on lives in one validated config: the Synthea JAR pinned by
sha256, the module configuration, the RNG seeds, and the two population profiles (dev ~500,
staging ~50k — runtime readiness §2). Re-pinning is an explicit, reviewed edit to the config
file, never automatic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

DEFAULT_PIN_PATH = Path(__file__).parent / "config" / "synthea-pin.yaml"

#: Both tiers must exist in one config — dev covers the inner loop, staging is prod-shaped.
REQUIRED_PROFILES: tuple[str, ...] = ("dev", "staging")

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class JarPin(BaseModel):
    """The released Synthea JAR, identified by version and pinned by checksum."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    sha256: Sha256


class Profile(BaseModel):
    """One population tier: its size, region, and the manifest that receipts it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    population: int = Field(gt=0)
    state: str = Field(min_length=1)
    #: Path of the committed checksum manifest, relative to the package root.
    manifest: str = Field(min_length=1)


class PinConfig(BaseModel):
    """The full pin: JAR, seeds, module configuration, and population profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    jar: JarPin
    seed: int
    clinician_seed: int
    #: Synthea -r reference date, yyyymmdd — without it, wall-clock time enters generation.
    reference_date: Annotated[str, StringConstraints(pattern=r"^\d{8}$")]
    properties: dict[str, str]
    profiles: dict[str, Profile]

    @model_validator(mode="after")
    def _both_tiers_present(self) -> PinConfig:
        missing = [name for name in REQUIRED_PROFILES if name not in self.profiles]
        if missing:
            msg = f"pin config must define profiles {list(REQUIRED_PROFILES)}; missing {missing}"
            raise ValueError(msg)
        return self

    def profile(self, name: str) -> Profile:
        """The named profile, or a ValueError naming the ones that exist."""
        if name not in self.profiles:
            msg = f"unknown profile {name!r}; pinned profiles: {sorted(self.profiles)}"
            raise ValueError(msg)
        return self.profiles[name]


def load_pin(path: Path | None = None) -> PinConfig:
    """Load and validate the pin config (the packaged one unless a path is given)."""
    source = path if path is not None else DEFAULT_PIN_PATH
    raw = yaml.safe_load(source.read_text())
    return PinConfig.model_validate(raw)
