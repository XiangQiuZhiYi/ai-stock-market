#!/usr/bin/env python3
"""AI分析用数据采集器 — 提供给Heremes cron job使用

运行方式: python3 collect_for_ai.py
输出: market_data.json, portfolio.json
"""
import json
import sys
import os

# 确保能找到astock模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data import get_all_stocks, filter_candidates, save_market_snapshot, is_trading_time
from analysis import score_candidates
from portfolio import load_portfolio, get_portfolio_summary
from config import MARKET_DATA_FILE, PORTFOLIO_FILE, SUGGESTIONS_FILE


def collect():
    """采集数据并生成分析建议，直接写入 suggestions.json 供面板展示"""
    print("=" * 60)
    print("🤖 AI A股分析 - 数据采集 + 自动生成建议")
    print(f"交易状态: {'🔥 交易中' if is_trading_time() else '⏸️ 休市中'}")
    print("=" * 60)

    # 1. 拉取全市场行情
    print("\n[1/4] 拉取全市场行情...")
    df = get_all_stocks()
    if df.empty:
        print("  ❌ 获取失败（可能非交易时段）")
        return False
    print(f"  ✅ 共 {len(df)} 只股票")

    # 2. 过滤候选
    candidates = filter_candidates(df)
    print(f"\n[2/4] 筛选候选股票...")
    print(f"  过滤后: {len(candidates)} 只候选 (价格≤50, 有成交量)")

    # 3. 分析评分 Top 20
    print(f"\n[3/4] 综合评分 (技术+资金+形态)...")
    top = score_candidates(candidates, top_n=20)
    print(f"  已分析 {len(top)} 只股票")

    # 4. 保存快照
    save_market_snapshot(candidates)

    # 5. 输出分析摘要
    print("\n" + "=" * 60)
    print("📊 Top 10 评分结果:")
    print("-" * 60)
    print(f"{'#':<3} {'代码':<8} {'名称':<8} {'现价':<8} {'评分':<5} {'信号':<6} {'涨跌幅':<8}")
    print("-" * 60)
    for i, s in enumerate(top[:10], 1):
        print(f"{i:<3} {s['code']:<8} {s['name']:<8} "
              f"{s['price']:<8.2f} {s['score']:<5} {s['signal']:<6} "
              f"{s['change_pct'] if s['change_pct'] else 0:>+.2f}%")

    # 6. 打包 analysis_context.json（保留，供外部AI可选使用）
    market_stats = {
        "up_count": int((df["change_pct"] > 0).sum()),
        "down_count": int((df["change_pct"] < 0).sum()),
        "limit_up": int((df["change_pct"] > 9.5).sum()),
        "limit_down": int((df["change_pct"] < -9.5).sum()),
        "avg_change": round(float(df["change_pct"].mean()), 2),
    }

    context = {
        "trading_time": is_trading_time(),
        "total_stocks": len(df),
        "candidate_count": len(candidates),
        "top_stocks": top[:10],
        "market_stats": market_stats,
    }

    with open(os.path.join(os.path.dirname(__file__), "analysis_context.json"), "w") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)

    # 7. 自动生成 suggestions.json（核心新增逻辑）
    print(f"\n[4/4] 生成建议写入 suggestions.json...")
    _generate_suggestions(top, market_stats, df)

    print("\n✅ 数据采集 + 建议生成完成")
    return True


