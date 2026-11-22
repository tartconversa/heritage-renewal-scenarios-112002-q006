"""群体需求权重与加权评分。

价值判断边界（直接对应任务约束）：
- 权重只能来自外部显式输入，分析层绝不自行推断或补造权重。
- 缺少权重文件时，只输出分群体视角，不生成加权总分，避免把分析者的
  隐含偏好包装成“客观共识”。
- 权重未覆盖所有受影响群体时，聚合分不可用：只报覆盖情况与缺失群体。
- 权重不做自动归一化以外的政治判断；归一化仅为数学处理，来源与
  代表性说明随结果原样保留。
- 不可行方案不进入评分（保护底线不可折算）。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .models import (
    AccessBenefit,
    ValidationIssue,
    IssueLevel,
    WeightedScore,
)


@dataclass(frozen=True)
class WeightTable:
    weights: dict[str, float]
    source: str
    representativeness: str
    note: str = ""


def load_weights(path: str | Path) -> WeightTable:
    """读取权重 CSV。

    合同列：group_code, weight, source, representativeness。
    后两者记录权重的来源与代表性说明，必须随评分一起呈现，
    使任何阅读者都能看到这份“共识”的边界。
    """
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"group_code", "weight", "source", "representativeness"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"权重文件 {path.name} 必须包含列: {', '.join(sorted(required))}"
            )
        weights: dict[str, float] = {}
        sources: set[str] = set()
        repr_notes: set[str] = set()
        for row in reader:
            group = (row.get("group_code") or "").strip()
            raw = (row.get("weight") or "").strip()
            if not group or not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                raise ValueError(f"群体 {group} 的权重无法解析为数字: {raw!r}") from None
            if value < 0:
                raise ValueError(f"群体 {group} 的权重为负: {value}")
            weights[group] = value
            sources.add((row.get("source") or "").strip() or "未注明来源")
            repr_notes.add(
                (row.get("representativeness") or "").strip() or "未注明代表性"
            )

    if not weights:
        raise ValueError(f"权重文件 {path.name} 不包含任何有效权重")
    if sum(weights.values()) <= 0:
        raise ValueError("权重之和必须大于 0")

    return WeightTable(
        weights=weights,
        source="；".join(sorted(sources)),
        representativeness="；".join(sorted(repr_notes)),
    )


def validate_weights(table: WeightTable, known_groups: tuple[str, ...]) -> tuple[ValidationIssue, ...]:
    """权重引用了不存在的群体时给出 warning（不阻断，但需暴露）。"""
    issues: list[ValidationIssue] = []
    unknown = sorted(set(table.weights) - set(known_groups))
    if unknown:
        issues.append(
            ValidationIssue(
                IssueLevel.WARNING,
                "unknown_weight_group",
                f"权重文件引用了数据中不存在的群体: {', '.join(unknown)}",
            )
        )
    return tuple(issues)


def score_access(
    benefits: tuple[AccessBenefit, ...],
    table: WeightTable | None,
    all_groups: tuple[str, ...],
) -> WeightedScore:
    """按群体汇总可达节省分钟，再按外生权重聚合。

    - table 为 None → available=False，不产出聚合分。
    - 任一受影响群体缺少权重 → available=False。
    - 某 (服务×群体) 节省量未知 → 该群体得分未知，聚合不可用。
    """
    if table is None:
        return WeightedScore(
            available=False,
            aggregate=None,
            weights={},
            covered_groups=(),
            missing_groups=tuple(all_groups),
            note="未提供群体权重文件：仅呈现分群体视角，不生成加权总分，"
                 "不得将任何单一排序解读为客观共识",
        )

    per_group: dict[str, int | None] = {}
    for benefit in benefits:
        current = per_group.get(benefit.group_code, 0)
        if benefit.saving is None or current is None:
            per_group[benefit.group_code] = None
        else:
            per_group[benefit.group_code] = current + benefit.saving

    affected = tuple(sorted(per_group))
    if not affected:
        return WeightedScore(
            available=False,
            aggregate=None,
            weights=dict(table.weights),
            covered_groups=(),
            missing_groups=(),
            note="该方案没有任何可达改善记录，加权分无计算对象",
        )
    missing = tuple(g for g in affected if g not in table.weights)
    if missing:
        return WeightedScore(
            available=False,
            aggregate=None,
            weights=dict(table.weights),
            covered_groups=tuple(g for g in affected if g in table.weights),
            missing_groups=missing,
            note=(
                "权重未覆盖全部受影响群体 "
                f"{list(missing)}，加权总分不可用；分群体结果仍可比较，"
                "补全代表性权重前不得宣称总体最优"
            ),
        )

    if any(value is None for value in per_group.values()):
        unknown_groups = tuple(sorted(g for g, v in per_group.items() if v is None))
        return WeightedScore(
            available=False,
            aggregate=None,
            weights=dict(table.weights),
            covered_groups=affected,
            missing_groups=(),
            note=f"群体 {list(unknown_groups)} 的可达节省量存在缺失数据，聚合分不可用",
        )

    total_weight = sum(table.weights[g] for g in affected)
    aggregate = sum(
        per_group[g] * table.weights[g] for g in affected  # type: ignore[operator]
    ) / total_weight
    return WeightedScore(
        available=True,
        aggregate=round(aggregate, 3),
        weights={g: table.weights[g] for g in affected},
        covered_groups=affected,
        missing_groups=(),
        note=(
            f"加权结果基于外生权重（来源：{table.source}；代表性："
            f"{table.representativeness}），属价值判断而非客观共识；"
            "保护底线为一票否决，不参与加权"
        ),
    )
