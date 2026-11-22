"""测试用临时输入目录构造工具。"""
from __future__ import annotations

from pathlib import Path

FILES: dict[str, str] = {
    "buildings.csv": (
        "building_id,block,protection_level,permitted_work,condition\n"
        "B-1,Old-A,high,facade;access,poor\n"
        "B-2,Old-A,medium,repair;access,fair\n"
        "B-3,Old-B,high,repair,poor\n"
        "B-4,Old-B,medium,,fair\n"
    ),
    "proposals.csv": (
        "proposal_id,building_id,work,estimate_low,estimate_high,operator_id\n"
        "S-1,B-1,access,180000,260000,OP-1\n"
        "S-2,B-2,repair,220000,280000,\n"
        "S-3,B-3,repair,310000,390000,OP-2\n"
        # 工程类型超出 B-1 许可范围（facade;access），必须被否决
        "S-4,B-1,demolish,100000,150000,OP-1\n"
        # B-4 没有任何许可工程范围，任何工程都不可行
        "S-5,B-4,repair,50000,80000,\n"
        # 引用不存在的建筑
        "S-6,B-99,access,10000,20000,\n"
        # 成本区间倒置
        "S-7,B-2,access,300000,200000,OP-1\n"
        # 成本一侧缺失
        "S-8,B-2,access,,120000,OP-1\n"
    ),
    "access-links.csv": (
        "proposal_id,service_id,group_code,minutes_before,minutes_after\n"
        "S-1,clinic,older,24,12\n"
        "S-1,market,renter,18,10\n"
        "S-3,daycare,caregiver,31,19\n"
        # S-8 与 S-1 改善同一 (clinic, older)，用于组合去重；S-8 效果更优
        "S-8,clinic,older,24,9\n"
        # 通行恶化案例
        "S-7,market,renter,18,25\n"
        # 缺失一侧耗时
        "S-3,clinic,older,,12\n"
    ),
    "operations.csv": (
        "operator_id,service_id,capacity_per_day,confirmed_start\n"
        "OP-1,community_room,35,2027-04-01\n"
        "OP-2,clinic,18,\n"
        "OP-3,market,,2027-01-01\n"
    ),
}


def write_dataset(root: str | Path, overrides: dict[str, str] | None = None) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (root / name).write_text(
            overrides.get(name, content) if overrides else content,
            encoding="utf-8",
        )
    return root
