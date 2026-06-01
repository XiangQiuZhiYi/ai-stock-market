# AI A股盯盘系统

## 项目概述

5000 元小资金 A 股盯盘系统，覆盖选股、分析、模拟交易全流程。基于 Textual 终端 UI 展示，支持定时自动分析并输出买卖建议。

## 快速开始

```bash
# 激活虚拟环境
source .venv/bin/activate

# 启动终端面板（实时行情+持仓+建议展示）
python3 dashboard.py

# 运行一次完整分析（拉数据+评分+生成建议）
python3 collect_for_ai.py

# 初始化持仓文件（首次使用/重置）
python3 init_portfolio.py
```

## 核心架构

```
┌─────────────────────────────────────────────────────────┐
│                   dashboard.py (终端UI)                   │
│    读取 suggestions.json + portfolio.json 实时展示        │
└──────────────────────────┬──────────────────────────────┘
                           │ 读取
┌──────────────────────────▼──────────────────────────────┐
│              collect_for_ai.py (主分析入口)               │
│  拉取行情 → 筛选候选 → 综合评分 → 写入 suggestions.json   │
└──────────────────────────┬──────────────────────────────┘
                           │ 调用
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│  data.py     │  │ analysis.py  │  │  portfolio.py    │
│  数据采集层   │  │  分析评分层   │  │  持仓管理层       │
└──────────────┘  └──────┬───────┘  └──────────────────┘
                         │ 调用
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│capital_flow.py│ │ patterns.py  │ │news_sentiment.py │
│  资金流向     │ │  形态识别     │ │  消息面情绪       │
└──────────────┘ └──────────────┘ └──────────────────┘
```

## 文件说明

| 文件 | 功能 |
|------|------|
| `config.py` | 全局配置（资金、交易时间、文件路径） |
| `data.py` | 数据采集：全市场行情、K线、分时、个股报价 |
| `analysis.py` | 综合评分引擎：调用各分析模块，输出 0-100 分 |
| `capital_flow.py` | 资金流向分析：主力净流入/流出 |
| `patterns.py` | 形态识别：新高、平台突破、回踩均线等 |
| `news_sentiment.py` | 消息面情绪：新闻关键词利好/利空判定 |
| `portfolio.py` | 持仓管理：买入、卖出、手续费计算、止盈止损 |
| `collect_for_ai.py` | 主分析入口：拉数据→评分→生成 suggestions.json |
| `dashboard.py` | Textual 终端面板 UI |
| `init_portfolio.py` | 初始化持仓文件 |

## 数据文件

| 文件 | 说明 |
|------|------|
| `portfolio.json` | 当前持仓数据（现金、持仓列表、交易历史） |
| `suggestions.json` | 最新分析建议（面板读取展示） |
| `market_data.json` | 最近一次行情快照 |
| `analysis_context.json` | 分析上下文（可供外部AI使用） |

---

## 分析体系详解

### 评分模型（满分 100，基准 50）

评分由 **4 大维度 10 个指标** 综合得出：

#### 一、技术面（基础评分）

| # | 指标 | 看多条件 | 加分 | 看空条件 | 减分 |
|---|------|----------|------|----------|------|
| 1 | 均线系统 | MA5>MA10>MA20 多头排列 | +15 | MA5<MA10<MA20 空头排列 | -15 |
| 2 | RSI(14) | <30 超卖 | +15 | >70 超买 | -15 |
| 3 | MACD | DIF上穿DEA（金叉） | +20 | DIF下穿DEA（死叉） | -20 |
| 4 | 布林带 | 触及下轨 | +10 | 触及上轨 | -10 |
| 5 | KDJ | K上穿D（金叉） | +10 | K下穿D（死叉） | -10 |
| 6 | 成交量 | 放量>2倍 | +5 | 缩量<0.5倍 | -5 |
| 7 | 当日涨跌 | 大涨>5% | +3 | 大跌>5% | -3 |

#### 二、资金面（capital_flow.py）

通过东财 `fflow/kline/get` 接口获取近5日主力资金流向。

