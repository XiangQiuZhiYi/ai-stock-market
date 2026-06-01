---
name: morning-analysis
description: "早盘分析（10:00）。执行 A 股早盘买卖决策分析，回顾昨日复盘、运行数据分析、检查持仓风险、制定行动计划。Use when: 早盘分析、开盘决策、今日操作计划、买卖建议、持仓风险检查。"
argument-hint: "执行早盘分析，制定今日买卖计划"
---

# 🌅 早盘分析 (10:00)

## 定位
专注**买卖决策**。早盘是一天中最重要的分析时段，需要明确今天"做什么"。

## 执行步骤

### 1. 回顾昨日分析（必做）

**首先找到上一交易日的分析记录：**
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
# 列出最近的分析日志目录
ls -la analysis_logs/ | tail -5
```

**读取上一交易日的尾盘复盘（最重要）：**
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
# 找到最近一个有 afternoon.json 的日期
LAST_DAY=$(ls analysis_logs/ | sort | tail -1)
cat analysis_logs/$LAST_DAY/afternoon.json
```

需要从昨日尾盘记录中提取：
- `review_summary` — 昨日总结（验证是否与今日市场延续）
- `next_day_plan` — 昨日给今日的计划（今天要执行的）
- `next_day_focus` — 昨日筛选的今日关注标的（优先分析这些）
- `lessons` — 昨日经验教训（今日避免重复犯错）

**如果有昨日早盘/午间记录，也一并查看：**
```bash
ls analysis_logs/$LAST_DAY/
# 如有 morning.json 或 midday.json 也读取，了解昨日全天脉络
```

**关注要点：**
- 昨日哪些决策是对的/错的？今天能否改进？
- 昨日"明日关注"标的是否仍有效？开盘后是否符合预期？
- 是否有隔夜消息改变了判断？（财报、政策、外盘等）
- 昨日的经验教训，今天具体怎么落实？

### 2. 执行数据分析
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
.venv/bin/python scheduled_analysis.py morning
```

### 3. 检查持仓风险（必做）
对每一只持仓逐一确认：
- [ ] 当前价是否已触及止损？→ 必须卖出
- [ ] 当前价是否接近止盈？→ 考虑分批止盈
- [ ] 评分是否大幅下降（<50）？→ 考虑减仓
- [ ] 是否有利空消息？→ 评估影响

### 4. 制定行动计划
输出格式：
```
## 今日行动计划

### 卖出（优先执行）
- [ ] {代码} {名称} — 原因：xxx | 目标价：xxx

### 买入（确认后执行）
- [ ] {代码} {名称} — 原因：xxx | 限价：xxx | 止损：xxx | 止盈：xxx

### 持仓观望
- {代码} {名称} — 当前状态正常，继续持有

### 关键价位提醒
- {代码} 跌破 xxx 需止损
- {代码} 突破 xxx 可加仓
```

### 5. 保存分析记录（必做）

`scheduled_analysis.py morning` 已自动保存量化数据到 `analysis_logs/YYYY-MM-DD/morning.json`。

**检查保存的文件：**
```bash
cat analysis_logs/$(date +%Y-%m-%d)/morning.json | .venv/bin/python -c "
import json,sys; d=json.load(sys.stdin)
print('session:', d.get('session'))
print('decision_summary:', d.get('decision_summary'))
print('action_plan count:', len(d.get('action_plan',[])))" 
```

保存的 JSON 结构应包含：
```json
{
  "session": "morning",
  "timestamp": "ISO时间",
  "focus": "买卖决策",
  "yesterday_reference": {
    "date": "上一交易日日期",
    "summary": "昨日复盘要点"
  },
  "market": { "stats": {}, "mood": "" },
  "portfolio": { "cash": 0, "total_value": 0, "profit": 0, "positions": [] },
  "top_candidates": [],
  "action_plan": [
    { "type": "buy/sell", "code": "", "name": "", "reason": "" }
  ],
  "decision_summary": "一句话总结今日计划"
}
```

同时 `suggestions.json` 也已自动更新，面板会在下次刷新时展示。

## 决策原则

1. **止损第一**：触及止损线必须执行，不犹豫
2. **仓位控制**：单只不超过总资金40%，最多3只
3. **买入条件**：评分≥70 + 至少一个强信号（金叉/突破/资金流入）
4. **不追涨**：当日涨幅>5%的不追，等回踩
5. **市场弱势（均涨<-1%）时**：不开新仓

## 输出文件
- `analysis_logs/YYYY-MM-DD/morning.json` — 完整分析记录
- `suggestions.json` — 面板展示数据

## 关键 API 说明
- 数据来源：eastmoney 免费接口，无需 key
- 非交易时段会使用 `market_data.json` 缓存
- 资金流向 API 偶尔会超时，不影响核心评分
