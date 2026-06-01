"""AI A股盯盘系统 - 资金流向分析

通过东财 fflow/kline 接口获取个股主力资金流向，
用于判断主力态度（吸筹/出货）。
"""
import json
import logging
import urllib.request
import urllib.parse
from typing import Optional

logger = logging.getLogger("astock.capital_flow")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_capital_flow(code: str, days: int = 5) -> Optional[list]:
    """获取个股近N日资金流向
    
    返回列表，每条格式:
    {
        "date": "2026-05-29",
        "main_net": -232936960.0,  # 主力净流入（正=流入，负=流出）
        "huge_net": ...,           # 超大单净流入
        "big_net": ...,            # 大单净流入
        "mid_net": ...,            # 中单净流入
        "small_net": ...,          # 小单净流入
    }
    """
    # 构建 secid：沪市=1，深市/创业板=0
    prefix = "1" if code.startswith(("6", "9", "5")) else "0"
    secid = f"{prefix}.{code}"

    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "klt": 101,   # 日线级别
        "lmt": days,  # 最近N天
    }
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers=_HEADERS)

    try:
        with _OPENER.open(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        if not data or data.get("rc") != 0:
            return None
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return None

        result = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 6:
                try:
                    result.append({
                        "date": parts[0],
                        "main_net": float(parts[1]),   # 主力净流入
                        "huge_net": float(parts[2]),   # 超大单净流入
                        "big_net": float(parts[3]),    # 大单净流入
                        "mid_net": float(parts[4]),    # 中单净流入
                        "small_net": float(parts[5]),  # 小单净流入
                    })
                except (ValueError, IndexError):
                    continue
        return result if result else None
    except Exception as e:
        logger.warning(f"获取{code}资金流向失败: {e}")
        return None


def analyze_capital_flow(code: str) -> dict:
    """分析资金流向，返回信号和评分调整
    
    返回:
    {
        "score_adj": int,       # 评分调整值（-15 ~ +15）
        "signal": str,          # 信号描述
        "main_net_today": float # 今日主力净流入
        "consecutive_days": int # 连续流入/流出天数
    }
    """
    flows = get_capital_flow(code, days=5)
    if not flows:
        return {"score_adj": 0, "signal": "", "main_net_today": 0, "consecutive_days": 0}

    # 今日主力净流入
    today = flows[-1]
    main_net_today = today["main_net"]

    # 计算连续流入/流出天数
    consecutive = 0
    if main_net_today > 0:
        # 统计连续流入天数
        for f in reversed(flows):
            if f["main_net"] > 0:
                consecutive += 1
            else:
                break
    elif main_net_today < 0:
        # 统计连续流出天数
        for f in reversed(flows):
            if f["main_net"] < 0:
                consecutive -= 1
            else:
                break

    # 计算近5日主力总净流入
    total_net = sum(f["main_net"] for f in flows)

    # 评分逻辑
    score_adj = 0
    signal = ""

    # 格式化金额显示：超过1亿用"亿"，否则用"万"
    def _fmt_amount(val):
        abs_val = abs(val)
        if abs_val >= 100_000_000:
            return f"{val/100_000_000:.2f}亿"
        else:
            return f"{val/10_000:.0f}万"

    if consecutive >= 3:
        # 连续3天以上主力流入 → 强烈看多
        score_adj = 15
        signal = f"主力连续{consecutive}日流入"
    elif consecutive >= 2:
        score_adj = 10
        signal = f"主力连续{consecutive}日流入"
    elif consecutive == 1 and main_net_today > 5_000_000:
        # 今日大额流入（>500万）
        score_adj = 8
        signal = f"主力今日流入{_fmt_amount(main_net_today)}"
    elif consecutive <= -3:
        # 连续3天以上流出 → 强烈看空
        score_adj = -15
        signal = f"主力连续{abs(consecutive)}日流出"
    elif consecutive <= -2:
        score_adj = -10
        signal = f"主力连续{abs(consecutive)}日流出"
    elif consecutive == -1 and main_net_today < -5_000_000:
        # 今日大额流出
        score_adj = -8
        signal = f"主力今日流出{_fmt_amount(abs(main_net_today))}"
    elif main_net_today > 0:
        score_adj = 3
        signal = f"主力小幅流入{_fmt_amount(main_net_today)}"
    elif main_net_today < 0:
        score_adj = -3
        signal = f"主力小幅流出{_fmt_amount(abs(main_net_today))}"

    # 额外：近5日总体判断加成
    if total_net > 20_000_000 and score_adj > 0:
        score_adj = min(score_adj + 5, 20)
        signal += " (5日累计流入)"
    elif total_net < -20_000_000 and score_adj < 0:
        score_adj = max(score_adj - 5, -20)
        signal += " (5日累计流出)"

    return {
        "score_adj": score_adj,
        "signal": signal,
        "main_net_today": main_net_today,
        "consecutive_days": consecutive,
    }
