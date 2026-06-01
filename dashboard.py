"""AI A股盯盘系统 - Textual 终端面板 v3"""
import json
import os
from datetime import datetime
from rich.table import Table
from textual.app import App, ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import Header, Footer, Static, Label, Input
from textual.binding import Binding
from textual import work
from textual.screen import ModalScreen

from data import get_all_stocks, filter_candidates, is_trading_time, save_market_snapshot, get_minute_trend, get_stock_quote
from analysis import score_candidates
from portfolio import (
    load_portfolio, get_portfolio_summary, save_portfolio,
    record_buy, record_sell, calc_buy_fee, calc_sell_fee,
)
from config import REFRESH_INTERVAL, SUGGESTIONS_FILE, MARKET_DATA_FILE

# 面板按 A 股常用语义显示：上涨/利好 用红色，下跌/利空 用绿色。
POSITIVE_COLOR = "red"
NEGATIVE_COLOR = "green"
POSITIVE_ICON = "🔴"
NEGATIVE_ICON = "🟢"


def gain_loss_color(value: float) -> str:
    """统一涨跌和盈亏配色，避免不同面板出现相反语义。"""
    return POSITIVE_COLOR if value >= 0 else NEGATIVE_COLOR


def sentiment_color(is_positive: bool) -> str:
    """统一利好/利空配色，和涨跌颜色保持一致。"""
    return POSITIVE_COLOR if is_positive else NEGATIVE_COLOR


# ══════════════════ 组件 ══════════════════

class PortfolioPanel(Static):
    def update_data(self, portfolio: dict):
        s = get_portfolio_summary(portfolio)
        c = gain_loss_color(s["profit"])
        sign = "+" if s["profit"] >= 0 else ""
        self.update(
            f"💰 总资产: [bold]{s['total_value']:.2f}[/]   "
            f"现金: [bold]{s['cash']:.2f}[/]   "
            f"市值: {s['market_value']:.2f}   "
            f"手续费: {s['total_fees']:.2f}\n"
            f"📊 浮动盈亏: [bold {c}]{sign}{s['profit']:.2f} ({sign}{s['profit_pct']}%)[/]   "
            f"持仓: {s['positions']}只"
        )


class MarketClock(Static):
    def update_data(self):
        now = datetime.now()
        wd = ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()]
        status = "🔥 交易中" if is_trading_time() else "⏸ 休市"
        self.update(f"[bold]{now.strftime('%Y-%m-%d %H:%M:%S')}[/] {wd}  {status}")


class HoldingsTable(Static):
    def update_data(self, portfolio: dict, spots: dict):
        holdings = portfolio.get("holdings", [])
        if not holdings:
            self.update("[dim]暂无持仓，按B买入[/]")
            return
        lines = ["┌─ 代码 ──┬─ 名称 ──┬─ 股数 ─┬── 成本 ──┬── 现价 ──┬── 涨跌 ──┬─ 手续费 ─┬── 浮盈 ───┐"]
        alerts = []
        for h in holdings:
            code = h["code"]
            bp = h["buy_price"]
            shares = h["shares"]
            cp = spots.get(code, h.get("current_price", bp))
            fee = h.get("buy_fee", 0)
            pct = ((cp - bp) / bp * 100) if bp > 0 else 0
            pnl = (cp - bp) * shares - fee
            pc, pp = (gain_loss_color(x) for x in (pct, pnl))
            lines.append(
                f"│ {code:<8} │ {h['name']:<8} │ "
                f"{shares:>4}  │ {bp:>8.2f} │ {cp:>8.2f} │ "
                f"[{pc}]{pct:>+.2f}%[/] │ {fee:>8.2f} │ [{pp}]{pnl:>+.2f}[/] │"
            )
            sl = h.get("stop_loss", bp * 0.95)
            tp = h.get("take_profit", bp * 1.08)
            if cp <= sl:
                alerts.append(f"{NEGATIVE_ICON} {code} 触及止损!")
            elif cp >= tp:
                alerts.append(f"{POSITIVE_ICON} {code} 触及止盈!")
        lines.append("└───────────┴──────────┴────────┴───────────┴───────────┴──────────┴──────────┴───────────┘")
        content = "\n".join(lines)
        if alerts:
            content += "\n  " + "  ".join(alerts)
        self.update(content)


class SectorPanel(Static):
    """板块信息面板：市场方向 + 热门板块"""
    def update_data(self):
        try:
            with open(SUGGESTIONS_FILE, "r") as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.update("[dim]等待分析...[/]")
            return
        ms = d.get("market_summary", {})
        lines = [
            f"📈 方向: [bold]{ms.get('direction','-')}[/]  ⚡ 风险: {ms.get('risk_level','-')}",
            "",
        ]
        for s in ms.get("hot_sectors", [])[:5]:
            lines.append(f"  • {s}")
        bp = d.get("buy_plan", {}).get("summary", {})
        if bp:
            lines.append("")
            lines.append(f"💰 投入: {bp.get('total_invest','-')}  💵 余: {bp.get('remaining_cash','-')}")
        self.update("\n".join(lines))


