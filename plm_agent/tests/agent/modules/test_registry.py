# -*- coding: utf-8 -*-
"""Unit tests for the registry / @register_module decorator."""

import pytest
from pydantic import BaseModel

from agent.modules import registry
from agent.modules.base import InteractiveModule


@pytest.fixture
def isolated_registry(monkeypatch):
    """Run each test against an empty registry and restore after."""
    monkeypatch.setattr(registry, "_REGISTRY", {})
    monkeypatch.setattr(registry, "_ROUTABLE_ORDER", [])
    monkeypatch.setattr(registry, "_REPLY_TYPE_MAP", {})
    yield


class _Args(BaseModel):
    foo: str = "x"


def _make_module(name, *, reply_types=("module_reply",), routable=True):
    """Build a minimal InteractiveModule subclass on the fly for tests.

    Concrete ``run`` / ``consume_reply`` are defined inside the class body so
    Python's ABC machinery doesn't keep them as abstract.
    """

    class M(InteractiveModule):
        async def run(self, body, state, args):  # noqa: ARG001
            if False:
                yield {}

        async def consume_reply(self, body, state):  # noqa: ARG001
            if False:
                yield {}

    M.name = name
    M.content_type = name
    M.args_model = _Args
    M.tool_description = f"test module {name}"
    M.reply_types = tuple(reply_types)
    M.routable = routable
    return M


class TestRegistration:
    def test_register_appends_routable(self, isolated_registry):
        registry.register_module(_make_module("a"))
        registry.register_module(_make_module("b"))
        names = [m.name for m in registry.iter_routable()]
        assert names == ["a", "b"]

    def test_register_idempotent_same_class(self, isolated_registry):
        cls = _make_module("dup")
        registry.register_module(cls)
        registry.register_module(cls)  # same class re-import is fine
        assert [m.name for m in registry.iter_routable()] == ["dup"]

    def test_register_rejects_name_collision(self, isolated_registry):
        registry.register_module(_make_module("x"))
        with pytest.raises(ValueError, match="already registered"):
            registry.register_module(_make_module("x"))

    def test_non_routable_excluded(self, isolated_registry):
        registry.register_module(_make_module("r", routable=False))
        names = [m.name for m in registry.iter_routable()]
        assert names == []
        # But still findable by name
        assert registry.has("r")


class TestReplyTypeRouting:
    def test_module_reply_is_wildcard(self, isolated_registry):
        """Two modules can both declare 'module_reply' — it doesn't claim ownership."""
        registry.register_module(_make_module("a", reply_types=("module_reply",)))
        registry.register_module(_make_module("b", reply_types=("module_reply",)))
        # No exception; both registered
        assert registry.has("a") and registry.has("b")
        # 'module_reply' routes via body['module'], not the type map
        assert registry.find_by_reply_type("module_reply") is None

    def test_specific_reply_type_claimed(self, isolated_registry):
        registry.register_module(_make_module("c", reply_types=("module_reply", "edit")))
        assert registry.find_by_reply_type("edit").name == "c"

    def test_specific_reply_type_collision_rejected(self, isolated_registry):
        registry.register_module(_make_module("c1", reply_types=("edit",)))
        with pytest.raises(ValueError, match="already owned"):
            registry.register_module(_make_module("c2", reply_types=("edit",)))

    def test_routes_reply(self, isolated_registry):
        registry.register_module(_make_module("c", reply_types=("module_reply", "edit")))
        assert registry.routes_reply("edit") is True
        assert registry.routes_reply("module_reply") is True
        assert registry.routes_reply("unknown") is False
        assert registry.routes_reply(None) is False
        assert registry.routes_reply("") is False


class TestToolSchema:
    def test_schema_uses_args_model(self, isolated_registry):
        cls = _make_module("schema_test")
        registry.register_module(cls)
        sch = cls.tool_schema()
        assert sch["type"] == "function"
        assert sch["function"]["name"] == "ask_schema_test"
        assert "foo" in sch["function"]["parameters"]["properties"]


class TestWhitelist:
    def test_only_general_writing_enabled(self):
        # The whitelist is module-level state, not affected by isolated_registry.
        assert registry.is_pipeline_enabled("general_writing") is True
        for other in ("planning", "mindsearch", "article_editing", "policy"):
            assert registry.is_pipeline_enabled(other) is False
