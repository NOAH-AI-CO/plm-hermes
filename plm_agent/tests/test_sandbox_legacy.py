# -*- coding: utf-8 -*-
"""Backward-compat regression tests for ``SandboxManager`` and
``AgentRunSandboxClient``.

These guard the legacy ``session_id``-only construction path from regressions
during the v2 refactor. NSFC, mindsearch / HITL agents, planning, clarification
and confirmation modules all build sandboxes with ``session_id=...`` and **no**
``workspace_paths``; they must produce the exact same paths as before v2.
"""

from agent.runtime.paths import WorkspacePaths
from tools.sandbox.agentrun_sandbox import AgentRunSandboxClient
from tools.sandbox.sandbox_manager import SandboxManager


# ---------------------------------------------------------------------------
# Legacy mode — must match pre-v2 behavior byte-for-byte
# ---------------------------------------------------------------------------


def test_sandbox_manager_legacy_workspace_path():
    sm = SandboxManager(session_id="abc-123")
    assert sm.workspace == "/mnt/workspace/sessions/abc-123/workspace"
    assert sm.session_id == "abc-123"


def test_sandbox_manager_legacy_paths_attribute_is_legacy():
    sm = SandboxManager(session_id="abc-123")
    assert sm.paths is not None
    assert sm.paths.is_legacy is True
    assert sm.paths.session_id == "abc-123"


def test_agentrun_sandbox_client_legacy_session_workspace():
    client = AgentRunSandboxClient(session_id="abc-123")
    assert client.session_workspace == "/mnt/workspace/sessions/abc-123/workspace"
    assert client.session_memory_dir == "/mnt/workspace/sessions/abc-123/.memory"


def test_agentrun_sandbox_client_no_session_falls_back_to_home():
    client = AgentRunSandboxClient()
    assert client.session_workspace == "/home/user"
    assert client.session_memory_dir == "/home/user/execution_log"


def test_sandbox_manager_no_session_falls_back_to_home():
    sm = SandboxManager()
    assert sm.workspace == "/home/user"
    assert sm.paths is None


# ---------------------------------------------------------------------------
# New v2 mode — paths use {env}/users/{user_id}/sessions/{tid}/
# ---------------------------------------------------------------------------


def test_sandbox_manager_v2_workspace_path():
    paths = WorkspacePaths(env="dev", user_id="42", session_id="abc-123")
    sm = SandboxManager(workspace_paths=paths)
    assert sm.workspace == "/mnt/workspace/dev/users/42/sessions/abc-123/workspace"
    assert sm.session_id == "abc-123"
    assert sm.paths is paths


def test_agentrun_sandbox_client_v2_session_workspace():
    paths = WorkspacePaths(env="prod", user_id="100", session_id="xyz-789")
    client = AgentRunSandboxClient(workspace_paths=paths)
    assert client.session_workspace == "/mnt/workspace/prod/users/100/sessions/xyz-789/workspace"
    assert client.session_memory_dir == "/mnt/workspace/prod/users/100/sessions/xyz-789/.memory"


def test_workspace_paths_takes_precedence_over_session_id():
    paths = WorkspacePaths(env="dev", user_id="42", session_id="from-paths")
    sm = SandboxManager(session_id="from-kwarg-but-ignored", workspace_paths=paths)
    # workspace_paths wins; session_id mirrors paths.session_id
    assert sm.session_id == "from-paths"
    assert sm.paths is paths
