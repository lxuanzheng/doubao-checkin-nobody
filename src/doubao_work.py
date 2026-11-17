"""豆包工作每日签到 · 三步链路客户端。

链路（与官方活动页行为对齐）：
    POST /alice/user/launch                         发现活动组 campaign_group_code
    POST /alice/ug/campaign/v3/detail/ (或 list/)    读取任务列表与今日签到状态
    POST /alice/ug/campaign/landing/checkin         {"scene": 活动组} 领取，再回查确认

设计原则：
1. 只操作本人账号的每日签到任务，不碰其他成长任务；
2. 已签到直接判 ALREADY，不重复提交；
3. 领取后以详情回查的 checked_in_today 为准，不把单个 code=0 当成功；
4. 风控码 710010702 不伪造 SDK 字段（biz_params / AgwCommonParam），如实上报。
"""

from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

from . import http, logger
from .client import (
    ALREADY,
    AUTH_FAILED,
    FAILED,
    RISK,
    SUCCESS,
    CheckinResult,
)
from .config import Config

LAUNCH_PATH = "/alice/user/launch"
DETAIL_V3_PATH = "/alice/ug/campaign/v3/detail/"
DETAIL_LIST_PATH = "/alice/ug/campaign/list/"
CLAIM_PATH = "/alice/ug/campaign/landing/checkin"

RISK_SYSTEM_ERROR_CODE = 710010702
# 领取后轮询回查的间隔（秒），最后一次为兜底
CONFIRM_DELAYS = (0, 2, 4)


@dataclass
class DailyTask:
    key: str
    title: str
    group: str
    checked: bool
    points: Any = None
    streak: Any = None


