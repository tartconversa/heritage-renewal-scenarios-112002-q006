"""评估编排：把加载、可行性、可达性、容量、评分与快照组装成决策资料。

输出的 AssessmentResult 是后续报告层的唯一数据来源，保证“同一套可比资料”
对应同一份输入快照。编排层不做价值取舍，只负责：
1. 单方案逐项评估（硬约束裁决 → 收益构成 → 运营状态）；
2. 枚举组合方案并对共享街巷改善、容量承诺去重；
3. 产出分群体矩阵、服务错配对照与需求追溯链；
4. 在权重可用时才生成加权分，否则显式声明不可用。
"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations

from . import access as access_mod
from . import capacity as capacity_mod
from . import feasibility as feasibility_mod
from . import scoring as scoring_mod
from .models import (
    AccessBenefit,
    AssessmentResult,
    CombinationAssessment,
    Dataset,
    DemandTrace,
    ProposalAssessment,
    Snapshot,
    WeightedScore,
)
from .scoring import WeightTable

# 组合枚举的默认上限：方案数较大时避免组合爆炸；截断会在结果中显式标注。
DEFAULT_MAX_MEMBERS = 3


def _assess_proposal(
    dataset: Dataset,
    weight_table: WeightTable | None,
    known_groups: tuple[str, ...],
) -> list[ProposalAssessment]:
    assessments: list[ProposalAssessment] = []
    for proposal in dataset.proposals:
        building = dataset.buildings_by_id.get(proposal.building_id)
        verdict = feasibility_mod.check_proposal(proposal, dataset)
        links = dataset.links_by_proposal.get(proposal.proposal_id, ())
        benefits = access_mod.proposal_access(links)
        cap_lines = capacity_mod.capacity_lines_for(proposal, dataset)
        affected = tuple(sorted({b.group_code for b in benefits if b.group_code}))

        notes: list[str] = []
        notes.extend(verdict.reasons)
        notes.extend(b.note for b in benefits if b.note)
        notes.extend(line.note for line in cap_lines)
        if proposal.estimate_low is None or proposal.estimate_high is None:
            notes.append("成本区间不完整，汇总时未知一侧不得按零处理")

        score: WeightedScore | None = None
        if verdict.verdict.value == "feasible":
            score = scoring_mod.score_access(benefits, weight_table, known_groups)

        assessments.append(
            ProposalAssessment(
                proposal=proposal,
                building=building,
                feasibility=verdict,
                access=benefits,
                capacity_lines=cap_lines,
                affected_groups=affected,
                notes=tuple(notes),
                score=score,
            )
        )
    return assessments


def _cost_sum(
    member_ids: tuple[str, ...], dataset: Dataset
) -> tuple[int | None, int | None, bool]:
    """成本区间相加：任一侧缺失则该侧未知；complete 表示两侧全部已知。"""
    lows: list[int] = []
    highs: list[int] = []
    complete = True
    for pid in member_ids:
        proposal = dataset.proposals_by_id[pid]
        if proposal.estimate_low is None or proposal.estimate_high is None:
            complete = False
        if proposal.estimate_low is not None:
            lows.append(proposal.estimate_low)
        if proposal.estimate_high is not None:
            highs.append(proposal.estimate_high)
    return (
        sum(lows) if lows else None,
        sum(highs) if highs else None,
        complete,
    )


def _assess_combinations(
    dataset: Dataset,
    weight_table: WeightTable | None,
    known_groups: tuple[str, ...],
    max_members: int,
) -> tuple[tuple[CombinationAssessment, ...], bool]:
    ids = tuple(p.proposal_id for p in dataset.proposals)
    limit = min(max_members, len(ids))
    combos: list[CombinationAssessment] = []
    truncated = False

    for size in range(2, limit + 1):
        for member_ids in combinations(ids, size):
            check = feasibility_mod.check_combination(member_ids, dataset)
            links = tuple(
                link
                for pid in member_ids
                for link in dataset.links_by_proposal.get(pid, ())
            )
            benefits, shared = access_mod.merge_access(links)
            raw_capacity = tuple(
                line
                for pid in member_ids
                for line in capacity_mod.capacity_lines_for(
                    dataset.proposals_by_id[pid], dataset
                )
            )
            cap_lines = capacity_mod.merge_capacity(raw_capacity)
            cost_low, cost_high, cost_complete = _cost_sum(member_ids, dataset)
            groups_covered = tuple(
                sorted({b.group_code for b in benefits if b.group_code})
            )

            notes: list[str] = []
            if shared:
                notes.append(
                    f"{len(shared)} 项（服务×群体）改善由多个成员共同贡献，"
                    "已按最优耗时去重，未重复计分"
                )
            if not cost_complete:
                notes.append("部分成员成本区间缺失，合计区间仅覆盖已知部分")
            if not benefits:
                notes.append("组合中没有任何可达改善记录")

            score: WeightedScore | None = None
            if check.verdict.value == "feasible":
                score = scoring_mod.score_access(
                    benefits, weight_table, known_groups
                )

            combos.append(
                CombinationAssessment(
                    member_ids=member_ids,
                    feasible=check.verdict.value == "feasible",
                    infeasible_reasons=check.reasons,
                    cost_low=cost_low,
                    cost_high=cost_high,
                    cost_complete=cost_complete,
                    access=benefits,
                    capacity_lines=cap_lines,
                    groups_covered=groups_covered,
                    shared_links=shared,
                    notes=tuple(notes),
                    score=score,
                )
            )

    # 组合总数超过实际枚举范围时显式截断提示
    if max_members < len(ids):
        truncated = True
    return tuple(combos), truncated


def _group_matrix(
    assessments: tuple[ProposalAssessment, ...],
    groups: tuple[str, ...],
) -> dict[str, dict[str, int | None]]:
    """方案 × 群体的节省分钟矩阵；缺失数据保持 None，区分“无改善”与“未知”。"""
    matrix: dict[str, dict[str, int | None]] = {}
    for assessment in assessments:
        row: dict[str, int | None] = {group: 0 for group in groups}
        for benefit in assessment.access:
            if benefit.group_code in row:
                row[benefit.group_code] = benefit.saving
        matrix[assessment.proposal.proposal_id] = row
    return matrix


def _demand_traces(
    dataset: Dataset,
    all_access: tuple[AccessBenefit, ...],
) -> tuple[DemandTrace, ...]:
    """为每条（群体 × 服务）需求建立可追溯链。

    链条覆盖：哪些方案影响该需求、施工前后耗时与最优方案、对应工程成本、
    目标建筑的保护等级与许可边界、相关运营容量状态。任一环节缺失都保留
    显式备注，使决策者能追查需求如何影响设施规模、保护边界和运营成本。
    """
    keys = sorted({(b.group_code, b.service_id) for b in all_access})
    traces: list[DemandTrace] = []
    for group_code, service_id in keys:
        entries = [
            b
            for b in all_access
            if b.group_code == group_code and b.service_id == service_id
        ]
        proposal_ids = tuple(
            sorted({pid for b in entries for pid in b.sources})
        )
        baselines = [b.minutes_before for b in entries if b.minutes_before is not None]
        afters = [
            (b.minutes_after, b.sources[0] if b.sources else "")
            for b in entries
            if b.minutes_after is not None
        ]
        baseline = max(baselines) if baselines else None
        best_after = min((a for a, _ in afters), default=None)
        best_proposal = next(
            (pid for a, pid in afters if a == best_after), None
        )
        saving = (
            baseline - best_after
            if baseline is not None and best_after is not None
            else None
        )

        cost_ranges: list[tuple[str, int | None, int | None]] = []
        boundaries: list[tuple[str, str, tuple[str, ...]]] = []
        cap_lines = []
        notes: list[str] = []
        for pid in proposal_ids:
            proposal = dataset.proposals_by_id.get(pid)
            if proposal is None:
                continue
            cost_ranges.append(
                (pid, proposal.estimate_low, proposal.estimate_high)
            )
            building = dataset.buildings_by_id.get(proposal.building_id)
            if building is not None:
                boundaries.append(
                    (
                        building.building_id,
                        building.protection_level,
                        building.permitted_work,
                    )
                )
            for line in capacity_mod.capacity_lines_for(proposal, dataset):
                # 追溯链只保留与本需求服务直接相关的容量行：
                # 服务匹配的承诺，或无运营方/无承诺这类运营缺口行；
                # 同一运营方名下的其他服务容量不得计入本需求。
                if line.service_id == service_id or line.service_id is None:
                    cap_lines.append(line)
        cap_lines = capacity_mod.merge_capacity(tuple(cap_lines))

        # 运营表中任何责任方对该服务的全局承诺也纳入追溯（即使方案未指定）
        for row in dataset.operations:
            if row.service_id != service_id:
                continue
            if any(line.operator_id == row.operator_id for line in cap_lines):
                continue
            cap_lines = cap_lines + (
                capacity_mod.CapacityLine(
                    state=(
                        capacity_mod.CapacityState.STABLE
                        if row.confirmed_start is not None
                        and row.capacity_per_day is not None
                        else capacity_mod.CapacityState.UNCONFIRMED
                    ),
                    operator_id=row.operator_id,
                    service_id=row.service_id,
                    capacity_per_day=row.capacity_per_day,
                    confirmed_start=row.confirmed_start,
                    note="运营表中存在该服务的承诺，但与本方案指定运营方不一致",
                ),
            )

        if all(c.state.value != "stable" for c in cap_lines):
            notes.append(
                f"服务 {service_id} 没有可计入的稳定运营容量，"
                "可达改善无法等同于可持续服务收益"
            )
        if saving is None:
            notes.append("耗时数据缺失，节省量未知")

        traces.append(
            DemandTrace(
                group_code=group_code,
                service_id=service_id,
                proposal_ids=proposal_ids,
                baseline_minutes=baseline,
                best_after_minutes=best_after,
                best_proposal_id=best_proposal,
                saving=saving,
                capacity_lines=tuple(cap_lines),
                cost_ranges=tuple(cost_ranges),
                protection_boundaries=tuple(boundaries),
                notes=tuple(notes),
            )
        )
    return tuple(traces)


def assess_dataset(
    dataset: Dataset,
    snapshot: Snapshot,
    weight_table: WeightTable | None = None,
    max_members: int = DEFAULT_MAX_MEMBERS,
) -> AssessmentResult:
    """对已加载数据集执行完整评估，返回绑定快照的结果。"""
    groups = tuple(
        sorted({link.group_code for link in dataset.links if link.group_code})
    )

    proposal_assessments = tuple(
        _assess_proposal(dataset, weight_table, groups)
    )
    combinations, truncated = _assess_combinations(
        dataset, weight_table, groups, max_members
    )
    matrix = _group_matrix(proposal_assessments, groups)

    all_access = tuple(
        benefit
        for assessment in proposal_assessments
        for benefit in assessment.access
    )
    coverage = capacity_mod.service_coverage(dataset, all_access)
    traces = _demand_traces(dataset, all_access)

    overall_score: WeightedScore | None = None
    if weight_table is not None:
        overall_score = scoring_mod.score_access(
            all_access, weight_table, groups
        )

    return AssessmentResult(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        snapshot=snapshot,
        dataset=dataset,
        proposal_assessments=proposal_assessments,
        combinations=combinations,
        groups=groups,
        group_matrix=matrix,
        service_coverage=coverage,
        demand_traces=traces,
        weighted_score=overall_score,
        max_members=max_members,
        combo_truncated=truncated,
    )
