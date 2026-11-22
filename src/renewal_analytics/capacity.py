"""运营责任与服务容量。

不可互换的规则（直接对应任务约束）：
- 新增设施只有在“有运营责任方且容量与启用日期均确认”时，才能按稳定
  服务容量计入收益（CapacityState.STABLE）。
- 有责任方但 confirmed_start 缺失 → UNCONFIRMED，容量仅作未确认展示。
- 方案指定的运营方在运营表中没有该服务承诺 → UNCOMMITTED。
- 方案未指定运营方 → NO_OPERATOR，建成后无人运营，稳定容量按“不可计入”
  处理，而不是按 0 或按满容量处理。
- 容量按 (operator_id, service_id) 去重；负容量/缺失容量在加载层已拦截。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .models import (
    CapacityLine,
    CapacityState,
    Dataset,
    OperationRow,
    Proposal,
    ServiceCoverage,
)

if TYPE_CHECKING:
    from .models import AccessBenefit


def capacity_lines_for(proposal: Proposal, dataset: Dataset) -> tuple[CapacityLine, ...]:
    """推导单个方案名下的运营容量归属（可能为空元组，表示无任何容量信息）。"""
    if proposal.operator_id is None:
        return (
            CapacityLine(
                state=CapacityState.NO_OPERATOR,
                operator_id=None,
                service_id=None,
                capacity_per_day=None,
                confirmed_start=None,
                note=(
                    f"方案 {proposal.proposal_id} 未指定运营责任方，"
                    "即使设施建成也不得按稳定服务容量计入收益"
                ),
            ),
        )

    rows = dataset.operations_by_operator.get(proposal.operator_id, ())
    if not rows:
        return (
            CapacityLine(
                state=CapacityState.UNCOMMITTED,
                operator_id=proposal.operator_id,
                service_id=None,
                capacity_per_day=None,
                confirmed_start=None,
                note=(
                    f"运营方 {proposal.operator_id} 在运营表中无服务承诺，"
                    "方案容量不可计入"
                ),
            ),
        )

    lines: list[CapacityLine] = []
    for row in rows:
        if row.confirmed_start is None:
            state = CapacityState.UNCONFIRMED
            note = (
                f"运营方 {row.operator_id} 的 {row.service_id} 缺少确认启用日期，"
                f"容量 {row.capacity_per_day if row.capacity_per_day is not None else '未知'}"
                " 人/日只能列为未确认容量"
            )
        elif row.capacity_per_day is None:
            state = CapacityState.UNCONFIRMED
            note = (
                f"运营方 {row.operator_id} 的 {row.service_id} 已确认启用日期 "
                f"{row.confirmed_start.isoformat()}，但容量数值缺失，稳定容量未知"
            )
        else:
            state = CapacityState.STABLE
            note = (
                f"运营方 {row.operator_id} 承诺 {row.service_id} 稳定容量 "
                f"{row.capacity_per_day} 人/日，启用日期 "
                f"{row.confirmed_start.isoformat()}"
            )
        lines.append(
            CapacityLine(
                state=state,
                operator_id=row.operator_id,
                service_id=row.service_id,
                capacity_per_day=row.capacity_per_day,
                confirmed_start=row.confirmed_start,
                note=note,
            )
        )
    return tuple(lines)


def merge_capacity(lines: tuple[CapacityLine, ...]) -> tuple[CapacityLine, ...]:
    """组合方案的容量按 (operator_id, service_id) 去重。

    同一运营方对同一服务的承诺只计一次；NO_OPERATOR 等无服务键的行按
    (state, note) 保留，以便暴露每个成员的运营缺口。
    """
    seen: dict[tuple[object, ...], CapacityLine] = {}
    for line in lines:
        if line.service_id is not None:
            key = ("service", line.operator_id, line.service_id)
        else:
            key = ("gap", line.state, line.note)
        if key not in seen:
            seen[key] = line
    return tuple(sorted(seen.values(), key=lambda l: (l.state.value, str(l.service_id))))


def stable_capacity_total(lines: tuple[CapacityLine, ...]) -> int:
    """仅统计 STABLE 行的容量；其他状态不计入稳定容量。"""
    return sum(
        line.capacity_per_day
        for line in lines
        if line.state is CapacityState.STABLE and line.capacity_per_day is not None
    )


def service_coverage(
    dataset: Dataset,
    all_access: tuple["AccessBenefit", ...] = (),
) -> tuple[ServiceCoverage, ...]:
    """按服务汇总可达改善与运营容量，并标注错配。

    错配示例：某服务有可达改善但没有任何运营容量承诺（街巷把人引到设施，
    设施却无法稳定运营）；或运营表存在容量承诺但没有任何方案带来可达改善。
    """
    benefits_by_service: dict[str, list[AccessBenefit]] = {}
    for benefit in all_access:
        benefits_by_service.setdefault(benefit.service_id, []).append(benefit)

    operations_by_service: dict[str, list[OperationRow]] = {}
    for row in dataset.operations:
        operations_by_service.setdefault(row.service_id, []).append(row)

    service_ids = sorted(set(benefits_by_service) | set(operations_by_service))
    coverage: list[ServiceCoverage] = []
    for service_id in service_ids:
        entries = tuple(benefits_by_service.get(service_id, ()))
        rows = operations_by_service.get(service_id, [])
        cap_lines = tuple(
            CapacityLine(
                state=(
                    CapacityState.STABLE
                    if r.confirmed_start is not None and r.capacity_per_day is not None
                    else CapacityState.UNCONFIRMED
                ),
                operator_id=r.operator_id,
                service_id=r.service_id,
                capacity_per_day=r.capacity_per_day,
                confirmed_start=r.confirmed_start,
                note=(
                    "已确认稳定容量"
                    if r.confirmed_start is not None and r.capacity_per_day is not None
                    else "启用日期或容量缺失，未确认"
                ),
            )
            for r in rows
        )
        notes: list[str] = []
        if entries and not rows:
            notes.append(
                f"服务 {service_id} 有街巷可达改善，但运营表中没有任何容量承诺，"
                "改善后可能无稳定服务可及"
            )
        if rows and not entries:
            notes.append(
                f"服务 {service_id} 有运营容量承诺，但没有任何方案改善其可达性"
            )
        coverage.append(
            ServiceCoverage(
                service_id=service_id,
                access_entries=entries,
                capacity_lines=cap_lines,
                mismatch_notes=tuple(notes),
            )
        )
    return tuple(coverage)
