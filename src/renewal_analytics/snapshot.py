"""输入快照、版本指纹与差异比对。

每次评估都对当时的输入文件计算 SHA-256 指纹：
- 评估结论与居民意见绑定快照哈希，方案版本更新后旧意见仍保留当时依据；
- diff_snapshots 指出变化文件，调用方据此标注“依据已过期、需复核”；
- 施工范围（proposals.csv）变化会改变可达性、受影响群体与保护审查结论，
  因此任何文件变化都要求重新评估，而非在旧结论上做局部修补。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .models import FileChange, FileFingerprint, Snapshot

SNAPSHOT_FILES = (
    "buildings.csv",
    "proposals.csv",
    "access-links.csv",
    "operations.csv",
)


def _fingerprint(path: Path) -> FileFingerprint:
    digest = hashlib.sha256()
    raw = path.read_bytes()
    digest.update(raw)
    return FileFingerprint(
        path=path.name,
        sha256=digest.hexdigest(),
        size_bytes=len(raw),
    )


def take_snapshot(data_dir: str | Path, run_id: str | None = None) -> Snapshot:
    """对输入目录中的合同文件计算指纹，生成不可变快照。"""
    data_dir = Path(data_dir)
    fingerprints = tuple(
        _fingerprint(data_dir / name)
        for name in SNAPSHOT_FILES
        if (data_dir / name).is_file()
    )
    combined = hashlib.sha256(
        "".join(f"{f.path}:{f.sha256}\n" for f in fingerprints).encode("utf-8")
    ).hexdigest()
    return Snapshot(
        run_id=run_id or f"run-{combined[:12]}",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        files=fingerprints,
        combined_sha256=combined,
    )


def diff_snapshots(old: Snapshot, new: Snapshot) -> tuple[FileChange, ...]:
    """比对两次快照，逐文件给出 added / removed / modified / unchanged。"""
    old_map = {f.path: f.sha256 for f in old.files}
    new_map = {f.path: f.sha256 for f in new.files}
    changes: list[FileChange] = []
    for path in sorted(set(old_map) | set(new_map)):
        old_hash = old_map.get(path)
        new_hash = new_map.get(path)
        if old_hash is None:
            kind = "added"
        elif new_hash is None:
            kind = "removed"
        elif old_hash != new_hash:
            kind = "modified"
        else:
            kind = "unchanged"
        changes.append(FileChange(path, old_hash, new_hash, kind))
    return tuple(changes)


def changed_files(changes: tuple[FileChange, ...]) -> tuple[FileChange, ...]:
    """过滤出真正发生变化的文件。"""
    return tuple(c for c in changes if c.kind != "unchanged")
