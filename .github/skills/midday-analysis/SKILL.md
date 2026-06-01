---
name: midday-analysis
description: "午间分析（11:25）。执行 A 股午间复盘和策略调整，回顾早盘计划执行情况、分析上午走势、制定下午策略。Use when: 午间分析、午盘复盘、上午总结、下午策略、盘中调整。"
argument-hint: "执行午间分析，复盘上午走势并调整下午策略"
---

# ☀️ 午间分析 (11:25)

## 定位
专注**复盘和策略调整**。上午收盘，数据相对完整，适合冷静回顾上午走势并调整下午策略。

## 执行步骤

### 1. 回顾早盘计划
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
cat analysis_logs/$(date +%Y-%m-%d)/morning.json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('早盘决策:', d.get('decision_summary',''))
print('行动计划:')
for a in d.get('action_plan',[]):
    print(f'  {a[\"type\"]} {a[\"code\"]} {a[\"name\"]} — {a[\"reason\"]}')"
```

**思考：**
- 早盘计划的操作执行了吗？为什么执行/未执行？
- 未执行的原因是价格没到？还是临时改变了判断？

### 2. 执行数据分析
```bash
.venv/bin/python scheduled_analysis.py midday
```

### 3. 上午复盘（核心环节）

#### 持仓变化追踪
对比早盘数据，回答：
- 持仓浮盈较早盘变化了多少？
- 变化的原因是什么？（大盘带动 / 个股独立走势 / 板块轮动）
- 持仓评分有无明显变化？

#### 市场环境变化
- 上午哪些板块走强/走弱？
- 是否有盘中突发消息影响市场？
- 资金流向是否发生转变？

#### 错判检视
- 如果买了不该买的：分析为什么当时会做出错误判断
- 如果错过了机会：是信号不够明确还是执行不够果断

### 4. 下午策略制定
```
## 下午策略

### 风险管理
- {持仓A} — 下午若跌破 xxx 需减仓/止损
- {持仓B} — 运行正常，继续持有

### 机会捕捉
- 若 {代码} 回踩至 xxx 附近可考虑建仓
- 若大盘企稳回升，关注 {板块} 方向

### 不做的事
- 不追涨（上午涨幅已大的标的）
- 不在尾盘前仓促决策
```

### 5. 保存分析记录（必做）

`scheduled_analysis.py midday` 已自动保存量化数据到 `analysis_logs/YYYY-MM-DD/midday.json`。

**检查保存的文件：**
```bash
cat analysis_logs/$(date +%Y-%m-%d)/midday.json | .venv/bin/python -c "
import json,sys; d=json.load(sys.stdin)
print('session:', d.get('session'))
print('review_summary:', d.get('review_summary',''))
print('afternoon_strategy:', d.get('afternoon_strategy',[]))"
```

保存的 JSON 结构应包含：
```json
{
  "session": "midday",
  "timestamp": "ISO时间",
  "focus": "复盘+策略调整",
  "morning_reference": {
    "decision": "早盘决策摘要",
    "actions": []
  },
  "market": { "stats": {}, "morning_vs_now": "" },
  "portfolio": {
    "cash": 0, "total_value": 0, "profit": 0,
    "day_change": 0, "positions": []
  },
  "review_summary": "上午走势一句话总结",
  "afternoon_strategy": ["下午策略要点1", "下午策略要点2"],
  "observations": "市场观察和思考记录"
}
```

### 6. 思考记录（可选但推荐）
记录今天的市场"感觉"和观察：
- 今天的走势符合预期吗？
- 有没有发现新的规律/异常？
- 对下午或明天有什么直觉判断？

## 分析维度

### 量价关系
- 上午成交量与昨日对比（放量/缩量）
- 涨跌停数量变化趋势
- 高位放量（警惕）vs 低位放量（关注）

### 板块轮动
- 对比早盘和午间，是否有板块切换
- 持续强势的板块 vs 冲高回落的板块
- 持仓所在板块的表现

### 情绪指标
- 涨跌比（>1.5 偏乐观，<0.7 偏悲观）
- 涨停/跌停数量
- 是否有恐慌/贪婪迹象

## 输出文件
- `analysis_logs/YYYY-MM-DD/midday.json` — 午间分析记录（含上午复盘 + 下午策略）
- `suggestions.json` — 面板数据更新

**重要：** 午间记录中的 `afternoon_strategy` 字段将在尾盘分析时被读取，用于对比"下午计划 vs 实际"。

## 注意事项
- 午间分析不要着急做决策，重在**观察和思考**
- 如果上午已执行了买卖，重点评估执行质量
- 避免因短期波动改变长期判断
- 记住：11:30-13:00 是冷静期，利用这段时间做好功课
