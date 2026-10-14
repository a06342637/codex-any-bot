# codex-any-bot

**一个 Telegram Bot 管理多台 Windows / Mac：选会话、定时挤、独立设置保持分钟数和发送“在”的间隔。**

每台电脑运行一次配对命令，后台上线待命；之后在 TG 命名、选择已有会话或新建、开始、停止和调整参数。Cloudflare 托管分发消息，不需要额外常开主控电脑，也不需要给电脑开放端口。

```text
我的机器 · 3 台在线
🟢 家里 Windows   保持 30 分钟 · 间隔 1 分钟
🟢 办公室 Mac     保持 120 分钟 · 间隔 5 分钟
🟢 工作电脑       待命

[添加机器] [刷新] [批量操作] [全部停止]
```

## 快速开始

1. 准备 Cloudflare 账号、Telegram Bot 和自己的 Telegram 用户 ID。
2. 克隆本仓库，在项目目录运行 `python scripts/deploy.py`，按向导部署。详见 [部署说明](docs/DEPLOY.md)。
3. 向 Bot 发送 `/start`，点击“添加机器”。
4. 在对应电脑运行 TG 生成的 Windows 或 Mac 一次性命令。安装包包含运行依赖，本机仍需安装并登录 Codex CLI。
5. 在 TG 选择机器、会话、保持时长和发送间隔，然后点“开始”。安装或重新登录不会自动挤。

安装命令来自已发布的固定 [GitHub Release](https://github.com/a06342637/codex-any-bot/releases)，归档通过 SHA-256 校验。初次配对码十分钟有效且只能使用一次；Bot Token 不下发到电脑。

## 两个独立的分钟设置

| 设置 | 规则 |
| --- | --- |
| 保持时长 | 从首次明确成功开始计时；到期中断当前执行并停止后续轮次。支持指定整数分钟或不限时。 |
| 发送间隔 | 每轮结束后等待指定整数分钟再发送，不同时运行重叠轮次。默认 1 分钟。 |
| 运行中修改 | 立即应用并保存为本机默认值；缩短时长仍以最初成功时间计算，已超时立即停止。 |
| 断线与重试 | 不重置保持计时；截止时间由本地客户端检查。 |

时长快捷按钮：10 / 30 / 60 / 120 分钟。间隔快捷按钮：1 / 2 / 5 / 10 分钟。两项均支持自定义。

## TG 操作

- 机器列表、重命名、状态卡片、移除绑定。
- 已有会话分页选择，查看目录和更新时间；新建会话并开始，保存常用目录。
- 一键开始、立即停止、按机设置发送内容。
- 指定时间或每天启动，指定时间停止，统一使用北京时间；错过的启动不补执行。
- 多机选择与批量开始、停止、设置时长或间隔。
- 诊断、重启客户端、更新客户端；首次成功、到期或异常时通知，常规轮次更新原卡片。

客户端登录系统后后台启动，关闭命令窗口不影响它；关机、休眠或退出登录时不保证继续运行。每台机器同时挤一个会话，多台可以并行。持续发送可能消耗 Codex 用量，不代表保证抢到或预留服务容量。

## 文档

- [Cloudflare 与 Telegram 部署](docs/DEPLOY.md)
- [Windows 安装、更新、卸载](docs/WINDOWS.md)
- [macOS 安装、更新、卸载](docs/MACOS.md)
- [协议、任务规则和状态恢复](docs/ARCHITECTURE.md)
- [排查问题与测试](docs/TESTING.md)

## 开发

```sh
python -m pip install -e '.[test]'
python -m pytest -q
cd cloud
npm ci
npm run check
npm test
npx wrangler deploy --dry-run
```

源码中的 Agent 使用 Python，托管端使用 TypeScript。CI 在 Windows、Apple Silicon Mac 和 Intel Mac 检查客户端，在 Linux 检查真实 Workers 测试环境。发布标签触发平台安装包构建与校验清单生成。

这是独立新项目；只参考原 `codex-anycodex-any` 的 Codex 定位和会话控制思路，不修改或依赖原项目目录。
