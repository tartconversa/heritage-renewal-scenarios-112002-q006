# Heritage Renewal Scenarios

历史街区更新方案比较的决策分析工具：把工程投入、居民可达性、保护要求与运营
能力放进同一份可比较资料，同时保留价值判断的边界。全部为合成数据，仅使用
Python 3.12+ 标准库。

## 核心原则

- **保护底线一票否决**：工程超出建筑 `permitted_work` 即不可行，不进入评分，
  不可被高分指标折算抵消。
- **未知不是零，成本保留区间**：空单元格按未知处理，不补零、不压成点估计。
- **无运营责任方不计稳定容量**：启用日期未确认、无服务承诺、无运营方的容量
  分层标注，只有确认容量计入收益。
- **权重外生**：无权重文件只出分群体视角，不包装“客观总分”；有权重也附出来源
  与代表性边界。
- **版本留痕**：评估与意见绑定输入文件哈希快照，输入修订后旧意见标注过期但
  原样保留。

## 运行环境

Python 3.12 或更新版本，仅使用标准库。

## 常用命令

```bash
# 校验输入合同与引用完整性（有阻断错误时退出码为 2）
PYTHONPATH=src python -m renewal_analytics validate --data data

# 计算输入快照哈希
PYTHONPATH=src python -m renewal_analytics snapshot --data data

# 完整评估，输出 Markdown 决策资料与 JSON 机器结果到 reports/
PYTHONPATH=src python -m renewal_analytics assess --data data --out reports

# 带外生群体权重的评估（权重示例见 examples/weights.csv）
PYTHONPATH=src python -m renewal_analytics assess \
  --data data --out reports --weights examples/weights.csv

# 追加一条与当前快照绑定的评估意见
PYTHONPATH=src python -m renewal_analytics opinion --data data --out reports \
  --run-id <run-id> --author 居民代表甲 --stance support \
  --basis "通行时间缩短明显" --proposal S-1
```

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖：输入合同校验、保护否决、可达去重与恶化告警、容量四态认定、
权重边界、组合枚举、需求追溯链、快照差异与意见过期标注、CLI 端到端。

## 文档

- `docs/input-contract.md`：输入字段合同与已知数据缺口
- `docs/decision-method.md`：决策方法、容量认定规则与价值判断边界