def _generate_suggestions(top_stocks: list, market_stats: dict, df):
    """基于评分结果自动生成 suggestions.json，供面板展示
    
    逻辑：
    - 评分≥70 且非已持仓 → 买入建议
    - 已持仓的股票 → 持仓建议（含止盈止损）
    - 评分≤40 → do_not_buy
    - 评分55-69 → watch_list
    """
    from datetime import datetime, timezone, timedelta
    from portfolio import load_portfolio

    pf = load_portfolio()
    holdings = {h["code"]: h for h in pf.get("holdings", [])}
    cash = pf.get("cash", 0)

    # 市场方向判断
    avg_chg = market_stats.get("avg_change", 0)
    up_count = market_stats.get("up_count", 0)
    down_count = market_stats.get("down_count", 0)
    
    if avg_chg > 1.0:
        direction = "强势上涨"
        risk_level = "低"
    elif avg_chg > 0.3:
        direction = "偏强震荡"
        risk_level = "低"
    elif avg_chg > -0.3:
        direction = "横盘震荡"
        risk_level = "中"
    elif avg_chg > -1.0:
        direction = "偏弱震荡"
        risk_level = "中"
    else:
        direction = "弱势下跌"
        risk_level = "高"

    # 热门板块：从top股票的信号中提取
    hot_sectors = []
    for s in top_stocks[:10]:
        name = s.get("name", "")
        # 简单按名称关键字归类板块
        if any(k in name for k in ["电力", "能源", "电气"]):
            hot_sectors.append("电力能源")
        elif any(k in name for k in ["科技", "电子", "信息", "芯片", "半导"]):
            hot_sectors.append("电子科技")
        elif any(k in name for k in ["有色", "铜", "铝", "锂"]):
            hot_sectors.append("有色金属")
        elif any(k in name for k in ["光电", "光伏", "太阳"]):
            hot_sectors.append("光伏新能源")
        elif any(k in name for k in ["通信", "通讯", "5G"]):
            hot_sectors.append("通信")
    hot_sectors = list(dict.fromkeys(hot_sectors))[:5]  # 去重取前5

    def _build_entry_plan(stock: dict) -> tuple[float, str, str]:
        """生成入场价格和方式。

        这里不再用固定涨跌幅分档，而是把市场环境、技术形态、资金流和消息面合并成
        一个入场强弱判断：越强势越倾向现价执行，分歧越大越倾向回落限价。
        """
        price = stock["price"]
        stock_change = stock.get("change_pct", 0) or 0
        score = stock.get("score", 0)
        signals = stock.get("signals", [])
        news_sentiment = stock.get("news_sentiment", "neutral")
        capital_flow = stock.get("capital_flow", "")

        strength = 0
        reasons = []

        # 市场环境先决定大方向：弱市优先低吸，强市允许更积极。
        if direction in {"强势上涨", "偏强震荡"}:
            strength += 1
            reasons.append(f"大盘{direction}")
        elif direction == "弱势下跌":
            strength -= 2
            reasons.append("大盘偏弱")
        elif direction == "偏弱震荡":
            strength -= 1
            reasons.append("市场偏谨慎")

        # 个股当日走势代表买盘意愿，但大涨也要防止追高，所以只适度加分。
        if stock_change >= 4:
            strength += 2
            reasons.append(f"个股强势上涨{stock_change:.1f}%")
        elif stock_change >= 1:
            strength += 1
            reasons.append(f"个股走强{stock_change:.1f}%")
        elif stock_change <= -3:
            strength -= 2
            reasons.append(f"个股回调{stock_change:.1f}%")
        elif stock_change < 0:
            strength -= 1
            reasons.append(f"个股小幅回落{stock_change:.1f}%")

        # 综合评分高说明技术/形态/资金多个维度共振，允许减少等待回调幅度。
        if score >= 85:
            strength += 2
            reasons.append(f"综合评分高({score})")
        elif score >= 75:
            strength += 1
            reasons.append(f"综合评分较强({score})")

        # 技术面与形态面：突破、金叉、多头、新高偏强；死叉、空头、跌破偏弱。
        bullish_keywords = ("多头", "金叉", "突破", "反转", "新高", "回踩MA20", "放量")
        bearish_keywords = ("空头", "死叉", "跌破", "新低", "大跌", "高位死叉")
        bullish_hits = sum(1 for sig in signals if any(k in sig for k in bullish_keywords))
        bearish_hits = sum(1 for sig in signals if any(k in sig for k in bearish_keywords))
        if bullish_hits:
            strength += min(bullish_hits, 2)
            reasons.append(f"技术偏强({bullish_hits})")
        if bearish_hits:
            strength -= min(bearish_hits, 2)
            reasons.append(f"技术有分歧({bearish_hits})")

        # 资金流和消息面用于决定是“马上跟”还是“等回踩再接”。
        if "连续" in capital_flow and "流入" in capital_flow:
            strength += 2
            reasons.append("主力连续流入")
        elif "流入" in capital_flow:
            strength += 1
            reasons.append("主力流入")
        elif "流出" in capital_flow:
            strength -= 2
            reasons.append("主力流出")

        if news_sentiment == "positive":
            strength += 1
            reasons.append("消息面偏多")
        elif news_sentiment == "negative":
            strength -= 2
            reasons.append("消息面偏空")

        # 映射成入场方式。任何情况下限价都不高于参考价，避免“主动加价买入”。
        if strength >= 5:
            entry_style = "直接买入"
            limit = round(price, 2)
        elif strength >= 2:
            entry_style = "轻微回落买入"
            limit = round(price * 0.997, 2)
        elif strength >= 0:
            entry_style = "回踩限价买入"
            limit = round(price * 0.992, 2)
        else:
            entry_style = "低吸限价买入"
            limit = round(price * 0.985, 2)

        limit = min(round(price, 2), limit)
        entry_reason = "、".join(reasons[:4]) if reasons else "按综合信号等待合适入场点"
        return limit, entry_style, entry_reason

    def _build_exit_plan(stock: dict, holding: dict, current_price: float) -> tuple[float, str, str]:
        """生成卖出价格和方式。

        卖出更强调“先保住利润/本金，再考虑卖在更高处”，因此用市场、技术、
        资金、消息和当前盈亏综合判断是继续等高点，还是优先反弹减仓/保护性卖出。
        """
        buy_price = holding["buy_price"]
        stop_loss = holding.get("stop_loss", round(buy_price * 0.95, 2))
        take_profit = holding.get("take_profit", round(buy_price * 1.08, 2))
        pnl_pct = (current_price - buy_price) / buy_price * 100 if buy_price > 0 else 0

        score = stock.get("score", 0)
        signals = stock.get("signals", [])
        news_sentiment = stock.get("news_sentiment", "neutral")
        capital_flow = stock.get("capital_flow", "")
        stock_change = stock.get("change_pct", 0) or 0

        support = 0
        pressure = 0
        reasons = []

        # 大盘弱时优先兑现和防守，大盘强时允许多给强股一点波动空间。
        if direction in {"强势上涨", "偏强震荡"}:
            support += 1
            reasons.append(f"大盘{direction}")
        elif direction == "弱势下跌":
            pressure += 2
            reasons.append("大盘偏弱")
        elif direction == "偏弱震荡":
            pressure += 1
            reasons.append("市场偏谨慎")

        # 综合评分承接了技术、形态和资金的结果，是卖出判断的核心底座。
        if score >= 85:
            support += 2
            reasons.append(f"综合评分高({score})")
        elif score >= 70:
            support += 1
            reasons.append(f"综合评分偏强({score})")
        elif score < 50:
            pressure += 2
            reasons.append(f"综合评分转弱({score})")
        elif score < 60:
            pressure += 1
            reasons.append(f"综合评分走弱({score})")

        strong_keywords = ("多头", "金叉", "突破", "新高", "反转", "放量")
        weak_keywords = ("空头", "死叉", "跌破", "短期回调", "大跌")
        hot_keywords = ("超买", "触及上轨", "高位死叉")

        strong_hits = sum(1 for sig in signals if any(k in sig for k in strong_keywords))
        weak_hits = sum(1 for sig in signals if any(k in sig for k in weak_keywords))
        hot_hits = sum(1 for sig in signals if any(k in sig for k in hot_keywords))

        if strong_hits:
            support += min(strong_hits, 2)
            reasons.append(f"技术偏强({strong_hits})")
        if weak_hits:
            pressure += min(weak_hits, 2)
            reasons.append(f"技术转弱({weak_hits})")
        if hot_hits and pnl_pct > 0:
            # 超买或触上轨不代表一定转空，但对已有盈利的仓位意味着可考虑落袋。
            pressure += min(hot_hits, 2)
            reasons.append("技术偏热")

        if "连续" in capital_flow and "流入" in capital_flow:
            support += 2
            reasons.append("主力连续流入")
        elif "流入" in capital_flow:
            support += 1
            reasons.append("主力流入")
        elif "流出" in capital_flow:
            pressure += 2
            reasons.append("主力流出")

        if news_sentiment == "positive":
            support += 1
            reasons.append("消息面偏多")
        elif news_sentiment == "negative":
            pressure += 2
            reasons.append("消息面偏空")

        # 盈亏状态决定卖出的紧迫度：盈利越厚越偏向止盈，亏损越深越偏向防守。
        if pnl_pct >= 8:
            pressure += 2
            reasons.append(f"浮盈{pnl_pct:.1f}%可兑现")
        elif pnl_pct >= 4:
            pressure += 1
            reasons.append(f"已有浮盈{pnl_pct:.1f}%")
        elif pnl_pct <= -5:
            pressure += 2
            reasons.append(f"亏损{pnl_pct:.1f}%需防守")
        elif pnl_pct < 0:
            pressure += 1
            reasons.append(f"小幅亏损{pnl_pct:.1f}%")

        if stock_change <= -3:
            pressure += 2
            reasons.append(f"当日大跌{stock_change:.1f}%")
        elif stock_change < 0:
            pressure += 1
            reasons.append(f"当日回落{stock_change:.1f}%")
        elif stock_change >= 3 and pnl_pct > 0:
            pressure += 1
            reasons.append(f"当日冲高{stock_change:.1f}%")

        # 先处理最明确的风控场景，避免“该走时还在等反弹目标价”。
        if current_price <= stop_loss or (pressure - support >= 4 and pnl_pct <= 0):
            exit_style = "保护性卖出"
            suggested_sell = round(current_price, 2)
        elif pressure - support >= 3:
            exit_style = "反弹减仓卖出"
            suggested_sell = round(max(current_price * 1.01, stop_loss), 2)
        elif support - pressure >= 3:
            exit_style = "趋势持有止盈"
            suggested_sell = round(max(current_price * 1.03, take_profit), 2)
        elif pnl_pct > 0 and pressure >= support:
            exit_style = "冲高止盈卖出"
            suggested_sell = round(max(current_price * 1.015, buy_price * 1.05), 2)
        else:
            exit_style = "择机卖出"
            suggested_sell = round(max(current_price * 1.02, buy_price * 1.05), 2)

        exit_reason = "、".join(reasons[:5]) if reasons else "按综合信号择机处理仓位"
        return suggested_sell, exit_style, exit_reason

    # 买入建议：评分≥70、非已持仓、现金够买1手
    buy_positions = []
    total_invest = 0
    for s in top_stocks:
        if s["score"] < 70:
            break
        code = s["code"]
        if code in holdings:
            continue
        price = s["price"]
        # 能否买得起1手（100股）
        cost_1lot = price * 100 + 10  # 预留手续费
        if cash - total_invest < cost_1lot:
            continue
        
        shares = int((min(cash - total_invest, 2000) // (price * 100)) * 100)
        if shares < 100:
            shares = 100
        
        # 根据评分和信号生成买入理由
        key_signals = [sig for sig in s.get("signals", []) 
                       if any(k in sig for k in ["排列", "金叉", "流入", "突破", "新高", "反转"])]
        reason = ", ".join(key_signals[:3]) if key_signals else f"综合评分{s['score']}"
        
        # 入场价由综合信号决定，避免简单固定比例导致误导性的挂单价。
        limit, entry_style, entry_reason = _build_entry_plan(s)

        buy_positions.append({
            "code": code,
            "name": s["name"],
            "shares": shares,
            "reference_price": price,
            "limit_price": limit,
            "entry_style": entry_style,
            "entry_reason": entry_reason,
            "stop_loss": round(price * 0.95, 2),
            "take_profit": round(price * 1.08, 2),
            "reason": reason,
            "score": s["score"],
        })
        total_invest += shares * price
        if len(buy_positions) >= 3:  # 最多推荐3只
            break

    # 买入逻辑说明
    if not buy_positions:
        if risk_level == "高":
            buy_logic = "市场弱势，暂不建议开仓"
        elif len(holdings) >= 3:
            buy_logic = "已满仓（3只），等待卖出后再买入"
        else:
            buy_logic = "当前无评分≥70的强势标的，等待机会"
    else:
        buy_logic = (
            f"基于技术、资金、消息和市场环境综合判断，筛选出{len(buy_positions)}只候选标的；"
            "入场价按强弱区分为直接买入或回踩限价买入"
        )

    # 持仓建议
    holding_advice = []
    for code, h in holdings.items():
        # 在 top 中找该股，找不到则单独分析
        stock_info = next((s for s in top_stocks if s["code"] == code), None)
        if not stock_info:
            from analysis import analyze_stock
            cp = h.get("current_price", h["buy_price"])
            stock_info = analyze_stock(code, h["name"], cp, 0)

        cp = h.get("current_price", h["buy_price"])
        bp = h["buy_price"]
        pnl_pct = (cp - bp) / bp * 100 if bp > 0 else 0

        # 卖出价同样改成综合判断，区分保护性卖出、反弹减仓、冲高止盈和趋势持有。
        suggested_sell, exit_style, exit_reason = _build_exit_plan(stock_info, h, cp)

        key_signals = ", ".join(stock_info.get("signals", [])[:3])
        holding_advice.append({
            "code": code,
            "name": h["name"],
            "suggested_sell_price": suggested_sell,
            "exit_style": exit_style,
            "exit_reason": exit_reason,
            "stop_loss": h.get("stop_loss", round(bp * 0.95, 2)),
            "take_profit": h.get("take_profit", round(bp * 1.08, 2)),
            "reason": f"{exit_style}。{exit_reason}。{key_signals}",
        })

    # 黑名单：评分低但涨幅大（追高陷阱）
    do_not_buy = []
    for s in top_stocks:
        if s["score"] <= 40 and s.get("change_pct", 0) > 3:
            do_not_buy.append({
                "code": s["code"],
                "name": s["name"],
                "reason": f"评分仅{s['score']}但涨{s['change_pct']:.1f}%，勿追高",
            })
        elif s["score"] <= 35:
            bad_signals = [sig for sig in s.get("signals", []) if "流出" in sig or "空头" in sig or "死叉" in sig]
            if bad_signals:
                do_not_buy.append({
                    "code": s["code"],
                    "name": s["name"],
                    "reason": bad_signals[0],
                })
        if len(do_not_buy) >= 5:
            break

    # 关注列表：评分55-69，展示更丰富的推荐理由
    watch_list = []
    for s in top_stocks:
        if 55 <= s["score"] < 70 and s["code"] not in holdings:
            key_signals = [sig for sig in s.get("signals", []) 
                           if any(k in sig for k in ["流入", "金叉", "突破", "反转", "回踩", "排列", "新高", "放量"])]
            # 附带价格和涨跌信息
            price_info = f"现价{s['price']:.2f}" if s.get("price") else ""
            chg_info = f"涨{s['change_pct']:.1f}%" if s.get("change_pct", 0) > 0 else (
                f"跌{abs(s.get('change_pct',0)):.1f}%" if s.get("change_pct", 0) < 0 else "")
            detail = ", ".join(key_signals[:3]) if key_signals else "观察中"
            reason = f"评分{s['score']} {price_info} {chg_info} | {detail}"
            # 新闻利好补充
            if s.get("key_news"):
                reason += f" | 📰{s['key_news'][0][:20]}"
            watch_list.append({
                "code": s["code"],
                "name": s["name"],
                "reason": reason.strip(),
            })
            if len(watch_list) >= 5:
                break

    # 择时建议
    if risk_level == "高":
        timing = "市场偏弱，控制仓位，不追涨"
    elif holdings and any(h.get("current_price", h["buy_price"]) <= h.get("stop_loss", 0) for h in pf.get("holdings", [])):
        timing = "有持仓触及止损线，优先处理风险"
    elif buy_positions:
        timing = (
            f"可关注{buy_positions[0]['name']}等标的，优先按“{buy_positions[0].get('entry_style', '回踩限价买入')}”执行"
        )
    else:
        timing = "暂无明确方向，持仓守好止损，等待信号"

    # 收集重要新闻（从分析结果中提取 key_news）
    news_highlights = []
    for s in top_stocks[:20]:
        for news_item in s.get("key_news", []):
            sentiment = s.get("news_sentiment", "neutral")
            news_highlights.append({
                "code": s["code"],
                "name": s["name"],
                "title": news_item,
                "sentiment": sentiment,
            })
            if len(news_highlights) >= 8:
                break
        if len(news_highlights) >= 8:
            break

    # 组装 suggestions.json
    tz = timezone(timedelta(hours=8))
    suggestions = {
        "timestamp": datetime.now(tz).isoformat(),
        "market_summary": {
            "direction": direction,
            "avg_change": market_stats.get("avg_change", 0),
            "hot_sectors": hot_sectors,
            "risk_level": risk_level,
        },
        "buy_plan": {
            "logic": buy_logic,
            "positions": buy_positions,
            "summary": {
                "total_invest": round(total_invest, 2),
                "remaining_cash": round(cash - total_invest, 2),
                "sectors": hot_sectors[:3],
            },
        },
        "holding_advice": holding_advice,
        "alerts": {
            "do_not_buy": do_not_buy,
            "watch_list": watch_list,
        },
        "timing_advice": timing,
        "news_highlights": news_highlights,
    }

    with open(SUGGESTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(suggestions, f, ensure_ascii=False, indent=2)
    
    print(f"  ✅ 已写入 suggestions.json")
    print(f"     买入建议: {len(buy_positions)}只  持仓建议: {len(holding_advice)}只")
    print(f"     关注: {len(watch_list)}只  回避: {len(do_not_buy)}只")


if __name__ == "__main__":
    collect()
