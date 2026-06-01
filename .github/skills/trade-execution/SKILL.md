---
name: trade-execution
description: "交易执行与记录。在分析决策后执行实际的买入/卖出操作，更新 portfolio.json，确认手续费和止盈止损设置。Use when: 买入股票、卖出股票、记录交易、执行操作、更新持仓、调整止损止盈。"
argument-hint: "记录买卖操作，如：买入300184力源信息100股@17.0"
---

# 💰 交易执行与记录

## 定位
将分析决策转化为**实际操作记录**，确保每笔交易有据可查、费用透明、风控到位。

## 执行步骤

### 1. 确认交易前提
在执行任何交易前，必须确认：
- [ ] 该操作来源于分析系统的建议（评分、信号）
- [ ] 资金充足（买入）或持仓存在（卖出）
- [ ] 价格合理（非追涨杀跌）

```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
# 查看当前持仓和现金
.venv/bin/python -c "
from portfolio import load_portfolio, get_portfolio_summary
pf = load_portfolio()
s = get_portfolio_summary(pf)
print(f'现金: {s[\"cash\"]:.2f}')
print(f'持仓数: {s[\"positions\"]}')
print(f'总市值: {s[\"total_value\"]:.2f}')
for h in pf['holdings']:
    print(f'  {h[\"code\"]} {h[\"name\"]} {h[\"shares\"]}股 成本{h[\"buy_price\"]} 止损{h[\"stop_loss\"]} 止盈{h[\"take_profit\"]}')"
```

### 2. 执行买入
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
.venv/bin/python -c "
from portfolio import load_portfolio, record_buy
pf = load_portfolio()
result = record_buy(pf, code='{CODE}', name='{NAME}', shares={SHARES}, price={PRICE})
print(result)"
```

**买入检查清单：**
- 评分 ≥ 70？
- 当日涨幅 < 5%？（不追涨）
- 持仓数 < 3？
- 单只金额 < 总资金 40%（即 < 2000 元）？
- 市场均涨 > -1%？（弱势不开新仓）
- 止损位设在哪？（默认 -5%）
- 止盈位设在哪？（默认 +8%）

### 3. 执行卖出
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
.venv/bin/python -c "
from portfolio import load_portfolio, record_sell
pf = load_portfolio()
result = record_sell(pf, code='{CODE}', shares={SHARES}, price={PRICE})
print(result)"
```

**卖出触发条件（满足任一即可）：**
- 触及止损价
- 触及止盈价
- 评分跌破 45
- 出现强利空消息
- 用户主动决定

### 4. 调整止损/止盈（可选）
```bash
cd /Users/zhiyi/Documents/Code/XIAOBAO/astock
.venv/bin/python -c "
import json
from portfolio import load_portfolio, save_portfolio
pf = load_portfolio()
for h in pf['holdings']:
    if h['code'] == '{CODE}':
        h['stop_loss'] = {NEW_STOP_LOSS}
        h['take_profit'] = {NEW_TAKE_PROFIT}
        break
save_portfolio(pf)
print('已更新')"
```

**调整原则：**
- 只能上调止损（保护利润），不能下调
- 盈利超过 5% 时，止损上移至成本价（保本）
- 止盈可根据走势分批设定

### 5. 记录交易理由
每笔交易执行后，口头记录：
```
## 交易记录

| 字段 | 内容 |
|------|------|
| 时间 | YYYY-MM-DD HH:MM |
| 方向 | 买入/卖出 |
| 代码 | 300184 |
| 名称 | 力源信息 |
| 价格 | 17.00 |
| 数量 | 100股 |
| 手续费 | 5.02 |
| 理由 | 评分75，MACD金叉，主力净流入 |
| 止损 | 16.15 |
| 止盈 | 18.36 |
```

## 费率说明

| 费用项 | 比例 | 备注 |
|--------|------|------|
| 佣金 | 万2.5 | 最低5元，买卖双向 |
| 印花税 | 万5 | 仅卖出收取 |
| 过户费 | 万0.1 | 买卖双向 |

**示例：** 买入 100 股 @ 17.00 = 1700 元
- 佣金: max(1700×0.025%, 5) = 5.00
- 过户费: 1700×0.001% = 0.02
- 总费用: 5.02

## 仓位管理规则

- 总资金 5000 元，最多 3 只
- 单只上限 2000 元（40%）
- 首次建仓 100 股（最小单位）
- 加仓需在已盈利基础上，且新止损不低于成本

## 约束

- 不在开盘前 30 分钟内交易（9:30-10:00 观察期）
- 不在收盘前 10 分钟决策买入（14:50 后只卖不买）
- 每笔交易必须有明确理由，不凭"感觉"操作
- 连续亏损 2 笔后暂停一天，冷静复盘
