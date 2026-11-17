#!/usr/bin/env python3
"""豆包「天天领额度」每日自动签到 —— 命令行入口。

用法：
    python main.py                # 正常签到
    python main.py --dry-run      # 只打印将要发出的请求，不真的签到
    python main.py --check        # 只检查配置是否完整
    python main.py --json         # 以 JSON 输出结果（方便被其他程序调用）
    python main.py --no-notify    # 跳过通知

退出码：
    0  签到成功 / 今日已签到
    1  签到失败
    2  配置错误
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 允许直接 `python main.py` 运行而不必先安装成包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import __version__, logger  # noqa: E402
from src.client import ALREADY, AUTH_FAILED, RISK, SUCCESS, CheckinResult  # noqa: E402
from src.config import Config, ConfigError, load_config  # noqa: E402
from src.doubao_work import DoubaoWorkClient  # noqa: E402
from src.notifier import build_message, notify  # noqa: E402

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="doubao-daily-checkin",
        description="豆包「天天领额度」每日自动签到",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印请求，不实际发送")
    parser.add_argument("--check", action="store_true", help="只检查配置完整性后退出")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    parser.add_argument("--no-notify", action="store_true", help="本次不发送通知")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def describe_request(config: Config) -> None:
    logger.info("配置检查通过", base_url=config.base_url, client=config.client_version)
    logger.info("Cookie", value=logger.mask(config.cookie))
    logger.info("超时/重试", timeout=f"{config.timeout}s", retries=config.retries)
    logger.info("通知通道", channels=", ".join(config.notify_channels) or "<none>")


def write_step_summary(result: CheckinResult) -> None:
    """GitHub Actions 任务页会展示这个 Markdown 摘要。"""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    title, body = build_message(result)
    try:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(f"## {title}\n\n{body}\n\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger.info(f"豆包每日签到 v{__version__} 启动", time=logger.timestamp())

    with logger.section("读取配置"):
        try:
            config = load_config()
        except ConfigError as exc:
            logger.error(str(exc))
            logger.info("提示：本地运行请复制 .env.example 为 .env 并填写；线上运行请配置仓库 Secrets。")
            return EXIT_CONFIG
        describe_request(config)

    if args.check:
        logger.ok("配置文件完整，可以开始签到")
        return EXIT_OK

    client = DoubaoWorkClient(config)

    result: CheckinResult
    if args.dry_run:
        with logger.section("Dry Run（只读探测，不领取）"):
            result = client.probe()
            logger.ok("dry-run 结束，未提交领取请求")
    else:
        with logger.section("执行签到"):
            result = client.run()

    if result.status == SUCCESS:
        logger.ok(result.message, amount=result.amount or "-", elapsed=f"{result.elapsed:.2f}s")
    elif result.status == ALREADY:
        logger.ok(result.message)
    elif result.status == AUTH_FAILED:
        logger.error(result.message)
        logger.info("处理建议：重新抓一次 Cookie，更新 DOUBAO_COOKIE 后重试。")
    elif result.status == RISK:
        logger.error(result.message)
        logger.info("处理建议：降低频率、换网络环境，或改为手动签到。")
    else:
        logger.error(result.message)
        logger.info(f"响应片段：{result.body_snippet[:500]}")

    write_step_summary(result)

    if not args.no_notify and not args.dry_run and config.notify_channels:
        with logger.section("发送通知"):
            notify(result, config.notify_channels, config.notify_on_already)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))

    return EXIT_OK if result.ok else EXIT_FAILED


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warn("已手动中断")
        raise SystemExit(130)
