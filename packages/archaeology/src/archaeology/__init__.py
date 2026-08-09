"""archaeology — read-only access seam to the legacy Mongo cluster (BF-0a).

Everything backfill discovery (BF-0b) and later bulk extraction (BF-5) flows
through this seam. Connections are built from documented env-var names only;
credentials are secret-store references, never literals. See README.md for the
env-var interface and the hard read-only-Atlas-role precondition.
"""

from archaeology.client import (
    ENV_VAR_NAMES,
    ArchaeologyConfig,
    MissingEnvVarsError,
    SecretRefError,
    WriteRoleRefusedError,
    create_readonly_client,
)

__all__ = [
    "ENV_VAR_NAMES",
    "ArchaeologyConfig",
    "MissingEnvVarsError",
    "SecretRefError",
    "WriteRoleRefusedError",
    "create_readonly_client",
]
