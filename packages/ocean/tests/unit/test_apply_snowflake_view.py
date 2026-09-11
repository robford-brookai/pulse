"""Tests for `apply_snowflake_view.connect_kwargs` (task snowflake:subject-current-state).

Verified 2026-09-11: applying `subject_current_state.sql` with the warehouse-sync credential
(role `OCEAN_WRITER`, grants scoped to `STREAMLINE.OCEAN_RAW`) failed with `Schema
'STREAMLINE.STG_EVENTS' does not exist or not authorized` — both `STG_EVENTS` views are
`ACCOUNTADMIN`-owned. `SNOWFLAKE_ROLE` lets an operator credential pass `role=ACCOUNTADMIN`
through; its absence must not change today's behaviour (no `role` kwarg, `OCEAN_WH`).
Loaded by file path per the module docstring's pattern: the script is a standalone tool, not a
package member.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

OCEAN_ROOT = Path(__file__).resolve().parents[2]
SOURCE = OCEAN_ROOT / "scripts" / "apply_snowflake_view.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("apply_snowflake_view", SOURCE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


apply_snowflake_view = _load_module()

REQUIRED_ENV = {
    "SNOWFLAKE_ACCOUNT": "acct-placeholder",
    "SNOWFLAKE_USER": "user-placeholder",
    "SNOWFLAKE_PRIVATE_KEY_PATH": "/dev/null",
}


def test_defaults_have_no_role_and_the_ocean_wh_warehouse():
    kwargs = apply_snowflake_view.connect_kwargs(REQUIRED_ENV)

    assert kwargs == {
        "account": "acct-placeholder",
        "user": "user-placeholder",
        "warehouse": "OCEAN_WH",
    }
    assert "role" not in kwargs


def test_role_and_warehouse_pass_through_when_set():
    env = {**REQUIRED_ENV, "SNOWFLAKE_ROLE": "ACCOUNTADMIN", "SNOWFLAKE_WAREHOUSE": "OTHER_WH"}

    kwargs = apply_snowflake_view.connect_kwargs(env)

    assert kwargs["role"] == "ACCOUNTADMIN"
    assert kwargs["warehouse"] == "OTHER_WH"


@pytest.mark.parametrize("missing", ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_PATH"])
def test_missing_required_variable_is_named_in_the_error(missing: str):
    env = {k: v for k, v in REQUIRED_ENV.items() if k != missing}

    with pytest.raises(KeyError, match=missing):
        apply_snowflake_view.connect_kwargs(env)
