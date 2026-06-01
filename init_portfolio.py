#!/usr/bin/env python3
"""初始化持仓文件"""
import json
import os
from datetime import datetime
from config import PORTFOLIO_FILE, BUDGET

portfolio = {
    "cash": BUDGET,
    "holdings": [],
    "history": [],
    "total_budget": BUDGET,
    "total_fees_paid": 0,
    "created_at": datetime.now().isoformat(),
    "updated_at": datetime.now().isoformat(),
}

# 安全创建目录：仅在 PORTFOLIO_FILE 有目录部分时才 makedirs
dir_path = os.path.dirname(PORTFOLIO_FILE)
if dir_path:
    os.makedirs(dir_path, exist_ok=True)
with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
    json.dump(portfolio, f, ensure_ascii=False, indent=2)

print(f"✅ 持仓初始化完成，资金: {BUDGET} 元")
print(f"   文件: {PORTFOLIO_FILE}")
