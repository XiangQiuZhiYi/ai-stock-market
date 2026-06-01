"""AI A股盯盘系统 - 持仓管理（含手续费）"""
import json
from datetime import datetime
from typing import Optional

from config import PORTFOLIO_FILE, BUDGET

# A股交易费率（2023年8月28日起生效）
COMMISSION_RATE = 0.00025     # 佣金万分之2.5
COMMISSION_MIN = 5.0           # 最低5元
STAMP_TAX_RATE = 0.0005       # 卖出印花税万分之5（即千分之0.5，2023.8.28下调）
TRANSFER_FEE_RATE = 0.00001   # 过户费万分之0.1（双向）


def calc_buy_fee(amount: float) -> float:
    """计算买入费用"""
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    transfer = amount * TRANSFER_FEE_RATE
    return round(commission + transfer, 2)


def calc_sell_fee(amount: float) -> float:
    """计算卖出费用"""
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    stamp_tax = amount * STAMP_TAX_RATE
    transfer = amount * TRANSFER_FEE_RATE
    return round(commission + stamp_tax + transfer, 2)


def load_portfolio() -> dict:
    """加载当前持仓"""
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "cash": BUDGET,
            "holdings": [],
            "history": [],
            "total_budget": BUDGET,
            "total_fees_paid": 0,
            "updated_at": None,
        }


def save_portfolio(portfolio: dict):
    """保存持仓"""
    portfolio["updated_at"] = datetime.now().isoformat()
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)


def get_portfolio_summary(portfolio: dict) -> dict:
    """计算持仓汇总"""
    holdings = portfolio.get("holdings", [])
    total_market_value = 0
    total_cost = 0
    total_sold_profit = 0

    for h in holdings:
        shares = h["shares"]
        buy_price = h["buy_price"]
        current_price = h.get("current_price", buy_price)
        total_market_value += shares * current_price
        total_cost += shares * buy_price

    # 已平仓盈亏
    for h in portfolio.get("history", []):
        if h.get("profit"):
            total_sold_profit += h["profit"]

    cash = portfolio.get("cash", 0)
    total_value = cash + total_market_value
    total_invested = portfolio.get("total_budget", BUDGET)
    profit = total_value - total_invested

    return {
        "cash": round(cash, 2),
        "market_value": round(total_market_value, 2),
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "profit": round(profit, 2),
        "profit_pct": round((profit / total_invested) * 100, 2) if total_invested > 0 else 0,
        "positions": len(holdings),
        "total_fees": round(portfolio.get("total_fees_paid", 0), 2),
        "realized_profit": round(total_sold_profit, 2),
    }


def record_buy(portfolio: dict, code: str, name: str, shares: int, price: float) -> dict:
    """记录买入操作（含手续费+止盈止损）"""
    amount = shares * price
    fee = calc_buy_fee(amount)
    total_cost = amount + fee

    if total_cost > portfolio["cash"]:
        return {"success": False, "error": f"现金不足: 需要{total_cost:.2f}, 只有{portfolio['cash']:.2f}"}

    portfolio["cash"] = round(portfolio["cash"] - total_cost, 2)
    portfolio["total_fees_paid"] = round(portfolio["total_fees_paid"] + fee, 2)

    # 检查是否已有该持仓
    for h in portfolio["holdings"]:
        if h["code"] == code:
            # 加仓：加权平均成本
            old_shares = h["shares"]
            old_cost = old_shares * h["buy_price"]
            new_cost = old_cost + amount
            h["shares"] = old_shares + shares
            h["buy_price"] = round(new_cost / h["shares"], 4)
            h["current_price"] = price
            h["buy_fee"] = round(h.get("buy_fee", 0) + fee, 2)
            # 加仓后按新成本重新计算止盈止损
            h["stop_loss"] = round(h["buy_price"] * 0.95, 2)
            h["take_profit"] = round(h["buy_price"] * 1.08, 2)
            h["cost_price"] = round(h["buy_price"] + h["buy_fee"] / h["shares"], 4)
            save_portfolio(portfolio)
            return {"success": True, "fee": fee, "action": "加仓"}

    # 新开仓：默认止盈止损线 +8% / -5%
    stop_loss = round(price * 0.95, 2)
    take_profit = round(price * 1.08, 2)

    portfolio["holdings"].append({
        "code": code,
        "name": name,
        "shares": shares,
        "buy_price": price,
        "current_price": price,
        "cost_price": round(price + fee / shares, 4),
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "buy_fee": round(fee, 2),
        "buy_date": datetime.now().strftime("%m-%d %H:%M"),
    })
    save_portfolio(portfolio)
    return {"success": True, "fee": fee, "action": "买入"}


def record_sell(portfolio: dict, code: str, shares: int, price: float) -> dict:
    """记录卖出操作（含印花税、佣金）"""
    for h in portfolio["holdings"]:
        if h["code"] == code:
            if shares > h["shares"]:
                return {"success": False, "error": f"持仓不足: 需要{shares}股, 只有{h['shares']}股"}

            sell_amount = shares * price
            fee = calc_sell_fee(sell_amount)
            net_proceeds = sell_amount - fee

            # 计算该笔盈亏：按持仓均价和记录的买入手续费按比例分摊
            buy_cost = shares * h["buy_price"]
            # 买入手续费按卖出比例分摊
            total_buy_fee = h.get("buy_fee", 0)
            sell_ratio = shares / h["shares"]
            allocated_buy_fee = total_buy_fee * sell_ratio
            profit = net_proceeds - buy_cost - allocated_buy_fee

            portfolio["cash"] = round(portfolio["cash"] + net_proceeds, 2)
            portfolio["total_fees_paid"] = round(portfolio["total_fees_paid"] + fee, 2)

            # 记录历史
            portfolio["history"].append({
                "code": code,
                "name": h["name"],
                "action": "卖出",
                "shares": shares,
                "sell_price": price,
                "buy_price": h["buy_price"],
                "profit": round(profit, 2),
                "fee": round(fee, 2),
                "date": datetime.now().strftime("%m-%d %H:%M"),
            })

            # 更新持仓
            if shares == h["shares"]:
                portfolio["holdings"].remove(h)
            else:
                h["shares"] -= shares
                # 剩余持仓按比例扣减已分摊的买入手续费
                h["buy_fee"] = round(total_buy_fee - allocated_buy_fee, 2)

            save_portfolio(portfolio)
            return {"success": True, "fee": fee, "profit": round(profit, 2)}

    return {"success": False, "error": f"未找到持仓: {code}"}


def price_simulator():
    """模拟运行 - 在terminal中测试"""
    if __name__ == "__main__":
        p = load_portfolio()
        print(f"初始现金: {p['cash']}")
        r = record_buy(p, "600795", "国电电力", 400, 5.07)
        print(f"买入结果: {r}")
        print(f"剩余现金: {p['cash']}")
        r2 = record_buy(p, "002354", "天娱数科", 200, 7.17)
        print(f"买入结果: {r2}")
        print(f"剩余现金: {p['cash']}")
        print(f"持仓: {p['holdings']}")
        print(f"总费用: {p['total_fees_paid']}")
        summary = get_portfolio_summary(p)
        print(f"汇总: {summary}")
        save_portfolio(p)
        print(f"\n✅ 已保存到 {PORTFOLIO_FILE}")