class NewsPanel(Static):
    """消息面面板：从分析结果中展示重要新闻"""
    def update_data(self):
        try:
            with open(SUGGESTIONS_FILE, "r") as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.update("[dim]等待分析...[/]")
            return
        # 从 news_highlights 字段读取重要新闻
        news_items = d.get("news_highlights", [])
        if not news_items:
            # 兜底：从 timing_advice 提取
            timing = d.get("timing_advice", "")
            if timing:
                self.update(f"[dim]{timing}[/]")
            else:
                self.update("[dim]暂无重要消息[/]")
            return
        lines = []
        for item in news_items[:6]:
            tag = item.get("sentiment", "")
            code = item.get("code", "")
            title = item.get("title", "")
            # 按情感着色
            if "利好" in tag or "positive" in tag:
                lines.append(f"  [{sentiment_color(True)}]▲[/] {code} {title}")
            elif "利空" in tag or "negative" in tag:
                lines.append(f"  [{sentiment_color(False)}]▼[/] {code} {title}")
            else:
                lines.append(f"  [dim]●[/] {code} {title}")
        self.update("\n".join(lines))


class WatchList(Static):
    def update_data(self):
        try:
            with open(SUGGESTIONS_FILE, "r") as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.update("[dim]等待分析...[/]")
            return
        items = []
        for pos in d.get("buy_plan", {}).get("positions", []):
            # 买入建议附带完整推荐理由
            reason_parts = []
            if pos.get("reason"):
                reason_parts.append(pos["reason"])
            if pos.get("entry_style"):
                # 把入场方式单独展示，避免用户误把限价当成固定公式。
                reason_parts.append(f"{pos['entry_style']}：{pos.get('entry_reason', '')}")
            reason_parts.append(f"限价:{pos.get('limit_price','-')} 止损:{pos.get('stop_loss','-')} 止盈:{pos.get('take_profit','-')}")
            items.append({"code": pos.get("code",""), "name": pos.get("name",""),
                          "reason": " | ".join(reason_parts), "source": "buy"})
        for it in d.get("alerts", {}).get("watch_list", []):
            items.append({"code": it.get("code",""), "name": it.get("name",""),
                          "reason": it.get("reason","观察中"), "source": "watch"})
        if not items:
            self.update("[dim]暂无关注[/]")
            return
        lines = []
        for i, item in enumerate(items[:6], 1):
            tag = f"[{POSITIVE_COLOR}]买[/]" if item["source"] == "buy" else "[dim]关[/]"
            lines.append(f"  [{i}] {tag} {item['code']} {item['name']}")
            # 展示完整推荐理由（不截断）
            lines.append(f"      [dim]{item['reason']}[/]")
        self.update("\n".join(lines))


class AIRecommendations(Static):
    def update_data(self, mode: str = "buy"):
        try:
            with open(SUGGESTIONS_FILE, "r") as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.update("[dim]等待分析...[/]")
            return
        content = []
        if mode == "buy":
            bp = d.get("buy_plan", {})
            logic = bp.get("logic", "")
            if logic:
                content.append(f"[dim]{logic}[/]\n")
            for pos in bp.get("positions", []):
                content.append(f"[bold {POSITIVE_COLOR}]{pos['code']}[/] {pos['name']} {pos.get('shares','')}股")
                content.append(f"  参考价: {pos.get('reference_price','-')}  限价: [bold yellow]{pos.get('limit_price','-')}[/]")
                if pos.get("entry_style"):
                    content.append(f"  入场方式: {pos['entry_style']}")
                if pos.get("entry_reason"):
                    content.append(f"  [dim]入场依据: {pos['entry_reason']}[/]")
                content.append(f"  止损: {pos.get('stop_loss','-')}  止盈: {pos.get('take_profit','-')}")
                cc = pos.get("caution", "")
                if cc:
                    content.append(f"  [{NEGATIVE_COLOR}]⚠ {cc}[/]")
                content.append(f"  [dim]↳ {pos.get('reason','')}[/]\n")
            if not bp.get("positions"):
                content.append("[dim]当前无买入建议[/]")
            dnb = d.get("alerts", {}).get("do_not_buy", [])
            if dnb:
                content.append(f"[dim]🚫 {', '.join(x['code'] for x in dnb[:4])} 不追[/]")
        else:
            ha = d.get("holding_advice", [])
            if ha:
                for h in ha:
                    content.append(f"[bold {NEGATIVE_COLOR}]{h['code']}[/] {h['name']}")
                    content.append(f"  建议卖价: [bold yellow]{h.get('suggested_sell_price','-')}[/]")
                    if h.get("exit_style"):
                        content.append(f"  卖出方式: {h['exit_style']}")
                    if h.get("exit_reason"):
                        content.append(f"  [dim]卖出依据: {h['exit_reason']}[/]")
                    content.append(f"  止损: {h.get('stop_loss','-')}  止盈: {h.get('take_profit','-')}")
                    content.append(f"  [dim]↳ {h.get('reason','')}[/]\n")
            else:
                pf = load_portfolio()
                hld = pf.get("holdings", [])
                if hld:
                    for h in hld:
                        content.append(f"[bold {NEGATIVE_COLOR}]{h['code']}[/] {h['name']} {h['shares']}股")
                        content.append(f"  成本: {h.get('buy_price','-')}  止损: {h.get('stop_loss','-')}  止盈: {h.get('take_profit','-')}")
                        content.append(f"  [dim]↳ 买入 {h.get('buy_date','?')}[/]\n")
                else:
                    content.append("[dim]空仓中[/]")
            wl = d.get("alerts", {}).get("watch_list", [])
            if wl:
                content.append(f"[dim]👀 {', '.join(x['code'] for x in wl[:4])}[/]")
        ta = d.get("timing_advice", "")
        if ta:
            content.append(f"\n[dim]📝 {ta}[/]")
        self.update("\n".join(content))


