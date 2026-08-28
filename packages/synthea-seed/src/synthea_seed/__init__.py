"""synthea-seed — deterministic synthetic population for every non-production tier.

Pins the Synthea JAR (by checksum), module configuration, and RNG seeds so two generations
from the same pin emit byte-identical populations, receipted by a committed checksum manifest.
Brook-specific fixture patients are declarative YAML overlays applied on top of the generated
base — never hand-edits to generated output. Synthetic data only; no PHI exists anywhere in
this package by construction.
"""
