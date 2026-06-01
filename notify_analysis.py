#!/usr/bin/env python3
"""A股分析提醒：按早盘/午盘/尾盘时间点发送 macOS 通知。"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime


def _resolve_session(cli_session: str) -> str:
    """把命令行参数映射到提醒场景，auto 时按当前时刻推断。"""
    if cli_session in {"morning", "midday", "afternoon"}:
        return cli_session

    now = datetime.now()
    hour_min = now.hour * 60 + now.minute
    # 与 scheduled_analysis.py 保持一致：10:30前算早盘，13:00前算午盘，其余算尾盘。
    if hour_min < 10 * 60 + 30:
        return "morning"
    if hour_min < 13 * 60:
        return "midday"
    return "afternoon"


def _build_notification(session: str) -> tuple[str, str]:
    """根据时段构造通知标题与正文。"""
    mapping = {
        "morning": ("🌅 早盘提醒", "该做早盘分析了（开盘决策 / 持仓风险检查）"),
        "midday": ("☀️ 午盘提醒", "该做午盘分析了（早盘复盘 / 下午策略）"),
        "afternoon": ("🌇 尾盘提醒", "该做尾盘复盘了（全日总结 / 次日计划）"),
    }
    return mapping[session]


def _is_weekday() -> bool:
    """仅在工作日提醒，避免周末打扰。"""
    return datetime.now().weekday() < 5


def _send_macos_notification(title: str, message: str) -> None:
    """通过 osascript 调用系统通知中心。"""
    # 使用 argv 传参给 AppleScript，避免手写字符串转义带来的注入和格式问题。
    applescript = (
        'on run argv\n'
        '  set nTitle to item 1 of argv\n'
        '  set nBody to item 2 of argv\n'
        '  display notification nBody with title "A股盯盘提醒" subtitle nTitle\n'
        'end run'
    )
    subprocess.run(
        ["/usr/bin/osascript", "-e", applescript, title, message],
        check=True,
    )


def main() -> int:
    session = _resolve_session(sys.argv[1] if len(sys.argv) > 1 else "auto")
    if not _is_weekday():
        print("非交易日，跳过提醒。")
        return 0

    title, message = _build_notification(session)
    _send_macos_notification(title, message)
    print(f"已发送提醒: {title} - {message}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"发送通知失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
