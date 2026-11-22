"""保护可行性裁决（硬约束，一票否决）。

规则：
- 方案声明的工程类型必须落在目标建筑的 permitted_work 集合内。
- 建筑不存在或许可范围为空时，方案不可行（无许可依据不得开工）。
- 不可行是硬底线：不可行方案不参与任何加权评分与排序，其保护约束
  不允许被可达性、受益人数等高分指标“折算抵消”。
"""
from __future__ import annotations

from .models import (
    Dataset,
    FeasibilityCheck,
    Proposal,
    Verdict,
)


def check_proposal(proposal: Proposal, dataset: Dataset) -> FeasibilityCheck:
    """裁决单个方案是否满足保护底线。"""
    reasons: list[str] = []

    building = dataset.buildings_by_id.get(proposal.building_id)
    if building is None:
        reasons.append(
            f"目标建筑 {proposal.building_id} 不存在，无保护审查依据，工程不可行"
        )
        return FeasibilityCheck(Verdict.INFEASIBLE, tuple(reasons))

    if not building.permitted_work:
        reasons.append(
            f"建筑 {building.building_id} 未声明许可工程范围，"
            f"工程 {proposal.work!r} 无许可依据"
        )
        return FeasibilityCheck(Verdict.INFEASIBLE, tuple(reasons))

    if proposal.work not in building.permitted_work:
        reasons.append(
            f"工程类型 {proposal.work!r} 超出建筑 {building.building_id}"
            f"（保护等级 {building.protection_level}）的许可范围 "
            f"{list(building.permitted_work)}，违反保护底线"
        )

    if not proposal.work:
        reasons.append("方案未声明工程类型，无法进行保护符合性审查")

    if reasons:
        return FeasibilityCheck(Verdict.INFEASIBLE, tuple(reasons))

    return FeasibilityCheck(
        Verdict.FEASIBLE,
        (
            f"工程 {proposal.work!r} 位于建筑 {building.building_id}"
            f"（保护等级 {building.protection_level}）许可范围 "
            f"{list(building.permitted_work)} 内",
        ),
    )


def check_combination(member_ids: tuple[str, ...], dataset: Dataset) -> FeasibilityCheck:
    """组合方案只有在每个成员都满足底线时才可行。"""
    reasons: list[str] = []
    for pid in member_ids:
        proposal = dataset.proposals_by_id.get(pid)
        if proposal is None:
            reasons.append(f"成员方案 {pid} 不存在")
            continue
        member = check_proposal(proposal, dataset)
        if member.verdict is Verdict.INFEASIBLE:
            reasons.extend(f"[{pid}] {reason}" for reason in member.reasons)
    if reasons:
        return FeasibilityCheck(Verdict.INFEASIBLE, tuple(reasons))
    return FeasibilityCheck(Verdict.FEASIBLE, ("全部成员满足保护底线",))
