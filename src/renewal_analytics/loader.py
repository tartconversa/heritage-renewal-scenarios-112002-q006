"""CSV 输入解析与合同校验。

设计要点：
- 解析层只做结构与引用校验，不做业务裁决（可行性在 feasibility 模块）。
- 空单元格统一保留为 None；数值/日期解析失败产生 error 级问题。
- 引用完整性（外键悬空、重复主键、成本区间倒置）作为 error 收集，
  评估流程在存在 error 时中止，避免在残缺数据上生成看似精确定量的结论。
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from .models import (
    AccessLink,
    Building,
    Dataset,
    IssueLevel,
    OperationRow,
    Proposal,
    ValidationIssue,
)


class LoaderError(Exception):
    """输入目录或文件结构不满足合同（缺文件、缺列、空表等）。"""


REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "buildings.csv": (
        "building_id",
        "block",
        "protection_level",
        "permitted_work",
        "condition",
    ),
    "proposals.csv": (
        "proposal_id",
        "building_id",
        "work",
        "estimate_low",
        "estimate_high",
        "operator_id",
    ),
    "access-links.csv": (
        "proposal_id",
        "service_id",
        "group_code",
        "minutes_before",
        "minutes_after",
    ),
    "operations.csv": (
        "operator_id",
        "service_id",
        "capacity_per_day",
        "confirmed_start",
    ),
}


def _clean(value: str | None) -> str | None:
    """空字符串/纯空白归一为 None；其余去掉首尾空白。"""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _split_semicolon(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(";") if part.strip())


def _parse_int(
    raw: str | None,
    issues: list[ValidationIssue],
    code: str,
    related: str,
) -> int | None:
    value = _clean(raw)
    if value is None:
        return None  # 未知，不是零
    try:
        return int(value)
    except ValueError:
        issues.append(
            ValidationIssue(
                IssueLevel.ERROR,
                code,
                f"无法解析为整数: {value!r}",
                related,
            )
        )
        return None


def _parse_iso_date(
    raw: str | None,
    issues: list[ValidationIssue],
    related: str,
) -> date | None:
    value = _clean(raw)
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        issues.append(
            ValidationIssue(
                IssueLevel.ERROR,
                "invalid_date",
                f"无法解析为 ISO 8601 日期: {value!r}",
                related,
            )
        )
        return None


def _read_rows(path: Path, issues: list[ValidationIssue]) -> list[dict[str, str]]:
    if not path.is_file():
        raise LoaderError(f"缺少必需输入文件: {path.name}")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise LoaderError(f"{path.name} 缺少表头")
        missing = [c for c in REQUIRED_COLUMNS[path.name] if c not in fieldnames]
        if missing:
            raise LoaderError(f"{path.name} 缺少列: {', '.join(missing)}")
        extra = [c for c in fieldnames if c not in REQUIRED_COLUMNS[path.name]]
        if extra:
            issues.append(
                ValidationIssue(
                    IssueLevel.WARNING,
                    "unknown_column",
                    f"{path.name} 存在合同外列，将被忽略: {', '.join(extra)}",
                    path.name,
                )
            )
        rows: list[dict[str, str]] = []
        for line_no, row in enumerate(reader, start=2):
            if None in row:
                issues.append(
                    ValidationIssue(
                        IssueLevel.ERROR,
                        "ragged_row",
                        f"第 {line_no} 行列数与表头不一致",
                        f"{path.name}:{line_no}",
                    )
                )
                continue
            if not any(_clean(v) for v in row.values()):
                continue  # 空行跳过
            rows.append({k: _clean(v) for k, v in row.items()})
        if not rows:
            raise LoaderError(f"{path.name} 没有任何数据记录")
        return rows


def load_dataset(data_dir: str | Path) -> Dataset:
    """读取并校验四张输入表，返回带索引的 Dataset。"""
    data_dir = Path(data_dir)
    issues: list[ValidationIssue] = []

    building_rows = _read_rows(data_dir / "buildings.csv", issues)
    proposal_rows = _read_rows(data_dir / "proposals.csv", issues)
    link_rows = _read_rows(data_dir / "access-links.csv", issues)
    operation_rows = _read_rows(data_dir / "operations.csv", issues)

    # ------------------------------------------------------------ buildings
    buildings: list[Building] = []
    buildings_by_id: dict[str, Building] = {}
    for row in building_rows:
        bid = row["building_id"]
        if not bid:
            issues.append(ValidationIssue(IssueLevel.ERROR, "missing_key",
                                          "building_id 为空", "buildings.csv"))
            continue
        if bid in buildings_by_id:
            issues.append(ValidationIssue(IssueLevel.ERROR, "duplicate_id",
                                          f"建筑 {bid} 重复出现", bid))
            continue
        record = Building(
            building_id=bid,
            block=row["block"] or "",
            protection_level=row["protection_level"] or "",
            permitted_work=_split_semicolon(row["permitted_work"]),
            condition=row["condition"] or "",
        )
        buildings.append(record)
        buildings_by_id[bid] = record
        if not record.permitted_work:
            issues.append(ValidationIssue(
                IssueLevel.WARNING, "no_permitted_work",
                f"建筑 {bid} 未声明任何许可工程范围，任何工程都将被否决", bid))
        if not record.protection_level:
            issues.append(ValidationIssue(
                IssueLevel.WARNING, "missing_protection_level",
                f"建筑 {bid} 缺少保护等级", bid))

    # ------------------------------------------------------------ proposals
    proposals: list[Proposal] = []
    proposals_by_id: dict[str, Proposal] = {}
    for row in proposal_rows:
        pid = row["proposal_id"]
        if not pid:
            issues.append(ValidationIssue(IssueLevel.ERROR, "missing_key",
                                          "proposal_id 为空", "proposals.csv"))
            continue
        if pid in proposals_by_id:
            issues.append(ValidationIssue(IssueLevel.ERROR, "duplicate_id",
                                          f"方案 {pid} 重复出现", pid))
            continue
        low = _parse_int(row["estimate_low"], issues, "invalid_cost", pid)
        high = _parse_int(row["estimate_high"], issues, "invalid_cost", pid)
        if low is not None and high is not None and low > high:
            issues.append(ValidationIssue(
                IssueLevel.ERROR, "inverted_cost_range",
                f"方案 {pid} 的 estimate_low({low}) > estimate_high({high})", pid))
        record = Proposal(
            proposal_id=pid,
            building_id=row["building_id"] or "",
            work=row["work"] or "",
            estimate_low=low,
            estimate_high=high,
            operator_id=row["operator_id"],
        )
        proposals.append(record)
        proposals_by_id[pid] = record
        if not record.work:
            issues.append(ValidationIssue(
                IssueLevel.ERROR, "missing_work", f"方案 {pid} 未声明工程类型", pid))
        if low is None or high is None:
            issues.append(ValidationIssue(
                IssueLevel.WARNING, "incomplete_cost",
                f"方案 {pid} 成本区间不完整，未知一侧不得按 0 处理", pid))
        if record.building_id not in buildings_by_id:
            issues.append(ValidationIssue(
                IssueLevel.ERROR, "dangling_reference",
                f"方案 {pid} 引用了不存在的建筑 {record.building_id}", pid))

    # ------------------------------------------------------------ access links
    links: list[AccessLink] = []
    links_by_proposal: dict[str, list[AccessLink]] = {}
    for row in link_rows:
        pid = row["proposal_id"]
        if pid not in proposals_by_id:
            issues.append(ValidationIssue(
                IssueLevel.ERROR, "dangling_reference",
                f"可达记录引用了不存在的方案 {pid}", pid))
            continue
        record = AccessLink(
            proposal_id=pid,
            service_id=row["service_id"] or "",
            group_code=row["group_code"] or "",
            minutes_before=_parse_int(row["minutes_before"], issues,
                                      "invalid_minutes", f"{pid}/{row.get('service_id')}"),
            minutes_after=_parse_int(row["minutes_after"], issues,
                                     "invalid_minutes", f"{pid}/{row.get('service_id')}"),
        )
        links.append(record)
        links_by_proposal.setdefault(pid, []).append(record)
        if not record.service_id or not record.group_code:
            issues.append(ValidationIssue(
                IssueLevel.ERROR, "missing_key",
                f"方案 {pid} 的可达记录缺少 service_id 或 group_code", pid))

    # ------------------------------------------------------------ operations
    operations: list[OperationRow] = []
    operations_by_operator: dict[str, list[OperationRow]] = {}
    for row in operation_rows:
        oid = row["operator_id"]
        if not oid:
            issues.append(ValidationIssue(
                IssueLevel.ERROR, "missing_key",
                "operator_id 为空", "operations.csv"))
            continue
        record = OperationRow(
            operator_id=oid,
            service_id=row["service_id"] or "",
            capacity_per_day=_parse_int(row["capacity_per_day"], issues,
                                        "invalid_capacity", f"{oid}/{row.get('service_id')}"),
            confirmed_start=_parse_iso_date(row["confirmed_start"], issues, oid),
        )
        operations.append(record)
        operations_by_operator.setdefault(oid, []).append(record)
        if record.capacity_per_day is not None and record.capacity_per_day < 0:
            issues.append(ValidationIssue(
                IssueLevel.ERROR, "negative_capacity",
                f"运营方 {oid} 服务 {record.service_id} 容量为负", oid))

    # 方案指定了运营方，但运营表中完全查不到该责任方
    for proposal in proposals:
        if proposal.operator_id and proposal.operator_id not in operations_by_operator:
            issues.append(ValidationIssue(
                IssueLevel.ERROR, "uncommitted_operator",
                f"方案 {proposal.proposal_id} 指定的运营方 "
                f"{proposal.operator_id} 在运营表中无任何服务承诺",
                proposal.proposal_id))

    return Dataset(
        buildings=tuple(buildings),
        proposals=tuple(proposals),
        links=tuple(links),
        operations=tuple(operations),
        issues=tuple(issues),
        buildings_by_id=dict(buildings_by_id),
        proposals_by_id=dict(proposals_by_id),
        links_by_proposal={k: tuple(v) for k, v in links_by_proposal.items()},
        operations_by_operator={k: tuple(v) for k, v in operations_by_operator.items()},
    )


def has_blocking_errors(dataset: Dataset) -> bool:
    """是否存在阻断评估的 error 级问题。"""
    return any(issue.level is IssueLevel.ERROR for issue in dataset.issues)
