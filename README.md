# 豆包「天天领额度」每日自动签到

> 每天早上自动帮你领掉豆包电脑端「天天领额度」的 200 活动额度，连续签到不断签。
> 跑在 GitHub Actions 上，零服务器、零依赖、零成本。

![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/platform-GitHub%20Actions-black)

---

## 这是什么

豆包电脑端（PC 版）有个「天天领额度」活动：每天签到一次送 **200 活动额度**，实时到账，连续签到还有累计奖励。额度能用在图片生成、AI PPT、深度研究这些高消耗功能上。

问题是——**得每天记着点那一一下**。断一天，连续天数从头算。

这个项目把「点那一下」交给 GitHub Actions：每天北京时间 08:20 自动请求签到接口，成功与否通过 Server 酱 / 企业微信 / Telegram / Bark 推给你，签到结果同时写进 Actions 任务页的摘要里。

**它不是外挂，也不模拟客户端**，只是替你发出那一次 HTTP 请求。所以：

- 不需要开着电脑，不需要装豆包客户端
- 不需要任何第三方库（纯 Python 标准库）
- 不需要服务器和域名

---

## 特性

| 能力 | 说明 |
| --- | --- |
| ⏰ 定时自动执行 | 北京时间 08:20 主跑 + 08:50 兜底重跑，防止 GitHub 定时任务丢跑 |
| 🔁 幂等 | 「今日已签到」被识别为成功，跑两次也不会报错、不会重复领 |
| 🔗 三步链路 | `launch` 发现活动组 → `detail` 读取签到状态 → `landing/checkin` 领取并回查 `checked_in_today` 确认 |
| 🧠 状态判定 | 以详情回查的今日签到状态为准，不把单个 `code=0` 当作成功 |
| 🛡️ 凭据安全 | Cookie 只存 GitHub Secrets，日志全程脱敏，仓库里不存在任何明文 |
| 📮 多渠道通知 | Server 酱 / 企业微信机器人 / Telegram / Bark / 自定义 Webhook |
| 🧪 可测试 | 32 项单元 + 端到端测试，本地起假接口就能验证整条链路 |
| 🩺 保活机制 | 每月自动心跳提交，避免公开仓库 60 天无活动导致定时任务被暂停 |

---

## 五分钟部署

### 第 1 步：Fork 这个仓库

点右上角 **Fork**，复制到你自己的账号下。

> 为什么要 Fork 而不是直接用？因为 Secrets 只能配在自己的仓库里。

### 第 2 步：抓 Cookie

三步链路会自动发现活动组和领取路径，**只需要 Cookie**，不用手动找签到接口。

1. 电脑浏览器打开 <https://www.doubao.com> 并登录
2. `F12` → **Network** 面板 → 任选一条请求 → **Request Headers** → 复制完整 `Cookie`（需含 `sessionid` 或 `sessionid_ss`）
3. 也可以用 [tools/capture-snippet.js](tools/capture-snippet.js) 在 Console 里辅助观察请求

### 第 3 步：配置 Secrets

进入你 Fork 后的仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，添加：

| Name | 必填 | Value |
| --- | --- | --- |
| `DOUBAO_COOKIE` | ✅ | 浏览器里豆包的完整 Cookie 字符串 |

其余客户端环境参数（版本号、设备 ID 等）都有默认值，一般无需配置；通知渠道按需再填。

### 第 4 步：手动跑一次验证

**Actions** 标签页 → 左侧「每日自动签到」→ 右侧 **Run workflow**。

先勾上 `dry_run` —— 它只走 `launch` + `detail` 只读探测，不会提交领取：

```
[INFO ] 活动组已识别  group=pc_incentive_task_mvp_v3
[OK   ] dry-run 结束，未提交领取请求
[OK   ] 今日已签到（连续 1 天），只读演练未重复领取
```

确认状态正常，再取消 `dry_run` 跑一次真实的；今天已签时会识别为 `ALREADY`，不会重复领。

### 第 5 步：等它自己跑

什么都不用做了，每天 08:20 自动执行。任务失败 GitHub 会发邮件提醒你。

---

## 配置项

所有配置都走环境变量。本地开发时复制 `.env.example` 为 `.env` 填写即可（`.env` 已被 `.gitignore` 排除）。

### 必填

