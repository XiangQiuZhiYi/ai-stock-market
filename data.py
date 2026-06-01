"""AI A股盯盘系统 - 数据采集层（urllib直连，绕开macOS代理）"""
import json
import logging
import urllib.request
import urllib.parse
import pandas as pd
import numpy as np
import time
from datetime import datetime
from typing import Optional

from config import MARKET_DATA_FILE, MAX_PRICE, MIN_VOLUME

logger = logging.getLogger("astock.data")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

EASTMONEY_LIST = "https://push2.eastmoney.com/api/qt/clist/get"
FIELDS = {
    "f2": "price", "f3": "change_pct", "f4": "change_amount",
    "f5": "volume", "f6": "amount", "f8": "turnover",
    "f9": "pe", "f12": "code", "f14": "name",
    "f15": "high", "f16": "low", "f17": "open",
    "f18": "close", "f23": "pb",
}
_ALL_FIELDS = ",".join(FIELDS.keys())


def _fetch_json(url: str, params: dict = None) -> Optional[dict]:
    """通用GET请求"""
    if params:
        qs = urllib.parse.urlencode(params)
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with _OPENER.open(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def is_trading_time() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.strftime("%H:%M")
    return ("09:30" <= t <= "11:30") or ("13:00" <= t <= "15:00")


def get_all_stocks() -> pd.DataFrame:
    """A股活跃列表"""
    params = {
        "pn": 1, "pz": 500, "po": 1, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2,
        "fid": "f6",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": _ALL_FIELDS,
    }
    data = None
    for attempt in range(3):
        try:
            data = _fetch_json(EASTMONEY_LIST, params)
            break
        except Exception:
            if attempt == 2:
                logger.error("获取行情失败: 重试3次均失败")
                return pd.DataFrame()
            time.sleep(1)

    # 防御：请求成功但返回 None 或非法格式
    if not data or not isinstance(data, dict) or data.get("rc") != 0:
        return pd.DataFrame()

    items = data.get("data", {}).get("diff", [])
    if not items:
        return pd.DataFrame()

    rows = []
    for item in items:
        row = {}
        for fk, cn in FIELDS.items():
            val = item.get(fk)
            if val == "-" or val is None:
                val = np.nan
            else:
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    pass
            row[cn] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    if "code" in df.columns:
        # code 可能是 float/int/str，统一转换为6位字符串
        def _safe_code(x):
            if pd.isna(x) or x == "":
                return ""
            try:
                return str(int(float(x))).zfill(6)
            except (ValueError, TypeError):
                return str(x).zfill(6)
        df["code"] = df["code"].apply(_safe_code)
    if "volume" in df.columns:
        df["volume"] = df["volume"].astype(float) * 100
    if "amount" in df.columns:
        df["amount"] = df["amount"].astype(float) * 10000
    return df


def get_realtime_price(code: str) -> Optional[float]:
    """获取单只股票的实时最新价（东方财富个股快照接口）。
    
    用于在生成买入建议前做二次价格确认，避免用过时的缓存价格计算限价。
    返回 None 表示获取失败。
    """
    market = "0" if code.startswith(("0", "3")) else "1"
    secid = f"{market}.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": secid,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fields": "f43,f44,f45,f46,f47,f48,f170",
        "invt": 2,
        "fltt": 2,
    }
    try:
        data = _fetch_json(url, params)
        if not data or data.get("rc") != 0:
            return None
        d = data.get("data", {})
        # f43=最新价 f44=最高 f45=最低 f46=开盘
        price = d.get("f43")
        if price and price != "-" and float(price) > 0:
            return float(price)
        return None
    except Exception as e:
        logger.warning(f"获取{code}实时价失败: {e}")
        return None


