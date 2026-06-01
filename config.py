"""AI A股盯盘系统 - 配置"""
import os

# 资金配置
BUDGET = 5000       # 总资金
MAX_POSITIONS = 3   # 同时持仓数（5000元分3只差不多了）
MIN_VOLUME = 500000 # 最小日成交量(股)，排除僵尸股
MAX_PRICE = 50      # 最大股价，保证5000能买1手
LONGTERM_MAX_PRICE = 60  # 中长期候选价格上限，避免纳入过高单价标的

# 交易时间
TRADING_START = "09:30"
TRADING_END = "15:00"
MORNING_END = "11:30"
AFTERNOON_START = "13:00"

# 分析频率（秒）
REFRESH_INTERVAL = 30  # 行情刷新间隔
AI_ANALYSIS_INTERVAL = 300  # AI深度分析间隔(5分钟)

# 文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUGGESTIONS_FILE = os.path.join(BASE_DIR, "suggestions.json")
PORTFOLIO_FILE = os.path.join(BASE_DIR, "portfolio.json")
MARKET_DATA_FILE = os.path.join(BASE_DIR, "market_data.json")
LONGTERM_SUGGESTIONS_FILE = os.path.join(BASE_DIR, "longterm_suggestions.json")
LONGTERM_LOG_DIR = os.path.join(BASE_DIR, "longterm_logs")