# ══════════════════ 弹窗 ══════════════════

class ProfitChartScreen(ModalScreen[None]):
    """每日浮盈折线图：从 analysis_logs 中读取每日收盘浮盈，绘制趋势"""
    CSS = """ProfitChartScreen { align: center middle; background: rgba(0,0,0,0.85); } #profit-chart-box { width: 90; height: auto; max-height: 40; border: solid $primary 50%; background: $surface; padding: 1 2; }"""
    BINDINGS = [Binding("escape", "dismiss_chart", "返回"), Binding("q", "dismiss_chart", "返回")]

    def compose(self):
        yield Static("加载中...", id="profit-chart-box")

    def on_mount(self):
        self.run_worker(self._do_load, thread=True)

    def _do_load(self):
        data = self._collect_daily_profit()
        self.app.call_from_thread(lambda: self._render_chart(data))

    @staticmethod
    def _collect_daily_profit() -> list:
        """扫描 analysis_logs，提取每日浮盈数据，返回 [{date, profit, total_value}]"""
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_logs")
        if not os.path.isdir(log_dir):
            return []
        results = []
        for day in sorted(os.listdir(log_dir)):
            day_dir = os.path.join(log_dir, day)
            if not os.path.isdir(day_dir):
                continue
            # 优先用 afternoon（收盘数据最完整），其次 midday，最后 morning
            record = None
            for session in ("afternoon", "midday", "morning"):
                path = os.path.join(day_dir, f"{session}.json")
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            record = json.load(f)
                        break
                    except (json.JSONDecodeError, OSError):
                        continue
            if record:
                pf = record.get("portfolio", {})
                profit = pf.get("profit", 0)
                total_value = pf.get("total_value", 5000)
                results.append({"date": day, "profit": profit, "total_value": total_value})
        # 补充当天实时数据（如果 analysis_logs 里还没有今天的）
        today = datetime.now().strftime("%Y-%m-%d")
        if not results or results[-1]["date"] != today:
            try:
                from portfolio import load_portfolio, get_portfolio_summary
                pf = load_portfolio()
                s = get_portfolio_summary(pf)
                results.append({"date": today, "profit": s["profit"], "total_value": s["total_value"]})
            except Exception:
                pass
        return results

    def _render_chart(self, data: list):
        if not data:
            self.query_one("#profit-chart-box", Static).update(
                "\n  📉 每日浮盈走势\n\n  [dim]暂无数据，运行分析后生成[/]\n"
            )
            return

        profits = [d["profit"] for d in data]
        dates = [d["date"][5:] for d in data]  # MM-DD
        latest = data[-1]

        pmax, pmin = max(profits), min(profits)
        # 确保零线在范围内
        pmax = max(pmax, 0)
        pmin = min(pmin, 0)
        prange = pmax - pmin if pmax > pmin else 1.0

        W, H = 68, 16
        lines = []

        # 标题
        cur_profit = latest["profit"]
        cc = gain_loss_color(cur_profit)
        sign = "+" if cur_profit >= 0 else ""
        lines.append(f"\n  📉 [bold]每日浮盈走势[/]  当前: [{cc}]{sign}{cur_profit:.2f}[/]")
        lines.append(f"  [dim]总资产: {latest['total_value']:.2f}  |  共{len(data)}个交易日[/]\n")

        # 计算零线位置
        zero_y = int((0 - pmin) / prange * (H - 1)) if prange > 0 else H // 2

        # 采样：将数据点映射到 W 列
        if len(profits) >= W:
            step = len(profits) / W
            sampled = [profits[int(i * step)] for i in range(W)]
        else:
            # 数据少于宽度时，每个数据点占多列
            sampled = []
            for p in profits:
                cols = max(1, W // len(profits))
                sampled.extend([p] * cols)
            sampled = sampled[:W]
            # 补齐
            while len(sampled) < W:
                sampled.append(sampled[-1])

        norm = [int((p - pmin) / prange * (H - 1)) for p in sampled]

        # 绘制
        for y in range(H - 1, -1, -1):
            row = "  "
            for x in range(W):
                v = norm[x]
                if v == y:
                    c = gain_loss_color(sampled[x])
                    row += f"[{c}]●[/]"
                elif y == zero_y:
                    row += "[dim]·[/]"
                else:
                    row += " "
            # 标注价格刻度
            price_at_y = pmin + (y / (H - 1)) * prange
            if y == H - 1:
                row += f" [{POSITIVE_COLOR}]{pmax:+.2f}[/]"
            elif y == 0:
                row += f" [{NEGATIVE_COLOR}]{pmin:+.2f}[/]"
            elif y == zero_y:
                row += " [dim]  0.00[/]"
            lines.append(row)

        # X 轴
        lines.append("  " + "─" * W)

        # 日期标注
        if len(dates) == 1:
            lines.append(f"  {dates[0]:^{W}}")
        elif len(dates) <= 3:
            lab = f"  {dates[0]}"
            lab += " " * (W - len(dates[0]) - len(dates[-1])) + dates[-1]
            lines.append(lab)
        else:
            d0, dm, d1 = dates[0], dates[len(dates)//2], dates[-1]
            lab = f"  {d0}"
            lab += " " * (W // 2 - len(d0) - len(dm)//2) + dm
            lab += " " * (W // 2 - len(dm)//2 - len(d1)) + d1
            lines.append(lab)

        # 统计摘要
        lines.append("")
        max_p = max(profits)
        min_p = min(profits)
        mc = gain_loss_color(max_p)
        nc = gain_loss_color(min_p)
        lines.append(f"  最高: [{mc}]{max_p:+.2f}[/]  最低: [{nc}]{min_p:+.2f}[/]")

        lines.append("\n  [dim]按 ESC/Q 返回[/]")
        self.query_one("#profit-chart-box", Static).update("\n".join(lines))

    def action_dismiss_chart(self):
        self.dismiss(None)


class ChartScreen(ModalScreen[None]):
    CSS = """ChartScreen { align: center middle; background: rgba(0,0,0,0.85); } #chart-box { width: 96; height: auto; max-height: 34; border: solid $primary 50%; background: $surface; padding: 1 0; }"""
    BINDINGS = [
        Binding("escape", "dismiss_chart", "返回"), Binding("q", "dismiss_chart", "返回"),
        Binding("left", "prev_stock", "上一个", show=False), Binding("right", "next_stock", "下一个", show=False),
    ]
    def __init__(self, stocks: list, index: int = 0, cache: dict = None):
        super().__init__()
        self._stocks = stocks
        self._idx = index % len(stocks) if stocks else 0
        self._cache = cache or {}
    @property
    def _cur(self):
        return self._stocks[self._idx]
    def compose(self):
        total = len(self._stocks)
        yield Static(f"加载中... ({self._idx+1}/{total})" if total > 1 else "加载中...", id="chart-box")
    def on_mount(self):
        # 分时图优先占满终端宽度，尽量压缩每列代表的时间跨度。
        self._resize_chart_box()
        self._load()
    def _resize_chart_box(self):
        box = self.query_one("#chart-box", Static)
        box.styles.width = max(96, min(self.app.size.width - 4, 180))
        box.styles.max_height = max(24, min(self.app.size.height - 2, 40))
    def _load(self):
        self.run_worker(self._do_load_chart, thread=True)
    def _do_load_chart(self):
        code = self._cur["code"]
        trends = self._cache.get(code)
        # 缓存中没有有效分时数据 → 实时拉取
        if not trends or len(trends) < 5:
            fresh = get_minute_trend(code)
            if fresh and len(fresh) >= 5:
                trends = fresh
                self._cache[code] = trends
        idx, total = self._idx, len(self._stocks)
        def u():
            self._show(trends, idx, total)
        self.app.call_from_thread(u)
    def _show(self, trends, idx, total):
        s = self._cur
        code, name, bp = s["code"], s["name"], s.get("buy_price", 0)
        if not trends or len(trends) < 5:
            nav = f" ({idx+1}/{total})" if total > 1 else ""
            hint = "当前休市，暂无分时数据" if not is_trading_time() else "暂无分时数据，请按 S 扫描后查看"
            self.query_one("#chart-box", Static).update(f"\n  📈 {name} ({code}){nav}\n\n  [dim]{hint}[/]\n")
            return
        prices = [t["price"] for t in trends]
        times = [t["time"][:5] for t in trends]
        pmax, pmin = max(prices), min(prices)
        prange = pmax - pmin if pmax > pmin else 0.01
        latest, first = prices[-1], prices[0]
        chg = ((latest - first) / first * 100) if first > 0 else 0
        cc = gain_loss_color(chg)
        # 采样列数跟随终端可用宽度动态放大，避免固定 72 列导致分时柱过宽。
        plot_area_width = max(60, min(self.app.size.width - 16, 156))
        W, H = plot_area_width, 12
        norm = [int((p - pmin) / prange * (H - 1)) for p in prices]
        # 用浮点步长均匀铺满横轴，避免整数截断让前半段点位过密、后半段过疏。
        if W <= 1:
            samp = [norm[-1]]
        else:
            step = (len(norm) - 1) / (W - 1)
            samp = [norm[min(len(norm) - 1, round(i * step))] for i in range(W)]
        lines = []
        nav = f" ({idx+1}/{total})  ◀ ▶ 切换" if total > 1 else ""
        lines.append(f"\n 📈 [bold]{name} ({code})[/]{nav}\n")
        for y in range(H - 1, -1, -1):
            row = " "
            for x in range(W):
                v = samp[x]
                row += "█" if v == y else "│" if v > y else " "
            if y in (H - 1, 0, H // 2):
                row += f" {pmin + (y / (H - 1)) * prange:.2f}"
            lines.append(row)
        lines.append(" " + "─" * W)
        if len(times) > 1:
            t0, tm, t1 = times[0], times[len(times)//2], times[-1]
            lab = f" {t0}"
            lab += " " * (W // 2 - len(t0) - len(tm)//2) + tm
            lab += " " * (W // 2 - len(tm)//2 - len(t1)) + t1
            lines.append(lab)
        if bp > 0 and pmin <= bp <= pmax:
            lines.append(f" [dim]━━ 买入价: {bp:.2f}[/]")
        lines.append("")
        lines.append(f" 📊 开:{first:.2f}  收:{latest:.2f}  高:{pmax:.2f}  低:{pmin:.2f}  涨跌: [{cc}]{chg:+.2f}%[/]")
        self.query_one("#chart-box", Static).update("\n".join(lines))
    def action_prev_stock(self):
        if len(self._stocks) > 1:
            self._idx = (self._idx - 1) % len(self._stocks)
            self._load()
    def action_next_stock(self):
        if len(self._stocks) > 1:
            self._idx = (self._idx + 1) % len(self._stocks)
            self._load()
    def action_dismiss_chart(self):
        self.dismiss(None)


class StockSelectScreen(ModalScreen[dict]):
    CSS = """StockSelectScreen { align: center middle; background: rgba(0,0,0,0.85); } #select-box { width: 50; height: auto; border: solid $primary 50%; background: $surface; padding: 1 2; }"""
    BINDINGS = [Binding("escape", "cancel", "取消")] + [Binding(str(i), f"pick({i})", "", show=False) for i in range(1, 7)]
    def __init__(self, stocks: list, title: str = "选择股票"):
        super().__init__()
        self._stocks = stocks
        self._title = title
    def compose(self):
        lines = [f"\n  [bold]{self._title}[/]\n"]
        for i, s in enumerate(self._stocks, 1):
            lines.append(f"  [{i}] {s['code']} {s['name']}")
        lines.append(f"\n  [dim]按 1-{len(self._stocks)} 选择, ESC 取消[/]")
        yield Static("\n".join(lines), id="select-box")
    def action_pick(self, n):
        if 0 <= n - 1 < len(self._stocks):
            self.dismiss(self._stocks[n - 1])
    def action_cancel(self):
        self.dismiss(None)


class TradeInputScreen(ModalScreen[str]):
    CSS = """TradeInputScreen { align: center middle; background: rgba(0,0,0,0.7); } #trade-dialog { width: 55; height: auto; border: solid $primary 50%; background: $surface; padding: 1 2; }"""
    BINDINGS = [Binding("escape", "cancel", "取消")]
    def __init__(self, trade_type: str):
        super().__init__()
        self.trade_type = trade_type
    def compose(self):
        label = f"{POSITIVE_ICON} 买入" if self.trade_type == "buy" else f"{NEGATIVE_ICON} 卖出"
        yield Container(
            Label(label), Label("格式: 代码 股数 价格", id="trade-hint"),
            Input(placeholder="代码 股数 价格", id="trade-input"), Static("", id="trade-result"),
            id="trade-dialog",
        )
    def on_mount(self):
        self.query_one("#trade-input", Input).focus()
    def on_input_submitted(self, event):
        self._process()
    def _process(self):
        inp = self.query_one("#trade-input", Input)
        raw = inp.value.strip()
        if not raw:
            return
        parts = raw.split()
        if len(parts) < 3:
            self.query_one("#trade-result", Static).update(f"[{NEGATIVE_COLOR}]格式: 代码 股数 价格[/]")
            inp.value = ""
            inp.focus()
            return
        code = parts[0].zfill(6)
        try:
            int(parts[1]); float(parts[2])
        except ValueError:
            self.query_one("#trade-result", Static).update(f"[{NEGATIVE_COLOR}]股数和价格必须是数字[/]")
            inp.value = ""
            inp.focus()
            return
        self.dismiss(f"{self.trade_type}:{code}:{parts[1]}:{parts[2]}")
    def action_cancel(self):
        self.dismiss(None)


class TradeHistoryScreen(ModalScreen[None]):
    """交易记录弹窗：以列表形式展示选中股票的买卖历史"""
    CSS = """
    TradeHistoryScreen { align: center middle; background: rgba(0,0,0,0.85); }
    #history-box { width: 90; height: auto; max-height: 36; border: solid $primary 50%; background: $surface; padding: 1 2; overflow-y: auto; }
    .hist-header { text-style: bold; color: $primary; }
    .hist-row { height: 1; }
    .hist-separator { color: $primary-darken-2; }
    """
    BINDINGS = [Binding("escape", "dismiss_history", "返回"), Binding("q", "dismiss_history", "返回")]

    def __init__(self, code: str, name: str, holdings: list, history: list):
        super().__init__()
        self._code = code
        self._name = name
        self._holdings = holdings
        self._history = history

    def compose(self):
        lines = []
        lines.append(f"[bold]📋 {self._name} ({self._code}) 交易记录[/]")
        lines.append("")

        # 当前持仓摘要（单行）
        holding = next((h for h in self._holdings if h["code"] == self._code), None)
        if holding:
            cp = holding.get("current_price", holding["buy_price"])
            pnl = (cp - holding["buy_price"]) * holding["shares"]
            pnl_pct = (cp - holding["buy_price"]) / holding["buy_price"] * 100
            color = gain_loss_color(pnl)
            lines.append(f"[bold]▶ 当前持仓[/]  {holding['shares']}股 @ {holding['buy_price']:.2f}  "
                         f"现价 {cp:.2f}  [{color}]{pnl:+.2f}({pnl_pct:+.1f}%)[/]  "
                         f"止损{holding.get('stop_loss','-')} 止盈{holding.get('take_profit','-')}")
            lines.append(f"  买入时间: {holding.get('buy_date','?')}  手续费: {holding.get('buy_fee',0):.2f}元")
            lines.append("")

        # 历史交易列表（表格形式）
        related = [h for h in self._history if h.get("code") == self._code]
        if related:
            lines.append("[bold]▶ 交易明细[/]")
            # 表头
            lines.append(f"  {'序号':^4} │ {'时间':<14} │ {'操作':<4} │ {'数量':>5} │ {'价格':>8} │ {'盈亏':>10} │ {'手续费':>7}")
            lines.append(f"  {'─'*4}─┼─{'─'*14}─┼─{'─'*4}─┼─{'─'*5}─┼─{'─'*8}─┼─{'─'*10}─┼─{'─'*7}")
            total_profit = 0
            total_fee = 0
            for i, h in enumerate(related, 1):
                date = h.get("date", "?")
                action = h.get("action", "?")
                shares = h.get("shares", 0)
                price = h.get("sell_price", h.get("buy_price", 0))
                profit = h.get("profit", 0)
                fee = h.get("fee", 0)
                total_profit += profit
                total_fee += fee
                pc = gain_loss_color(profit)
                action_tag = f"[{POSITIVE_COLOR}]买入[/]" if "buy" in action.lower() or "买" in action else f"[{NEGATIVE_COLOR}]卖出[/]"
                lines.append(
                    f"  {i:^4} │ {date:<14} │ {action_tag:<4} │ {shares:>5} │ {price:>8.2f} │ [{pc}]{profit:>+10.2f}[/] │ {fee:>7.2f}"
                )
            lines.append(f"  {'─'*4}─┼─{'─'*14}─┼─{'─'*4}─┼─{'─'*5}─┼─{'─'*8}─┼─{'─'*10}─┼─{'─'*7}")
            # 合计行
            pc = gain_loss_color(total_profit)
            lines.append(f"  {'合计':^4} │ {'':14} │ {'':4} │ {'':>5} │ {'':>8} │ [{pc}]{total_profit:>+10.2f}[/] │ {total_fee:>7.2f}")
            lines.append("")
            lines.append(f"  共 {len(related)} 笔交易  总盈亏: [{pc}]{total_profit:+.2f}[/]  总费用: {total_fee:.2f}")
        elif not holding:
            lines.append("[dim]该股票无任何交易记录[/]")
        else:
            lines.append("[dim]暂无历史卖出记录[/]")

        lines.append("")
        lines.append("[dim]按 ESC/Q 返回[/]")
        yield Static("\n".join(lines), id="history-box")

    def action_dismiss_history(self):
        self.dismiss(None)


# ══════════════════ 市场整体判断面板 ══════════════════

class MarketJudgmentPanel(Static):
    """一行展示每次分析后的市场整体判断：方向、涨幅、风险等级、操作建议。"""

    def update_data(self):
        try:
            with open(SUGGESTIONS_FILE, "r") as f:
                d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.update("[dim]等待分析...[/]")
            return

        ms = d.get("market_summary", {})
        direction = ms.get("direction", "未知")
        avg_change = ms.get("avg_change", 0)
        risk_level = ms.get("risk_level", "未知")
        hot_sectors = ms.get("hot_sectors", [])
        timing = d.get("timing_advice", "")
        logic = d.get("buy_plan", {}).get("logic", "")

        # 方向颜色：含"涨"/"多" → 红；含"跌"/"空" → 绿；其余 yellow
        if any(k in direction for k in ("涨", "多", "强")):
            dir_color = POSITIVE_COLOR
        elif any(k in direction for k in ("跌", "弱", "空", "震")):
            dir_color = NEGATIVE_COLOR
        else:
            dir_color = "yellow"

        # 均涨幅颜色
        change_color = gain_loss_color(avg_change)
        change_str = f"{avg_change:+.2f}%" if isinstance(avg_change, (int, float)) else str(avg_change)

        # 风险等级颜色：高风险 → 绿（坏）；低/中 → 红（好）
        if risk_level in ("高", "极高"):
            risk_color = NEGATIVE_COLOR
        elif risk_level in ("低", "极低"):
            risk_color = POSITIVE_COLOR
        else:
            risk_color = "yellow"

        sectors_str = "  ".join(f"[bold]{s}[/]" for s in hot_sectors[:3]) if hot_sectors else ""

        parts = [
            f"[bold {dir_color}]▶ {direction}[/]",
            f"均涨 [{change_color}]{change_str}[/]",
            f"风险 [{risk_color}]{risk_level}[/]",
        ]
        if sectors_str:
            parts.append(f"热点 {sectors_str}")
        if timing:
            parts.append(f"[dim]│ {timing}[/]")
        if logic:
            # 截断较长的逻辑说明
            short_logic = logic[:60] + ("…" if len(logic) > 60 else "")
            parts.append(f"[dim]│ {short_logic}[/]")

        self.update("  ".join(parts))


# ══════════════════ 主面板 ══════════════════

class AstockDashboard(App):
    CSS = """
    Screen { background: $surface; }
    #clock-panel { height: 2; padding: 0 1; background: $boost; }
    #portfolio-panel { height: auto; min-height: 3; max-height: 6; padding: 0 1; background: $boost; border-bottom: solid $primary 30%; }
    #stocks-section { height: 1fr; min-height: 12; layout: horizontal; padding: 0 1; }
    #holdings-panel { width: 70%; border-right: solid $primary 20%; padding-right: 1; }
    #sector-panel { width: 30%; padding-left: 1; }
    #holdings-section { height: 50%; min-height: 6; }
    #watch-section { height: 50%; min-height: 6; border-top: solid $primary 20%; padding-top: 1; }
    #holdings-table { height: 1fr; min-height: 4; }
    #watch-table { height: 1fr; min-height: 4; }
    #sector-content { height: 1fr; }
    #sector-top { height: 50%; border-bottom: solid $primary 20%; }
    #news-section { height: 50%; padding-top: 1; }
    #news-content { height: 1fr; }
    #judgment-section { height: 2; padding: 0 1; background: $boost; border-top: solid $primary 30%; }
    #judgment-panel { height: 1; }
    #bottom-section { height: 35%; min-height: 12; layout: horizontal; border-top: solid $primary 30%; }
    #buy-panel { width: 50%; padding: 0 1; border-right: solid $primary 20%; }
    #sell-panel { width: 50%; padding: 0 1; }
    .section-title { text-style: bold; color: $primary; height: 1; }
    #status-bar { height: 1; background: $boost; }
    """
    BINDINGS = [
        Binding("q", "quit", "退出"), Binding("r", "refresh", "刷新"),
        Binding("s", "force_scan", "扫描"), Binding("b", "buy", "买入"),
        Binding("e", "sell", "卖出"), Binding("v", "view_chart", "走势"),
        Binding("w", "watch_chart", "关注"), Binding("h", "view_history", "记录"),
        Binding("m", "profit_chart", "盈亏"),
    ]
    def __init__(self):
        super().__init__()
        self._spot_prices = {}
        self._stock_names = {}
        self._minute_cache = {}
        self.refresh_count = 0
    def compose(self):
        yield Header(show_clock=True)
        yield MarketClock(id="clock")
        yield PortfolioPanel(id="portfolio")
        with Container(id="stocks-section"):
            with Vertical(id="holdings-panel"):
                with Vertical(id="holdings-section"):
                    yield Label("📊 持仓股票", classes="section-title")
                    yield HoldingsTable(id="holdings-table")
                with Vertical(id="watch-section"):
                    yield Label("👀 今日关注", classes="section-title")
                    yield WatchList(id="watch-table")
            with Vertical(id="sector-panel"):
                with Vertical(id="sector-top"):
                    yield Label("🔥 板块", classes="section-title")
                    yield SectorPanel(id="sector-content")
                with Vertical(id="news-section"):
                    yield Label("📰 消息面", classes="section-title")
                    yield NewsPanel(id="news-content")
        with Container(id="bottom-section"):
            with Vertical(id="buy-panel"):
                yield Label(f"{POSITIVE_ICON} 买入建议", classes="section-title")
                yield AIRecommendations(id="buy-advice")
            with Vertical(id="sell-panel"):
                yield Label(f"{NEGATIVE_ICON} 卖出建议", classes="section-title")
                yield AIRecommendations(id="sell-advice")
        with Container(id="judgment-section"):
            yield Label("🧭 整体判断", classes="section-title")
            yield MarketJudgmentPanel(id="judgment-panel")
        yield Static("", id="status-bar")
    def on_mount(self):
        self.refresh_count = 5  # 首次刷新即触发分时缓存（+1=6, 6%6==0）
        self.set_interval(REFRESH_INTERVAL, self._periodic)
        self._update_clock()
        self.call_after_refresh(self._fetch_and_render)
    def _periodic(self):
        self._update_clock()
        self.call_after_refresh(self._fetch_and_render)
    def _update_clock(self):
        self.query_one("#clock", MarketClock).update_data()
    @work(thread=True)
    async def _fetch_and_render(self):
        self.refresh_count += 1
        
        # 先拉数据，再更新持仓（顺序重要）
        if self.refresh_count % 3 == 0:
            try:
                df = get_all_stocks()
                if not df.empty:
                    for _, row in df.iterrows():
                        code = row.get("code",""); price = row.get("price"); name = row.get("name","")
                        if code:
                            if price and price > 0: self._spot_prices[code] = float(price)
                            if name and name != str(code): self._stock_names[code] = str(name)
            except Exception:
                pass
        
        if self.refresh_count % 6 == 0:
            codes = set()
            pf = load_portfolio()
            for h in pf.get("holdings", []): codes.add(h["code"])
            try:
                with open(SUGGESTIONS_FILE) as f: d = json.load(f)
                for p in d.get("buy_plan",{}).get("positions",[]): codes.add(p.get("code",""))
                for it in d.get("alerts",{}).get("watch_list",[]): codes.add(it.get("code",""))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                pass
            for code in codes:
                if code:
                    t = get_minute_trend(code)
                    if t:
                        # 只在拿到有效数据时更新缓存，保留旧缓存以备休市时显示
                        self._minute_cache[code] = t
        
        # 数据就绪后更新持仓
        pf = load_portfolio()
        # 补全持仓中不在 _spot_prices 里的个股价格（如不在前500活跃列表）
        for h in pf.get("holdings", []):
            code = h.get("code", "")
            if code and code not in self._spot_prices:
                price = get_stock_quote(code)
                if price and price > 0:
                    self._spot_prices[code] = price
        # 将数据拷贝传入主线程，避免线程间共享可变对象
        import copy
        pf_copy = copy.deepcopy(pf)
        self.app.call_from_thread(lambda: self._update_holdings(pf_copy))
        self.app.call_from_thread(lambda: self._update_panels())
    def _update_holdings(self, pf):
        updated = False
        for h in pf.get("holdings", []):
            code = h.get("code","")
            if code in self._spot_prices:
                new_price = self._spot_prices[code]
                if h.get("current_price") != new_price:
                    h["current_price"] = new_price
                    updated = True
        if updated:
            save_portfolio(pf)
        self.query_one("#holdings-table", HoldingsTable).update_data(pf, self._spot_prices)
        self.query_one("#portfolio", PortfolioPanel).update_data(pf)
        s = get_portfolio_summary(pf)
        t = "--:--:--"
        try:
            with open(SUGGESTIONS_FILE) as f: d = json.load(f)
            raw = d.get("timestamp","")
            if "T" in raw: t = raw.split("T")[1][:5]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        trading = "🔥交易中" if is_trading_time() else "⏸休市"
        hs = f"{len(pf.get('holdings',[]))}只持仓" if pf.get("holdings") else "空仓"
        self.query_one("#status-bar", Static).update(
            f"  💰 可用: [bold]{s['cash']:.2f}[/]  |  {hs}  |  {trading}  |  "
            f"分析: [bold]{t}[/]  |  S扫描 B买入 E卖出 V/W走势 H记录 M盈亏"
        )
    def _update_panels(self):
        self.query_one("#judgment-panel", MarketJudgmentPanel).update_data()
        self.query_one("#buy-advice", AIRecommendations).update_data("buy")
        self.query_one("#sell-advice", AIRecommendations).update_data("sell")
        self.query_one("#sector-content", SectorPanel).update_data()
        self.query_one("#news-content", NewsPanel).update_data()
        self.query_one("#watch-table", WatchList).update_data()
    def _lookup_name(self, code):
        return self._stock_names.get(code, code)
    # ── 操作 ──
    def action_refresh(self):
        self.refresh_count = 2
        self._update_clock()
        self.call_after_refresh(self._fetch_and_render)
    def action_force_scan(self):
        """S键：强制刷新所有数据，包括分时图缓存"""
        self.refresh_count = 5  # +1=6 触发分时缓存
        # 不清空旧缓存：休市时新请求可能拿不到数据，保留旧数据以供展示
        self._update_clock()
        self.query_one("#status-bar", Static).update("  🔄 [bold yellow]获取数据中...[/]")
        self.call_after_refresh(self._fetch_and_render)
    def action_view_chart(self):
        pf = load_portfolio()
        hld = pf.get("holdings", [])
        if not hld: return
        stocks = [{"code": h["code"], "name": h["name"], "buy_price": h.get("buy_price",0)} for h in hld]
        self.push_screen(StockSelectScreen(stocks, "📊 持仓股票"),
                         lambda s: self.push_screen(ChartScreen(stocks, stocks.index(s), self._minute_cache)) if s else None)
    def action_watch_chart(self):
        try:
            with open(SUGGESTIONS_FILE) as f: d = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        items = []
        for p in d.get("buy_plan",{}).get("positions",[]): items.append({"code":p["code"],"name":p["name"]})
        for it in d.get("alerts",{}).get("watch_list",[]): items.append({"code":it["code"],"name":it["name"]})
        if not items: return
        self.push_screen(StockSelectScreen(items, "👀 关注股票"),
                         lambda s: self.push_screen(ChartScreen(items, items.index(s), self._minute_cache)) if s else None)
    def action_buy(self):
        self.push_screen(TradeInputScreen("buy"), self._handle_trade)
    def action_sell(self):
        self.push_screen(TradeInputScreen("sell"), self._handle_trade)
    def action_profit_chart(self):
        """M键：查看每日浮盈折线图"""
        self.push_screen(ProfitChartScreen())
    def action_view_history(self):
        """H键：查看持仓股票的交易记录"""
        pf = load_portfolio()
        # 收集所有有记录的股票（当前持仓 + 历史交易过的）
        stock_map = {}
        for h in pf.get("holdings", []):
            stock_map[h["code"]] = {"code": h["code"], "name": h["name"]}
        for h in pf.get("history", []):
            code = h.get("code", "")
            if code and code not in stock_map:
                stock_map[code] = {"code": code, "name": h.get("name", code)}
        stocks = list(stock_map.values())
        if not stocks:
            return
        self.push_screen(
            StockSelectScreen(stocks, "📋 查看交易记录"),
            lambda s: self._show_history(s, pf) if s else None
        )
    def _show_history(self, stock: dict, pf: dict):
        """显示选中股票的交易记录弹窗"""
        self.push_screen(TradeHistoryScreen(
            code=stock["code"],
            name=stock["name"],
            holdings=pf.get("holdings", []),
            history=pf.get("history", []),
        ))
    def _handle_trade(self, result):
        pf = load_portfolio()
        if not result: return
        try:
            tp, code, shares_str, price_str = result.split(":")
            shares = int(shares_str); price = float(price_str)
        except (ValueError, AttributeError):
            return
        if tp == "buy":
            name = self._lookup_name(code)
            r = record_buy(pf, code, name, shares, price)
            if r["success"]: save_portfolio(pf)
        elif tp == "sell":
            r = record_sell(pf, code, shares, price)
            if r["success"]: save_portfolio(pf)
        self._update_holdings(pf)


def run_dashboard():
    AstockDashboard().run()

if __name__ == "__main__":
    run_dashboard()
