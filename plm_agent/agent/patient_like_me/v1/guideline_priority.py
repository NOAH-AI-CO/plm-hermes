"""
Guideline priority configuration.

User picks ONE primary publisher among NCCN / CSCO / ESMO / CACA.
That publisher's guidelines become the primary source; the others are
returned as supplements when available.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_ORG_PRIORITY = ["NCCN", "CSCO", "ESMO", "CACA"]


@dataclass
class GuidelinePriorityConfig:
    order: list[str] = field(default_factory=lambda: list(DEFAULT_ORG_PRIORITY))


def resolve_priority(config: GuidelinePriorityConfig | None) -> list[str]:
    if config is None or not config.order:
        return list(DEFAULT_ORG_PRIORITY)
    # 用户选的协会放第一位，DEFAULT_ORG_PRIORITY 里其他协会按原顺序补在后面
    primary = config.order[0]
    rest = [org for org in DEFAULT_ORG_PRIORITY if org != primary]
    return [primary] + rest


def rank_organizations(
    org_results: dict[str, any],
    priority: list[str],
    strict_primary: bool = False,
) -> tuple[str | None, str, dict[str, any]]:
    """Pick primary org and return (primary_org, primary_status, secondaries).

    primary_status:
      - 'matched'              用户指定的最高优先级 org 本次有结果
      - 'user_specified_empty' 用户指定 strict_primary=True 但其最高优先级 org 没召回到内容
      - 'auto'                 用户未指定优先级，系统按默认顺序挑了 primary
    """
    user_top = priority[0] if priority else None

    if strict_primary and user_top:
        if user_top in org_results:
            secondaries = {k: v for k, v in org_results.items() if k != user_top}
            return user_top, "matched", secondaries
        # 严格模式：用户指定 org 没结果 → 主指南为空，其他全部归次要
        return user_top, "user_specified_empty", dict(org_results)

    # 非严格：按 priority 顺序挑第一个有结果的；priority 为空走原 fallback。
    # OTHER 组只作补充指南, 不允许提为主指南 — 若 org_results 只剩 OTHER, 返回空 primary.
    primary_org = next((org for org in priority if org in org_results), None)
    if primary_org is None:
        # 从 org_results 里挑第一个非 OTHER 的组; 全是 OTHER 就返 None primary
        primary_org = next((org for org in org_results if org != "OTHER"), None)
    secondaries = {k: v for k, v in org_results.items() if k != primary_org}
    return primary_org, "auto", secondaries
