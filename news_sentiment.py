"""AI A股盯盘系统 - 消息面分析

通过东财搜索接口获取个股最新新闻/公告，
通过关键词匹配判断利好/利空，生成评分调整。
"""
import json
import re
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("astock.news")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://so.eastmoney.com/",
}
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# === 利好/利空关键词库 ===

# 强利好关键词（权重高）
STRONG_POSITIVE = [
    "净利润大增", "净利润同比增长", "业绩预增", "业绩大增",
    "中标", "签订.*合同", "签署.*协议", "重大订单",
    "回购", "增持", "股权激励",
    "获批", "突破", "首次",
    "战略合作", "战略投资",
    "纳入.*指数", "入选",
]

# 一般利好
MILD_POSITIVE = [
    "净利润增长", "营收增长", "业绩预告.*增",
    "分红", "派息", "送转",
    "基金调研", "机构调研", "北向资金.*买入",
    "扩产", "投产", "产能",
    "利好", "看好", "推荐",
    "突破.*均线", "新高",
]

# 强利空关键词
STRONG_NEGATIVE = [
    "净利润下降", "净利润亏损", "业绩预减", "业绩预亏", "亏损",
    "减持", "股东.*减持", "大股东.*减持",
    "立案调查", "违规", "处罚", "警示函",
    "退市", r"\bST\b", r"\*ST",
    "诉讼", "仲裁.*败诉",
    "暴雷", "爆雷",
]

# 一般利空
MILD_NEGATIVE = [
    "下跌", "跌停", "大跌",
    "质押", "冻结",
    "解禁", "限售股.*上市",
    "高管.*辞职", "董事.*辞职",
    "利空", "风险提示",
    "破发", "破净",
]


def get_stock_news(code: str, count: int = 10) -> Optional[list]:
    """获取个股最新新闻/公告
    
    通过东财搜索接口按股票代码搜索相关资讯。
    返回新闻列表，每条包含 title, date, content 字段。
    """
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    param_obj = {
        "uid": "",
        "keyword": code,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": count,
            }
        },
    }
    params = {
        "cb": "jQuery_cb",
        "param": json.dumps(param_obj, ensure_ascii=False),
    }
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers=_HEADERS)

    try:
        with _OPENER.open(req, timeout=10) as r:
            text = r.read().decode()
        # 去掉 JSONP 包装 jQuery_cb(...)
        text = text[text.index("(") + 1 : text.rindex(")")]
        data = json.loads(text)

        if data.get("code") != 0:
            return None

        articles = data.get("result", {}).get("cmsArticleWebOld", [])
        if not articles or not isinstance(articles, list):
            return None

        result = []
        for a in articles:
            title = a.get("title", "")
            # 清除 <em> 标签
            title = re.sub(r"</?em>", "", title)
            result.append({
                "title": title,
                "date": a.get("date", ""),
                "content": re.sub(r"</?em>", "", a.get("content", "")),
                "source": a.get("mediaName", ""),
            })
        return result
    except Exception as e:
        logger.warning(f"获取{code}新闻失败: {e}")
        return None


def _match_keywords(text: str, keywords: list) -> list:
    """匹配关键词列表，返回命中的关键词"""
    matched = []
    for kw in keywords:
        if re.search(kw, text):
            matched.append(kw)
    return matched


def analyze_news_sentiment(code: str, name: str = "") -> dict:
    """分析个股消息面情绪
    
    返回:
    {
        "score_adj": int,         # 评分调整（-20 ~ +20）
        "signal": str,            # 信号描述
        "sentiment": str,         # "positive" / "negative" / "neutral"
        "news_count": int,        # 近期新闻数
        "key_news": list[str],    # 关键新闻标题（最多3条）
        "positive_hits": list,    # 利好命中
        "negative_hits": list,    # 利空命中
    }
    """
    news = get_stock_news(code, count=10)
    if not news:
        return {
            "score_adj": 0, "signal": "", "sentiment": "neutral",
            "news_count": 0, "key_news": [], "positive_hits": [], "negative_hits": [],
        }

    # 只分析近7天的新闻
    now = datetime.now()
    recent_news = []
    for n in news:
        try:
            news_date = datetime.strptime(n["date"][:10], "%Y-%m-%d")
            if (now - news_date).days <= 7:
                recent_news.append(n)
        except (ValueError, TypeError):
            recent_news.append(n)  # 解析失败也保留

    if not recent_news:
        return {
            "score_adj": 0, "signal": "", "sentiment": "neutral",
            "news_count": 0, "key_news": [], "positive_hits": [], "negative_hits": [],
        }

    # 对每条新闻做关键词匹配
    total_positive_score = 0
    total_negative_score = 0
    all_positive_hits = []
    all_negative_hits = []
    key_news = []

    for n in recent_news:
        # 合并标题和摘要内容做匹配
        text = f"{n['title']} {n.get('content', '')}"
        # 相关性过滤：新闻必须与该股直接相关（包含股票名或代码）
        # 排除"个股一览""盘点"等泛泛而谈的文章
        is_generic = any(k in n["title"] for k in ["一览", "盘点", "多只", "批量", "今日"])
        is_specific = name and name in text
        if is_generic and not is_specific:
            continue

        # 强利好
        hits = _match_keywords(text, STRONG_POSITIVE)
        if hits:
            total_positive_score += 10
            all_positive_hits.extend(hits)
            key_news.append(f"🟢 {n['title'][:30]}")

        # 一般利好
        hits = _match_keywords(text, MILD_POSITIVE)
        if hits:
            total_positive_score += 4
            all_positive_hits.extend(hits)
            if not key_news or len(key_news) < 3:
                key_news.append(f"🟢 {n['title'][:30]}")

        # 强利空
        hits = _match_keywords(text, STRONG_NEGATIVE)
        if hits:
            total_negative_score += 12
            all_negative_hits.extend(hits)
            key_news.append(f"🔴 {n['title'][:30]}")

        # 一般利空
        hits = _match_keywords(text, MILD_NEGATIVE)
        if hits:
            total_negative_score += 5
            all_negative_hits.extend(hits)
            if len(key_news) < 3:
                key_news.append(f"🔴 {n['title'][:30]}")

    # 计算净情绪分
    net_score = total_positive_score - total_negative_score

    # 映射到评分调整（上限±20）
    if net_score >= 15:
        score_adj = 20
        sentiment = "positive"
        signal = f"消息面强利好({len(all_positive_hits)}条)"
    elif net_score >= 8:
        score_adj = 12
        sentiment = "positive"
        signal = f"消息面利好"
    elif net_score >= 3:
        score_adj = 5
        sentiment = "positive"
        signal = f"消息面偏多"
    elif net_score <= -15:
        score_adj = -20
        sentiment = "negative"
        signal = f"消息面强利空({len(all_negative_hits)}条)"
    elif net_score <= -8:
        score_adj = -12
        sentiment = "negative"
        signal = f"消息面利空"
    elif net_score <= -3:
        score_adj = -5
        sentiment = "negative"
        signal = f"消息面偏空"
    else:
        score_adj = 0
        sentiment = "neutral"
        signal = ""

    # 去重
    all_positive_hits = list(set(all_positive_hits))
    all_negative_hits = list(set(all_negative_hits))

    return {
        "score_adj": score_adj,
        "signal": signal,
        "sentiment": sentiment,
        "news_count": len(recent_news),
        "key_news": key_news[:3],
        "positive_hits": all_positive_hits[:5],
        "negative_hits": all_negative_hits[:5],
    }
