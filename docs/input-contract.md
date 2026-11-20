# 合成输入材料

这里的记录均为合成数据，不对应真实住户、项目或城市。每个文件表示一个来源数据表，不包含分析结论；解释记录时应保留来源标识和修订关系。

- `buildings.csv`：CSV 表格，字段为 `building_id, block, protection_level, permitted_work, condition`。日期字段使用 ISO 8601 格式；空单元格表示未知或未提供，不代表数值零。
- `proposals.csv`：CSV 表格，字段为 `proposal_id, building_id, work, estimate_low, estimate_high, operator_id`。日期字段使用 ISO 8601 格式；空单元格表示未知或未提供，不代表数值零。
- `access-links.csv`：CSV 表格，字段为 `proposal_id, service_id, group_code, minutes_before, minutes_after`。日期字段使用 ISO 8601 格式；空单元格表示未知或未提供，不代表数值零。
- `operations.csv`：CSV 表格，字段为 `operator_id, service_id, capacity_per_day, confirmed_start`。日期字段使用 ISO 8601 格式；空单元格表示未知或未提供，不代表数值零。