| 条件 | 评分调整 |
|------|----------|
| 主力连续3日+流入 | +15 |
| 主力连续2日流入 | +10 |
| 今日大额流入(>500万) | +8 |
| 主力连续3日+流出 | -15 |
| 主力连续2日流出 | -10 |
| 今日大额流出(>500万) | -8 |
| 5日累计>2000万额外加成 | ±5 |

#### 三、形态面（patterns.py）

基于90日K线识别6种形态：

| 形态 | 条件 | 评分调整 |
|------|------|----------|
| 60日新高 | 当前价≥60日最高 | +12 |
| 20日新高 | 当前价≥20日最高 | +8 |
| 放量突破平台 | 横盘(振幅<15%)后放量突破 | +15 |
| 缩量回踩MA20 | 均线向上+价在MA20±3%+缩量 | +12 |
| 放量突破前高 | 突破20日高+量>2倍 | +15 |
| 底部放量反转 | 跌>10%后出现放量阳线 | +12 |
| 连续4-5阴 | 连续阴线下跌 | -8/-12 |
| 60日新低 | 当前价≤60日最低 | -10 |

#### 四、消息面（news_sentiment.py）

通过东财搜索接口获取个股近7天新闻，关键词匹配判定情绪：

**利好关键词（部分）：**
- 强利好(+10/条)：业绩大增、回购、中标、重大合同、战略合作
- 温和利好(+4/条)：分红、基金调研、扩产、北向资金买入

**利空关键词（部分）：**
- 强利空(-12/条)：减持、立案调查、退市、亏损、暴雷
- 温和利空(-5/条)：质押、解禁、高管辞职

**评分映射：**
| 净情绪分 | 评分调整 |
|----------|----------|
| ≥15 | +20 |
| 8~14 | +12 |
| 3~7 | +5 |
| -3~-7 | -5 |
| -8~-14 | -12 |
| ≤-15 | -20 |

### 最终信号

| 评分范围 | 信号 | 含义 |
|----------|------|------|
| ≥70 | 买入 | 多维度共振，强势 |
| 55-69 | 关注 | 有亮点但未达共振 |
| 46-54 | 中性 | 方向不明 |
| 31-45 | 回避 | 偏空信号 |
| ≤30 | 卖出 | 多维度看空 |

---

## 选股流程

```python
# 完整选股流程（collect_for_ai.py 内部逻辑）

1. 拉取全市场行情（东财接口，前500只活跃股）
2. 初筛过滤：
   - 价格: 1~50 元（确保5000元能买1手）
   - 成交量: ≥50万股（排除僵尸股）
3. 综合评分（top_n * 5 = 50~100只深度分析）：
   - 拉取90日K线 → 技术指标计算
   - 拉取5日资金流向 → 主力态度
   - K线形态识别 → 买卖形态
   - 近7天新闻 → 消息面情绪
4. 按评分排序，输出 Top 15-20
5. 自动生成 suggestions.json：
   - 评分≥70 且非持仓 → 买入建议
   - 评分55-69 → 关注列表
   - 评分≤40 且涨幅大 → 不追高黑名单
   - 已持仓 → 持仓操作建议
```

---

## API 接口说明

所有接口均为东财免费接口，无需 API Key。

| 接口 | 用途 | URL |
|------|------|-----|
| 活跃股列表 | 全市场行情 | `push2.eastmoney.com/api/qt/clist/get` |
| 个股报价 | 实时价格 | `push2.eastmoney.com/api/qt/stock/get` |
| K线数据 | 技术分析 | `money.finance.sina.com.cn` (新浪) |
| 分时数据 | 走势图 | `push2.eastmoney.com/api/qt/stock/trends2/get` |
| 资金流向 | 主力态度 | `push2.eastmoney.com/api/qt/stock/fflow/kline/get` |
| 新闻搜索 | 消息面 | `search-api-web.eastmoney.com/search/jsonp` |

### 接口限制

- 全市场列表接口在**非交易时段可能不可用**
- 分时数据在**休市期间返回空**
- 个股报价和资金流向接口**全天可用**
- 新闻搜索接口**全天可用**

---

## 编程调用示例

### 分析单只股票

```python
from analysis import analyze_stock

result = analyze_stock(
    code="300184",
    name="力源信息",
    current_price=16.58,
    change_pct=-2.4
)
print(f"评分: {result['score']} → {result['signal']}")
print(f"信号: {result['signals']}")
print(f"资金: {result['capital_flow']}")
print(f"消息: {result['news_sentiment']}, 新闻: {result['key_news']}")
```

