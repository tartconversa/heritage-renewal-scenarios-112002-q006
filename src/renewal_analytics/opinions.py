"""评估意见的追加式存储与过期标注。

约束：
- 意见只能追加，不提供修改/删除接口；方案版本更新后旧意见原样保留，
  其依据快照哈希随之保留。
- 读取意见时对照当前快照：哈希不同则标记 stale=True，提示“依据已过期，
  需复核”，而不是把旧意见当作对新方案的有效结论。
- 存储为 JSON Lines，每行一条；文件不存在视为尚无意见，不报错。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import Opinion


@dataclass(frozen=True)
class StoredOpinion:
    opinion: Opinion
    stale: bool


def _to_row(opinion: Opinion) -> dict[str, object]:
    return {
        "opinion_id": opinion.opinion_id,
        "run_id": opinion.run_id,
        "snapshot_combined": opinion.snapshot_combined,
        "created_at": opinion.created_at,
        "author": opinion.author,
        "stance": opinion.stance,
        "basis": opinion.basis,
        "scope_proposal_id": opinion.scope_proposal_id,
    }


def _from_row(row: dict[str, object]) -> Opinion:
    return Opinion(
        opinion_id=str(row["opinion_id"]),
        run_id=str(row["run_id"]),
        snapshot_combined=str(row["snapshot_combined"]),
        created_at=str(row["created_at"]),
        author=str(row["author"]),
        stance=str(row["stance"]),
        basis=str(row["basis"]),
        scope_proposal_id=(
            str(row["scope_proposal_id"])
            if row.get("scope_proposal_id") is not None
            else None
        ),
    )


def record_opinion(
    store_path: str | Path,
    snapshot_combined: str,
    run_id: str,
    author: str,
    stance: str,
    basis: str,
    scope_proposal_id: str | None = None,
) -> Opinion:
    """追加一条意见并返回它。opinion_id 由时间戳与作者派生，避免重复写入。"""
    store_path = Path(store_path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    opinion = Opinion(
        opinion_id=f"op-{now.strftime('%Y%m%d%H%M%S')}-{abs(hash((author, basis))) % 10_000:04d}",
        run_id=run_id,
        snapshot_combined=snapshot_combined,
        created_at=now.isoformat(timespec="seconds"),
        author=author,
        stance=stance,
        basis=basis,
        scope_proposal_id=scope_proposal_id,
    )
    with store_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(_to_row(opinion), ensure_ascii=False) + "\n")
    return opinion


def load_opinions(
    store_path: str | Path,
    current_snapshot_combined: str | None = None,
) -> tuple[StoredOpinion, ...]:
    """读取全部意见；给定当前快照哈希时标注哪些意见的依据已过期。"""
    store_path = Path(store_path)
    if not store_path.is_file():
        return ()
    stored: list[StoredOpinion] = []
    with store_path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                opinion = _from_row(json.loads(line))
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(
                    f"意见存储 {store_path.name} 第 {line_no} 行无法解析: {exc}"
                ) from exc
            stale = (
                current_snapshot_combined is not None
                and opinion.snapshot_combined != current_snapshot_combined
            )
            stored.append(StoredOpinion(opinion=opinion, stale=stale))
    return tuple(stored)
