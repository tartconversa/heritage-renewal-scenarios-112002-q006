"""街巷与设施可达性分析。

关键规则：
- 街巷通行改善可能同时服务多个片区，因此可达记录按 (service_id, group_code)
  合并；组合方案中同键只计一次，取改善后最小耗时，避免重复计分。
- 基准（施工前）耗时取该键下所有记录的最大值：它代表组合实施前居民
  实际面对的最差通行条件，改善后取最优值，节省量据此计算。
- 任一侧耗时缺失时 saving 保持 None（未知），绝不按 0 呈现。
- 施工后耗时高于施工前属于“通行恶化”，保留记录并显式告警，不静默翻转。
"""
from __future__ import annotations

from .models import AccessBenefit, AccessLink, ValidationIssue, IssueLevel


def _saving(before: int | None, after: int | None) -> int | None:
    if before is None or after is None:
        return None
    return before - after


def proposal_access(links: tuple[AccessLink, ...]) -> tuple[AccessBenefit, ...]:
    """单方案的可达收益（同键合并，保留来源与告警）。"""
    return _merge_links(links)


def merge_access(
    links: tuple[AccessLink, ...],
) -> tuple[tuple[AccessBenefit, ...], tuple[tuple[str, str, tuple[str, ...]], ...]]:
    """组合方案的可达合并。

    返回 (合并后的收益, 共享记录)。共享记录列出被多个方案同时改善的
    (service_id, group_code) 及其来源方案，用于解释去重与片区外溢。
    """
    benefits = _merge_links(links)
    shared = tuple(
        (b.service_id, b.group_code, b.sources)
        for b in benefits
        if len(b.sources) > 1
    )
    return benefits, shared


def _merge_links(links: tuple[AccessLink, ...]) -> tuple[AccessBenefit, ...]:
    grouped: dict[tuple[str, str], list[AccessLink]] = {}
    for link in links:
        grouped.setdefault((link.service_id, link.group_code), []).append(link)

    benefits: list[AccessBenefit] = []
    for (service_id, group_code), rows in sorted(grouped.items()):
        before_values = [r.minutes_before for r in rows if r.minutes_before is not None]
        after_values = [r.minutes_after for r in rows if r.minutes_after is not None]
        baseline = max(before_values) if before_values else None
        best_after = min(after_values) if after_values else None
        sources = tuple(sorted({r.proposal_id for r in rows}))

        notes: list[str] = []
        for r in rows:
            if (
                r.minutes_before is not None
                and r.minutes_after is not None
                and r.minutes_after > r.minutes_before
            ):
                notes.append(
                    f"方案 {r.proposal_id} 施工后耗时 {r.minutes_after} 分钟高于"
                    f"施工前 {r.minutes_before} 分钟，属于通行恶化"
                )
        if baseline is None or best_after is None:
            notes.append("施工前或施工后耗时缺失，节省量未知，不得按零计入")

        benefits.append(
            AccessBenefit(
                service_id=service_id,
                group_code=group_code,
                minutes_before=baseline,
                minutes_after=best_after,
                saving=_saving(baseline, best_after),
                sources=sources,
                note="；".join(notes),
            )
        )
    return tuple(benefits)


def worsening_issues(benefits: tuple[AccessBenefit, ...]) -> tuple[ValidationIssue, ...]:
    """把通行恶化备注提升为 warning 级校验问题。"""
    issues: list[ValidationIssue] = []
    for benefit in benefits:
        if "通行恶化" in benefit.note:
            issues.append(
                ValidationIssue(
                    IssueLevel.WARNING,
                    "access_worsening",
                    benefit.note,
                    f"{benefit.service_id}/{benefit.group_code}",
                )
            )
    return tuple(issues)


def total_saving(benefits: tuple[AccessBenefit, ...]) -> int | None:
    """总节省分钟数；任一组成缺失时返回 None 并交由展示层标注未知。"""
    if not benefits:
        return 0
    savings = [b.saving for b in benefits]
    if any(s is None for s in savings):
        return None
    return sum(s for s in savings if s is not None)
