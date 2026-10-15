# Windows 完整使用教程

[返回首页](../README.md) · [先部署 CF](DEPLOY.md) · [TG 操作](TELEGRAM.md) · [问题排查](TESTING.md)

本页适用于 Windows x64 / ARM64、当前 v0.1.1。接入时使用 **CMD（命令提示符）**；本页所有 bat 命令块都在 CMD 执行。

## 1. 开始前确认两件事

1. 已按 [CF 教程](DEPLOY.md)部署服务，向自己的 Bot 发送 /start 能看到“添加机器”。
2. 这台电脑已安装并登录 Codex CLI。

本程序安装包包含 Python 运行环境。只作为受控电脑时，不需要为本程序安装 Python、Git 或 Node.js；如果还要用 npm 安装 Codex，则需要 Node.js。

在开始菜单搜索 CMD，打开后检查：

~~~bat
codex --version
codex login status
~~~

未登录时运行：

~~~bat
codex login
~~~

按 Codex 的提示完成本机登录。如果命令找不到，先安装 Codex CLI。选择 npm 安装方式时，安装 Node.js 后重新打开 CMD，再执行：

~~~bat
npm.cmd install -g @openai/codex
codex login
~~~

已有可用 CLI 不必重装。桌面端能打开不一定代表 CLI 已登录，以登录检查结果为准。[Codex CLI 官方说明](https://developers.openai.com/codex/cli/)

## 2. 为这台电脑生成配对命令

在同一个 TG Bot 中：

1. 发送 /start。
2. 点击“添加机器”。
3. 找到机器人回复中的 **Windows 命令**，复制完整一行。

配对码十分钟有效，只能绑定一台电脑。过期或已使用时重新生成。电脑 A、电脑 B 要分别点“添加机器”，不能复制同一条命令给多台电脑。

**这里不再输入 Bot Token、用户 ID 或 CF 账号。** 这些已在部署 CF 时配置，配对命令负责把本机绑定到该服务。

## 3. 在 CMD 执行，等待后台上线

在要接入的电脑打开 CMD。先进入希望作为默认工作目录的位置，例如：

~~~bat
cd /d "%USERPROFILE%\Documents"
~~~

也可以改为自己实际存在的项目目录。然后在同一窗口粘贴 TG 生成的 Windows 命令，按回车。

程序会下载固定版本、校验归档、安装客户端、检查 Codex、完成配对、注册登录启动任务，并在后台启动。成功时会显示类似：

~~~text
Bound successfully / 绑定成功，客户端将上线待命。
Installed. The client runs in the background and starts when you sign in.
~~~

它还会显示本机的状态查询和卸载命令。**没有报错且显示安装成功后，才关闭窗口。**

回到 TG 点击“刷新”，应能看到这台电脑上线。初始名称通常是系统电脑名，可以在“机器设置 → 重命名”中修改。

### 如果当前打开的是 PowerShell

当前 Bot 生成的 Windows 接入命令采用 CMD 的引号方式，内含 PowerShell 变量。直接粘贴进 PowerShell 可能提前展开变量，导致无法执行。

先在 PowerShell 输入：

~~~bat
cmd
~~~

进入 CMD 后，再粘贴机器人给出的命令。不要把命令截断，也不要把示例配对码当成实际配对码。

## 4. 关闭窗口后的运行方式

- 客户端后台运行，不需要保留 CMD 窗口。
- Windows 任务计划程序中的任务名是 **codex-any-bot**，在当前用户登录后启动。
- 使用当前用户的身份和 Codex 配置，不会让 Windows 自动登录。
- 电脑关机、休眠、退出登录或断网时不保证能接受即时控制。
- 首次安装、重新登录、重启客户端或更新后，均先上线待命，不会自动开始挤。

在 TG 选择这台电脑，再选择已有会话或新建会话，设置保持时长、发送间隔后点“开始”。详见 [TG 操作教程](TELEGRAM.md)。

## 5. 打印日志路径、查看日志和状态

安装器当前不一定专门打印日志路径。安装完成后在 CMD 执行下面命令，可以把准确位置打印出来并打开目录：

~~~bat
echo 日志位置：%LOCALAPPDATA%\codex-any-bot\agent.log
explorer "%LOCALAPPDATA%\codex-any-bot"
~~~

用记事本打开日志：

~~~bat
notepad "%LOCALAPPDATA%\codex-any-bot\agent.log"
~~~

| 文件/目录 | 内容 |
| --- | --- |
| agent.log、agent.log.1 等 | 客户端轮换日志。 |
| config.json | 本机设备 ID、服务地址及设备凭据，不要公开分享。 |
| state.sqlite 及其附属文件 | 参数、任务状态、命令去重记录。 |
| current.json / previous.json | 当前和上一版本程序路径。 |
| versions | 安装过的客户端版本。 |
| uninstall.ps1 | 本机卸载脚本。 |

直接使用已安装客户端查看状态，不需要另外安装 Python。下面整行仍在 **CMD** 执行：

~~~bat
powershell -NoProfile -Command "& ((Get-Content -LiteralPath (Join-Path $env:LOCALAPPDATA 'codex-any-bot\current.json') -Raw | ConvertFrom-Json).executable) status"
~~~

将末尾的 status 换成 diagnose 可检查 Codex 版本和 CLI 登录状态，换成 --version 可查看客户端版本。正常情况下也可以直接使用 TG 的“诊断”按钮。

中文输出乱码时，可以在当前 CMD 运行 chcp 65001 后再查看；这只调整当前终端的代码页。

## 6. 在 TG 一键更新，电脑不用重新输入命令

当项目发布新的正式安装包后：

1. 确认这台电脑在 TG 中在线。
2. 打开机器卡片，点击“机器设置 → 更新客户端”。
3. 等待下载、校验和安装。期间可能短暂离线。
4. 客户端重新上线后先待命，需要继续时再点“开始”。

更新会停止当前执行，旧版本目录会保留用于回退。下载或安装失败时检查 agent.log；旧版恢复措施不等于所有故障都能自动恢复，最终以设备是否重新上线为准。

**TG 按钮更新电脑客户端，不更新 CF 控制服务。** 云端升级按 [CF 更新说明](DEPLOY.md#9-更新电脑端与云端分别处理)执行一次。

## 卸载与清理

本节针对本项目。不会删除你的 Codex 会话、Codex 登录资料、原项目代码，也不会卸载你原本安装的 Python、Node.js 或 Git。

### 1. 先结束任务和更新

先在 TG 点“立即停止”，确认任务结束。如果正在更新客户端，等更新结束后再卸载，避免安装器重新启动客户端。

### 2. 删除客户端、配置、日志和自启动项

在 CMD 执行：

~~~bat
powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\codex-any-bot\uninstall.ps1" -Purge
~~~

-Purge 会删除本机安装目录，包括配置、日志、数据库和保留的旧版本。需要保留这些数据时，去掉 -Purge，只移除运行程序和登录启动项。

卸载脚本报错时先处理错误，不能把命令已运行当成卸载成功。如果提示找不到脚本，先确认是否安装过、是否已卸载，不要直接删除整个 AppData 目录。

### 3. 检查本机清理结果

~~~bat
if exist "%LOCALAPPDATA%\codex-any-bot" (echo 安装目录仍存在，请检查卸载错误) else (echo 安装目录已删除)
schtasks /Query /TN "codex-any-bot"
~~~

第二条在卸载成功后应提示找不到该任务。如果任务仍在，先检查卸载输出。

### 4. 清理临时下载文件

**v0.1.1 的 -Purge 不会统一清理系统临时目录。** 在 CMD 打开：

~~~bat
explorer "%TEMP%"
~~~

根据安装/更新时间和文件内容，检查本项目留下的：

- codex-any-bot- 后接随机标识的下载暂存文件夹，里面通常是本项目安装包。
- anybot-update- 开头、包含本项目更新安装脚本的文件夹。
- anybot- 开头的首次接入 .ps1 临时脚本。

确认属于本项目且没有安装/更新正在运行后再删除。不要删除整个 TEMP，也不要只凭模糊名称批量删除其他程序的文件。

### 5. 移除 TG 绑定和其他副本

在 TG 进入“机器设置 → 移除绑定 → 确认移除”，使该设备凭据失效。其他电脑的绑定不受影响。

如果这台电脑还下载过源码 ZIP、Git 仓库或手动下载的安装包，它们不在客户端安装目录中；不再需要时另行删除自己的这些副本。整个 CF 服务也不再使用时，按 [CF 停用说明](DEPLOY.md#10-停用与数据清理)处理云端资源。

**完整清理需要以上各项检查。当前版本没有“一条命令自动清理本机、临时目录和云端全部记录”的功能。**

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 粘贴命令出现变量、赋值或路径错误 | 确认是在 CMD 中执行完整 Windows 命令，未直接粘贴到 PowerShell。 |
| 找不到 Codex 或未登录 | 先在同一 Windows 用户下完成 CLI 安装和登录。 |
| 配对码失效 | 在 TG 重新点“添加机器”，不要复用已用过的命令。 |
| Already installed | 本机已有配置；更新用 TG 按钮，重新绑定先按教程卸载清理。 |
| 设备一直离线 | 检查安装输出、agent.log、网络和 CF 服务地址。 |
| 会话被占用 | 在 Codex 桌面端释放对应会话后重试，不删除写锁。 |
| 自定义 Codex 路径 | 可配置用户环境变量 ANYBOT_CODEX 为原生 codex.exe 的绝对路径，然后重启客户端。 |

更多见 [问题排查](TESTING.md)。
