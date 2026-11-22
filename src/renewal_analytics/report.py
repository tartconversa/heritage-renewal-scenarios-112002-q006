"""决策资料输出：中文 Markdown 报告与机器可读 JSON。

报告刻意保留三类边界，不做抹平：
1. 不可行（硬底线冲突）与价值偏好不同（均可行但收益结构不同）分节呈现；
2. 未知数据显示“未知”，不显示 0；成本始终以区间呈现；
3. 加权分不可用时明确写出原因，不以单一总分替代价值讨论。
"""
from __future__ import annotations

import dataclasses
import enum
import json
from datetime import date
from pathlib import Path

from .models import (
    AssessmentResult,
    CapacityState,
    IssueLevel,
    Verdict,
)

STATE_LABELS = {
    CapacityState.STABLE: "稳定（可计入）",
    CapacityState.UNCONFIRMED: "未确认",
    CapacityState.UNCOMMITTED: "无服务承诺",
    CapacityState.NO_OPERATOR: "无运营方",
}

VERDICT_LABELS = {
    Verdict.FEASIBLE: "可行",
    Verdict.INFEASIBLE: "不可行（保护底线）",
}


def _money(value: int | None) -> str:
    return "未知" if value is None else f"¥{value:,}"


def _minutes(value: int | None) -> str:
    return "未知" if value is None else f"{value} 分钟"


def _score(cell: object) -> str:
    if cell is None:
        return "—"
    score = getattr(cell, "aggregate", None)
    if score is None:
        return "不可用（见价值边界）"
    return f"{score}"


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(_md_escape(str(cell)) for cell in row)
            + " |"
        )
    return "\n".join(lines)


def _issues_section(result: AssessmentResult) -> str:
    issues = result.dataset.issues
    if not issues:
        return "## 1. 输入校验\n\n未发现校验问题。\n"
    errors = [i for i in issues if i.level is IssueLevel.ERROR]
    warnings = [i for i in issues if i.level is IssueLevel.WARNING]
    parts = ["## 1. 输入校验\n"]
    if errors:
        parts.append(f"### 阻断性错误（{len(errors)} 项，评估结论不应据此决策）\n")
        parts.append(_table(
            ("代码", "说明", "相关对象"),
            [(i.code, i.message, i.related or "—") for i in errors],
        ))
        parts.append("")
    if warnings:
        parts.append(f"### 预警（{len(warnings)} 项，不阻断但必须知晓）\n")
        parts.append(_table(
            ("代码", "说明", "相关对象"),
            [(i.code, i.message, i.related or "—") for i in warnings],
        ))
        parts.append("")
    return "\n".join(parts)


def _feasibility_section(result: AssessmentResult) -> str:
    rows: list[tuple[object, ...]] = []
    for a in result.proposal_assessments:
        rows.append((
            a.proposal.proposal_id,
            a.proposal.building_id,
            a.proposal.work,
            VERDICT_LABELS[a.feasibility.verdict],
            "；".join(a.feasibility.reasons),
        ))
    return (
        "## 2. 保护可行性裁决（硬约束，一票否决）\n\n"
        + _table(
            ("方案", "建筑", "工程类型", "裁决", "依据"),
            rows,
        )
        + "\n\n不可行方案不进入任何评分排序；保护底线不可被可达性、受益人数等"
        "高分指标折算抵消。\n"
    )


