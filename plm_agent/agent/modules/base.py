# -*- coding: utf-8 -*-
"""``InteractiveModule`` — base class for pluggable conversational modules.

Each subclass declares:
- ``name`` / ``content_type`` for identification and v2 protocol routing
- ``args_model`` (a ``pydantic.BaseModel``) — params the router LLM may pass
- ``tool_description`` — natural-language gating shown to the router LLM
- ``reply_types`` — body['type'] values this module consumes (e.g. 'edit')
- ``routable`` — whether the router LLM may pick this module

State is keyed by ``thread_id`` and persisted via ``_state_store``. The
pipeline drives the lifecycle: router LLM picks a module → ``run(args)``
emits frames and pauses → user replies via ``/chat`` → ``consume_reply``
advances state → ``enrich_prompt`` mutates the body before the downstream
agent runs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, ClassVar, Literal, Optional

from pydantic import BaseModel

from tools.sandbox.sandbox_manager import SandboxManager

from agent.modules import _state_store


class InteractiveModule(ABC):
    """Base class for pluggable modules. See module docstring for the lifecycle."""

    name: ClassVar[str] = ""
    content_type: ClassVar[str] = ""
    stage: ClassVar[Literal["preflight", "inflight"]] = "preflight"
    max_rounds: ClassVar[int] = 3

    # Router-LLM integration
    args_model: ClassVar[Optional[type[BaseModel]]] = None
    tool_description: ClassVar[str] = ""
    routable: ClassVar[bool] = True

    # Reply routing — body['type'] values this module owns. ``module_reply`` is a
    # wildcard handled by ``body['module']`` lookup; specific types like
    # ``edit`` are claimed exclusively (registry rejects collisions).
    reply_types: ClassVar[tuple[str, ...]] = ()

    # ------------------------------------------------------------------
    # Tool schema — auto-generated from args_model
    # ------------------------------------------------------------------

    @classmethod
    def tool_schema(cls) -> Optional[dict]:
        """OpenAI function schema for the router LLM. None if not routable."""
        if not cls.routable or cls.args_model is None:
            return None
        return {
            "type": "function",
            "function": {
                "name": f"ask_{cls.name}",
                "description": cls.tool_description,
                "parameters": cls.args_model.model_json_schema(),
            },
        }

    # ------------------------------------------------------------------
    # Lifecycle hooks — subclasses MUST implement.
    # ------------------------------------------------------------------

    @abstractmethod
    def run(self, body: dict, state: dict, args: BaseModel) -> AsyncIterator[dict]:
        """Yield event_v2 frames; mutate ``state`` to record what was asked.

        ``args`` is an instance of ``cls.args_model``, validated by the router
        before this method is called. When pausing for user input, set
        ``state['awaiting_user'] = True`` before the generator returns.
        """

    @abstractmethod
    def consume_reply(self, body: dict, state: dict) -> AsyncIterator[dict]:
        """Process a reply (``module_reply`` or a module-specific type like
        ``edit``). May yield more frames. Set ``state['done'] = True`` when
        the module is finished so the pipeline runs the downstream agent.
        """

    # ------------------------------------------------------------------
    # Defaults — most modules can leave these alone.
    # ------------------------------------------------------------------

    def is_paused(self, state: dict) -> bool:
        return bool(state.get("awaiting_user"))

    def is_done(self, state: dict) -> bool:
        return bool(state.get("done"))

    def enrich_prompt(self, body: dict, state: dict) -> dict:
        """Default: pass body through unchanged. Override to mutate ``user_prompt``."""
        return body

    # ------------------------------------------------------------------
    # State storage — subclasses generally don't override these.
    # The pipeline calls these via thread-level helpers in _state_store,
    # but instance-level wrappers are kept for ergonomic single-module
    # access from tests and ad-hoc paths.
    # ------------------------------------------------------------------

    async def load_state(
        self,
        thread_id: str,
        sandbox: Optional[SandboxManager] = None,
    ) -> dict:
        return await _state_store.load_state(thread_id, self.name, sandbox=sandbox)

    async def save_state(
        self,
        thread_id: str,
        state: dict,
        sandbox: Optional[SandboxManager] = None,
    ) -> None:
        await _state_store.save_state(thread_id, self.name, state, sandbox=sandbox)

    def drop_state(self, thread_id: str) -> None:
        _state_store.drop_state(thread_id, self.name)
