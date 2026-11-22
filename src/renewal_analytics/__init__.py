"""城市更新方案比较分析包。

模块划分：
- models：不可变领域记录与枚举
- loader：CSV 解析与合同校验（空值保留为 None）
- feasibility：保护底线硬约束裁决（一票否决，不可折算）
- access：街巷可达改善与组合去重
- capacity：运营责任与稳定容量认定
- scoring：外生群体权重与加权分（无权重则不产出总分）
- snapshot：输入哈希快照与版本差异
- opinions：追加式意见留痕与过期标注
- assessment：评估编排
- report：中文 Markdown 决策资料与 JSON 输出
- cli：命令行入口
"""
from .assessment import assess_dataset
from .loader import load_dataset
from .snapshot import diff_snapshots, take_snapshot

__all__ = [
    "assess_dataset",
    "load_dataset",
    "take_snapshot",
    "diff_snapshots",
]