| 变量 | 说明 |
| --- | --- |
| `DOUBAO_COOKIE` | 豆包登录后的完整 Cookie，**最关键的凭据**，需含 `sessionid` 或 `sessionid_ss` |

### 客户端环境（可选，一般用默认值）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOUBAO_BASE_URL` | `https://www.doubao.com` | 站点地址 |
| `DOUBAO_CLIENT_VERSION` | `2.33.5` | 桌面客户端版本号，随请求带上 |
| `DOUBAO_RUNTIME_VERSION` | `3.42.2` | 运行时版本号 |
| `DOUBAO_DEVICE_ID` / `DOUBAO_WEB_ID` / `DOUBAO_FINGERPRINT` | 空 | 设备标识，风控要求时再补 |
| `DOUBAO_TIMEOUT` | `20` | 单次请求超时（秒） |
| `DOUBAO_RETRY` | `3` | 失败重试次数 |
| `DOUBAO_RETRY_BACKOFF` | `3` | 重试退避基数（秒），实际间隔会加随机抖动 |

### 结果判定

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DOUBAO_SUCCESS_KEYWORDS` | `签到成功,领取成功,签到完成,success` | 命中任意一个即判成功（兜底） |
| `DOUBAO_ALREADY_KEYWORDS` | `已签到,已经签到,今日已领,重复签到,already` | 命中即判「今天签过了」，按成功处理 |
| `DOUBAO_AUTH_KEYWORDS` | `未登录,登录已过期,not login,unauthorized,登录失效` | 业务消息命中即提示 Cookie 失效 |
| `DOUBAO_RISK_KEYWORDS` | `风控,验证,captcha,risk,verify,频繁` | 业务消息命中即提示疑似触发风控 |

主判定以详情回查的 `daily_checkin.checked_in_today` 为准；关键词只作为兜底。鉴权/风控只在业务消息字段上匹配，避免在整段 JSON、JWT 里误命中数字子串。

### 通知

| 变量 | 说明 |
| --- | --- |
| `DOUBAO_NOTIFY` | 通道列表，逗号分隔：`serverchan,wecom,telegram,bark,webhook` |
| `DOUBAO_NOTIFY_ON_ALREADY` | 设为 `1` 时，即使今天已签到也发通知（默认不发，避免噪音） |
| `SERVERCHAN_KEY` | Server 酱 SendKey |
| `WECOM_WEBHOOK` | 企业微信群机器人 Webhook 完整地址 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram 机器人 |
| `BARK_URL` | Bark 推送地址，形如 `https://api.day.app/你的key` |
| `CUSTOM_WEBHOOK` | 自定义接收端，会 POST `{"title": ..., "content": ...}` |

不配 `DOUBAO_NOTIFY` 就完全不发通知，静默运行。

---

## 本地运行

```bash
git clone https://github.com/<your-name>/doubao-daily-checkin.git
cd doubao-daily-checkin

cp .env.example .env
# 编辑 .env，填入 DOUBAO_COOKIE

python main.py --check     # 只检查配置是否完整
python main.py --dry-run   # 只读探测活动与签到状态，不提交领取
python main.py             # 真的签到
```

不需要 `pip install` 任何东西，Python 3.9+ 直接跑。

其他用法：

```bash
python main.py --json       # 输出 JSON，方便被别的程序调用
python main.py --no-notify  # 这次不发通知
python main.py --version
```

退出码：`0` 成功或今日已签到 / `1` 签到失败 / `2` 配置错误。可以直接接 `cron` 或 Windows 任务计划，见 [docs/部署方式.md](docs/部署方式.md)。

跑测试：

```bash
python -m unittest discover -s tests -v
```

其中的端到端测试会在本地起一个假接口，完整验证「配置 → 请求 → 判定 → 退出码」链路，不需要真实账号。

---

## 工作原理

```
GitHub Actions (UTC 00:20)
        │
        ▼
   读取 Secrets（Cookie）
        │
        ├─ POST /alice/user/launch                  发现活动组 campaign_group_code
        ├─ POST /alice/ug/campaign/v3/detail/        读取任务与 checked_in_today 状态
        │       ├─ 今日已签 ──► ALREADY，静默结束
        │       └─ 未领取
        ├─ POST /alice/ug/campaign/landing/checkin  {"scene": 活动组} 提交领取
        └─ 回查 detail 确认 checked_in_today=true ──► SUCCESS / 未确认则告警
        ▼
   通知 + 写入任务摘要，退出码回传 Actions
```

