# Mac 完整使用教程

[返回首页](../README.md) · [先部署 CF](DEPLOY.md) · [TG 操作](TELEGRAM.md) · [问题排查](TESTING.md)

本页适用于 Mac Apple Silicon / Intel、当前 v0.1.1。所有 bash 命令块都在 macOS 的“终端”中执行。

## 1. 开始前确认两件事

1. 已完成 [CF 部署](DEPLOY.md)，向自己的 Bot 发送 /start 能看到“添加机器”。
2. 这台 Mac 已安装并登录 Codex CLI。

客户端安装包包含 Python 运行环境。只作为受控电脑时，不需要为本程序另装 Python、Git 或 Node.js；用 npm 安装 Codex 本身时才需要 Node.js。

打开“终端”，检查：

~~~bash
codex --version
codex login status
~~~

未登录时：

~~~bash
codex login
~~~

若找不到命令，先安装 Codex CLI。选择 npm 方式时，安装 Node.js 后重新打开终端，再运行：

~~~bash
npm install -g @openai/codex
codex login
~~~

已有可用 CLI 不必重装。桌面端登录与 CLI 登录不一定相同，以检查结果为准。[Codex CLI 官方说明](https://developers.openai.com/codex/cli/)

## 2. 从同一个 Bot 获取 Mac 命令

1. 向自己的 Bot 发送 /start。
2. 点击“添加机器”。
3. 复制机器人给出的 **Mac 命令**。

配对码十分钟有效，只能使用一次。给另一台电脑接入时重新生成，不能把同一个码用于多台电脑。

**不用在 Mac 上再次注册 CF、部署服务或输入 Bot Token。** 当前 CF 版本已经在首次部署时配置了 Bot Token 和你的用户 ID。

## 3. 运行命令，后台上线

在终端进入希望作为默认工作目录的位置，例如：

~~~bash
cd "$HOME/Documents"
~~~

也可以替换为实际项目目录。然后粘贴 TG 生成的完整 Mac 命令并运行。

安装器会识别 Apple Silicon / Intel，下载对应的固定版本归档、验证 SHA-256、安装客户端、检查 Codex、完成配对并创建登录启动项。

正常完成时会显示类似：

~~~text
Bound successfully / 绑定成功，客户端将上线待命。
Installed. The client starts in the background when you sign in.
~~~

**确认没有报错且显示安装成功后，再关闭终端。** 回到 TG 点击“刷新”，应能看到 Mac 上线；可以在“机器设置 → 重命名”中改成易辨认的名称。

若系统阻止运行或安装输出报错，先检查错误信息与发布来源，不要把下载完成当成安装成功。

## 4. 后台运行的含义

- 关闭终端不影响后台客户端。
- 登录启动项标签是 **com.codex-any-bot.agent**，使用当前用户身份运行。
- 登录后自动上线；不会替你登录 macOS，也不会阻止系统休眠。
- 关机、休眠、退出登录或网络不可用时，不保证能接收即时控制。
- 首次安装、重新登录、重启或更新客户端后均先待命，不自动开始挤。

在 TG 选择这台 Mac，选已有会话或新建会话，设置保持时长、发送间隔后再开始。[查看 TG 操作教程](TELEGRAM.md)

## 5. 打印日志位置、查看日志和状态

安装后在终端执行：

~~~bash
printf '日志位置：%s\n' "$HOME/Library/Application Support/codex-any-bot/agent.log"
open "$HOME/Library/Application Support/codex-any-bot"
~~~

查看最近 50 行并持续跟踪：

~~~bash
tail -n 50 -f "$HOME/Library/Application Support/codex-any-bot/agent.log"
~~~

按 Control+C 只退出日志查看，不会停止后台客户端。

| 文件/目录 | 内容 |
| --- | --- |
| agent.log、agent.log.1 等 | 客户端轮换日志。 |
| launch-error.log / launch-output.log | 登录启动进程的错误与输出。 |
| update-error.log | 部分更新回退过程的输出，未发生时可能不存在。 |
| config.json | 设备凭据和服务地址，不要公开分享。 |
| state.sqlite 及其附属文件 | 参数、任务状态、命令去重。 |
| current.json / previous.json | 当前和上一版本路径。 |
| versions | 安装过的客户端版本。 |

使用已安装客户端查询状态，不需要额外安装 Python：

~~~bash
client_bin=$(/usr/bin/plutil -extract executable raw -o - "$HOME/Library/Application Support/codex-any-bot/current.json")
"$client_bin" status
~~~

在同一终端执行下面命令，可检查 Codex 登录及客户端版本：

~~~bash
"$client_bin" diagnose
"$client_bin" --version
~~~

也可以直接使用 TG 的“诊断”按钮。

## 6. TG 一键更新，Mac 不用重新输入命令

新的正式安装包发布后：

1. 确认 Mac 在 TG 中在线。
2. 点击“机器设置 → 更新客户端”。
3. 等待下载、校验与安装，期间可能短暂离线。
4. 重新上线后先待命，需要继续时再点“开始”。

更新会停止当前执行。旧版本与 previous.json 保留用于回退；更新失败时查看 agent.log、update-error.log，最终以机器是否重新上线为准。

**该按钮更新 Mac 客户端，不更新 CF 服务。** 云端升级按 [CF 更新说明](DEPLOY.md#9-更新电脑端与云端分别处理)执行。

## 卸载与清理

本节只处理本项目，不删除原本的 Codex 会话、登录资料或其他软件。

### 1. 先停止任务，等待更新结束

在 TG 点“立即停止”。如果正在更新客户端，等更新结束后再卸载，避免更新安装器重新启动程序。

### 2. 删除程序、配置、日志和登录启动项

在终端运行：

~~~bash
bash "$HOME/Library/Application Support/codex-any-bot/uninstall.sh" --purge
~~~

--purge 会删除本项目的安装目录及保留版本。想暂时停止并保留配置时，去掉 --purge；保留模式还会留下本地停止标记，需要重新安装/更新启动流程才能恢复运行。

卸载报错时先处理错误，不能把已运行命令当作完成。

### 3. 检查卸载结果

~~~bash
test ! -d "$HOME/Library/Application Support/codex-any-bot" && echo "安装目录已删除"
test ! -f "$HOME/Library/LaunchAgents/com.codex-any-bot.agent.plist" && echo "登录启动文件已删除"
launchctl print "gui/$(id -u)/com.codex-any-bot.agent"
~~~

第三条在卸载成功后应提示找不到该服务。若目录、文件或服务仍在，检查卸载输出。

### 4. 检查临时文件

正常安装会自动清理下载暂存目录。**v0.1.1 的 --purge 不会统一扫描所有系统临时位置**；远程更新可能留下 anybot-update- 开头的文件夹，异常中断也可能留下暂存文件。

在终端打开当前用户临时目录：

~~~bash
open "$TMPDIR"
~~~

按更新/安装时间与文件内容确认哪些属于本项目，再删除对应项目。不要删除整个临时目录，也不要盲删无法确认用途的随机目录。

### 5. 移除 TG 绑定与不再需要的副本

在 TG 点击“机器设置 → 移除绑定 → 确认移除”，使本机设备凭据失效。其他机器不受影响。

手动下载的安装包、源码 ZIP 或 Git 副本不在客户端安装目录里，不再需要时另行清理。整个 CF 服务也不再使用时，按 [CF 停用说明](DEPLOY.md#10-停用与数据清理)检查云端资源。

**当前没有一条命令自动清理本机、临时目录和云端全部记录的功能；完整清理需要上述逐项检查。**

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 找不到 Codex | 检查 PATH、CLI 安装位置，或在 TG 诊断中查看检测结果。 |
| 已安装桌面端但配对提示未登录 | 在同一 macOS 用户下完成 Codex CLI 登录。 |
| 配对失败 | 检查码是否过期、是否已使用、CF 地址是否可达。 |
| 后台上线失败 | 查看 agent.log 和 launch-error.log，确认当前用户已登录桌面。 |
| 自定义 Codex 路径 | 给 LaunchAgent 配置 ANYBOT_CODEX 环境变量指向实际可执行文件，再重新加载启动项。 |
| 会话被占用 | 在桌面端释放对应会话，再让客户端重试，不删除写锁。 |

更多见 [问题排查](TESTING.md)。
