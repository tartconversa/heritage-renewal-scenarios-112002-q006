# 合成输入材料

这里的记录均为合成数据，不对应真实住户、项目或城市。每个文件表示一个来源数据表，不包含分析结论；解释记录时应保留来源标识和修订关系。

## 字段合同

- `buildings.csv`：字段为 `building_id, block, protection_level, permitted_work, condition`。
  - `permitted_work` 以分号分隔，表示该建筑**允许实施的工程类型集合**，是保护审查的硬边界。
  - 该字段为空表示建筑未声明任何许可范围，任何工程都将被可行性裁决否决。
- `proposals.csv`：字段为 `proposal_id, building_id, work, estimate_low, estimate_high, operator_id`。
  - `work` 必须落在目标建筑 `permitted_work` 内，否则方案不可行（一票否决，不参与评分）。
  - `estimate_low/estimate_high` 是成本区间；任一为空表示该侧未知，汇总时不得按零处理。
  - `operator_id` 为空表示没有运营责任方，建成后不得按稳定服务容量计入收益。
- `access-links.csv`：字段为 `proposal_id, service_id, group_code, minutes_before, minutes_after`。
  - 一条记录表示某方案对某群体（`group_code`）到达某服务（`service_id`）的通行时间影响。
  - 同一 `(service_id, group_code)` 可被多个方案改善（街巷外溢），组合评估时按最优施工后耗时去重。
  - 任一耗时字段为空表示节省量未知；施工后高于施工前视为通行恶化并显式告警。
- `operations.csv`：字段为 `operator_id, service_id, capacity_per_day, confirmed_start`。
  - `confirmed_start` 为空表示启用日期未确认，容量只能列为“未确认”，不计入稳定容量。
  - 方案指定的运营方在此表中没有对应服务承诺时，容量同样不可计入。

日期字段使用 ISO 8601 格式；空单元格表示未知或未提供，不代表数值零。

## 已知数据缺口

当前合成输入**未包含**以下决策维度，分析层不会用假设值填补，而会在报告的“不确定性与数据缺口”一节显式声明：

- 施工影响（扬尘、噪声、临时封路、商户周转等）；
- 运营期成本（人员、维护、补贴），因此容量不等于可持续运营能力；
- 居民需求权重与代表性说明（需通过独立权重文件提供，见 `docs/decision-method.md`）。
