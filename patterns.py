"""AI A股盯盘系统 - 形态识别

基于K线数据识别常见技术形态：
- N日新高/新低
- 突破平台（箱体突破）
- 缩量回踩均线
- 放量突破前高
- 底部放量反转
"""
import numpy as np
import pandas as pd
from typing import Optional


def detect_patterns(kline: pd.DataFrame, current_price: float = 0) -> dict:
    """综合形态识别
    
    参数:
        kline: K线 DataFrame，需包含 close, high, low, volume 列
        current_price: 当前实时价格（0则用最后收盘价）
    
    返回:
        {
            "score_adj": int,       # 评分调整（-20 ~ +20）
            "signals": list[str],   # 形态信号列表
            "patterns": list[str],  # 识别到的形态名称
        }
    """
    if kline is None or len(kline) < 20:
        return {"score_adj": 0, "signals": [], "patterns": []}

    close = kline["close"].astype(float)
    high = kline["high"].astype(float)
    low = kline["low"].astype(float)
    volume = kline["volume"].astype(float)

    price = current_price if current_price > 0 else close.iloc[-1]
    score_adj = 0
    signals = []
    patterns = []

    # === 1. N日新高/新低 ===
    high_20 = high.iloc[-20:].max()
    low_20 = low.iloc[-20:].min()
    high_60 = high.iloc[-60:].max() if len(high) >= 60 else high.max()
    low_60 = low.iloc[-60:].min() if len(low) >= 60 else low.min()

    if price >= high_60:
        signals.append(f"60日新高")
        patterns.append("new_high_60")
        score_adj += 12
    elif price >= high_20:
        signals.append(f"20日新高")
        patterns.append("new_high_20")
        score_adj += 8
    elif price <= low_60:
        signals.append(f"60日新低")
        patterns.append("new_low_60")
        score_adj -= 10
    elif price <= low_20:
        signals.append(f"20日新低")
        patterns.append("new_low_20")
        score_adj -= 6

    # === 2. 突破平台（近20日箱体震荡后突破） ===
    platform_result = _detect_platform_breakout(close, high, low, volume, price)
    if platform_result:
        signals.append(platform_result["signal"])
        patterns.append(platform_result["pattern"])
        score_adj += platform_result["score_adj"]

    # === 3. 缩量回踩均线 ===
    pullback_result = _detect_pullback_to_ma(close, volume, price)
    if pullback_result:
        signals.append(pullback_result["signal"])
        patterns.append(pullback_result["pattern"])
        score_adj += pullback_result["score_adj"]

    # === 4. 放量突破前高 ===
    breakout_result = _detect_volume_breakout(close, high, volume, price)
    if breakout_result:
        signals.append(breakout_result["signal"])
        patterns.append(breakout_result["pattern"])
        score_adj += breakout_result["score_adj"]

    # === 5. 底部放量反转 ===
    reversal_result = _detect_bottom_reversal(close, low, volume, price)
    if reversal_result:
        signals.append(reversal_result["signal"])
        patterns.append(reversal_result["pattern"])
        score_adj += reversal_result["score_adj"]

    # === 6. 连续阴线（持续下跌信号） ===
    bear_result = _detect_consecutive_decline(close)
    if bear_result:
        signals.append(bear_result["signal"])
        patterns.append(bear_result["pattern"])
        score_adj += bear_result["score_adj"]

    # 分数上下限
    score_adj = max(-25, min(25, score_adj))

    return {
        "score_adj": score_adj,
        "signals": signals,
        "patterns": patterns,
    }


def _detect_platform_breakout(close, high, low, volume, price) -> Optional[dict]:
    """检测平台突破
    
    条件：近10-20日振幅<15%的窄幅震荡后，当前价突破箱体上沿
    """
    if len(close) < 25:
        return None

    # 取第-25到-5日作为平台区间（排除最近5日，看是否刚突破）
    platform_high = high.iloc[-25:-5].max()
    platform_low = low.iloc[-25:-5].min()
    platform_range = (platform_high - platform_low) / platform_low if platform_low > 0 else 999

    # 平台振幅需<15%才算横盘整理
    if platform_range > 0.15:
        return None

    # 当前价突破平台上沿
    if price > platform_high:
        # 检查是否伴随放量
        vol_ma = volume.iloc[-25:-5].mean()
        vol_recent = volume.iloc[-3:].mean()
        vol_amplified = vol_recent > vol_ma * 1.5 if vol_ma > 0 else False

        if vol_amplified:
            return {"signal": f"放量突破平台(振幅{platform_range*100:.0f}%)", "pattern": "platform_breakout_vol", "score_adj": 15}
        else:
            return {"signal": f"突破平台(振幅{platform_range*100:.0f}%)", "pattern": "platform_breakout", "score_adj": 10}

    # 跌破平台下沿
    if price < platform_low:
        return {"signal": "跌破平台支撑", "pattern": "platform_breakdown", "score_adj": -10}

    return None


