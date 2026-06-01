#!/usr/bin/env python3
"""定时分析调度器 — 每日三次分析，分场景记录

分析时段：
  - 10:00 早盘分析：专注买卖决策，参考昨日复盘
  - 11:25 午间分析：上午走势复盘 + 下午策略思考
  - 14:50 尾盘分析：全日复盘 + 次日展望

运行方式：
  手动: python3 scheduled_analysis.py [morning|midday|afternoon]
  定时: crontab 配置（见底部说明）
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data import get_all_stocks, filter_candidates, save_market_snapshot, is_trading_time
from analysis import score_candidates, analyze_stock
from portfolio import load_portfolio, get_portfolio_summary
from config import MARKET_DATA_FILE, SUGGESTIONS_FILE

# 分析日志存储目录
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_logs")

TZ = timezone(timedelta(hours=8))


def _ensure_log_dir(date_str: str) -> str:
    """创建当日日志目录，返回目录路径"""
    day_dir = os.path.join(LOG_DIR, date_str)
    os.makedirs(day_dir, exist_ok=True)
    return day_dir


def _load_yesterday_review() -> dict:
    """加载昨日的分析记录，供早盘决策参考"""
    yesterday = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    # 向前找最近的交易日（跳过周末）
    for delta in range(1, 4):
        check_date = (datetime.now(TZ) - timedelta(days=delta)).strftime("%Y-%m-%d")
        day_dir = os.path.join(LOG_DIR, check_date)
        if os.path.exists(day_dir):
            review = {}
            # 优先读取尾盘复盘（最完整），其次午间，再次早盘
            for session in ["afternoon", "midday", "morning"]:
                path = os.path.join(day_dir, f"{session}.json")
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            review[session] = json.load(f)
                    except (json.JSONDecodeError, OSError):
                        pass
            if review:
                return {"date": check_date, "sessions": review}
    return {}


def _get_market_data():
    """获取市场数据，返回 (df, candidates, top_stocks, market_stats) 或 None。
    
    API 失败时不再静默使用缓存：交易时段必须获取实时数据，
    非交易时段才允许使用缓存（并在 market_stats 中标记 is_cached=True）。
    """
    from data import is_trading_time
    df = get_all_stocks()
    is_cached = False
    
    if df.empty:
        if is_trading_time():
            # 交易时段 API 失败：提示用户重新拉取，不用过时缓存
            print("  ❌ 实时行情获取失败！交易时段不使用缓存，请检查网络后重试。")
            print("  💡 提示：可稍后按 S 键（强制扫描）重新拉取数据")
            return None
        else:
            # 非交易时段允许用缓存（收盘后数据不会变）
            try:
                import pandas as pd
                with open(MARKET_DATA_FILE, "r", encoding="utf-8") as f_cache:
                    cached = json.load(f_cache)
                stocks = cached.get("stocks", [])
                if not stocks:
                    return None
                df = pd.DataFrame(stocks)
                is_cached = True
                print("  ⚠️ 非交易时段，使用缓存数据")
            except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
                return None

    candidates = filter_candidates(df)
    if candidates is None or (hasattr(candidates, 'empty') and candidates.empty) or len(candidates) == 0:
        return None

    top = score_candidates(candidates, top_n=20)
    save_market_snapshot(candidates)

    market_stats = {
        "up_count": int((df["change_pct"] > 0).sum()) if "change_pct" in df.columns else 0,
        "down_count": int((df["change_pct"] < 0).sum()) if "change_pct" in df.columns else 0,
        "limit_up": int((df["change_pct"] > 9.5).sum()) if "change_pct" in df.columns else 0,
        "limit_down": int((df["change_pct"] < -9.5).sum()) if "change_pct" in df.columns else 0,
        "avg_change": round(float(df["change_pct"].mean()), 2) if "change_pct" in df.columns else 0,
        "is_cached": is_cached,
    }

    return df, candidates, top, market_stats


def _format_holding_status(pf: dict, top_stocks: list) -> list:
    """整理当前持仓状态和建议"""
    holdings_info = []
    for h in pf.get("holdings", []):
        code = h["code"]
        # 在评分结果中找到该股
        stock_info = next((s for s in top_stocks if s["code"] == code), None)
        if not stock_info:
            stock_info = analyze_stock(code, h["name"], h.get("current_price", h["buy_price"]), 0)

        cp = h.get("current_price", h["buy_price"])
        pnl_pct = (cp - h["buy_price"]) / h["buy_price"] * 100
        holdings_info.append({
            "code": code,
            "name": h["name"],
            "shares": h["shares"],
            "buy_price": h["buy_price"],
            "current_price": cp,
            "pnl_pct": round(pnl_pct, 2),
            "stop_loss": h.get("stop_loss"),
            "take_profit": h.get("take_profit"),
            "score": stock_info.get("score", 0) if isinstance(stock_info, dict) else 0,
            "signals": stock_info.get("signals", []) if isinstance(stock_info, dict) else [],
        })
    return holdings_info


# ═══════════════════ 三个分析场景 ═══════════════════


def run_morning():
    """10:00 早盘分析 — 专注买卖决策
    
    重点：
    1. 回顾昨日决策和复盘结论
    2. 当前持仓状态检查（是否触及止损止盈）
    3. 今日市场环境判断
    4. 明确的买入/卖出行动计划
    """
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    day_dir = _ensure_log_dir(date_str)

    print("=" * 60)
    print("🌅 早盘分析 (10:00) — 买卖决策")
    print(f"📅 {date_str} {now.strftime('%H:%M')}")
    print("=" * 60)

    # 1. 加载昨日复盘
    yesterday = _load_yesterday_review()
    yesterday_summary = ""
    if yesterday:
        print(f"\n📖 参考上一交易日 ({yesterday['date']}) 的分析:")
        # 提取关键结论
        if "afternoon" in yesterday["sessions"]:
            af = yesterday["sessions"]["afternoon"]
            yesterday_summary = af.get("review_summary", "")
            next_day_plan = af.get("next_day_plan", "")
            if yesterday_summary:
                print(f"  复盘: {yesterday_summary}")
            if next_day_plan:
                print(f"  计划: {next_day_plan}")
        elif "midday" in yesterday["sessions"]:
            md = yesterday["sessions"]["midday"]
            yesterday_summary = md.get("review_summary", "")
            if yesterday_summary:
                print(f"  午间结论: {yesterday_summary}")
    else:
        print("\n📖 无上一交易日分析记录")

    # 2. 获取实时市场数据
    print("\n📊 获取市场数据...")
    result = _get_market_data()
    if not result:
        print("  ❌ 数据获取失败")
        return False
    df, candidates, top_stocks, market_stats = result
    print(f"  ✅ {len(df)}只股票, {len(candidates)}只候选, Top评分{len(top_stocks)}只")

    # 3. 持仓检查
    pf = load_portfolio()
    summary = get_portfolio_summary(pf)
    holdings_info = _format_holding_status(pf, top_stocks)

    print(f"\n💼 持仓状态: {summary['positions']}只, 浮盈{summary['profit']:+.2f}")
    for hi in holdings_info:
        status = "⚠️触止损" if hi["current_price"] <= (hi["stop_loss"] or 0) else (
            "🎯触止盈" if hi["current_price"] >= (hi["take_profit"] or 999) else "正常")
        print(f"  {hi['code']} {hi['name']} | {hi['pnl_pct']:+.1f}% | 评分{hi['score']} | {status}")

    # 4. 市场环境判断
    avg_chg = market_stats["avg_change"]
    if avg_chg > 1.0:
        market_mood = "强势上涨，可积极操作"
    elif avg_chg > 0.3:
        market_mood = "偏强，可正常操作"
    elif avg_chg > -0.3:
        market_mood = "震荡，谨慎操作"
    elif avg_chg > -1.0:
        market_mood = "偏弱，控制仓位"
    else:
        market_mood = "弱势，建议观望"

    print(f"\n🌡️ 市场温度: 均涨{avg_chg:+.2f}% | {market_mood}")
    print(f"  涨:{market_stats['up_count']} 跌:{market_stats['down_count']} "
          f"涨停:{market_stats['limit_up']} 跌停:{market_stats['limit_down']}")

    # 5. 生成行动计划
    actions = []
    # 卖出检查
    for hi in holdings_info:
        if hi["current_price"] <= (hi["stop_loss"] or 0):
            actions.append({"type": "sell", "code": hi["code"], "name": hi["name"],
                           "reason": f"触及止损{hi['stop_loss']}，建议止损卖出"})
        elif hi["current_price"] >= (hi["take_profit"] or 999):
            actions.append({"type": "sell", "code": hi["code"], "name": hi["name"],
                           "reason": f"触及止盈{hi['take_profit']}，建议止盈卖出"})
        elif hi["score"] < 45:
            actions.append({"type": "sell", "code": hi["code"], "name": hi["name"],
                           "reason": f"评分{hi['score']}转弱，考虑减仓"})

    # 买入机会
    cash = pf.get("cash", 0)
    for s in top_stocks:
        if s["score"] >= 70 and s["code"] not in {h["code"] for h in pf.get("holdings", [])}:
            cost = s["price"] * 100 + 10
            if cash >= cost and len(pf.get("holdings", [])) < 3:
                key_signals = [sig for sig in s.get("signals", [])
                               if any(k in sig for k in ["排列", "金叉", "流入", "突破"])]
                actions.append({"type": "buy", "code": s["code"], "name": s["name"],
                               "price": s["price"], "score": s["score"],
                               "reason": ", ".join(key_signals[:3]) or f"综合评分{s['score']}"})
                if len(actions) >= 5:
                    break

    print(f"\n📋 今日行动计划 ({len(actions)}条):")
    for a in actions:
        icon = "🟢买" if a["type"] == "buy" else "🔴卖"
        print(f"  {icon} {a['code']} {a['name']} — {a['reason']}")
    if not actions:
        print("  暂无明确操作信号，持仓观望")

    # 6. 保存分析记录
    record = {
        "session": "morning",
        "timestamp": now.isoformat(),
        "focus": "买卖决策",
        "yesterday_reference": {
            "date": yesterday.get("date", ""),
            "summary": yesterday_summary,
        },
        "market": {
            "stats": market_stats,
            "mood": market_mood,
        },
        "portfolio": {
            "cash": summary["cash"],
            "total_value": summary["total_value"],
            "profit": summary["profit"],
            "positions": holdings_info,
        },
        "top_candidates": [
            {"code": s["code"], "name": s["name"], "score": s["score"],
             "price": s["price"], "signals": s.get("signals", [])[:5]}
            for s in top_stocks[:10]
        ],
        "action_plan": actions,
        "decision_summary": f"市场{market_mood}。" + (
            f"计划执行{len(actions)}条操作。" if actions else "暂无操作，持仓观望。"
        ),
    }

    log_path = os.path.join(day_dir, "morning.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已保存至 {log_path}")

    # 同时更新 suggestions.json 供面板显示
    from collect_for_ai import _generate_suggestions
    _generate_suggestions(top_stocks, market_stats, df)
    print("  ✅ suggestions.json 已更新")

    return True


def run_midday():
    """11:25 午间分析 — 上午复盘 + 下午策略
    
    重点：
    1. 上午走势回顾（与早盘计划对比）
    2. 持仓表现跟踪
    3. 资金流向变化
    4. 下午操作策略调整
    """
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    day_dir = _ensure_log_dir(date_str)

    print("=" * 60)
    print("☀️ 午间分析 (11:25) — 复盘 + 策略调整")
    print(f"📅 {date_str} {now.strftime('%H:%M')}")
    print("=" * 60)

    # 加载早盘计划进行对比
    morning_plan = {}
    morning_path = os.path.join(day_dir, "morning.json")
    if os.path.exists(morning_path):
        try:
            with open(morning_path, "r", encoding="utf-8") as f:
                morning_plan = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    if morning_plan:
        print(f"\n📖 早盘计划回顾:")
        print(f"  决策: {morning_plan.get('decision_summary', '-')}")
        for a in morning_plan.get("action_plan", []):
            print(f"  {'🟢' if a['type']=='buy' else '🔴'} {a['code']} {a['name']} — {a['reason']}")

    # 获取最新数据
    print("\n📊 获取午间数据...")
    result = _get_market_data()
    if not result:
        print("  ❌ 数据获取失败")
        return False
    df, candidates, top_stocks, market_stats = result

    # 持仓跟踪
    pf = load_portfolio()
    summary = get_portfolio_summary(pf)
    holdings_info = _format_holding_status(pf, top_stocks)

    # 与早盘对比
    morning_profit = morning_plan.get("portfolio", {}).get("profit", 0)
    profit_change = summary["profit"] - morning_profit

    print(f"\n💼 持仓变化: 浮盈{summary['profit']:+.2f} (较早盘{profit_change:+.2f})")
    for hi in holdings_info:
        print(f"  {hi['code']} {hi['name']} | {hi['pnl_pct']:+.1f}% | 评分{hi['score']}")

    # 市场变化
    print(f"\n🌡️ 上午走势: 均涨{market_stats['avg_change']:+.2f}%")
    print(f"  涨:{market_stats['up_count']} 跌:{market_stats['down_count']}")

    # 下午策略
    afternoon_strategy = []
    for hi in holdings_info:
        if hi["pnl_pct"] <= -4:
            afternoon_strategy.append(f"{hi['name']}跌幅较大({hi['pnl_pct']:.1f}%)，关注止损位")
        elif hi["pnl_pct"] >= 5:
            afternoon_strategy.append(f"{hi['name']}涨幅可观({hi['pnl_pct']:.1f}%)，可考虑止盈")
        elif hi["score"] < 50:
            afternoon_strategy.append(f"{hi['name']}评分走低({hi['score']})，下午观察是否减仓")

    if not afternoon_strategy:
        afternoon_strategy.append("持仓运行正常，继续持有观望")

    print(f"\n📋 下午策略:")
    for s in afternoon_strategy:
        print(f"  • {s}")

    # 复盘总结
    review = []
    if morning_plan.get("action_plan"):
        # 检查早盘计划是否执行了
        review.append(f"早盘计划{len(morning_plan['action_plan'])}条操作")
    if profit_change > 0:
        review.append(f"上午盈利改善{profit_change:+.2f}")
    elif profit_change < 0:
        review.append(f"上午盈利回撤{profit_change:+.2f}")
    review_summary = "。".join(review) if review else "上午运行平稳"

    # 保存
    record = {
        "session": "midday",
        "timestamp": now.isoformat(),
        "focus": "复盘+策略调整",
        "morning_reference": {
            "decision": morning_plan.get("decision_summary", ""),
            "actions": morning_plan.get("action_plan", []),
        },
        "market": {
            "stats": market_stats,
            "am_performance": f"均涨{market_stats['avg_change']:+.2f}%",
        },
        "portfolio": {
            "cash": summary["cash"],
            "total_value": summary["total_value"],
            "profit": summary["profit"],
            "profit_change_from_morning": round(profit_change, 2),
            "positions": holdings_info,
        },
        "top_candidates": [
            {"code": s["code"], "name": s["name"], "score": s["score"],
             "price": s["price"]}
            for s in top_stocks[:10]
        ],
        "afternoon_strategy": afternoon_strategy,
        "review_summary": review_summary,
    }

    log_path = os.path.join(day_dir, "midday.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已保存至 {log_path}")

    # 更新面板
    from collect_for_ai import _generate_suggestions
    _generate_suggestions(top_stocks, market_stats, df)
    print("  ✅ suggestions.json 已更新")

    return True


def run_afternoon():
    """14:50 尾盘分析 — 全日复盘 + 次日展望
    
    重点：
    1. 全日操作回顾（计划vs实际）
    2. 盈亏归因分析
    3. 今日经验教训
    4. 明日关注方向和计划
    """
    now = datetime.now(TZ)
    date_str = now.strftime("%Y-%m-%d")
    day_dir = _ensure_log_dir(date_str)

    print("=" * 60)
    print("🌇 尾盘分析 (14:50) — 全日复盘")
    print(f"📅 {date_str} {now.strftime('%H:%M')}")
    print("=" * 60)

    # 加载今日早盘和午间记录
    morning_plan = {}
    midday_plan = {}
    for session, var in [("morning", morning_plan), ("midday", midday_plan)]:
        path = os.path.join(day_dir, f"{session}.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if session == "morning":
                        morning_plan = data
                    else:
                        midday_plan = data
            except (json.JSONDecodeError, OSError):
                pass

    # 获取收盘数据
    print("\n📊 获取尾盘数据...")
    result = _get_market_data()
    if not result:
        print("  ❌ 数据获取失败")
        return False
    df, candidates, top_stocks, market_stats = result

    # 全日持仓表现
    pf = load_portfolio()
    summary = get_portfolio_summary(pf)
    holdings_info = _format_holding_status(pf, top_stocks)

    # 计算全日盈亏变化
    morning_profit = morning_plan.get("portfolio", {}).get("profit", summary["profit"])
    day_change = summary["profit"] - morning_profit

    print(f"\n💼 全日表现: 浮盈{summary['profit']:+.2f} (今日变动{day_change:+.2f})")
    for hi in holdings_info:
        print(f"  {hi['code']} {hi['name']} | 盈亏{hi['pnl_pct']:+.1f}% | 评分{hi['score']}")

    # 全日市场总结
    print(f"\n🌡️ 全日市场: 均涨{market_stats['avg_change']:+.2f}%")
    print(f"  涨:{market_stats['up_count']} 跌:{market_stats['down_count']} "
          f"涨停:{market_stats['limit_up']} 跌停:{market_stats['limit_down']}")

    # 计划执行回顾
    planned_actions = morning_plan.get("action_plan", [])
    print(f"\n📋 计划执行回顾:")
    if planned_actions:
        # 检查历史记录看是否执行了
        history_today = [h for h in pf.get("history", [])
                        if h.get("date", "").startswith(date_str.replace("-", "")[4:])]
        executed_codes = {h.get("code") for h in history_today}
        for a in planned_actions:
            status = "✅已执行" if a["code"] in executed_codes else "❌未执行"
            print(f"  {status} {'买' if a['type']=='buy' else '卖'} {a['code']} {a['name']}")
    else:
        print("  今日无预定操作")

    # 经验总结
    lessons = []
    if not planned_actions:
        # 没有早盘计划会让“计划 vs 实际”的复盘失去基准，属于流程问题，应该明确记录。
        lessons.append("未生成早盘计划，复盘闭环不完整；明日开盘前先输出早盘计划")
    if day_change > 50:
        lessons.append("今日表现良好，策略有效")
    elif day_change < -50:
        lessons.append("今日回撤较大，需检视持仓风险")
    if market_stats["avg_change"] < -1 and day_change > 0:
        lessons.append("大盘下跌但持仓抗跌，选股质量不错")
    elif market_stats["avg_change"] > 1 and day_change < 0:
        lessons.append("大盘上涨但持仓滞涨，需审视持仓是否偏弱")

    for hi in holdings_info:
        if hi["score"] < 50:
            lessons.append(f"{hi['name']}评分{hi['score']}偏低，明日考虑调仓")

    if not lessons:
        lessons.append("运行正常，继续持有观察")

    print(f"\n📝 经验教训:")
    for l in lessons:
        print(f"  • {l}")

    # 明日展望
    holdings_codes = {h["code"] for h in pf.get("holdings", [])}
    next_day_focus = []
    risk_reminders = []
    tech_keywords = ("多头", "金叉", "突破", "反转", "回踩", "新高", "放量", "反弹")

    # 只保留次日可执行的关注标的：评分够高、非已持仓、技术信号明确、单价不高且现金够买1手。
    for s in top_stocks:
        if s["code"] in holdings_codes or s["score"] < 65:
            continue
        if s.get("price", 0) > 50 or s.get("price", 0) * 100 > summary["cash"]:
            continue

        signal = next((sig for sig in s.get("signals", []) if any(k in sig for k in tech_keywords)), "")
        if not signal:
            continue

        # 弱市优先等回踩，强市才允许更贴近现价观察。
        if market_stats["avg_change"] <= -1:
            target_price = round(s["price"] * 0.992, 2)
        elif market_stats["avg_change"] <= 0.3:
            target_price = round(s["price"] * 0.995, 2)
        else:
            target_price = round(s["price"], 2)

        next_day_focus.append({
            "code": s["code"],
            "name": s["name"],
            "score": s["score"],
            "signal": signal,
            "target_price": target_price,
        })
        if len(next_day_focus) >= 5:
            break

    # 持仓提醒单独记录到风险提示中，不再混入 next_day_focus，便于次日早盘直接读取关注列表。
    for hi in holdings_info:
        if hi["pnl_pct"] <= -3:
            risk_reminders.append(f"{hi['name']}浮亏{hi['pnl_pct']:.1f}%，跌破{hi['stop_loss']}止损")

    print(f"\n🔮 明日关注:")
    if next_day_focus:
        for f_item in next_day_focus:
            print(
                f"  • 关注 {f_item['code']} {f_item['name']} "
                f"(评分{f_item['score']}, {f_item['signal']}) | 目标买入价 {f_item['target_price']}"
            )
    else:
        print("  • 暂无满足条件的新关注标的")
    for risk in risk_reminders:
        print(f"  • 风险提醒: {risk}")

    # 整体复盘摘要
    position_summary = "；".join(
        f"{hi['name']}{hi['pnl_pct']:+.1f}%"
        + (f"，接近止损{hi['stop_loss']}" if hi["pnl_pct"] <= -3 else "")
        for hi in holdings_info
    ) or "无持仓变动"
    review_summary = (
        f"市场均涨{market_stats['avg_change']:+.2f}%偏弱，{position_summary}；"
        f"今日以观察为主，明日优先风险控制。"
    )

    if market_stats["avg_change"] <= -1:
        market_plan = "市场弱势，只守不攻，优先处理止损和回撤"
    elif market_stats["avg_change"] <= 0.3:
        market_plan = "市场震荡，控制仓位，等回踩再低吸"
    else:
        market_plan = "市场偏强，可跟踪强势股但不追高"

    focus_plan = [
        f"{item['code']} {item['name']} 回踩 {item['target_price']} 附近再观察"
        for item in next_day_focus[:3]
    ]
    next_day_plan_parts = [market_plan] + risk_reminders + focus_plan
    if market_stats["avg_change"] <= -1:
        next_day_plan_parts.append("若大盘低开超过1%，暂缓所有新开仓")
    next_day_plan = "；".join(next_day_plan_parts)
    lessons_text = "；".join(lessons)

    # 保存
    record = {
        "session": "afternoon",
        "timestamp": now.isoformat(),
        "focus": "全日复盘+次日展望",
        "morning_reference": {
            "decision": morning_plan.get("decision_summary", ""),
            "actions": morning_plan.get("action_plan", []),
        },
        "midday_reference": {
            "strategy": midday_plan.get("afternoon_strategy", []),
        },
        "market": {
            "stats": market_stats,
            "day_summary": f"均涨{market_stats['avg_change']:+.2f}%",
        },
        "portfolio": {
            "cash": summary["cash"],
            "total_value": summary["total_value"],
            "profit": summary["profit"],
            "day_change": round(day_change, 2),
            "positions": holdings_info,
        },
        "plan_execution": {
            "planned": planned_actions,
            "executed": list({h.get("code") for h in pf.get("history", [])
                            if h.get("date", "").startswith(date_str.replace("-", "")[4:])}),
        },
        "lessons": lessons_text,
        "next_day_plan": next_day_plan,
        "next_day_focus": next_day_focus,
        "review_summary": review_summary,
        "top_candidates": [
            {"code": s["code"], "name": s["name"], "score": s["score"],
             "price": s["price"], "signals": s.get("signals", [])[:5]}
            for s in top_stocks[:10]
        ],
    }

    log_path = os.path.join(day_dir, "afternoon.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    print(f"\n💾 已保存至 {log_path}")

    # 更新面板
    from collect_for_ai import _generate_suggestions
    _generate_suggestions(top_stocks, market_stats, df)
    print("  ✅ suggestions.json 已更新")

    return True


def run_auto():
    """根据当前时间自动选择分析场景"""
    now = datetime.now(TZ)
    hour_min = now.hour * 60 + now.minute

    if hour_min < 10 * 60 + 30:
        # 10:30 之前 → 早盘分析
        return run_morning()
    elif hour_min < 13 * 60:
        # 13:00 之前 → 午间分析
        return run_midday()
    else:
        # 其他 → 尾盘分析
        return run_afternoon()


if __name__ == "__main__":
    session = sys.argv[1] if len(sys.argv) > 1 else "auto"

    dispatch = {
        "morning": run_morning,
        "midday": run_midday,
        "afternoon": run_afternoon,
        "auto": run_auto,
    }

    if session not in dispatch:
        print(f"用法: python3 {sys.argv[0]} [morning|midday|afternoon|auto]")
        print(f"\ncrontab 配置示例:")
        print(f"  0 10 * * 1-5  cd {os.path.dirname(os.path.abspath(__file__))} && .venv/bin/python scheduled_analysis.py morning")
        print(f"  25 11 * * 1-5 cd {os.path.dirname(os.path.abspath(__file__))} && .venv/bin/python scheduled_analysis.py midday")
        print(f"  50 14 * * 1-5 cd {os.path.dirname(os.path.abspath(__file__))} && .venv/bin/python scheduled_analysis.py afternoon")
        sys.exit(1)

    success = dispatch[session]()
    sys.exit(0 if success else 1)
