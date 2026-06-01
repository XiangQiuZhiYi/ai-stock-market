---
name: afternoon-analysis
description: "尾盘分析（14:50）。执行 A 股尾盘全日复盘和次日展望，对比计划与实际、盈亏归因、提炼经验教训、筛选明日关注标的。Use when: 尾盘分析、收盘复盘、全日总结、明日计划、经验教训、次日展望。"
argument-hint: "执行尾盘分析，复盘全日并展望明日"
---

# 🌇 尾盘分析 (14:50)

## 定位
专注**全日复盘 + 次日展望**。这是一天中最重要的"学习"时段，总结经验、发现规律、为明天做准备。

## 执行步骤

### 1. 回顾全日记录
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
# 查看今日所有分析
ls analysis_logs/$(date +%Y-%m-%d)/

# 读取早盘计划
cat analysis_logs/$(date +%Y-%m-%d)/morning.json | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('早盘计划:', d.get('decision_summary',''))
for a in d.get('action_plan',[]): print(f'  {a[\"type\"]} {a[\"code\"]} {a[\"name\"]}')"

# 读取午间策略
cat analysis_logs/$(date +%Y-%m-%d)/midday.json | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('午间策略:', d.get('afternoon_strategy',[]))" 2>/dev/null || echo "无午间记录"
```

### 2. 执行数据分析
```bash
.venv/bin/python scheduled_analysis.py afternoon
```

### 3. 全日复盘（最核心环节）

#### A. 计划 vs 实际对比
用表格梳理：
```
| 计划操作 | 是否执行 | 实际结果 | 反思 |
|---------|---------|---------|------|
| 买入 xxx | 是/否 | 盈亏xxx | 判断正确/需改进 |
| 卖出 xxx | 是/否 | 避损xxx | 决策果断/犹豫 |
```

#### B. 盈亏归因（逐笔分析）
对今日每一笔变动：
- **正确的决策**：为什么对？能否制度化为规则？
- **错误的决策**：为什么错？是信息不足还是情绪干扰？
- **错过的机会**：是否在能力圈内？信号是否够强？

#### C. 系统反馈
- 评分系统今天的表现如何？（高分股是否涨了？低分股是否跌了？）
- 资金流向指标是否准确？
- 形态识别是否发出了有效信号？
- 消息面分析是否捕捉到了关键信息？

### 4. 经验教训提炼
格式：
```
## 今日教训

### 做得好的
1. xxx（继续保持）

### 需改进的
1. xxx → 改进方案：xxx

### 新发现
1. xxx（记录观察，待验证）
```

### 5. 次日展望

#### 大盘判断
- 今日收盘趋势（收阳/收阴/十字星）暗示明日方向
- 成交量变化趋势
- 外围市场情况（如有）

#### 明日关注标的
从今日 Top 评分中筛选，需满足：
- 评分 ≥ 65
- 非已持仓
- 有明确技术信号
- 价格在可买范围内（≤50元，现金够买1手）

格式：
```
## 明日关注

### 首选（评分≥75）
- {代码} {名称} — 评分xx, 信号: xxx | 目标买入价: xxx

### 备选（评分65-74）
- {代码} {名称} — 评分xx, 信号: xxx | 条件: xxx时考虑

### 风险提醒
- {持仓A} — 若明日跌破xxx需止损
- 若大盘低开>1%，暂缓所有买入计划
```

#### 明日操作原则
根据今日市场环境设定明日基调：
- 强势市场 → 可积极，挂限价单等回踩
- 震荡市场 → 控制仓位，快进快出
- 弱势市场 → 只守不攻，专注止损

### 6. 保存分析记录（必做）

`scheduled_analysis.py afternoon` 已自动保存量化数据到 `analysis_logs/YYYY-MM-DD/afternoon.json`。

**检查并确认关键字段已写入：**
```bash
cat analysis_logs/$(date +%Y-%m-%d)/afternoon.json | .venv/bin/python -c "
import json,sys; d=json.load(sys.stdin)
print('review_summary:', d.get('review_summary',''))
print('next_day_plan:', d.get('next_day_plan',''))
print('next_day_focus:', d.get('next_day_focus',[]))
print('lessons:', d.get('lessons',''))"
```

保存的 JSON 必须包含以下字段（供明日早盘读取）：
```json
{
  "session": "afternoon",
  "timestamp": "ISO时间",
  "focus": "全日复盘+次日展望",
  "morning_reference": { "decision": "", "actions": [] },
  "midday_reference": { "strategy": [] },
  "market": { "stats": {}, "day_summary": "" },
  "portfolio": {
    "cash": 0, "total_value": 0, "profit": 0,
    "day_change": 0, "positions": []
  },
  "top_candidates": [],
  "review_summary": "一句话总结今日（明日早盘必读）",
  "next_day_plan": "明日核心计划（明日早盘必读）",
  "next_day_focus": [
    { "code": "300184", "name": "力源信息", "score": 75, "signal": "MACD金叉" }
  ],
  "lessons": "今日经验教训"
}
```

**如果脚本输出缺少关键字段，手动补充：**
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
.venv/bin/python -c "
import json
path = 'analysis_logs/$(date +%Y-%m-%d)/afternoon.json'
with open(path, 'r') as f: d = json.load(f)
# 补充缺失字段
d.setdefault('review_summary', '待补充')
d.setdefault('next_day_plan', '待补充')
d.setdefault('next_day_focus', [])
d.setdefault('lessons', '待补充')
with open(path, 'w') as f: json.dump(d, f, ensure_ascii=False, indent=2)
print('已确认/补充关键字段')"
```

确保以下内容已写入（这是明日早盘的输入）：
- `review_summary`: 一句话总结今日
- `next_day_plan`: 明日核心计划
- `next_day_focus`: 明日关注标的列表（含代码、名称、评分、信号）
- `lessons`: 今日经验教训

## 复盘思维框架

### 三个层次
1. **操作层**：今天做对了什么/做错了什么
2. **策略层**：现有策略是否需要调整
3. **系统层**：分析系统本身是否需要优化

### 避免的陷阱
- **后视镜偏差**：不要用收盘结果反推早盘的"应该"
- **过度归因**：一天的涨跌可能只是随机波动
- **情绪化总结**：亏了不要自责过度，赚了不要过度自信
- **忽略基准**：个股表现要对比大盘和板块

### 好的复盘标志
- 能明确说出明天要做什么（具体到代码和价位）
- 能解释今天每一笔决策的逻辑
- 发现了一个可验证的规律或假设

## 输出文件
- `analysis_logs/YYYY-MM-DD/afternoon.json` — 尾盘复盘记录
- `suggestions.json` — 面板数据更新（含明日关注）

## 与其他 Skill 的衔接
- 本次 `review_summary` + `next_day_plan` → 明日早盘 morning skill 第一步读取
- 本次 `next_day_focus` → 明日早盘优先分析这些标的
- 形成闭环：早盘计划 → 午间检视 → 尾盘复盘 → 次日早盘参考