### 批量选股评分

```python
from data import get_all_stocks, filter_candidates
from analysis import score_candidates

df = get_all_stocks()
candidates = filter_candidates(df)
top = score_candidates(candidates, top_n=15)

for s in top:
    print(f"{s['code']} {s['name']} 评分:{s['score']} {s['signal']}")
```

### 单独调用资金流向

```python
from capital_flow import analyze_capital_flow

flow = analyze_capital_flow("300184")
print(f"主力: {flow['signal']}, 评分调整: {flow['score_adj']}")
```

### 单独调用消息面

```python
from news_sentiment import analyze_news_sentiment

news = analyze_news_sentiment("300184", "力源信息")
print(f"情绪: {news['sentiment']}, 调整: {news['score_adj']}")
print(f"利好: {news['positive_hits']}")
print(f"利空: {news['negative_hits']}")
```

### 单独调用形态识别

```python
from data import get_kline
from patterns import detect_patterns

kline = get_kline("300184", period="daily", days=90)
result = detect_patterns(kline, current_price=16.58)
print(f"形态: {result['patterns']}, 信号: {result['signals']}")
```

### 模拟买卖

```python
from portfolio import load_portfolio, record_buy, record_sell, get_portfolio_summary

pf = load_portfolio()

# 买入
r = record_buy(pf, "600021", "上海电力", 100, 21.96)
print(f"买入: {r}")

# 查看持仓
print(get_portfolio_summary(pf))

# 卖出
r = record_sell(pf, "600021", 100, 23.50)
print(f"卖出: {r}, 盈亏: {r.get('profit')}")
```

### 一键运行完整分析并更新面板

```python
from collect_for_ai import collect
collect()  # 自动拉数据+评分+写入suggestions.json
```

---

## 配置说明（config.py）

```python
BUDGET = 5000          # 总资金
MAX_POSITIONS = 3      # 最大同时持仓数
MIN_VOLUME = 500000    # 最小日成交量(股)
MAX_PRICE = 50         # 最大股价(保证能买1手)
REFRESH_INTERVAL = 30  # 面板刷新间隔(秒)
AI_ANALYSIS_INTERVAL = 300  # 深度分析间隔(秒)
```

## 交易费率（portfolio.py）

```
佣金: 万2.5（最低5元）
印花税: 千0.5（仅卖出，2023.8.28起）
过户费: 万0.1（双向）
```

---

## 定时运行建议

交易时段每5分钟运行一次分析：

```bash
# crontab 示例
*/5 9-15 * * 1-5 cd /path/to/astock && .venv/bin/python collect_for_ai.py >> /tmp/astock.log 2>&1
```

或在另一个终端窗口循环运行：

```bash
while true; do
  .venv/bin/python collect_for_ai.py
  sleep 300
done
```

### macOS 三段分析提醒（早盘/午盘/尾盘）

如果你只需要“到点提醒去做分析”，可用 `notify_analysis.py` + `launchd`：

```bash
# 手动测试（应弹出系统通知）
.venv/bin/python notify_analysis.py morning
.venv/bin/python notify_analysis.py midday
.venv/bin/python notify_analysis.py afternoon
```

安装 LaunchAgent：

```bash
# 1) 复制模板到 LaunchAgents
cp launchd/com.astock.analysis-reminder.plist ~/Library/LaunchAgents/

# 2) 编辑 plist 中两个绝对路径（python 与 notify_analysis.py）
#    /ABSOLUTE/PATH/TO/astock/.venv/bin/python
#    /ABSOLUTE/PATH/TO/astock/notify_analysis.py

# 3) 重新加载
launchctl unload ~/Library/LaunchAgents/com.astock.analysis-reminder.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.astock.analysis-reminder.plist
```

默认提醒时间：
- 10:00（早盘）
- 11:25（午盘）
- 14:50（尾盘）

说明：
- 脚本仅工作日提醒，周末自动跳过。
- 日志输出到 `/tmp/astock-analysis-reminder.log` 与 `/tmp/astock-analysis-reminder.err`。