北京时间 08:20 对应 UTC 的 00:20（同一天），所以 `cron: "20 0 * * *"`；兜底 08:50 对应 `cron: "50 0 * * *"`。

---

## 项目结构

```
doubao-daily-checkin/
├── main.py                      # 命令行入口
├── src/
│   ├── config.py                # 环境变量 → 配置对象，含校验
│   ├── doubao_work.py           # 三步链路：launch → detail → checkin + 回查
│   ├── client.py                 # 结果对象、判定与重试工具（兼容旧单接口）
│   ├── http.py                   # 极简 HTTP 客户端（标准库）
│   ├── notifier.py              # 五种通知通道
│   └── logger.py                 # 日志 + 脱敏 + Actions 分组
├── tools/
│   └── capture-snippet.js        # 浏览器控制台抓包脚本
├── tests/
│   ├── test_core.py              # 判定逻辑单元测试
│   ├── test_integration.py       # 假接口端到端测试
│   └── test_doubao_work.py       # 三步链路假接口测试
├── docs/
│   ├── 抓包指南.md
│   └── 部署方式.md
└── .github/workflows/
    ├── checkin.yml              # 每日定时签到
    ├── ci.yml                   # 推送时跑测试
    └── keepalive.yml            # 防止定时任务被暂停
```

---

## 常见问题

**Q：Cookie 多久失效？**
不固定，通常几周到几个月。失效后日志会出现 `AUTH_FAILED` 并推送告警，重新抓一次 Cookie 更新 Secret 即可。别把 Cookie 贴到任何公开地方——它等同于你的登录状态。

**Q：为什么不用自己填签到接口地址？**
活动组和领取路径由脚本在 `launch` / `detail` 响应里自动发现，只需提供 Cookie；活动页改版导致路径失效时，再按 `src/doubao_work.py` 顶部的常量调整即可。

**Q：返回风控码 710010702 怎么办？**
该码表示领取接口需要活动页 SDK 生成的 `biz_params` / `AgwCommonParam` 风控字段，纯 HTTP 无法可靠伪造。脚本不会伪造这些字段，遇到时请在官方客户端手动点一次「立即签到」，之后脚本回读状态即可。

**Q：会不会被封号？**
风险自担。每天一次低频请求，行为上跟手动签到没有本质区别，但自动化行为本身可能不符合服务条款。**建议只给自己用、只跑一个账号、不要改成高频轮询。** 如果你介意，就别用。

**Q：Actions 的定时任务准吗？**
不准。GitHub 的高峰期延迟几分钟到几十分钟都很常见，所以项目配了 08:20 和 08:50 两次。因为脚本是幂等的，多跑一次没任何副作用。

**Q：为什么同时有两个 cron，不会领两次吗？**
不会。第二次请求通常返回「今日已签到」，脚本判定为 `ALREADY`，按成功处理并退出 0。

**Q：公开仓库的定时任务会不会自己停？**
会。GitHub 对 60 天没有任何提交的公开仓库会暂停其中的 scheduled workflow。项目里的 `keepalive.yml` 每月提交一次心跳文件来规避这个问题。不想要就删掉那个文件，代价是每两个月手动点一次 Actions。

**Q：能跑多个账号吗？**
当前版本一个部署一个账号。多账号最简单的做法是 Fork 多份。如果需要，把 Cookie 改成用 `;` 分隔的数组循环请求也是一行改动的事。

**Q：签到成功但额度没到账？**
日志里的 `amount` 只是从响应文本里正则提取的，仅供参照。真实余额去豆包客户端「设置 → 订阅豆包专业版 → 订阅与额度管理」看。注意活动额度有有效期，过期清零。

---

## 免责声明

- 本项目仅供**个人学习与自动化技术研究**，不得用于商业用途。
- 使用本项目产生的任何后果（包括但不限于账号异常、额度未到账、违反服务条款）由使用者自行承担。
- 请遵守豆包及字节跳动的用户协议。若官方明确禁止此类自动化，请立即停止使用。
- 项目与豆包、字节跳动无任何关联。
- 活动规则、额度数值、有效期均以官方页面实时显示为准，本项目不保证任何特定收益。

---

## License

[MIT](LICENSE)
