#!/usr/bin/env python3
"""A股中长期分析脚本。

这条分析链路与短线系统完全隔离：
1. 不写 suggestions.json / market_data.json
2. 不调用 collect_for_ai.py / scheduled_analysis.py
3. 仅输出 longterm_suggestions.json 和 longterm_logs/YYYY-MM-DD/longterm.json

定位：
- 持有周期：3-12个月
- 核心依据：长期趋势、估值粗筛、波动与回撤、30天新闻情绪
- 非核心依据：日内涨跌、分时图、短线资金异动
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from statistics import mean

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LONGTERM_LOG_DIR, LONGTERM_MAX_PRICE, LONGTERM_SUGGESTIONS_FILE
from data import get_all_stocks, get_kline, is_trading_time
from news_sentiment import get_stock_news


TZ = timezone(timedelta(hours=8))


def _ensure_log_dir(date_str: str) -> str:
    """创建中长期日志目录。独立目录避免被短线复盘读取。"""
    day_dir = os.path.join(LONGTERM_LOG_DIR, date_str)
    os.makedirs(day_dir, exist_ok=True)
    return day_dir


def _build_longterm_universe(df: pd.DataFrame) -> pd.DataFrame:
    """中长期候选池。

    与短线不同，不沿用短线 50 元限制，也不依赖短线成交量阈值；
    但为了贴合当前资金体量和用户要求，这里单独限制在 60 元以内；
    只过滤掉价格异常、成交极低和估值明显失真的标的。
    """
    if df.empty:
        return df
    filtered = df[
        (df["price"] > 1)
        & (df["price"] <= LONGTERM_MAX_PRICE)
        & (df["volume"] > 100000)
        & (df["change_pct"].notna())
    ].copy()
    # 中长期不希望把估值异常值直接打成高分，因此先清洗极端值。
    if "pe" in filtered.columns:
        filtered = filtered[(filtered["pe"].isna()) | ((filtered["pe"] > 0) & (filtered["pe"] < 200))]
    if "pb" in filtered.columns:
        filtered = filtered[(filtered["pb"].isna()) | ((filtered["pb"] > 0) & (filtered["pb"] < 20))]
    return filtered


def _calc_ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def _analyze_longterm_news(code: str, name: str) -> dict:
    """分析30天新闻情绪。

    短线 `analyze_news_sentiment()` 只看7天且强调事件刺激，
    中长期改为观察30天窗口中的经营/政策/订单/风险信息。
    """
    news = get_stock_news(code, count=20)
    if not news:
        return {"score_adj": 0, "summary": "近30天无有效新闻", "highlights": []}

    positive_keywords = [
        "净利润增长", "业绩预增", "中标", "订单", "扩产", "投产",
        "回购", "增持", "分红", "战略合作", "景气", "突破",
    ]
    negative_keywords = [
        "亏损", "业绩预减", "减持", "立案", "处罚", "退市",
        "诉讼", "解禁", "风险提示", "质押", "冻结",
    ]
    now = datetime.now()
    recent = []
    for item in news:
        try:
            news_date = datetime.strptime(item.get("date", "")[:10], "%Y-%m-%d")
            if (now - news_date).days <= 30:
                recent.append(item)
        except (TypeError, ValueError):
            recent.append(item)

    pos_hits = 0
    neg_hits = 0
    highlights = []
    for item in recent:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        if name and name not in text and code not in text:
            continue
        pos = sum(1 for kw in positive_keywords if kw in text)
        neg = sum(1 for kw in negative_keywords if kw in text)
        if pos > neg and len(highlights) < 3:
            highlights.append(f"🟢 {item.get('title', '')[:36]}")
        elif neg > pos and len(highlights) < 3:
            highlights.append(f"🔴 {item.get('title', '')[:36]}")
        pos_hits += pos
        neg_hits += neg

    net = pos_hits - neg_hits
    if net >= 3:
        return {"score_adj": 10, "summary": "30天新闻偏多", "highlights": highlights}
    if net >= 1:
        return {"score_adj": 5, "summary": "30天新闻略偏多", "highlights": highlights}
    if net <= -3:
        return {"score_adj": -10, "summary": "30天新闻偏空", "highlights": highlights}
    if net <= -1:
        return {"score_adj": -5, "summary": "30天新闻略偏空", "highlights": highlights}
    return {"score_adj": 0, "summary": "30天新闻中性", "highlights": highlights}


def analyze_longterm_stock(row: pd.Series) -> dict | None:
    """单只股票中长期评分。

    模型强调：
    - MA60 / MA120 / MA250 长趋势
    - 当前价格相对长期均线和阶段高点的位置
    - 波动率与回撤是否适合中长期建仓
    - PE / PB 仅作粗筛，不做精细估值
    """
    code = str(row["code"])
    name = str(row["name"])
    price = float(row["price"])
    kline = get_kline(code, period="daily", days=360)
    if kline is None or len(kline) < 260:
        return None

    close = kline["close"].astype(float)
    high = kline["high"].astype(float)
    low = kline["low"].astype(float)

    ma60 = _calc_ma(close, 60)
    ma120 = _calc_ma(close, 120)
    ma250 = _calc_ma(close, 250)
    latest_close = float(close.iloc[-1])
    latest_ma60 = float(ma60.iloc[-1])
    latest_ma120 = float(ma120.iloc[-1])
    latest_ma250 = float(ma250.iloc[-1])
    yearly_high = float(high.tail(250).max())
    yearly_low = float(low.tail(250).min())
    drawdown_from_high = round((latest_close / yearly_high - 1) * 100, 2) if yearly_high else 0
    rebound_from_low = round((latest_close / yearly_low - 1) * 100, 2) if yearly_low else 0
    returns = close.pct_change().dropna()
    volatility = round(float(returns.tail(60).std() * np.sqrt(252) * 100), 2) if not returns.empty else 0

    score = 50
    reasons = []
    risks = []

    # 长期趋势是中长期体系的核心权重。
    if latest_close > latest_ma60 > latest_ma120 > latest_ma250:
        score += 25
        reasons.append("长周期多头排列")
    elif latest_close > latest_ma120 > latest_ma250:
        score += 15
        reasons.append("中长期趋势向上")
    elif latest_close < latest_ma60 < latest_ma120 < latest_ma250:
        score -= 25
        risks.append("长周期空头排列")
    elif latest_close < latest_ma120 < latest_ma250:
        score -= 15
        risks.append("中长期趋势偏弱")

    # MA250斜率代表长期经营/估值共振方向，优先级高于单日涨跌。
    if float(ma250.iloc[-1]) > float(ma250.iloc[-20]):
        score += 8
        reasons.append("年线走平向上")
    else:
        score -= 8
        risks.append("年线仍在下压")

    # 回撤适中更适合中长期分批建仓；离高点太近则安全边际不足。
    if -20 <= drawdown_from_high <= -5:
        score += 10
        reasons.append("距年内高点有合理回撤")
    elif drawdown_from_high > -5:
        score -= 8
        risks.append("接近阶段高位")
    elif drawdown_from_high < -35:
        score -= 6
        risks.append("深度回撤，可能趋势未修复")

    if volatility <= 28:
        score += 8
        reasons.append("60日波动率适中")
    elif volatility >= 45:
        score -= 8
        risks.append("60日波动率偏高")

    pe = row.get("pe")
    pb = row.get("pb")
    if pd.notna(pe):
        pe = float(pe)
        if 0 < pe <= 25:
            score += 8
            reasons.append(f"PE较合理({pe:.1f})")
        elif pe >= 60:
            score -= 8
            risks.append(f"PE偏高({pe:.1f})")
    if pd.notna(pb):
        pb = float(pb)
        if 0 < pb <= 3:
            score += 5
            reasons.append(f"PB较低({pb:.1f})")
        elif pb >= 8:
            score -= 5
            risks.append(f"PB偏高({pb:.1f})")

    news = _analyze_longterm_news(code, name)
    score += news["score_adj"]
    if news["score_adj"] > 0:
        reasons.append(news["summary"])
    elif news["score_adj"] < 0:
        risks.append(news["summary"])

    score = max(0, min(100, int(round(score))))
    if score >= 80:
        tier = "首选"
        holding_period = "6-12个月"
    elif score >= 68:
        tier = "备选"
        holding_period = "3-6个月"
    else:
        tier = "观察"
        holding_period = "等待趋势确认"

    # 中长期建仓区间强调分批，不给短线止损式点位。
    build_low = round(min(latest_close, latest_ma60) * 0.96, 2)
    build_high = round(min(latest_close, latest_ma60) * 1.00, 2)

    return {
        "code": code,
        "name": name,
        "price": round(price, 2),
        "score": score,
        "tier": tier,
        "holding_period": holding_period,
        "build_range": [build_low, build_high],
        "logic": reasons[:5],
        "risks": risks[:5] or ["暂无明显额外风险"],
        "valuation": {
            "pe": None if pd.isna(row.get("pe")) else round(float(row.get("pe")), 2),
            "pb": None if pd.isna(row.get("pb")) else round(float(row.get("pb")), 2),
        },
        "trend": {
            "ma60": round(latest_ma60, 2),
            "ma120": round(latest_ma120, 2),
            "ma250": round(latest_ma250, 2),
            "drawdown_from_high_pct": drawdown_from_high,
            "rebound_from_low_pct": rebound_from_low,
            "volatility_60d_pct": volatility,
        },
        "news": news,
    }


def score_longterm_candidates(df: pd.DataFrame, top_n: int = 15) -> list[dict]:
    """批量跑中长期评分。

    为了保持完全独立，不复用短线 `score_candidates()` 的评价体系。
    """
    results = []
    for _, row in df.iterrows():
        try:
            item = analyze_longterm_stock(row)
        except Exception:
            item = None
        if item:
            results.append(item)
        if len(results) >= top_n * 4:
            break
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


def _build_market_view(scored: list[dict], market_df: pd.DataFrame, is_cached: bool) -> dict:
    """生成中长期市场基调。"""
    avg_score = round(mean([x["score"] for x in scored]), 2) if scored else 0
    strong_count = sum(1 for x in scored if x["score"] >= 80)
    avg_change = round(float(market_df["change_pct"].mean()), 2) if not market_df.empty else 0
    if avg_score >= 78 and strong_count >= 3:
        stance = "偏进攻"
        summary = "长期趋势股占优，可考虑分批建仓。"
    elif avg_score >= 68:
        stance = "均衡配置"
        summary = "中长期机会存在，但更适合分批买入。"
    else:
        stance = "防守等待"
        summary = "长期趋势股不够集中，优先等待更好的安全边际。"
    if avg_change < -1:
        summary += " 短线环境偏弱，建仓节奏应放慢。"
    return {
        "stance": stance,
        "summary": summary,
        "avg_candidate_score": avg_score,
        "strong_candidate_count": strong_count,
        "market_avg_change": avg_change,
        "is_cached": is_cached,
    }


def run_longterm() -> bool:
    """运行中长期分析。"""
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    day_dir = _ensure_log_dir(date_str)

    print("=" * 60)
    print("📈 中长期分析（独立链路）")
    print(f"📅 {date_str} {now.strftime('%H:%M')}")
    print("=" * 60)

    df = get_all_stocks()
    is_cached = False
    if df.empty:
        print("  ❌ 市场数据获取失败")
        return False

    universe = _build_longterm_universe(df)
    print(f"\n📊 候选池: {len(universe)} 只（独立于短线筛选规则，价格≤{LONGTERM_MAX_PRICE}元）")
    scored = score_longterm_candidates(universe, top_n=15)
    if not scored:
        print("  ❌ 中长期评分失败，未得到有效标的")
        return False

    market_view = _build_market_view(scored, universe, is_cached)
    first_choices = [x for x in scored if x["tier"] == "首选"][:5]
    backups = [x for x in scored if x["tier"] == "备选"][:5]
    watch_only = [x for x in scored if x["tier"] == "观察"][:5]

    print(f"\n🧭 市场基调: {market_view['stance']} | {market_view['summary']}")
    print("\n⭐ 首选标的:")
    for item in first_choices[:5]:
        print(
            f"  • {item['code']} {item['name']} | 评分{item['score']} | "
            f"建仓区间 {item['build_range'][0]}-{item['build_range'][1]} | "
            f"持有周期 {item['holding_period']}"
        )
    if not first_choices:
        print("  • 暂无首选标的")

    suggestions = {
        "timestamp": now.isoformat(),
        "strategy_type": "longterm",
        "is_trading_time": is_trading_time(),
        "market_view": market_view,
        "first_choices": first_choices,
        "backups": backups,
        "watch_only": watch_only,
        "notes": {
            "isolation": "本文件独立于短线 suggestions.json，不会覆盖短线建议。",
            "positioning": f"适用于3-12个月持有，不使用分时图和短线止损逻辑，候选价格上限为{LONGTERM_MAX_PRICE}元。",
        },
    }

    log_record = {
        "session": "longterm",
        "timestamp": now.isoformat(),
        "focus": "中长期独立分析",
        "market_view": market_view,
        "review_summary": market_view["summary"],
        "core_plan": (
            f"当前基调为{market_view['stance']}；优先在建仓区间内分批买入首选标的，"
            "避免把短线波动当作中长期卖点。"
        ),
        "first_choices": first_choices,
        "backups": backups,
        "watch_only": watch_only,
    }

    with open(LONGTERM_SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(suggestions, f, ensure_ascii=False, indent=2)
    log_path = os.path.join(day_dir, "longterm.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_record, f, ensure_ascii=False, indent=2)

    print(f"\n💾 已写入 {LONGTERM_SUGGESTIONS_FILE}")
    print(f"💾 已写入 {log_path}")
    return True


if __name__ == "__main__":
    ok = run_longterm()
    sys.exit(0 if ok else 1)
