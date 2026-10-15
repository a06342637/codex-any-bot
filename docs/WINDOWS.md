# Windows 完整使用教程

[返回首页](../README.md) · [先部署 CF](DEPLOY.md) · [TG 操作](TELEGRAM.md) · [问题排查](TESTING.md)

适用于 v0.2.3、Windows x64 / ARM64。下面命令均在 **CMD（命令提示符）** 执行。

请从 Windows 开始菜单打开独立的 CMD 再安装。部分 MSIX 桌面应用的集成终端会把 AppData 写入应用隔离目录，导致安装时能上线，但系统登录启动任务找不到客户端。

## 1. 准备好 CF 与 Codex

先完成 [CF 部署](DEPLOY.md)。需要知道自己的 CF 根地址、Bot Token 和允许操作的数字用户 ID。不要填写别人的 CF 地址。

这台电脑还需安装可用的 Codex CLI：

~~~bat
codex --version
codex login status
~~~

使用 OpenAI 账号且未登录时：

~~~bat
codex login
~~~

若找不到命令，可按 [Codex CLI 官方说明](https://developers.openai.com/codex/cli/)安装。选择 npm 方式时，需要先装 Node.js，再在新 CMD 中运行：

~~~bat
npm.cmd install -g @openai/codex
codex login
~~~

已有可用 CLI 不必重装。本客户端安装包包含自身 Python 运行环境，不需要为客户端另外安装 Python 或 Git。桌面端登录与 CLI 登录不一定相同，以实际检查结果为准。

自定义模型服务：如果已在 Codex 的 config.toml 中配置自己的服务，且该服务不要求 OpenAI 登录，客户端会使用已有配置；即使 codex login status 显示未登录也能绑定，不必改动现有配置。诊断会显示认证方式；它不会发送模型请求来验证服务余额或连通性。服务使用 env_key 时，对应环境变量需对后台客户端可见。

## 2. 运行安装命令

在 CMD 进入默认工作目录，例如：

~~~bat
cd /d "%USERPROFILE%\Documents"
~~~

运行下面完整一行：

~~~bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Join-Path $env:TEMP ('anybot-'+[guid]::NewGuid()+'.ps1'); try { Invoke-WebRequest 'https://github.com/a06342637/codex-any-bot/releases/download/v0.2.3/install.ps1' -OutFile $p; & $p } finally { Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue }"
~~~

另一种方式：在自己的 Bot 点“添加机器”，复制它给出的 Windows 命令。该命令已包含你的 CF 地址，后面不用再填地址。

**请在 CMD 执行。** 如果当前打开的是 PowerShell，先输入 cmd 进入 CMD，再粘贴整行；直接在 PowerShell 粘贴可能提前展开命令中的变量。

## 3. 按提示输入信息

| 提示 | 填什么 |
| --- | --- |
| CF HTTPS 地址 | 自己部署的根地址，不带 /telegram/webhook；命令已预填时不再询问。 |
| Bot Token | 从 BotFather 取得的 Token，输入时不显示字符。 |
| 你的 Telegram 数字用户 ID | 与 CF 中配置的允许用户 ID 一致，不是 @用户名。 |

输入的 Bot Token 仅通过 HTTPS 交给自己的 CF 服务核对，**不会写进电脑配置或日志**。绑定成功后，本机使用独立设备凭据。

Windows 包含两个入口：命令行入口负责初次输入、状态查看和维护；后台入口负责无窗口运行。不要绕过安装器去双击后台程序输入信息。

命令可以在多台电脑使用，每台各输入一次信息，获得不同设备 ID。旧版一次性配对码接口仍兼容，但不是 v0.2.0 的主要接入方式。

## 4. 查看结果，关闭窗口

安装器会校验下载文件、安装客户端、配置当前用户登录启动项，并启动后台程序。

如果已连接控制服务，会显示：

~~~text
Online in Telegram. Waiting for your commands.
~~~

随后会打印本机的：

~~~text
Install directory: 安装目录
Log: agent.log 的完整路径
Config (private): 配置文件完整路径
Status: 查看状态的命令
Uninstall: 完整卸载命令
~~~

若只安装成功但未确认连接，会给出警告。此时先检查日志和网络，不要把“下载完成”当成上线。

回到 TG，发送 /start 或点“刷新”，确认设备在线。初始名称来自电脑主机名，可在“机器设置 → 重命名”中修改。然后关闭 CMD 即可。

客户端在当前用户登录后自动启动，任务计划程序中的任务名为 codex-any-bot。关机、休眠、退出登录或断网时不保证即时控制；安装、重启、更新后均先待命，不自动开始挤。

## 5. 打印日志路径、查看日志和状态

安装器已经打印日志位置，需要再次查看时在 CMD 执行：

~~~bat
echo 日志位置：%LOCALAPPDATA%\codex-any-bot\agent.log
explorer "%LOCALAPPDATA%\codex-any-bot"
notepad "%LOCALAPPDATA%\codex-any-bot\agent.log"
~~~

| 文件/目录 | 用途 |
| --- | --- |
| agent.log 及轮换副本 | 客户端日志。 |
| config.json | 独立设备凭据、CF 地址，不包含输入的 Bot Token；勿公开分享。 |
| state.sqlite 及附属文件 | 参数、任务状态、命令去重。 |
| current.json / previous.json | 当前及上一版本路径。 |
| versions | 当前和旧版程序，用于回退。 |
| cache | 安装、更新暂存位置；完成后清理。 |
| ownership.json | 标识本项目安装目录，卸载时校验。 |
| uninstall.ps1 | 完整卸载脚本。 |

查看本地状态，下面整行仍在 CMD 执行：

~~~bat
powershell -NoProfile -Command "& ((Get-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'codex-any-bot\current.json') -Raw | ConvertFrom-Json).console_executable) status"
~~~

将 status 换成 diagnose 可检查 Codex 路径和登录，换成 --version 可查看客户端版本。TG 设备卡片也显示客户端版本。

## 6. TG 一键更新，电脑不用操作

新的正式 Release 发布后：

1. 确认电脑在 TG 中在线。
2. 点击“机器设置 → 更新客户端”。
3. 等待下载、校验和安装；期间可能短暂离线。
4. 重新上线后查看客户端版本，需要继续任务时再点“开始”。

不需要重新运行安装命令，也不重新询问 Token 和 ID。更新会停止当前任务并保留旧版本用于回退，安装成功后继续后台待命。

**云端代码有变化时需要单独更新 CF。** 从 v0.1.x 升级到本版，先按 [CF 更新说明](DEPLOY.md#9-更新电脑端与云端分别处理)部署云端，再在 TG 更新客户端。

## 卸载与清理

### 1. 先停止任务，等待更新结束

在 TG 点“立即停止”。如果正在更新，等更新结束后再卸载，避免安装器与卸载同时运行。

### 2. 执行完整卸载

在 CMD 执行安装器打印的命令，默认路径如下：

~~~bat
powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\codex-any-bot\uninstall.ps1" -Purge
~~~

程序会：

1. 停止本客户端及其执行任务。
2. 移除本用户的 codex-any-bot 登录启动任务。
3. 尝试清理本设备的 CF 绑定、参数、定时任务及选择缓存。
4. 清理能够确认归属的旧版临时下载文件。
5. 删除本机安装目录，包括当前/旧版本、配置、数据库、日志及缓存。

不需要保留数据时使用 -Purge。明确需要保留配置时可使用 -KeepData；它不属于完整卸载。

### 3. 确认结果

正常完成会显示本机数据和启动项已移除。检查：

~~~bat
if exist "%LOCALAPPDATA%\codex-any-bot" (echo 安装目录仍存在，请检查错误) else (echo 安装目录已删除)
schtasks /Query /TN "codex-any-bot"
~~~

第二条应提示找不到任务。若卸载报错或目录仍在，不要认为已完整清理。

云端不可达时，会明确提示“Cloud binding could not be removed”。本机仍会清理，但之后要在 TG 点“移除绑定”，或恢复云端连接后处理。旧版临时文件被占用时也会打印未完成路径。

### 4. 清理边界

- 新版自动创建的安装、缓存、配置、日志和启动项都由卸载器处理。
- 老版本临时文件只删除能确认属于本项目的内容；有其他用户文件或无法确认的目录不会误删。
- 手动下载的源码 ZIP、Git 仓库、另存的安装包和 TG 聊天历史属于用户资料，不自动删除；不再需要时自行删除。
- 不删除你原本的 Codex 会话、登录资料、Python、Node.js、Git或原项目目录。
- 所有电脑都不再使用时，再按 [CF 停用说明](DEPLOY.md#10-停用与数据清理)清理整个云端服务。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 只想输入 Token 和 ID | 使用 Bot“添加机器”生成的命令，CF 地址已预填。 |
| 提示必须使用交互终端 | 在 CMD 运行完整安装命令，不要向程序传入管道输入，也不要调用后台入口做 setup。 |
| 绑定失败 | 检查自己的 CF 地址、Token、数字 ID，并确认云端已更新到 v0.2.0。 |
| Codex 未登录 | 在同一 Windows 用户下完成 CLI 登录。 |
| 安装后能上线，但登录启动报 0x80070002（找不到文件） | 确认是从独立 CMD 安装，而非 MSIX 应用的集成终端；后者可能把文件写入隔离目录。先核对真实安装位置并保留设备配置，不要删除不确定归属的目录。 |
| Already installed | 更新在 TG 操作；重新绑定先完整卸载。 |
| 未确认上线 | 查看安装器打印的日志，检查 CF HTTPS/WSS 与网络。 |
| 找不到卸载脚本 | 确认安装目录和版本；不要从源码目录直接运行卸载脚本。 |
| 目录归属无法验证 | 未知非空目录或残缺旧版配置不会被自动接管；先备份确认，再处理原目录。完整旧版可用更新方式升级。 |
| 卸载拒绝路径 | 配置、版本目录或文件存在链接，或 ownership.json 被移动/修改；先确认路径，不要扩大删除范围。 |

更多见 [问题排查](TESTING.md)。
