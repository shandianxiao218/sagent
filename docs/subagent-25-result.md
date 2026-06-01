# #25 预期盈亏比计算与筛选实施结果

## 修改文件

1. `sagent/kline.py` — describe_stock() 新增盈亏比计算和输出
2. `sagent/models.py` — Candidate 新增 risk_reward_ratio 字段
3. `sagent/technical.py` — technical_candidates() 新增盈亏比计算
4. `tests/test_sagent_behaviors.py` — 新增 3 个测试用例

## 变更内容

### 1. kline.py — describe_stock() 盈亏比

新增计算：
```python
risk = current - key_low  # 每股风险
r_ratio = (recent_high - current) / risk  # 当前距阶段高点的R值
target_2_5r = current + 2.5 * risk  # R=2.5 目标价
target_3r = current + 3.0 * risk    # R=3 目标价
```

K 线描述文本追加：
```
当前风险 X.XX 元，盈亏比 R=2.5 价位 XX.XX、R=3 价位 XX.XX，止损价 XX.XX。
```

fields 新增字段：
- `risk`: 每股风险（买入价 - key_low）
- `r_ratio`: 当前价格距阶段高点的R倍数
- `target_2_5r`: R=2.5 目标价
- `target_3r`: R=3 目标价

### 2. models.py — Candidate

```python
@dataclass(frozen=True)
class Candidate:
    ...
    risk_reward_ratio: float = 0.0  # 预期盈亏比
```

### 3. technical.py — technical_candidates()

用回调区间最低价近似 key_low 计算盈亏比：
```python
pullback_low = min(closes[-30:])
risk = current - pullback_low
reward = high_60 - current
risk_reward = reward / risk if risk > 0 else 0.0
```

- metrics 中新增 `risk_reward_ratio` 字段
- Candidate 构造时传入 `risk_reward_ratio=round(risk_reward, 2)`
- **不增加新的排除条件**（R < 2.0 的信号仍保留，只是标记）

### 4. 新增测试用例

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_describe_stock_includes_risk_reward_info` | fields 中有 risk/r_ratio/target_2_5r/target_3r，文本包含"R=2.5"、"R=3"、"止损价" |
| 2 | `test_candidate_includes_risk_reward_ratio` | candidate.metrics 和 candidate.risk_reward_ratio 都有值 |
| 3 | `test_risk_reward_ratio_calculation` | 构造 260+ bars 验证盈亏比数学正确（target_3r > target_2_5r > current） |

## 验证结果

```
50 passed in 0.38s
```

- 原有 47 个测试全部通过
- 新增 3 个盈亏比测试全部通过
- Lint clean

## 向后兼容性

- Candidate 新增 `risk_reward_ratio` 有默认值 0.0
- KlineDescription.fields 新增 4 个字段
- 文本长度仍控制在 max_chars 内（900字符）
- technical_candidates 的筛选条件不变（仍要求 4 个原因全满足）

## 设计决策

1. **不增加 R ≥ 2.0 排除条件**：按任务要求只增加信息不增加排除。后续可通过 sensitivity 分析确定最佳阈值。
2. **technical_candidates 用 min(closes[-30:]) 近似 key_low**：避免调用 find_key_low（需要完整 bars 列表和 swing low 计算），在粗筛阶段用简化估算即可。正式 key_low 在 describe_stock 中计算。
3. **reward = high_60 - current**：用第一波高点距当前价的距离作为潜在收益估算。