def _proposal_section(result: AssessmentResult) -> str:
    parts = ["## 3. 单方案收益构成与运营状态\n"]
    for a in result.proposal_assessments:
        parts.append(f"### 方案 {a.proposal.proposal_id}（{a.proposal.work}）\n")
        parts.append(
            f"- 裁决：{VERDICT_LABELS[a.feasibility.verdict]}\n"
            f"- 目标建筑：{a.proposal.building_id}"
            + (
                f"，保护等级 {a.building.protection_level}，许可范围 "
                f"{list(a.building.permitted_work)}"
                if a.building is not None
                else ""
            )
            + "\n"
            f"- 工程成本区间：{_money(a.proposal.estimate_low)} ~ "
            f"{_money(a.proposal.estimate_high)}"
            + ("（区间不完整）" if a.proposal.estimate_low is None
               or a.proposal.estimate_high is None else "")
            + "\n"
            f"- 指定运营方：{a.proposal.operator_id or '未指定'}\n"
        )
        if a.access:
            parts.append("\n可达性改善（街巷通行，按服务×群体）：\n\n")
            parts.append(_table(
                ("服务", "群体", "施工前", "施工后", "节省", "来源方案", "备注"),
                [
                    (
                        b.service_id,
                        b.group_code,
                        _minutes(b.minutes_before),
                        _minutes(b.minutes_after),
                        _minutes(b.saving),
                        ", ".join(b.sources),
                        b.note or "—",
                    )
                    for b in a.access
                ],
            ))
            parts.append("")
        else:
            parts.append("\n- 可达性：该方案无可达改善记录。\n")

        parts.append("\n运营容量归属：\n\n")
        parts.append(_table(
            ("状态", "运营方", "服务", "容量(人/日)", "确认启用日期", "说明"),
            [
                (
                    STATE_LABELS[c.state],
                    c.operator_id or "—",
                    c.service_id or "—",
                    "未知" if c.capacity_per_day is None else c.capacity_per_day,
                    c.confirmed_start.isoformat() if c.confirmed_start else "—",
                    c.note,
                )
                for c in a.capacity_lines
            ],
        ))
        stable = sum(
            c.capacity_per_day or 0
            for c in a.capacity_lines
            if c.state is CapacityState.STABLE
        )
        parts.append(f"\n\n可计入稳定容量合计：**{stable} 人/日**"
                     "（未确认与无运营方容量不计入）。\n")
        if a.score is not None:
            parts.append(f"\n加权评分：{_score(a.score)}\n")
            if a.score.available:
                parts.append(f"  - {a.score.note}\n")
            else:
                parts.append(f"  - {a.score.note}\n")
        parts.append("")
    return "\n".join(parts)


def _combination_section(result: AssessmentResult) -> str:
    parts = [
        "## 4. 组合方案比较\n",
        _table(
            ("成员", "可行性", "成本区间", "覆盖群体", "稳定容量(人/日)",
             "共享改善(去重项)", "加权分"),
            [
                (
                    " + ".join(c.member_ids),
                    "可行" if c.feasible else "不可行",
                    f"{_money(c.cost_low)} ~ {_money(c.cost_high)}",
                    ", ".join(c.groups_covered) or "—",
                    sum(
                        line.capacity_per_day or 0
                        for line in c.capacity_lines
                        if line.state is CapacityState.STABLE
                    ),
                    len(c.shared_links),
                    _score(c.score),
                )
                for c in result.combinations
            ],
        ),
        "",
    ]
    if result.combo_truncated:
        parts.append(
            f"> 注：组合枚举按最多 {result.max_members} 个成员截断，"
            "更大的组合未在本报告中展开。\n"
        )
    for c in result.combinations:
        if c.shared_links:
            parts.append(
                f"- 组合 {' + '.join(c.member_ids)} 的共享街巷改善："
                + "；".join(
                    f"{service}/{group}（来源：{', '.join(sources)}）"
                    for service, group, sources in c.shared_links
                )
            )
        if c.notes:
            parts.append(
                f"- 组合 {' + '.join(c.member_ids)} 备注：{'；'.join(c.notes)}"
            )
    parts.append("")
    return "\n".join(parts)


def _matrix_cell(value: int | None) -> str:
    if value is None:
        return "未知"
    if value == 0:
        return "0 分钟（无改善）"
    return f"{value} 分钟"


