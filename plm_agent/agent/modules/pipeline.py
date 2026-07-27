# -*- coding: utf-8 -*-
"""``ModulePipeline`` — dispatcher for whitelisted agents (general_writing only).

Two execution paths, both yielding event_v2 envelope dicts:

* ``run(body)`` — fresh ``/chat`` POST. Loads all module states, asks the
  router LLM whether any module should fire (single function-calling
  decision over all routable tools). On a tool_call: invoke that
  module's ``run(args)`` → yield frames → pause; otherwise dispatch the
  downstream agent.

* ``handle_reply(body)`` — replies (``module_reply`` or any module-claimed
  ``type`` like ``edit``). Routes to the owning module's
  ``consume_reply``, persists state, and either pauses (next round) or
  enriches the body and dispatches the downstream agent.

``dispatch(body)`` is the single entrypoint ``main.py`` calls, which
picks ``run`` or ``handle_reply`` based on ``body['type']``.

The whitelist (``MODULE_PIPELINE_AGENTS = {'general_writing'}``) is
enforced in ``main.py`` before this module is touched, so nothing here
ever runs for planning / mindsearch / other agents.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional

from tools.sandbox.sandbox_manager import SandboxManager

from agent.modules import _state_store, registry, router as router_llm

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _get_thread_id(body: dict) -> str:
    return (
        body.get("thread_id")
        or (body.get("planning_task") or {}).get("thread_id")
        or ""
    )


def _build_sandbox(
    thread_id: str,
    *,
    workspace_paths=None,
) -> Optional[SandboxManager]:
    """Best-effort sandbox manager for state persistence.

    No thread_id and no workspace_paths → ``None`` (cache-only mode).
    When ``workspace_paths`` is supplied (writing's v2 path), the sandbox uses
    the new ``{env}/users/{uid}/sessions/{tid}`` layout. Otherwise legacy
    ``sessions/{tid}`` layout — byte-identical to pre-v2 behavior.
    """
    if workspace_paths is not None:
        return SandboxManager(workspace_paths=workspace_paths)
    if not thread_id:
        return None
    return SandboxManager(session_id=thread_id)


def _build_sandbox_from_body(body: dict) -> Optional[SandboxManager]:
    """Pick the right sandbox mode from a chat-request body.

    If the body carries ``env`` + ``user_id`` (writing v2 contract), validate
    them via ``WorkspacePaths`` and return a v2 sandbox. Otherwise fall back
    to the legacy ``session_id``-only path.
    """
    thread_id = _get_thread_id(body)
    env = body.get("env")
    user_id = body.get("user_id")
    if env and user_id and thread_id:
        try:
            from agent.runtime.paths import WorkspacePaths
            paths = WorkspacePaths(env=env, user_id=str(user_id), session_id=thread_id)
            return _build_sandbox(thread_id, workspace_paths=paths)
        except ValueError as e:
            logger.warning(
                "[ModulePipeline] invalid env/user_id in body (%s); "
                "falling back to legacy sandbox path", e,
            )
    return _build_sandbox(thread_id)


async def _run_downstream_agent(body: dict) -> AsyncIterator[dict]:
    """Resolve the agent from ``agent_routing`` and stream its events."""
    # Lazy import to avoid pulling the whole router graph at module load time.
    from agent.router import agent_routing

    agent_name = body.get("agent")
    agent_cls = agent_routing[agent_name]
    agent = agent_cls(**body)
    async for frame in agent.start(**body):
        yield frame


def _strip_reply_markers(body: dict) -> dict:
    """Remove reply-only fields before handing off to a downstream agent."""
    new = dict(body)
    for k in ("type", "module", "approve", "feedback", "skip", "event_id"):
        new.pop(k, None)
    return new


# ----------------------------------------------------------------------
# Single entrypoint
# ----------------------------------------------------------------------


async def dispatch(body: dict) -> AsyncIterator[dict]:
    """Decide between ``run`` (router LLM) and ``handle_reply`` (reply path)."""
    rt = body.get("type")
    if registry.routes_reply(rt):
        async for frame in handle_reply(body):
            yield frame
    else:
        async for frame in run(body):
            yield frame


# ----------------------------------------------------------------------
# Run — router-LLM path
# ----------------------------------------------------------------------


async def run(body: dict) -> AsyncIterator[dict]:
    """Pre-flight: ask the router LLM whether any module should fire."""
    thread_id = _get_thread_id(body)
    sandbox = _build_sandbox_from_body(body)

    logger.info(
        "[ModulePipeline] run start agent=%s thread=%s",
        body.get("agent"), thread_id,
    )

    # 1) Load every module's state in a single NAS round-trip.
    states = await _state_store.load_thread_state(thread_id, sandbox=sandbox)

    # 2) Force overrides — bypass router for explicit caller intent.
    forced = await _maybe_force_run(body, states, thread_id, sandbox)
    if forced is not None:
        async for frame in forced:
            yield frame
        return

    # 3) Router LLM decision.
    routable_modules = list(registry.iter_routable())
    try:
        selection = await router_llm.select_tool(body, routable_modules, states)
    except Exception as e:
        logger.warning("[ModulePipeline] router select_tool crashed: %s", e)
        selection = None

    if selection is None:
        logger.info("[ModulePipeline] no module selected → dispatching downstream agent")
        body = _apply_done_enrichments(body, routable_modules, states)
        async for frame in _run_downstream_agent(body):
            yield frame
        return

    # 4) Run the selected module.
    module_name, args = selection
    module = registry.get(module_name)
    state = dict(states.get(module_name) or {})

    paused = False
    try:
        async for frame in module.run(body, state, args):
            yield frame
    except Exception as e:
        logger.exception("[ModulePipeline] module=%s run crashed: %s", module_name, e)
        state["done"] = True
        state["awaiting_user"] = False

    states[module_name] = state
    await _state_store.save_thread_state(thread_id, states, sandbox=sandbox)

    if module.is_paused(state):
        logger.info("[ModulePipeline] paused at module=%s thread=%s",
                    module_name, thread_id)
        paused = True

    if paused:
        return

    # 5) Module finished synchronously → enrich + dispatch downstream.
    body = _apply_done_enrichments(body, routable_modules, states)
    async for frame in _run_downstream_agent(body):
        yield frame


async def _maybe_force_run(
    body: dict,
    states: dict[str, dict],
    thread_id: str,
    sandbox: Optional[SandboxManager],
) -> Optional[AsyncIterator[dict]]:
    """If ``body`` contains ``force_<name>=True``, bypass the router.

    Returns an async iterator that callers should ``async for`` over, or
    ``None`` when no force flag is set / honored.
    """
    for module in registry.iter_routable():
        force_key = f"force_{module.name}"
        if force_key not in body:
            continue
        if not bool(body[force_key]):
            # Explicit False → mark done so router won't re-engage on next call.
            st = dict(states.get(module.name) or {})
            st["done"] = True
            states[module.name] = st
            continue

        # Explicit True → run the module with default args.
        default_args = _force_default_args(module)
        if default_args is None:
            continue

        return _force_run_iter(module, body, states, default_args, thread_id, sandbox)
    return None


def _force_default_args(module):
    """Return a default ``args_model`` instance for ``force_<name>=True``."""
    args_model = module.args_model
    if args_model is None:
        return None
    fallback = getattr(module, "default_args", None)
    if callable(fallback):
        try:
            return fallback()
        except Exception:
            return None
    return None


async def _force_run_iter(module, body, states, default_args,
                          thread_id, sandbox):
    state = dict(states.get(module.name) or {})
    try:
        async for frame in module.run(body, state, default_args):
            yield frame
    except Exception as e:
        logger.exception("[ModulePipeline] forced run failed %s: %s", module.name, e)
        state["done"] = True
        state["awaiting_user"] = False

    states[module.name] = state
    await _state_store.save_thread_state(thread_id, states, sandbox=sandbox)

    if module.is_paused(state):
        return

    enriched = _apply_done_enrichments(body, list(registry.iter_routable()), states)
    async for frame in _run_downstream_agent(enriched):
        yield frame


# ----------------------------------------------------------------------
# Handle reply — module-driven path
# ----------------------------------------------------------------------


async def handle_reply(body: dict) -> AsyncIterator[dict]:
    """Route a reply (``module_reply``/``edit``/...) to the owning module."""
    thread_id = _get_thread_id(body)
    sandbox = _build_sandbox_from_body(body)
    rt = body.get("type")

    module = _resolve_module_from_reply(body)
    if module is None:
        logger.warning("[ModulePipeline] no module owns reply type=%s module=%s",
                       rt, body.get("module"))
        cleaned = _strip_reply_markers(body)
        async for frame in _run_downstream_agent(cleaned):
            yield frame
        return

    states = await _state_store.load_thread_state(thread_id, sandbox=sandbox)
    state = dict(states.get(module.name) or {})

    logger.info(
        "[ModulePipeline] handle_reply module=%s type=%s thread=%s "
        "skip=%s approve=%s",
        module.name, rt, thread_id, body.get("skip"), body.get("approve"),
    )

    try:
        async for frame in module.consume_reply(body, state):
            yield frame
    except Exception as e:
        logger.exception("[ModulePipeline] consume_reply failed %s: %s",
                         module.name, e)
        state["done"] = True
        state["awaiting_user"] = False

    states[module.name] = state
    await _state_store.save_thread_state(thread_id, states, sandbox=sandbox)

    if module.is_paused(state):
        return  # next round pending

    if not module.is_done(state):
        logger.warning("[ModulePipeline] module=%s ended neither done nor paused",
                       module.name)
        return

    # Module finished. Strip reply markers, apply this module's enrichment,
    # then layer enrichments from any other already-done modules, and run
    # the downstream agent. We do NOT re-invoke the router after a reply —
    # the next /chat will naturally re-trigger if more modules are needed.
    cleaned = _strip_reply_markers(body)
    cleaned = module.enrich_prompt(cleaned, state)
    cleaned = _apply_done_enrichments(
        cleaned, list(registry.iter_routable()), states, exclude=module.name,
    )
    async for frame in _run_downstream_agent(cleaned):
        yield frame


def _resolve_module_from_reply(body: dict):
    """Find the module that should consume this reply.

    ``module_reply`` (wildcard) → look up via ``body['module']``.
    Other types → consult the registry's reply_type map.
    """
    rt = body.get("type")

    if rt == "module_reply":
        name = body.get("module")
        return registry.get(name) if name and registry.has(name) else None

    by_type = registry.find_by_reply_type(rt)
    if by_type is not None:
        return by_type

    # Fallback: legacy bodies that used 'module' without a recognized type.
    name = body.get("module")
    return registry.get(name) if name and registry.has(name) else None


def _apply_done_enrichments(
    body: dict,
    modules,
    states: dict[str, dict],
    exclude: Optional[str] = None,
) -> dict:
    """Run ``enrich_prompt`` for every module that's already done."""
    out = body
    for m in modules:
        if exclude and m.name == exclude:
            continue
        st = states.get(m.name) or {}
        if st.get("done"):
            out = m.enrich_prompt(out, st)
    return out


# ----------------------------------------------------------------------
# JSON serializer for FastAPI StreamingResponse
# ----------------------------------------------------------------------


async def stream_json(gen: AsyncIterator[dict]) -> AsyncIterator[str]:
    """Adapt a dict generator into the newline-delimited JSON wire format.

    Mirrors ``standardize_yield`` (used by other agents) so the front-end
    parser sees a uniform stream regardless of whether the chunk came from
    a module or the downstream agent.
    """
    async for item in gen:
        if isinstance(item, (dict, list)):
            yield json.dumps(item, ensure_ascii=False) + "\n"
        elif isinstance(item, str):
            yield item if item.endswith("\n") else item + "\n"
        else:
            yield str(item) + "\n"
