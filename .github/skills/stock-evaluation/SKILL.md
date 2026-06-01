---
name: stock-evaluation
description: "个股深度评估。对单只股票进行全面的技术面、资金面、消息面分析，输出综合评分和买卖建议。Use when: 评估某只股票、个股分析、深度分析、能不能买、值不值得持有、技术面怎么样。"
argument-hint: "提供股票代码或名称，如：评估300184力源信息"
---

# 🔍 个股深度评估

## 定位
对**单只股票**进行全维度深度分析，输出清晰的结论：能买/不能买/继续持有/该卖。

## 执行步骤

### 1. 获取基础数据
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
.venv/bin/python -c "
from data import get_stock_quote, get_kline
from analysis import analyze_stock
import json

code = '{CODE}'
name = '{NAME}'

# 获取实时报价
quote = get_stock_quote(code)
print('=== 实时报价 ===')
print(json.dumps(quote, ensure_ascii=False, indent=2))

# 获取K线
kline = get_kline(code)
if kline is not None:
    print(f'\n=== K线数据 (最近{len(kline)}根) ===')
    print(kline.tail(5).to_string())

# 综合分析
price = quote.get('price', 0) if quote else 0
change_pct = quote.get('change_pct', 0) if quote else 0
result = analyze_stock(code, name, price, change_pct)
print(f'\n=== 综合评分 ===')
print(json.dumps(result, ensure_ascii=False, indent=2))"
```

### 2. 技术面分析

逐项解读指标：

| 指标 | 看什么 | 多头信号 | 空头信号 |
|------|--------|----------|----------|
| MA均线 | 5/10/20/60日排列 | 多头排列(5>10>20) | 空头排列(5<10<20) |
| MACD | DIF/DEA交叉 | 金叉(DIF上穿DEA) | 死叉(DIF下穿DEA) |
| RSI | 超买超卖 | 30以下(超卖反弹) | 70以上(超买回调) |
| KDJ | 金叉死叉 | J<20后上穿 | J>80后下穿 |
| 布林带 | 价格位置 | 触下轨反弹 | 触上轨回落 |
| 成交量 | 量价配合 | 放量突破 | 放量下跌 |

### 3. 资金面分析
```bash
.venv/bin/python -c "
from capital_flow import analyze_capital_flow
import json
result = analyze_capital_flow('{CODE}')
print(json.dumps(result, ensure_ascii=False, indent=2))"
```

解读要点：
- 主力净流入 > 0 且连续 → 积极信号
- 主力净流出 + 股价下跌 → 危险信号
- 注意：资金流向 API 偶尔超时，单一数据不作为决策依据

### 4. 消息面分析
```bash
.venv/bin/python -c "
from news_sentiment import analyze_news_sentiment
import json
result = analyze_news_sentiment('{CODE}', '{NAME}')
print(json.dumps(result, ensure_ascii=False, indent=2))"
```

解读要点：
- 强利好（中标/业绩大增/回购）→ 评分加分
- 强利空（减持/违规/亏损）→ 一票否决
- 无消息 → 中性，不影响判断

### 5. 形态分析
```bash
.venv/bin/python -c "
from data import get_kline
from patterns import detect_patterns
import json
kline = get_kline('{CODE}')
result = detect_patterns(kline)
print(json.dumps(result, ensure_ascii=False, indent=2))"
```

关键形态：
- ✅ 积极：20/60日新高、平台突破、缩量回踩均线、底部放量
- ⚠️ 消极：60日新低、放量下跌、破位均线

### 6. 综合评估输出

```
## {CODE} {NAME} 深度评估

### 结论：【强烈推荐买入 / 可考虑买入 / 观望 / 建议卖出 / 强烈建议卖出】

### 评分：XX/100

### 核心逻辑
1. {最重要的看多/看空理由}
2. {第二重要的理由}
3. {第三重要的理由}

### 技术面 (权重40%)
- MA排列：xxx
- MACD状态：xxx
- RSI/KDJ：xxx
- 形态：xxx

### 资金面 (权重30%)
- 主力流向：xxx
- 连续天数：xxx

### 消息面 (权重20%)
- 最新消息：xxx
- 情绪判定：xxx

### 形态面 (权重10%)
- 识别形态：xxx

### 操作建议
- 建议价位：xxx（当前价 vs 建议买入价）
- 止损位：xxx（理由）
- 止盈位：xxx（理由）
- 仓位建议：xxx 股（占总资金 xx%）

### 风险提示
- 主要风险：xxx
- 关注事件：xxx
```

## 评分标准

| 分数段 | 含义 | 建议 |
|--------|------|------|
| 80-100 | 强势，多信号共振 | 可积极买入 |
| 70-79 | 偏强，信号明确 | 可考虑买入 |
| 55-69 | 中性，方向不明 | 观望，加入关注 |
| 45-54 | 偏弱，部分信号转空 | 持有者考虑减仓 |
| 0-44 | 弱势，多项看空 | 不买，持有者卖出 |

## 约束

- 必须先获取实时数据，不凭记忆判断
- 单一指标不构成买卖依据，需多维度交叉验证
- 评分仅供参考，最终决策需结合市场环境
- 明确标注数据时效性（交易时段实时 vs 缓存数据）
- 不做收益承诺，不提供确定性预测