def _matrix_section(result: AssessmentResult) -> str:
    headers = ("方案",) + result.groups
    rows: list[tuple[object, ...]] = []
    for pid, row in sorted(result.group_matrix.items()):
        rows.append(
            (pid,) + tuple(_matrix_cell(row.get(g)) for g in result.groups)
        )
    return (
        "## 5. 分群体可达节省矩阵（价值偏好对比，不做隐含加权）\n\n"
        + _table(headers, rows)
        + "\n\n“未知”表示数据缺失，与“0 分钟（无改善）”含义不同；"
        "未出现的群体默认该方案对其无可达改善记录。\n"
    )


def _coverage_section(result: AssessmentResult) -> str:
    parts = ["## 6. 服务覆盖与运营错配\n"]
    for coverage in result.service_coverage:
        parts.append(f"### 服务 {coverage.service_id}\n")
        if coverage.access_entries:
            parts.append("- 可达改善：" + "；".join(
                f"{b.group_code} {_minutes(b.minutes_before)}→"
                f"{_minutes(b.minutes_after)}"
                for b in coverage.access_entries
            ) + "\n")
        if coverage.capacity_lines:
            parts.append("- 运营容量：" + "；".join(
                f"{STATE_LABELS[c.state]}（{c.operator_id}，"
                f"{'未知' if c.capacity_per_day is None else c.capacity_per_day}"
                " 人/日）"
                for c in coverage.capacity_lines
            ) + "\n")
        for note in coverage.mismatch_notes:
            parts.append(f"- ⚠ {note}\n")
        parts.append("")
    return "\n".join(parts)


def _score_section(result: AssessmentResult) -> str:
    parts = ["## 7. 加权总分与价值判断边界\n"]
    score = result.weighted_score
    if score is None:
        parts.append(
            "本次评估**未提供群体权重文件**，因此不生成加权总分。\n\n"
            "各方案仅以分群体收益（见第 5 节）呈现：方案之间的差异属于价值"
            "偏好不同，应由具备代表性的居民与决策者共同确定权重后再排序，"
            "分析层不得把任何隐含偏好包装成客观共识。\n"
        )
        return "\n".join(parts)
    if not score.available:
        parts.append(
            "**加权总分当前不可用。**\n\n"
            f"- 原因：{score.note}\n"
            f"- 已覆盖群体：{', '.join(score.covered_groups) or '无'}\n"
            f"- 缺失群体：{', '.join(score.missing_groups) or '无'}\n"
        )
        return "\n".join(parts)
    parts.append(
        f"加权聚合分（可达节省分钟，加权）：**{score.aggregate}**\n\n"
        f"- 使用权重：{json.dumps(score.weights, ensure_ascii=False)}\n"
        f"- 边界说明：{score.note}\n"
        "- 该分数仅排序**可行**方案；不可行方案因保护底线被排除，"
        "其约束不参与任何折算。\n"
    )
    return "\n".join(parts)


def _uncertainty_section(result: AssessmentResult) -> str:
    items: list[str] = []
    for a in result.proposal_assessments:
        if a.proposal.estimate_low is None or a.proposal.estimate_high is None:
            items.append(
                f"- 方案 {a.proposal.proposal_id} 成本区间不完整，"
                "合计与排序中的成本信息存在未知侧"
            )
        for benefit in a.access:
            if benefit.saving is None:
                items.append(
                    f"- 方案 {a.proposal.proposal_id} 的 "
                    f"{benefit.service_id}/{benefit.group_code} "
                    "可达节省量未知"
                )
        for cap in a.capacity_lines:
            if cap.state is not CapacityState.STABLE:
                items.append(f"- 方案 {a.proposal.proposal_id}：{cap.note}")
    if result.combo_truncated:
        items.append(
            f"- 组合枚举在 {result.max_members} 个成员处截断，"
            "更大组合未评估"
        )
    items.append(
        "- 输入表未提供施工影响（扬尘、噪声、临时封路等）字段，"
        "施工期影响在本次资料中为数据缺口，需另行补充"
    )
    items.append(
        "- 输入表未提供运营期成本字段，追溯链中的运营成本维度只能标注"
        "“数据未提供”，容量不等于可持续性"
    )
    return "## 8. 不确定性与数据缺口\n\n" + "\n".join(items) + "\n"


