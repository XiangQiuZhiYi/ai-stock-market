"""AI A股盯盘系统 - 技术分析层"""
import numpy as np
import pandas as pd
from typing import Optional

from data import get_kline
from capital_flow import analyze_capital_flow
from patterns import detect_patterns
from news_sentiment import analyze_news_sentiment


def calc_ma(series: pd.Series, window: int) -> pd.Series:
    """计算移动平均线"""
    return series.rolling(window=window).mean()


def calc_rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """计算RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=window, min_periods=1).mean()
    avg_loss = loss.rolling(window=window, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(series: pd.Series) -> dict:
    """计算MACD，返回 {'dif', 'dea', 'macd'}"""
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = 2 * (dif - dea)
    return {"dif": dif, "dea": dea, "macd": macd}


def calc_bollinger(series: pd.Series, window: int = 20) -> dict:
    """布林带"""
    ma = series.rolling(window=window).mean()
    std = series.rolling(window=window).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    return {"mid": ma, "upper": upper, "lower": lower}


def calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9) -> dict:
    """KDJ指标"""
    low_n = low.rolling(window=n).min()
    high_n = high.rolling(window=n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    
    k = pd.Series(50.0, index=close.index)
    d = pd.Series(50.0, index=close.index)
    
    for i in range(1, len(close)):
        k.iloc[i] = 2/3 * k.iloc[i-1] + 1/3 * rsv.iloc[i] if not np.isnan(rsv.iloc[i]) else k.iloc[i-1]
        d.iloc[i] = 2/3 * d.iloc[i-1] + 1/3 * k.iloc[i]
    
    j = 3 * k - 2 * d
    return {"k": k, "d": d, "j": j}


def analyze_stock(code: str, name: str, current_price: float, change_pct: float) -> dict:
    """对单只股票进行全面技术分析"""
    kline = get_kline(code)
    if kline is None or len(kline) < 20:
        return {"code": code, "name": name, "signal": "neutral", "score": 0,
                "reason": "数据不足，无法分析", "price": current_price,
                "change_pct": change_pct, "signals": []}

    close = kline["close"].astype(float)
    high = kline["high"].astype(float)
    low = kline["low"].astype(float)
    volume = kline["volume"].astype(float)

    latest_close = close.iloc[-1]
    # 如果当前价格和收盘价差异太大，用最新价
    latest_price = current_price if current_price > 0 else latest_close

    # --- 计算指标 ---
    ma5 = calc_ma(close, 5)
    ma10 = calc_ma(close, 10)
    ma20 = calc_ma(close, 20)
    rsi = calc_rsi(close, 14)
    macd = calc_macd(close)
    boll = calc_bollinger(close)
    kdj = calc_kdj(high, low, close)

    signals = []
    score = 50  # 基准分50，往上加/往下减

    # 1. 均线系统
    if ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1]:
        signals.append("多头排列 ↑")
        score += 15
    elif ma5.iloc[-1] < ma10.iloc[-1] < ma20.iloc[-1]:
        signals.append("空头排列 ↓")
        score -= 15
    elif ma5.iloc[-1] > ma10.iloc[-1] and ma10.iloc[-1] < ma20.iloc[-1]:
        signals.append("短期反弹")
        score += 5
    elif ma5.iloc[-1] < ma10.iloc[-1] and ma10.iloc[-1] > ma20.iloc[-1]:
        signals.append("短期回调")
        score -= 5

    # 2. RSI
    if len(rsi) > 1:
        rsi_val = rsi.iloc[-1]
        if rsi_val < 30:
            signals.append(f"超卖(RSI={rsi_val:.0f})")
            score += 15
        elif rsi_val > 70:
            signals.append(f"超买(RSI={rsi_val:.0f})")
            score -= 15
        else:
            signals.append(f"RSI={rsi_val:.0f}")

    # 3. MACD
    dif_latest = macd["dif"].iloc[-1]
    dea_latest = macd["dea"].iloc[-1]
    dif_prev = macd["dif"].iloc[-2] if len(macd["dif"]) > 1 else 0
    dea_prev = macd["dea"].iloc[-2] if len(macd["dea"]) > 1 else 0
    macd_latest = macd["macd"].iloc[-1]

    # 金叉：DIF 从下方上穿 DEA
    if dif_latest > dea_latest and dif_prev <= dea_prev:
        signals.append("MACD金叉 ↑")
        score += 20
    # 死叉：DIF 从上方下穿 DEA
    elif dif_latest < dea_latest and dif_prev >= dea_prev:
        signals.append("MACD死叉 ↓")
        score -= 20
    elif dif_latest > dea_latest and macd_latest > 0:
        signals.append("MACD多头")
        score += 5
    elif dif_latest < dea_latest and macd_latest < 0:
        signals.append("MACD空头")
        score -= 5
    elif dif_latest > dea_latest and macd_latest < 0:
        # 零轴下方金叉，低位反弹信号
        signals.append("MACD低位金叉↑")
        score += 10
    elif dif_latest < dea_latest and macd_latest > 0:
        # 零轴上方死叉，高位回落信号
        signals.append("MACD高位死叉↓")
        score -= 10

    # 4. 布林带
    if not np.isnan(boll["upper"].iloc[-1]) and not np.isnan(boll["lower"].iloc[-1]):
        if latest_price <= boll["lower"].iloc[-1]:
            signals.append("触及下轨")
            score += 10
        elif latest_price >= boll["upper"].iloc[-1]:
            signals.append("触及上轨")
            score -= 10

    # 5. KDJ
    k_latest = kdj["k"].iloc[-1]
    d_latest = kdj["d"].iloc[-1]
    k_prev = kdj["k"].iloc[-2] if len(kdj["k"]) > 1 else 50
    d_prev = kdj["d"].iloc[-2] if len(kdj["d"]) > 1 else 50

    if k_latest > d_latest and k_prev <= d_prev:
        signals.append("KDJ金叉")
        score += 10
    elif k_latest < d_latest and k_prev >= d_prev:
        signals.append("KDJ死叉")
        score -= 10
    elif k_latest > 80:
        signals.append("KDJ超买")
        score -= 5
    elif k_latest < 20:
        signals.append("KDJ超卖")
        score += 5

    # 6. 成交量
    vol_ma5 = volume.rolling(5).mean()
    if len(vol_ma5) > 1:
        vol_ratio = volume.iloc[-1] / vol_ma5.iloc[-1] if vol_ma5.iloc[-1] > 0 else 1
        if vol_ratio > 2:
            signals.append(f"放量{vol_ratio:.1f}倍")
            score += 5
        elif vol_ratio < 0.5:
            signals.append(f"缩量{vol_ratio:.1f}倍")
            score -= 5

    # 7. 当日涨跌幅
    if abs(change_pct) <= 1:
        signals.append("窄幅震荡")
    elif change_pct > 5:
        signals.append(f"大涨{change_pct:.1f}%")
        score += 3
    elif change_pct < -5:
        signals.append(f"大跌{change_pct:.1f}%")
        score -= 3

    # 8. 资金流向分析
    flow = analyze_capital_flow(code)
    if flow["signal"]:
        signals.append(flow["signal"])
        score += flow["score_adj"]

    # 9. 形态识别
    pattern_result = detect_patterns(kline, current_price=latest_price)
    if pattern_result["signals"]:
        signals.extend(pattern_result["signals"])
        score += pattern_result["score_adj"]

    # 10. 消息面情绪分析
    news = analyze_news_sentiment(code, name)
    if news["signal"]:
        signals.append(news["signal"])
        score += news["score_adj"]

    # --- 最终信号 ---
    score = max(0, min(100, score))
    if score >= 70:
        signal = "买入"
    elif score >= 55:
        signal = "关注"
    elif score <= 30:
        signal = "卖出"
    elif score <= 45:
        signal = "回避"
    else:
        signal = "中性"

    return {
        "code": code,
        "name": name,
        "price": round(latest_price, 2),
        "change_pct": round(change_pct, 2),
        "score": score,
        "signal": signal,
        "signals": signals,
        "ma5": round(ma5.iloc[-1], 2) if not np.isnan(ma5.iloc[-1]) else None,
        "ma10": round(ma10.iloc[-1], 2) if not np.isnan(ma10.iloc[-1]) else None,
        "ma20": round(ma20.iloc[-1], 2) if not np.isnan(ma20.iloc[-1]) else None,
        "rsi": round(rsi.iloc[-1], 1) if not np.isnan(rsi.iloc[-1]) else None,
        "macd_signal": "金叉" if dif_latest > dea_latest else "死叉",
        "capital_flow": flow.get("signal", ""),
        "patterns": pattern_result.get("patterns", []),
        "news_sentiment": news.get("sentiment", "neutral"),
        "key_news": news.get("key_news", []),
    }


def score_candidates(df: pd.DataFrame, top_n: int = 10) -> list:
    """对候选股票批量评分，返回Top N
    
    会分析 top_n * 5 只候选，确保覆盖面足够，
    再按评分排序取前 top_n 只。
    """
    results = []
    for _, row in df.iterrows():
        try:
            result = analyze_stock(
                code=row["code"],
                name=row["name"],
                current_price=float(row["price"]),
                change_pct=float(row.get("change_pct", 0)),
            )
            results.append(result)
        except Exception:
            continue
        if len(results) >= top_n * 5:  # 分析 5 倍候选量
            break

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]