class DoubaoWorkError(Exception):
    def __init__(self, status: str, message: str, http_status: int = 0, snippet: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.http_status = http_status
        self.snippet = snippet


class DoubaoWorkClient:
    def __init__(self, config: Config):
        self.config = config

    # ---------- 基础请求 ----------

    def _query(self) -> list[tuple[str, str]]:
        q: list[tuple[str, str]] = [
            ("aid", "1044603"),
            ("real_aid", "1044603"),
            ("device_platform", "web"),
            ("version_code", "20800"),
            ("samantha_web", "1"),
            ("web_platform", "desktop"),
            ("doubao_device_platform", "desktop"),
            ("client_platform", "pc_client"),
            ("pkg_type", "release_version"),
            ("runtime", "web"),
            ("runtime_version", self.config.runtime_version),
            ("pc_version", self.config.client_version),
            ("doubao_pc_version", self.config.client_version),
            ("use-olympus-account", "1"),
            ("language", "zh"),
            ("region", "CN"),
            ("sys_region", "CN"),
        ]
        if self.config.device_id:
            q.append(("device_id", self.config.device_id))
        if self.config.web_id:
            q.append(("web_id", self.config.web_id))
        if self.config.device_id:
            q.append(("fp", "verify_" + self.config.device_id))
        elif self.config.fingerprint:
            q.append(("fp", self.config.fingerprint))
        return q

    def _headers(self) -> dict[str, str]:
        headers = {
            "Cookie": self.config.cookie,
            "Origin": self.config.base_url,
            "Referer": self.config.base_url + "/chat/",
            "User-Agent": self.config.headers.get("User-Agent", ""),
            "Agw-Js-Conv": "str",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        # 保留配置里显式追加的额外头（如 x-csrf-token）
        for key, value in self.config.headers.items():
            if key not in {"Cookie", "Content-Type", "Accept", "Accept-Language", "User-Agent"}:
                headers[key] = value
        return headers

    def _post(self, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any] | None, str]:
        url = self.config.base_url + path + "?" + urllib.parse.urlencode(self._query())
        payload = json.dumps(body, ensure_ascii=False)
        logger.debug("POST", path=path, body=payload[:200])
        resp = http.request(
            "POST",
            url,
            headers=self._headers(),
            body=payload,
            timeout=self.config.timeout,
        )
        text = resp.text or ""
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            data = None
        return resp.status, data, text

    # ---------- 业务步骤 ----------

    @staticmethod
    def _business_code(payload: dict[str, Any] | None) -> int | None:
        if isinstance(payload, dict):
            code = payload.get("code")
            if isinstance(code, int):
                return code
            try:
                return int(code)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _short_message(payload: dict[str, Any] | None) -> str:
        """只取业务消息字段，避免在整段 JSON / JWT 里做宽泛子串匹配。"""
        if not isinstance(payload, dict):
            return ""
        parts = [payload.get("msg"), payload.get("message"), payload.get("error_detail"), payload.get("error")]
        return " ".join(str(p) for p in parts if p)

    def _classify_http(self, status: int, payload: dict[str, Any] | None, text: str) -> str | None:
        if status in (401, 403):
            return AUTH_FAILED
        short = self._short_message(payload)
        low_short = short.lower()
        for keyword in self.config.auth_keywords:
            if keyword.lower() in low_short:
                return AUTH_FAILED
        for keyword in self.config.risk_keywords:
            if keyword.lower() in low_short:
                return RISK
        return None

    def launch(self) -> str:
        status, payload, text = self._post(LAUNCH_PATH, {})
        code = self._business_code(payload)

        if code == RISK_SYSTEM_ERROR_CODE:
            raise DoubaoWorkError(
                RISK,
                "命中风控码 710010702：活动页 SDK 缺少 biz_params/AgwCommonParam，纯 HTTP 无法完成；请在官方客户端手动点一次签到。",
                status,
                text[:300],
            )
        classified = self._classify_http(status, payload, text)
        if classified == AUTH_FAILED:
            raise DoubaoWorkError(AUTH_FAILED, "Cookie 可能已失效（launch 未登录）", status, text[:300])
        if classified == RISK:
            raise DoubaoWorkError(RISK, "launch 疑似触发风控/人机验证", status, text[:300])
        if not isinstance(payload, dict) or code not in (0, 200, None):
            raise DoubaoWorkError(FAILED, f"launch 返回异常（HTTP {status}，code={code}）", status, text[:300])

        data = payload.get("data") if isinstance(payload, dict) else None
        info = data.get("ug_campaign_info") if isinstance(data, dict) else None
        group = None
        if isinstance(info, dict):
            group = info.get("campaign_group_code") or info.get("campaign_code")
        if not group and isinstance(data, dict):
            group = data.get("campaign_group_code") or data.get("campaign_code")
        if not group:
            diag = ""
            if isinstance(data, dict):
                diag = (
                    f" data_keys={list(data.keys())} "
                    f"ug_campaign_info={json.dumps(info, ensure_ascii=False)[:200]}"
                )
            raise DoubaoWorkError(
                FAILED,
                f"launch 未返回活动组 campaign_group_code{diag}",
                status,
                text[:300],
            )
        logger.info("活动组已识别", group=group)
        return str(group)

    @staticmethod
    def _walk_tasks(value: Any, group: str, out: list[DailyTask], depth: int = 0) -> None:
        if depth > 8 or not isinstance(value, dict):
            return
        for key in ("tasks", "campaigns", "milestones"):
            rows = value.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item = row.get("campaign_code") or row.get("task_code") or row.get("code")
                if not item:
                    continue
                daily_info = row.get("daily_checkin")
                if not (isinstance(daily_info, dict) and "checked_in_today" in daily_info):
                    continue
                reward = daily_info.get("reward")
                points = reward.get("reward_amount") if isinstance(reward, dict) else None
                out.append(
                    DailyTask(
                        key=str(item),
                        title=str(row.get("title") or row.get("name") or item),
                        group=group,
                        checked=daily_info.get("checked_in_today") is True,
                        points=points,
                        streak=daily_info.get("continuous_days"),
                    )
                )
        child = value.get("campaign_group")
        if isinstance(child, dict):
            DoubaoWorkClient._walk_tasks(child, group, out, depth + 1)
        children = value.get("campaign_groups")
        if isinstance(children, list):
            for child in children:
                DoubaoWorkClient._walk_tasks(child, group, out, depth + 1)

    def detail(self, group: str) -> list[DailyTask]:
        last_text = ""
        for path in (DETAIL_V3_PATH, DETAIL_LIST_PATH):
            status, payload, text = self._post(path, {"campaign_group_code": group})
            last_text = text
            code = self._business_code(payload)
            if status == 200 and isinstance(payload, dict) and code in (0, 200, None):
                root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                tasks: list[DailyTask] = []
                self._walk_tasks(root, group, tasks)
                return tasks
            logger.debug("详情接口未命中", path=path, http=status, code=code)
        raise DoubaoWorkError(FAILED, "详情接口未返回有效活动任务", 0, last_text[:300])

    # ---------- 主流程 ----------

    def _claim(self, group: str) -> None:
        status, payload, text = self._post(CLAIM_PATH, {"scene": group})
        code = self._business_code(payload)
        if code == RISK_SYSTEM_ERROR_CODE:
            raise DoubaoWorkError(
                RISK,
                "命中风控码 710010702：领取需要活动页 SDK 生成的风控字段；请在官方客户端手动点一次签到。",
                status,
                text[:300],
            )
        classified = self._classify_http(status, payload, text)
        if classified == AUTH_FAILED:
            raise DoubaoWorkError(AUTH_FAILED, "Cookie 可能已失效（领取时未登录）", status, text[:300])
        if classified == RISK:
            raise DoubaoWorkError(RISK, "领取疑似触发风控/人机验证", status, text[:300])
        if code not in (0, 200, None) and not (status and 200 <= status < 300):
            raise DoubaoWorkError(FAILED, f"领取返回异常（HTTP {status}，code={code}）", status, text[:300])

    def _fail(self, exc: Exception, started: float, attempts: int = 1) -> CheckinResult:
        if isinstance(exc, DoubaoWorkError):
            return CheckinResult(
                status=exc.status,
                message=exc.message,
                http_status=exc.http_status,
                body_snippet=exc.snippet,
                elapsed=time.monotonic() - started,
                attempts=attempts,
            )
        return CheckinResult(
            status=FAILED,
            message=f"网络请求异常：{exc}",
            elapsed=time.monotonic() - started,
            attempts=attempts,
        )

    def probe(self) -> CheckinResult:
        """只读：launch + detail，不触发领取。用于 dry-run / 自检。"""
        started = time.monotonic()
        try:
            group = self.launch()
            tasks = self.detail(group)
        except (DoubaoWorkError, ConnectionError) as exc:
            return self._fail(exc, started)
        if not tasks:
            return CheckinResult(
                status=FAILED,
                message="当前活动未提供每日签到任务",
                body_snippet="",
                elapsed=time.monotonic() - started,
            )
        task = tasks[0]
        amount = str(task.points) if task.points is not None else ""
        if task.checked:
            return CheckinResult(
                status=ALREADY,
                message=f"今日已签到（连续 {task.streak} 天），只读演练未重复领取",
                amount=amount,
                streak=task.streak,
                elapsed=time.monotonic() - started,
            )
        return CheckinResult(
            status=SUCCESS,
            message=f"检测到可领取的每日签到任务「{task.title}」（只读演练，未领取）",
            amount=amount,
            streak=task.streak,
            elapsed=time.monotonic() - started,
        )

    def run(self) -> CheckinResult:
        started = time.monotonic()
        attempts = 1
        try:
            group = self.launch()
            tasks = self.detail(group)
            if not tasks:
                return CheckinResult(
                    status=FAILED,
                    message="当前活动未提供每日签到任务",
                    elapsed=time.monotonic() - started,
                )
            if len(tasks) > 1:
                return CheckinResult(
                    status=FAILED,
                    message="发现多个每日签到任务，无法确定领取对象，未提交领取",
                    elapsed=time.monotonic() - started,
                )

            task = tasks[0]
            amount = str(task.points) if task.points is not None else ""
            if task.checked:
                return CheckinResult(
                    status=ALREADY,
                    message=f"今日已签到（连续 {task.streak} 天）",
                    amount=amount,
                    streak=task.streak,
                    elapsed=time.monotonic() - started,
                )

            logger.info("提交领取", task=task.key, group=group)
            self._claim(group)
            attempts = 2

            # 回查确认：以详情 checked_in_today 为准
            for delay in CONFIRM_DELAYS:
                if delay:
                    time.sleep(delay)
                refreshed = self.detail(group)
                if refreshed and refreshed[0].checked:
                    pts = refreshed[0].points
                    return CheckinResult(
                        status=SUCCESS,
                        message=f"签到成功，+{pts if pts is not None else amount} 活动额度",
                        amount=str(pts) if pts is not None else amount,
                        streak=refreshed[0].streak,
                        elapsed=time.monotonic() - started,
                        attempts=attempts,
                    )
            return CheckinResult(
                status=FAILED,
                message="领取已提交，但回查详情尚未确认今日已签到，可能异步到账",
                amount=amount,
                elapsed=time.monotonic() - started,
                attempts=attempts,
            )
        except (DoubaoWorkError, ConnectionError) as exc:
            return self._fail(exc, started, attempts)
