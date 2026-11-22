"""领域模型与枚举。

本模块只定义不可变数据记录，不含解析与计算逻辑。所有跨模块共享的数据结构
集中在此，避免分析层各模块之间出现循环依赖。

数据约定（与 docs/input-contract.md 一致）：
- 空单元格表示“未知/未提供”，一律解析为 None，绝不当作数值 0。
- 分号分隔字段（如 permitted_work）解析为元组。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import date


# ---------------------------------------------------------------- 枚举


class IssueLevel(str, enum.Enum):
    """输入校验问题的严重级别。"""

    ERROR = "error"      # 阻断评估：数据不满足合同或存在引用完整性问题
    WARNING = "warning"  # 不阻断：结论可用，但决策者必须知晓的数据瑕疵


class Verdict(str, enum.Enum):
    """方案可行性裁决。"""

    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"


class CapacityState(str, enum.Enum):
    """服务容量的可计入状态。

    只有 STABLE 可以按稳定服务容量计入收益；其余状态必须在报告中显式标注，
    不能静默归零，也不能按稳定容量呈现。
    """

    STABLE = "stable"               # 有运营责任方，且 confirmed_start 已确认
    UNCONFIRMED = "unconfirmed"     # 有责任方，但 confirmed_start 缺失
    UNCOMMITTED = "uncommitted"     # 指定了运营方，但运营表中无该方服务承诺
    NO_OPERATOR = "no_operator"     # 方案未指定运营责任方


# ---------------------------------------------------------------- 原始输入记录


@dataclass(frozen=True)
class Building:
    building_id: str
    block: str
    protection_level: str
    permitted_work: tuple[str, ...]
    condition: str


@dataclass(frozen=True)
class Proposal:
    proposal_id: str
    building_id: str
    work: str
    estimate_low: int | None
    estimate_high: int | None
    operator_id: str | None


@dataclass(frozen=True)
class AccessLink:
    proposal_id: str
    service_id: str
    group_code: str
    minutes_before: int | None
    minutes_after: int | None


@dataclass(frozen=True)
class OperationRow:
    operator_id: str
    service_id: str
    capacity_per_day: int | None
    confirmed_start: date | None


@dataclass(frozen=True)
class ValidationIssue:
    level: IssueLevel
    code: str
    message: str
    related: str = ""


# ---------------------------------------------------------------- 快照与意见（版本留痕）


@dataclass(frozen=True)
class FileFingerprint:
    """单个输入文件的哈希指纹。"""

    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class Snapshot:
    """一次评估所依据的全部输入的不可变快照。"""

    run_id: str
    created_at: str
    files: tuple[FileFingerprint, ...]
    combined_sha256: str


@dataclass(frozen=True)
class FileChange:
    """两次快照之间某个文件的变化。"""

    path: str
    old_sha256: str | None
    new_sha256: str | None
    kind: str  # added / removed / modified / unchanged


@dataclass(frozen=True)
class Opinion:
    """一条与某次评估快照绑定的意见。

    快照哈希使意见在方案版本更新后仍能保留当时依据；若当前快照与意见绑定的
    快照不同，展示层必须标注“依据已过期，需复核”，而不是静默沿用。
    """

    opinion_id: str
    run_id: str
    snapshot_combined: str
    created_at: str
    author: str
    stance: str  # support / object / neutral
    basis: str
    scope_proposal_id: str | None = None


# ---------------------------------------------------------------- 分析结果记录


@dataclass(frozen=True)
class Dataset:
    """经过解析与索引的全套输入。"""

    buildings: tuple[Building, ...]
    proposals: tuple[Proposal, ...]
    links: tuple[AccessLink, ...]
    operations: tuple[OperationRow, ...]
    issues: tuple[ValidationIssue, ...]
    buildings_by_id: dict[str, Building]
    proposals_by_id: dict[str, Proposal]
    links_by_proposal: dict[str, tuple[AccessLink, ...]]
    operations_by_operator: dict[str, tuple[OperationRow, ...]]


@dataclass(frozen=True)
class FeasibilityCheck:
    verdict: Verdict
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class AccessBenefit:
    """一条（服务 × 群体）可达性改善记录。

    sources 记录贡献该改善的方案，便于组合方案去重与溯源；
    saving 为 None 表示数据缺失，不得按 0 分呈现。
    """

    service_id: str
    group_code: str
    minutes_before: int | None
    minutes_after: int | None
    saving: int | None
    sources: tuple[str, ...]
    note: str = ""


@dataclass(frozen=True)
class CapacityLine:
    """一条运营容量归属记录。"""

    state: CapacityState
    operator_id: str | None
    service_id: str | None
    capacity_per_day: int | None
    confirmed_start: date | None
    note: str = ""


@dataclass(frozen=True)
class ProposalAssessment:
    proposal: Proposal
    building: Building | None
    feasibility: FeasibilityCheck
    access: tuple[AccessBenefit, ...]
    capacity_lines: tuple[CapacityLine, ...]
    affected_groups: tuple[str, ...]
    notes: tuple[str, ...]
    score: "WeightedScore | None" = None


@dataclass(frozen=True)
class CombinationAssessment:
    member_ids: tuple[str, ...]
    feasible: bool
    infeasible_reasons: tuple[str, ...]
    cost_low: int | None
    cost_high: int | None
    cost_complete: bool
    access: tuple[AccessBenefit, ...]
    capacity_lines: tuple[CapacityLine, ...]
    groups_covered: tuple[str, ...]
    shared_links: tuple[tuple[str, str, tuple[str, ...]], ...]
    notes: tuple[str, ...]
    score: "WeightedScore | None" = None


@dataclass(frozen=True)
class ServiceCoverage:
    """某项服务的可达改善与运营容量对照（用于暴露错配）。"""

    service_id: str
    access_entries: tuple[AccessBenefit, ...]
    capacity_lines: tuple[CapacityLine, ...]
    mismatch_notes: tuple[str, ...]


@dataclass(frozen=True)
class DemandTrace:
    """一条居民需求（群体 × 服务）到工程、保护边界、容量与运营方的追溯链。"""

    group_code: str
    service_id: str
    proposal_ids: tuple[str, ...]
    baseline_minutes: int | None
    best_after_minutes: int | None
    best_proposal_id: str | None
    saving: int | None
    capacity_lines: tuple[CapacityLine, ...]
    cost_ranges: tuple[tuple[str, int | None, int | None], ...]
    protection_boundaries: tuple[tuple[str, str, tuple[str, ...]], ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class WeightedScore:
    """群体加权结果。available 为 False 时 aggregate 必须为 None。"""

    available: bool
    aggregate: float | None
    weights: dict[str, float]
    covered_groups: tuple[str, ...]
    missing_groups: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class AssessmentResult:
    generated_at: str
    snapshot: Snapshot
    dataset: Dataset
    proposal_assessments: tuple[ProposalAssessment, ...]
    combinations: tuple[CombinationAssessment, ...]
    groups: tuple[str, ...]
    group_matrix: dict[str, dict[str, int | None]]
    service_coverage: tuple[ServiceCoverage, ...]
    demand_traces: tuple[DemandTrace, ...]
    weighted_score: WeightedScore | None
    max_members: int
    combo_truncated: bool