def _trace_section(result: AssessmentResult) -> str:
    parts = [
        "## 9. 居民需求追溯链（需求 → 工程 → 保护边界 → 容量与运营）\n",
        _table(
            ("群体", "服务", "相关方案", "施工前→施工后(最优)",
             "节省", "运营容量状态", "工程成本区间", "保护边界", "备注"),
            [
                (
                    t.group_code,
                    t.service_id,
                    ", ".join(t.proposal_ids),
                    f"{_minutes(t.baseline_minutes)} → "
                    f"{_minutes(t.best_after_minutes)}"
                    f"（{t.best_proposal_id or '—'}）",
                    _minutes(t.saving),
                    "；".join(
                        f"{STATE_LABELS[c.state]}:"
                        f"{c.service_id or '—'}"
                        for c in t.capacity_lines
                    ) or "—",
                    "；".join(
                        f"{pid} {_money(low)}~{_money(high)}"
                        for pid, low, high in t.cost_ranges
                    ) or "—",
                    "；".join(
                        f"{bid}(等级{level}, 许可{list(scope)})"
                        for bid, level, scope in t.protection_boundaries
                    ) or "—",
                    "；".join(t.notes) or "—",
                )
                for t in result.demand_traces
            ],
        ),
        "",
    ]
    return "\n".join(parts)


def _closing_section(result: AssessmentResult) -> str:
    infeasible = [
        a.proposal.proposal_id
        for a in result.proposal_assessments
        if a.feasibility.verdict is Verdict.INFEASIBLE
    ]
    feasible = [
        a.proposal.proposal_id
        for a in result.proposal_assessments
        if a.feasibility.verdict is Verdict.FEASIBLE
    ]
    return (
        "## 10. 结论边界\n\n"
        f"- 不可行方案（硬约束冲突）：{', '.join(infeasible) or '无'}"
        "——这些方案的问题不是分数高低，而是不允许实施。\n"
        f"- 可行方案：{', '.join(feasible) or '无'}"
        "——它们之间的取舍属于价值偏好与资源约束问题，"
        "本资料只并列收益构成、运营状态与不确定性，不替代政治与社区决定。\n"
        "- 保护底线（许可工程范围、保护等级要求）为不可互换约束，"
        "在任何视图中都不折算为可被高分抵消的普通指标。\n"
        f"- 本报告所有结论绑定快照 "
        f"`{result.snapshot.combined_sha256[:12]}`；输入修订后应以新快照"
        "重新评估，旧意见保留原依据并标注过期。\n"
    )


def render_markdown(result: AssessmentResult) -> str:
    header = (
        "# 历史街区更新方案比较决策资料\n\n"
        f"- 生成时间（UTC）：{result.generated_at}\n"
        f"- 评估运行：`{result.snapshot.run_id}`\n"
        f"- 输入快照哈希：`{result.snapshot.combined_sha256}`\n"
        "- 数据性质：合成数据，不对应真实住户、项目或城市\n\n"
    )
    sections = [
        header,
        _issues_section(result),
        _feasibility_section(result),
        _proposal_section(result),
        _combination_section(result),
        _matrix_section(result),
        _coverage_section(result),
        _score_section(result),
        _uncertainty_section(result),
        _trace_section(result),
        _closing_section(result),
    ]
    return "\n".join(sections)


def _to_jsonable(value: object) -> object:
    if dataclasses.is_dataclass(value):
        return {
            key: _to_jsonable(item)
            for key, item in dataclasses.asdict(value).items()
        }
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


def render_json(result: AssessmentResult) -> str:
    return json.dumps(
        _to_jsonable(result),
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
    )


def write_report(
    result: AssessmentResult,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """写出 Markdown 与 JSON 两个文件，返回它们的路径。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / f"{result.snapshot.run_id}-report.md"
    json_path = output_dir / f"{result.snapshot.run_id}-result.json"
    md_path.write_text(render_markdown(result), encoding="utf-8")
    json_path.write_text(render_json(result), encoding="utf-8")
    return md_path, json_path
