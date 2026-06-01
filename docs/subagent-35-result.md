# #35 波峰波谷结构与趋势线可视化实施结果

## 修改文件

1. `sagent/kline.py` — 新增 `find_swing_highs()` 函数
2. `sagent/chart.py` — 新增 `plot_structure_chart()` 函数
3. `tests/test_sagent_behaviors.py` — 新增 4 个测试用例

## 新增函数

### kline.py — `find_swing_highs()`

```python
def find_swing_highs(
    bars: list[DailyBar], left: int = 5, right: int = 3
) -> list[tuple[int, float]]:
    """检测波峰（swing high）。

    对称的 swing high 检测：某日 high 同时大于左侧 left 个和
    右侧 right 个相邻日的 high，则该日为一个 swing high。

    Returns:
        [(索引, high值), ...] 按索引升序排列。
    """
```

与 `find_swing_lows()` 完全对称：`bars[i].high > bars[j].high` for all j in `[i-left, i+right]`, j != i。

### chart.py — `plot_structure_chart()`

```python
def plot_structure_chart(
    bars: list[DailyBar],
    signal_idx: int,
    symbol: str = "",
    output_path: str | None = None,
) -> go.Figure:
```

在 K 线图上标注 6 个标注层：

| # | 标注层 | 颜色/样式 | 说明 |
|---|--------|-----------|------|
| 1 | Swing Highs | 红色 ▼ 三角 + "高 xx.xx" | 波峰标注 |
| 2 | Swing Lows | 绿色 ▲ 三角 + "低 xx.xx" | 波谷标注 |
| 3 | Higher Highs | 红色虚线 | 连接递增的波峰 |
| 4 | Higher Lows | 绿色虚线 | 连接递增的波谷 |
| 5 | Key Low | 蓝色大 ★ + "Key Low xx.xx" | 关键低点特别标注 |
| 6 | 趋势破坏参考 | 紫色水平虚线 | find_trend_break_ref 结果 |

内部调用 `plot_stock_kline()` 绘制基础 K 线，再叠加 swing 标注。

## 新增测试用例（4 个）

| # | 测试名 | 验证内容 |
|---|--------|----------|
| 1 | `test_find_swing_highs_basic` | 单一尖峰检测：lows=[10,10,10,10,10,14,...] → high=15 在索引5 被识别 |
| 2 | `test_find_swing_highs_multiple` | 两个尖峰：索引5(high=20) + 索引14(high=15) |
| 3 | `test_find_swing_highs_no_swing` | 单调上升序列无 swing high → 空列表 |
| 4 | `test_plot_structure_chart_returns_figure` | 返回 Figure，标题含"波峰波谷"，有趋势破坏参考线 |

## 验证结果

```
73 passed in 1.29s
```

- 原有 69 个测试全部通过
- 新增 4 个测试全部通过

## 设计说明

### Higher Highs / Higher Lows 连线算法

对相邻 swing points 检查是否递增：

```python
for i in range(1, len(swing_highs)):
    if swing_highs[i].high > swing_highs[i-1].high:
        # 加入连线
```

只连接递增的点对，不连接下降段。如果连续 3 个 swing highs 递增（如 10→15→20），会画出完整连线。

### Key Low 星号标注

使用 `find_key_low()` 自动获取 key_low 位置，在 K 线上用 18px 蓝色星号标注，附带文字 "Key Low xx.xx"。

### 趋势破坏参考线

调用 `find_trend_break_ref()` 获取趋势破坏参考位，以紫色水平虚线显示。