def _detect_pullback_to_ma(close, volume, price) -> Optional[dict]:
    """检测缩量回踩均线
    
    条件：
    1. 均线（MA20）向上（趋势向好）
    2. 当前价回落到MA20附近（±3%范围内）
    3. 近3日成交量缩小（<5日均量的70%）
    """
    if len(close) < 25:
        return None

    ma20 = close.rolling(20).mean()
    if pd.isna(ma20.iloc[-1]) or pd.isna(ma20.iloc[-5]):
        return None

    # 均线向上
    ma_slope = (ma20.iloc[-1] - ma20.iloc[-5]) / ma20.iloc[-5] if ma20.iloc[-5] > 0 else 0
    if ma_slope <= 0:
        return None

    # 当前价在MA20附近（-3% ~ +3%）
    ma_val = ma20.iloc[-1]
    distance = (price - ma_val) / ma_val if ma_val > 0 else 999
    if not (-0.03 <= distance <= 0.03):
        return None

    # 缩量判断
    vol_ma5 = volume.rolling(5).mean()
    if pd.isna(vol_ma5.iloc[-4]):
        return None
    vol_recent = volume.iloc[-3:].mean()
    vol_avg = vol_ma5.iloc[-4]  # 用回踩前的均量做参考
    is_shrink = vol_recent < vol_avg * 0.7 if vol_avg > 0 else False

    if is_shrink:
        return {"signal": "缩量回踩MA20", "pattern": "pullback_ma20_shrink", "score_adj": 12}
    else:
        return {"signal": "回踩MA20", "pattern": "pullback_ma20", "score_adj": 5}


def _detect_volume_breakout(close, high, volume, price) -> Optional[dict]:
    """检测放量突破前高
    
    条件：
    1. 突破近20日最高价
    2. 当日/近2日成交量 > 5日均量的2倍
    """
    if len(close) < 22:
        return None

    # 前高：取第-22到-2日的最高价（排除最近1日）
    prev_high = high.iloc[-22:-1].max()
    if price <= prev_high:
        return None

    # 放量判断
    vol_ma5 = volume.iloc[-6:-1].mean()
    vol_today = volume.iloc[-1]
    if vol_ma5 <= 0:
        return None
    vol_ratio = vol_today / vol_ma5

    if vol_ratio >= 2.0:
        return {"signal": f"放量{vol_ratio:.1f}倍突破前高", "pattern": "vol_breakout_high", "score_adj": 15}
    elif vol_ratio >= 1.5:
        return {"signal": f"温和放量突破前高", "pattern": "mild_vol_breakout", "score_adj": 8}

    return None


def _detect_bottom_reversal(close, low, volume, price) -> Optional[dict]:
    """检测底部放量反转
    
    条件：
    1. 近20日处于下跌趋势（跌幅>10%）
    2. 最近2-3日出现放量阳线
    3. 当前价高于近3日低点
    """
    if len(close) < 22:
        return None

    # 近20日跌幅
    high_20_ago = close.iloc[-22:-10].max()
    low_recent = low.iloc[-5:].min()
    decline = (low_recent - high_20_ago) / high_20_ago if high_20_ago > 0 else 0

    # 需有明显下跌（>10%）
    if decline > -0.10:
        return None

    # 近3日是否有放量阳线
    vol_ma5 = volume.iloc[-8:-3].mean()
    if vol_ma5 <= 0:
        return None

    has_reversal = False
    for i in range(-3, 0):
        if i >= -len(close):
            daily_change = close.iloc[i] - close.iloc[i-1] if i-1 >= -len(close) else 0
            vol_ratio = volume.iloc[i] / vol_ma5 if vol_ma5 > 0 else 0
            # 阳线 + 放量1.5倍以上
            if daily_change > 0 and vol_ratio > 1.5:
                has_reversal = True
                break

    if has_reversal and price > low_recent:
        return {"signal": f"底部放量反转(跌{decline*100:.0f}%后)", "pattern": "bottom_reversal", "score_adj": 12}

    return None


def _detect_consecutive_decline(close) -> Optional[dict]:
    """检测连续阴线下跌
    
    连续4根以上阴线 → 做空信号
    """
    if len(close) < 6:
        return None

    # 统计最近连续阴线数
    consecutive_down = 0
    for i in range(-1, -7, -1):
        if i - 1 >= -len(close):
            if close.iloc[i] < close.iloc[i-1]:
                consecutive_down += 1
            else:
                break

    if consecutive_down >= 5:
        return {"signal": f"连续{consecutive_down}阴", "pattern": "consecutive_decline", "score_adj": -12}
    elif consecutive_down >= 4:
        return {"signal": f"连续{consecutive_down}阴", "pattern": "consecutive_decline", "score_adj": -8}

    return None