def get_kline(code: str, period: str = "daily", days: int = 90) -> Optional[pd.DataFrame]:
    """K线（新浪接口）"""
    market = "sh" if code.startswith(("6", "9", "5")) else "sz"
    scale_map = {"daily": 240, "weekly": 1200, "monthly": 7200}
    scale = scale_map.get(period, 240)
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": f"{market}{code}", "scale": scale, "datalen": days}
    try:
        data = _fetch_json(url, params)
        if not data or not isinstance(data, list):
            return None
        records = []
        for item in data:
            records.append({
                "date": item.get("day", ""),
                "open": float(item.get("open", 0)),
                "close": float(item.get("close", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "volume": float(item.get("volume", 0)),
                "change_pct": 0,
            })
        return pd.DataFrame(records)
    except Exception as e:
        logger.warning(f"获取{code} K线失败: {e}")
        return None


def get_minute_trend(code: str) -> Optional[list]:
    """分时数据
    
    注意：非交易时段（午间休市、收盘后）东财接口可能返回空数据，
    此时尝试获取最近一个交易日的分时数据。
    """
    prefix = "1" if code.startswith(("6", "9", "5")) else "0"
    secid = f"{prefix}.{code}"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        # 统一补上东财常用 ut，减少接口偶发拒绝/空返回。
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "ndays": 1, "iscr": 0, "iscca": 0,
    }
    url = "https://push2.eastmoney.com/api/qt/stock/trends2/get"
    last_error = None
    for attempt in range(3):
        try:
            data = _fetch_json(url, params)
            if not data or not isinstance(data, dict):
                last_error = "empty response"
                time.sleep(0.6 * (attempt + 1))
                continue
            inner = data.get("data")
            if not inner or not isinstance(inner, dict):
                last_error = "missing data"
                time.sleep(0.6 * (attempt + 1))
                continue
            trends = inner.get("trends", [])
            if not trends:
                last_error = "empty trends"
                time.sleep(0.6 * (attempt + 1))
                continue
            result = []
            for line in trends:
                parts = line.split(",")
                if len(parts) >= 8:
                    try:
                        result.append({
                            "time": parts[0][-8:],
                            "price": float(parts[2]),
                            "avg": float(parts[7]),
                        })
                    except (ValueError, IndexError):
                        continue
            if result:
                return result
            last_error = "parsed no trend rows"
        except Exception as e:
            last_error = str(e)
        # 分时接口偶发 RemoteDisconnected，做短退避重试。
        time.sleep(0.6 * (attempt + 1))
    logger.warning(f"获取{code}分时失败: {last_error}")
    return None


def get_stock_quote(code: str) -> Optional[float]:
    """获取单只股票最新价（东财个股接口）
    
    注意：东财 qt/stock/get 接口 f43 返回值单位为"分"（即实际价格×100），
    f60 为昨收（同样以分为单位），用于交叉验证。
    """
    prefix = "1" if code.startswith(("6", "9", "5")) else "0"
    params = {
        "secid": f"{prefix}.{code}",
        "fields": "f43,f58,f60",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    }
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    try:
        data = _fetch_json(url, params)
        if not data or data.get("rc") != 0 or not data.get("data"):
            return None
        price = data["data"].get("f43")
        if price is None:
            return None
        price = float(price)
        if price <= 0:
            return None
        # f43 以分为单位，转换为元
        return price / 100.0
    except (TypeError, ValueError, AttributeError, OSError, Exception):
        return None


def filter_candidates(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[
        (df["price"] > 1) & (df["price"] <= MAX_PRICE) &
        (df["volume"] >= MIN_VOLUME) & (df["volume"] > 0) &
        (df["change_pct"].notna())
    ].copy()


def save_market_snapshot(df: pd.DataFrame):
    if df.empty:
        return
    keep = ["code","name","price","change_pct","volume","amount","turnover","pe","pb"]
    keep = [c for c in keep if c in df.columns]
    snapshot = df[keep].head(200).to_dict(orient="records")
    with open(MARKET_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "is_trading": is_trading_time(),
            "total_stocks": len(df),
            "stocks": snapshot,
        }, f, ensure_ascii=False, indent=2)
