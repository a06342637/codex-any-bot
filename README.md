# codex-any-bot

**一个 Telegram Bot 控制多台 Windows / Mac。电脑运行安装命令，输入 Bot Token 和你的数字 ID，即可后台上线；以后在 TG 改名、选会话、设置保持时间、一键停止或更新。**

当前客户端版本 **v0.2.8**，使用 Cloudflare（CF）分发服务，支持 Windows x64 / ARM64、Mac Intel / Apple Silicon。

## 第一次使用

CF 服务只部署一次。Bot Token 和用户 ID 先配置到自己的 CF 服务；电脑安装时输入相同信息进行绑定校验。**Token 不保存在电脑上，客户端保存的是独立设备凭据。**

~~~text
你的 Telegram Bot ↔ 你的 CF 服务 ↔ Windows 电脑 A / Mac 电脑 B
~~~

| 步骤 | 教程 |
| --- | --- |
| 1. 注册 CF、配置 Bot，部署服务一次 | [CF 完整部署教程](docs/DEPLOY.md) |
| 2. Windows 运行命令，输入信息并后台上线 | [Windows 完整教程](docs/WINDOWS.md) |
| 2. Mac 运行命令，输入信息并后台上线 | [Mac 完整教程](docs/MACOS.md) |
| 3. 在同一个 Bot 管理所有机器 | [TG 操作教程](docs/TELEGRAM.md) |
| 遇到错误、无法上线或升级问题 | [问题排查](docs/TESTING.md) |

部署完成后，部署电脑可以关闭。CF 不运行 Codex 任务，任务仍在各台电脑本地执行。每台电脑需要可用的 Codex CLI（已登录 OpenAI，或已配置自定义模型服务）；本程序安装包包含自身运行依赖。

## 电脑一键安装

### Windows：在 CMD 运行

~~~bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Join-Path $env:TEMP ('anybot-'+[guid]::NewGuid()+'.ps1'); try { Invoke-WebRequest 'https://github.com/a06342637/codex-any-bot/releases/download/v0.2.8/install.ps1' -OutFile $p; & $p } finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }"
~~~

### Mac：在终端运行

~~~bash
(p=$(mktemp -t anybot-bootstrap); trap 'rm -f "$p"' EXIT; curl -fLsS 'https://github.com/a06342637/codex-any-bot/releases/download/v0.2.8/install.sh' -o "$p" && bash "$p")
~~~

运行后依次填写：

1. **自己的 CF HTTPS 地址**，例如自己部署的 workers.dev 根地址。
2. **Bot Token**，隐藏输入，只用于本次绑定。
3. **你的 Telegram 数字用户 ID**，与云端允许的用户 ID 一致。

也可以在 Bot 中点“添加机器”取得已预填 CF 地址的命令，这样电脑端只询问 Token 和 ID。命令可用于多台电脑，每次都会分配独立设备身份。不要把安装脚本通过管道直接交给 bash，否则交互输入可能不可用。

## 安装后会看到什么

安装器打印：

~~~text
Online in Telegram. Waiting for your commands.
Install directory: 本机安装目录
Log: 本机日志文件
Config (private): 本机设备配置
Status: 本机状态查看命令
Uninstall: 本机完整卸载命令
~~~

如果网络暂时不可用，会明确显示“已安装，尚未确认上线”，不会把安装成功误报为已上线。查看打印出的日志位置，再在 TG 刷新设备列表。

确认上线后即可关闭 CMD / 终端。客户端后台运行，当前用户以后登录系统时自动启动；关机、休眠或退出登录期间不保证运行。首次安装、重启或更新后先待命，不自动开始挤。

## TG 能控制什么

- “机器管理”中切换电脑；选中一台后独立控制，直接重命名或更新程序。
- 显示当前及实际发送会话的名称、ID；选择已有会话、新建会话，或确认后删除会话。
- 工作目录直接列出本机文件夹供选择，支持上级目录、分页、盘符及手动输入；新建会话也能选目录。
- 每台独立设置保持时长、发送间隔和发送内容，时间按钮即时显示已保存的分钟数。
- 对当前机器手动开始、立即停止或设置定时开始停止。
- 每次尝试显示运行卡，实时查看重试、成功与等待时间，卡片下可停止、继续或返回控制页。
- 一键诊断、重启客户端、更新客户端，电脑不用重新输入命令。

保持时长从首次明确成功开始计算，单位为分钟；到期结束当前执行和后续轮次。执行失败结束后立即重试同一会话；发送间隔只在成功后等待，始终不重叠执行。后续成功、失败和重连不会续期。

## 在 Codex 查看机器人会话

新版新建会话显示为 **AnyBot · 目录名**。打开对应电脑的 Codex，在最近会话中查看；暂停脚本或关闭客户端后，历史仍然保存。若该目录未加入 Codex 项目，可先在最近会话中查找，再加入对应项目。

旧版会话是 `exec` 来源，Codex 默认列表会过滤它。新版继续该会话时会保留旧历史，生成可见副本并显示新的实际会话 ID；原会话不删除。TG 的会话列表仍能选到旧记录。电脑断线、重连或重启待命不再反复发提醒，其他 TG 消息默认静默。

**v0.2.8：暂停、停止和待命期间不再自动发送 TG 消息，也不再后台更新状态卡。** 状态仍保存，点击“刷新状态”或“运行状态”可以查看。此修复必须[部署新版 CF 云端](docs/DEPLOY.md#9-更新电脑端与云端分别处理)，仅更新电脑客户端不会生效；已有 v0.2.7 客户端可以继续使用。

## 日志、卸载和更新

| 系统 | 日志位置 | 完整卸载 |
| --- | --- | --- |
| Windows | %LOCALAPPDATA%\codex-any-bot\agent.log | 安装器打印的 uninstall.ps1 -Purge 命令 |
| Mac | ~/Library/Application Support/codex-any-bot/agent.log | 安装器打印的 uninstall.sh --purge 命令 |

新版把安装和更新缓存放在程序目录中，结束时清理。完整卸载删除本机程序、旧版本、配置、日志、缓存和登录启动项，并清理能确认归属的旧版临时文件；联网时自动移除该设备的云端绑定和相关状态。网络不可用或文件被占用时会报告未完成的部分。

手动下载的源码/安装包、TG 聊天历史属于用户资料，不自动删除；已有 Codex、Python、Node.js 和原项目文件也不属于本客户端的卸载范围。具体检查方法见各系统教程。

**TG 的更新按钮更新电脑客户端，不更新 CF 云端代码。** 从 v0.1.x 升级时，先更新 CF 服务，再在 TG 更新客户端。以后常规客户端更新不再询问 Token 或 ID。

- [版本与升级说明](CHANGELOG.md)
- [正式安装包](https://github.com/a06342637/codex-any-bot/releases/latest)
- [协议说明](docs/ARCHITECTURE.md)
- [开发者检查](docs/TESTING.md#开发者检查)

持续发送可能消耗 Codex 用量，不保证抢到或预留服务容量。CF 可使用免费方案起步，仍受平台额度限制。本项目独立于原 codex-anycodex-any，不修改原项目目录。
