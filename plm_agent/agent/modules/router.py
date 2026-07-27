# -*- coding: utf-8 -*-
"""Router LLM — single function-calling decision over all routable modules.

Replaces the per-module ``should_engage`` LLM calls with one Deepseek call
that sees all available tools at once. The router is intentionally
stateless: state summaries are passed in by ``pipeline.run`` so the same
function can be unit-tested with mocked ``DeepseekChat``.

Failure modes (LLM down, malformed args, unknown tool) all return ``None``,
which the pipeline treats as "no module wants to run" — fail-soft, never
block the user.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Sequence, Tuple

from pydantic import BaseModel, ValidationError

from agent.modules.base import InteractiveModule

logger = logging.getLogger(__name__)


ROUTER_SYS_PROMPT_TEMPLATE = """\
你是写作流程的路由器。下面有若干个工具，每个对应一个交互模块。

调用原则——非常严格：
- 仅在用户请求"真的"缺关键信息（澄清）或"真的"需要先确认改写方向（确认）时才调用工具
- 描述足够具体、能直接动笔的请求**不要调用任何工具**，直接返回空
- 一次最多调用 1 个工具
- 工具描述里 "仅在 ... 时调用" 的硬约束必须严格遵守
- 已完成步骤（见下）不要重复触发

已完成步骤：
{state_summary}

记住：你的输出必须是工具调用或空。绝不要返回普通文本回复。
"""


def _summarize_states(modules: Sequence[InteractiveModule],
                      states: dict[str, dict]) -> str:
    if not modules:
        return "(无)"
    lines = []
    for m in modules:
        st = states.get(m.name) or {}
        if st.get("done"):
            lines.append(f"- {m.name}: 已完成（不要重复）")
        elif st.get("awaiting_user"):
            lines.append(f"- {m.name}: 等待用户回复中（不要重复）")
        else:
            lines.append(f"- {m.name}: 尚未触发")
    return "\n".join(lines)


async def select_tool(
    body: dict,
    modules: Sequence[InteractiveModule],
    states: dict[str, dict],
) -> Optional[Tuple[str, BaseModel]]:
    """Ask the router LLM whether to call any module's tool.

    Returns ``(module_name, args_instance)`` on a tool call, or ``None`` for
    "do nothing". ``args_instance`` is already validated against the
    module's ``args_model``.
    """
    candidates = [m for m in modules if m.tool_schema() is not None]
    if not candidates:
        return None

    # Skip modules already done or awaiting_user — they shouldn't appear in
    # the tool list, otherwise the LLM may "re-confirm" something settled.
    available: list[InteractiveModule] = []
    for m in candidates:
        st = states.get(m.name) or {}
        if st.get("done") or st.get("awaiting_user"):
            continue
        available.append(m)
    if not available:
        return None

    schemas = [m.tool_schema() for m in available]
    user_query = (body.get("user_prompt") or "").strip()
    if not user_query:
        return None

    sys_prompt = ROUTER_SYS_PROMPT_TEMPLATE.format(
        state_summary=_summarize_states(candidates, states),
    )

    try:
        # Deferred import — pulling DeepseekChat at module load time triggers
        # llm.gcp_models, which calls auth.default() and breaks tests without
        # GCP credentials.
        from llm.deepseek_models import DeepseekChat

        msg = await DeepseekChat()(
            sys_prompt=sys_prompt,
            user_prompt=user_query,
            tools=schemas,
            tool_choice="auto",
            temperature=0.1,
        )
    except Exception as e:
        logger.warning("[Router] LLM call failed; falling through: %s", e)
        return None

    calls = getattr(msg, "tool_calls", None) or []
    if not calls:
        logger.info("[Router] LLM chose no tool — passing through")
        return None

    call = calls[0]
    fn = getattr(call, "function", None)
    if fn is None:
        return None
    fn_name = getattr(fn, "name", "") or ""
    raw_args = getattr(fn, "arguments", "") or "{}"

    try:
        args_dict = json.loads(raw_args)
    except json.JSONDecodeError as e:
        logger.warning("[Router] non-JSON tool args %s: %s", raw_args[:200], e)
        return None

    # Match function name back to a module, then validate args.
    for m in available:
        sch = m.tool_schema()
        if not sch:
            continue
        if sch["function"]["name"] != fn_name:
            continue
        try:
            args = m.args_model(**args_dict)
        except ValidationError as e:
            logger.warning("[Router] args validation failed for %s: %s", m.name, e)
            return None
        logger.info("[Router] selected tool=%s args_keys=%s", m.name, list(args_dict.keys()))
        return m.name, args

    logger.warning("[Router] tool name %r matches no available module", fn_name)
    return None
