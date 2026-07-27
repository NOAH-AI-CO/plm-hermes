# -*- coding: utf-8 -*-
"""Unit tests for ``agent.runtime.paths.WorkspacePaths``.

Covers:
- Cycle 1: construction modes + ``is_legacy``.
- Cycle 2: sandbox-mounted path properties.
- Cycle 3: OSS-key prefix.
- Cycle 4: ``__post_init__`` validation.
"""

import pytest

from agent.runtime.paths import WorkspacePaths


# ---------------------------------------------------------------------------
# Cycle 1 — construction + is_legacy
# ---------------------------------------------------------------------------


def test_legacy_classmethod_yields_legacy_paths():
    paths = WorkspacePaths.legacy("abc-123")

    assert paths.is_legacy is True
    assert paths.env is None
    assert paths.user_id is None
    assert paths.session_id == "abc-123"


def test_full_construction_is_not_legacy():
    paths = WorkspacePaths(env="dev", user_id="42", session_id="abc-123")

    assert paths.is_legacy is False
    assert paths.env == "dev"
    assert paths.user_id == "42"
    assert paths.session_id == "abc-123"


def test_partial_construction_with_only_env_is_legacy():
    """Either env or user_id missing → legacy mode."""
    paths = WorkspacePaths(env="dev", user_id=None, session_id="abc-123")
    assert paths.is_legacy is True


def test_partial_construction_with_only_user_id_is_legacy():
    paths = WorkspacePaths(env=None, user_id="42", session_id="abc-123")
    assert paths.is_legacy is True


# ---------------------------------------------------------------------------
# Cycle 2 — sandbox-mounted path properties
# ---------------------------------------------------------------------------


def test_legacy_base_dir():
    paths = WorkspacePaths.legacy("abc-123")
    assert paths.base_dir == "/mnt/workspace/sessions/abc-123"


def test_new_mode_base_dir():
    paths = WorkspacePaths(env="dev", user_id="42", session_id="abc-123")
    assert paths.base_dir == "/mnt/workspace/dev/users/42/sessions/abc-123"


def test_legacy_subdirs():
    paths = WorkspacePaths.legacy("abc-123")
    assert paths.workspace_dir == "/mnt/workspace/sessions/abc-123/workspace"
    assert paths.memory_dir == "/mnt/workspace/sessions/abc-123/.memory"
    assert paths.module_state_dir == "/mnt/workspace/sessions/abc-123/.modules"


def test_new_mode_subdirs():
    paths = WorkspacePaths(env="prod", user_id="100", session_id="abc-123")
    assert paths.workspace_dir == "/mnt/workspace/prod/users/100/sessions/abc-123/workspace"
    assert paths.memory_dir == "/mnt/workspace/prod/users/100/sessions/abc-123/.memory"
    assert paths.module_state_dir == "/mnt/workspace/prod/users/100/sessions/abc-123/.modules"


def test_skills_link_is_global_in_both_modes():
    """Skills are shared across all sessions/users — the link is always the same."""
    legacy = WorkspacePaths.legacy("abc-123")
    new = WorkspacePaths(env="dev", user_id="42", session_id="abc-123")
    assert legacy.skills_link == "/mnt/workspace/skills"
    assert new.skills_link == "/mnt/workspace/skills"


# ---------------------------------------------------------------------------
# Cycle 3 — OSS-key prefix (mirrors sandbox layout, different leading prefix)
# ---------------------------------------------------------------------------


def test_legacy_oss_workspace_prefix():
    paths = WorkspacePaths.legacy("abc-123")
    assert paths.oss_workspace_prefix == "workspace/abc-123"


def test_new_mode_oss_workspace_prefix():
    paths = WorkspacePaths(env="dev", user_id="42", session_id="abc-123")
    assert paths.oss_workspace_prefix == "workspace/dev/users/42/sessions/abc-123"


def test_oss_prefix_mirrors_sandbox_session_segment():
    """OSS prefix and sandbox base_dir share the same {env}/users/{uid}/sessions/{tid} tail."""
    paths = WorkspacePaths(env="prod", user_id="100", session_id="xyz-789")
    sandbox_tail = paths.base_dir.removeprefix("/mnt/workspace/")
    oss_tail = paths.oss_workspace_prefix.removeprefix("workspace/")
    assert sandbox_tail == oss_tail == "prod/users/100/sessions/xyz-789"


# ---------------------------------------------------------------------------
# Cycle 4 — __post_init__ validation (path-traversal defense)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_env", ["evil", "PROD", "prod ", " prod", "dev/test", ""])
def test_invalid_env_rejected(bad_env):
    with pytest.raises(ValueError, match="env"):
        WorkspacePaths(env=bad_env, user_id="42", session_id="abc-123")


@pytest.mark.parametrize(
    "bad_user_id",
    ["../etc", "abc", "42abc", "", "42 ", " 42", "4/2", "anon"],
)
def test_invalid_user_id_rejected(bad_user_id):
    with pytest.raises(ValueError, match="user_id"):
        WorkspacePaths(env="dev", user_id=bad_user_id, session_id="abc-123")


@pytest.mark.parametrize(
    "bad_session_id",
    ["", "abc/def", "abc..def", "..", "../etc", "a b", "abc.def"],
)
def test_invalid_session_id_rejected(bad_session_id):
    with pytest.raises(ValueError, match="session_id"):
        WorkspacePaths(env="dev", user_id="42", session_id=bad_session_id)


def test_legacy_construction_skips_env_user_id_validation():
    """legacy() passes None for env+user_id — those branches must not fire."""
    paths = WorkspacePaths.legacy("abc-123")
    assert paths.env is None
    assert paths.user_id is None


def test_legacy_construction_still_validates_session_id():
    with pytest.raises(ValueError, match="session_id"):
        WorkspacePaths.legacy("../etc")


def test_legacy_construction_rejects_empty_session_id():
    with pytest.raises(ValueError, match="session_id"):
        WorkspacePaths.legacy("")


def test_partial_construction_validates_provided_field():
    """If only env is given (user_id=None → legacy mode), env must still be valid."""
    with pytest.raises(ValueError, match="env"):
        WorkspacePaths(env="evil", user_id=None, session_id="abc-123")


def test_well_formed_inputs_construct_without_error():
    """Smoke test: every whitelisted env + simple uuid-shape session_id constructs cleanly."""
    for env in ["dev", "test", "staging", "prod"]:
        WorkspacePaths(env=env, user_id="0", session_id="abc-123")
        WorkspacePaths(env=env, user_id="42", session_id="d290f1ee-6c54-4b01-90e6-d701748f0851")
