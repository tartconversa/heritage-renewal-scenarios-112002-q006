"""命令行入口：assess / validate / snapshot / opinion。

用法：
    python -m renewal_analytics assess --data data --out reports
    python -m renewal_analytics assess --data data --weights examples/weights.csv
    python -m renewal_analytics validate --data data
    python -m renewal_analytics snapshot --data data
    python -m renewal_analytics opinion --data data --run-id run-xxx \
        --author 居民代表甲 --stance support --basis "..." [--proposal S-1]

退出码：0 成功；2 输入存在阻断性错误；3 用法/文件错误。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import opinions as opinions_mod
from .assessment import DEFAULT_MAX_MEMBERS, assess_dataset
from .loader import LoaderError, has_blocking_errors, load_dataset
from .report import write_report
from .scoring import load_weights
from .snapshot import diff_snapshots, take_snapshot


def _cmd_validate(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.data)
    for issue in dataset.issues:
        print(f"[{issue.level.value.upper()}] {issue.code} "
              f"{issue.related}: {issue.message}")
    errors = sum(1 for i in dataset.issues if i.level.value == "error")
    warnings = sum(1 for i in dataset.issues if i.level.value == "warning")
    print(f"\n共 {errors} 个错误，{warnings} 个预警")
    return 2 if has_blocking_errors(dataset) else 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    snapshot = take_snapshot(args.data)
    print(json.dumps(
        {
            "run_id": snapshot.run_id,
            "created_at": snapshot.created_at,
            "combined_sha256": snapshot.combined_sha256,
            "files": [
                {"path": f.path, "sha256": f.sha256, "size_bytes": f.size_bytes}
                for f in snapshot.files
            ],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def _cmd_assess(args: argparse.Namespace) -> int:
    dataset = load_dataset(args.data)
    if has_blocking_errors(dataset):
        print("输入存在阻断性错误，拒绝在残缺数据上生成评估结论；"
              "请先运行 validate 查看详情。", file=sys.stderr)
        for issue in dataset.issues:
            if issue.level.value == "error":
                print(f"[ERROR] {issue.code} {issue.related}: {issue.message}",
                      file=sys.stderr)
        return 2

    weight_table = None
    if args.weights:
        weight_table = load_weights(args.weights)

    snapshot = take_snapshot(args.data)
    result = assess_dataset(
        dataset,
        snapshot,
        weight_table=weight_table,
        max_members=args.max_members,
    )
    md_path, json_path = write_report(result, args.out)

    # 与历史快照比对，提示哪些输入依据发生了变化
    history_dir = Path(args.out) / "snapshots"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"{snapshot.run_id}.json"
    history_path.write_text(
        json.dumps(
            {
                "run_id": snapshot.run_id,
                "created_at": snapshot.created_at,
                "combined_sha256": snapshot.combined_sha256,
                "files": [
                    {"path": f.path, "sha256": f.sha256}
                    for f in snapshot.files
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    previous = sorted(history_dir.glob("run-*.json"))
    if len(previous) > 1:
        from .models import Snapshot as _Snapshot  # 局部导入避免循环

        def _load(path: Path) -> _Snapshot:
            payload = json.loads(path.read_text(encoding="utf-8"))
            from .models import FileFingerprint

            return _Snapshot(
                run_id=payload["run_id"],
                created_at=payload["created_at"],
                files=tuple(
                    FileFingerprint(
                        path=f["path"], sha256=f["sha256"], size_bytes=0
                    )
                    for f in payload["files"]
                ),
                combined_sha256=payload["combined_sha256"],
            )

        changes = diff_snapshots(_load(previous[-2]), _load(history_path))
        changed = [c for c in changes if c.kind != "unchanged"]
        if changed:
            print("相较上一版本发生变化的输入（旧意见与结论需按新依据复核）：")
            for change in changed:
                print(f"  - {change.path}: {change.kind}")

    print(f"评估完成：{md_path}")
    print(f"机器结果：{json_path}")
    infeasible = [
        a.proposal.proposal_id
        for a in result.proposal_assessments
        if a.feasibility.verdict.value == "infeasible"
    ]
    if infeasible:
        print(f"不可行方案（保护底线一票否决）：{', '.join(infeasible)}")
    return 0


def _cmd_opinion(args: argparse.Namespace) -> int:
    snapshot = take_snapshot(args.data)
    store = Path(args.out) / "opinions.jsonl"
    opinion = opinions_mod.record_opinion(
        store_path=store,
        snapshot_combined=snapshot.combined_sha256,
        run_id=args.run_id,
        author=args.author,
        stance=args.stance,
        basis=args.basis,
        scope_proposal_id=args.proposal,
    )
    print(f"已追加意见 {opinion.opinion_id}，绑定快照 "
          f"{opinion.snapshot_combined[:12]}，存储于 {store}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="renewal_analytics",
        description="历史街区更新方案比较分析（合成数据，标准库实现）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="校验输入 CSV 合同与引用完整性")
    p_validate.add_argument("--data", default="data")
    p_validate.set_defaults(func=_cmd_validate)

    p_snapshot = sub.add_parser("snapshot", help="计算输入文件哈希快照")
    p_snapshot.add_argument("--data", default="data")
    p_snapshot.set_defaults(func=_cmd_snapshot)

    p_assess = sub.add_parser("assess", help="执行完整评估并写出决策资料")
    p_assess.add_argument("--data", default="data")
    p_assess.add_argument("--out", default="reports")
    p_assess.add_argument("--weights", default=None,
                          help="群体权重 CSV（group_code,weight,source,representativeness）")
    p_assess.add_argument("--max-members", type=int, default=DEFAULT_MAX_MEMBERS)
    p_assess.set_defaults(func=_cmd_assess)

    p_opinion = sub.add_parser("opinion", help="追加一条绑定快照的评估意见")
    p_opinion.add_argument("--data", default="data")
    p_opinion.add_argument("--out", default="reports")
    p_opinion.add_argument("--run-id", required=True)
    p_opinion.add_argument("--author", required=True)
    p_opinion.add_argument("--stance", required=True,
                           choices=["support", "object", "neutral"])
    p_opinion.add_argument("--basis", required=True)
    p_opinion.add_argument("--proposal", default=None)
    p_opinion.set_defaults(func=_cmd_opinion)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LoaderError as exc:
        print(f"输入错误：{exc}", file=sys.stderr)
        return 3
    except (ValueError, FileNotFoundError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
