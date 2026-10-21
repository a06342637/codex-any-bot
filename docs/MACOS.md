# Mac 完整使用教程

[返回首页](../README.md) · [先部署 CF](DEPLOY.md) · [TG 操作](TELEGRAM.md) · [问题排查](TESTING.md)

适用于 v0.2.7、Mac Apple Silicon / Intel。以下命令在 macOS 的“终端”执行。

## 1. 准备 CF 和 Codex

先完成 [CF 部署](DEPLOY.md)，准备自己的 CF 根地址、Bot Token 和允许操作的数字用户 ID。

这台 Mac 需要可用的 Codex CLI：

~~~bash
codex --version
codex login status
~~~

使用 OpenAI 账号且未登录时：

~~~bash
codex login
~~~

若找不到命令，可按 [Codex CLI 官方说明](https://developers.openai.com/codex/cli/)安装。选择 npm 方式时先装 Node.js，再运行：

~~~bash
npm install -g @openai/codex
codex login
~~~

已有可用 CLI 不必重装。安装包包含本客户端运行依赖，不需要为本程序另装 Python 或 Git。

自定义模型服务：如果已在 Codex 的 config.toml 中配置自己的服务，且该服务不要求 OpenAI 登录，客户端会使用已有配置；即使 codex login status 显示未登录也能绑定，不必改动现有配置。诊断会显示认证方式；它不会发送模型请求来验证服务余额或连通性。服务使用 env_key 时，对应环境变量需对后台客户端可见。

## 2. 运行一键安装命令

先进入希望作为默认工作目录的位置：

~~~bash
cd "$HOME/Documents"
~~~

运行下面完整一行：

~~~bash
(p=$(mktemp -t anybot-bootstrap); trap 'rm -f "$p"' EXIT; curl -fLsS 'https://github.com/a06342637/codex-any-bot/releases/download/v0.2.7/install.sh' -o "$p" && bash "$p")
~~~

也可以去 Bot 点击“添加机器”，使用它给出的 Mac 命令；该命令已预填自己的 CF 地址。

**不要改成 curl | bash。** 安装需要从终端读取信息，脚本应先下载到文件再执行，命令结束会清理启动脚本。

## 3. 输入信息

依次填写：

| 提示 | 内容 |
| --- | --- |
| CF HTTPS 地址 | 自己部署的根地址；使用 Bot 生成的命令时不再询问。 |
| Bot Token | BotFather 提供的 Token，输入时不显示字符。 |
| Telegram 数字用户 ID | 与 CF 中允许控制设备的用户 ID 一致。 |

Token 只通过 HTTPS 用于本次绑定，**不写进本机配置或日志**。之后使用独立设备凭据连接。

同一命令可用于不同电脑，每台输入一次信息、创建独立设备身份。无需每台注册 CF，也无需重复部署云端。

## 4. 确认后台上线

安装器会自动识别 Apple Silicon / Intel，下载并校验归档，安装客户端并创建当前用户的登录启动项。

绑定后会检查连接状态，成功时显示“Online / 已连接 TG 控制服务”。随后打印：

~~~text
Install directory: 本机安装目录
Log: 日志完整路径
Config (private): 配置文件路径
Status: 查看状态的命令
Uninstall: 完整卸载命令
~~~

如果显示“已安装，尚未确认上线”，先查看日志与网络，再去 TG 刷新。不要把下载完成当成上线成功。

确认后关闭终端即可。登录启动项标签为 com.codex-any-bot.agent；当前用户登录后后台启动，初次安装、重启或更新后先待命。关机、休眠、退出登录或断网时不保证即时控制。

## 5. 打印日志位置、查看日志和状态

安装器会直接打印日志路径。以后需要再次查看时：

~~~bash
printf '日志位置：%s\n' "$HOME/Library/Application Support/codex-any-bot/agent.log"
open "$HOME/Library/Application Support/codex-any-bot"
~~~

查看最近 50 行并跟踪：

~~~bash
tail -n 50 -f "$HOME/Library/Application Support/codex-any-bot/agent.log"
~~~

按 Control+C 只退出日志查看，不停止后台客户端。

| 文件/目录 | 用途 |
| --- | --- |
| agent.log 及轮换副本 | 客户端日志。 |
| launch-error.log / launch-output.log | 登录启动错误与输出。 |
| update-error.log | 部分更新回退输出，未发生时可能不存在。 |
| config.json | 独立设备凭据和 CF 地址，不含输入的 Bot Token；勿公开分享。 |
| state.sqlite 及附属文件 | 参数、状态、命令去重。 |
| current.json / previous.json | 当前和上一版本路径。 |
| versions | 当前/旧版程序。 |
| cache | 安装更新暂存，完成后清理。 |
| ownership.json | 本项目目录标识。 |

直接使用已安装的客户端查询，不需要另装 Python：

~~~bash
client_bin=$(/usr/bin/plutil -extract executable raw -o - "$HOME/Library/Application Support/codex-any-bot/current.json")
"$client_bin" status
"$client_bin" diagnose
"$client_bin" --version
~~~

TG 设备卡片也显示客户端版本。

## 6. 在 TG 一键更新，Mac 不用操作

新正式版发布后：

1. 确认设备在线。
2. 点击“机器管理 → 选择机器 → 更新程序”。
3. 等待下载、校验和安装；期间可能短暂离线。
4. 重新上线后查看版本，需要继续任务时再点“开始”。

不需要重新输入 Token、ID 或安装命令。更新会停止当前任务，保留旧版以便回退，成功后后台待命。

该按钮只更新电脑客户端。云端有变化时按 [CF 更新说明](DEPLOY.md#9-更新电脑端与云端分别处理)操作；从 v0.1.x 升级时先更新 CF，再在 TG 更新客户端。

## 卸载与清理

### 1. 停止任务，等待更新结束

先在 TG 点“立即停止”。如果正在更新，等结束后再卸载，避免安装器与卸载同时运行。

### 2. 运行完整卸载

执行安装器打印的命令，默认是：

~~~bash
bash "$HOME/Library/Application Support/codex-any-bot/uninstall.sh" --purge
~~~

卸载器会停止客户端，移除登录启动项，尝试删除本设备的云端绑定与关联状态，清理可识别的旧版临时文件，再删除程序、旧版本、配置、日志、数据库和缓存。

明确需要保留数据时可使用 --keep-data，它不属于完整卸载。

### 3. 检查结果

~~~bash
test ! -d "$HOME/Library/Application Support/codex-any-bot" && echo "安装目录已删除"
test ! -f "$HOME/Library/LaunchAgents/com.codex-any-bot.agent.plist" && echo "登录启动文件已删除"
launchctl print "gui/$(id -u)/com.codex-any-bot.agent"
~~~

第三条应提示找不到服务。若目录或启动项仍在，检查卸载错误。

网络不可用时会报告“Cloud binding could not be removed”，不会误报云端已清理；之后可从 TG 移除绑定。清理旧版文件失败也会报告未完成路径。

### 4. 哪些由卸载器清理

- 新版创建的安装文件、旧版本、配置、日志、缓存和登录启动项均会删除。
- 能确认归属的旧版临时下载文件会清理；有其他用户文件或无法确认用途的目录不会误删。
- 手动下载的源码/安装包、TG 聊天历史属于用户资料，不自动删除；不需要时自行清理。
- 你已有的 Codex 会话、账号资料、Python、Node.js、Git和原项目不属于本程序残留，不会被删除。
- 所有电脑都停用后，按 [CF 停用说明](DEPLOY.md#10-停用与数据清理)删除整个云端服务及相关存储。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 想只输入 Token 和 ID | 使用 Bot“添加机器”提供的命令，CF 地址已预填。 |
| 提示交互终端不可用 | 不使用 curl 管道执行脚本，按教程完整命令运行。 |
| 绑定失败 | 核对自己的 CF 地址、Token、数字 ID，并先升级云端到 v0.2.0。 |
| 已开桌面端但提示未登录 | 在同一 macOS 用户下完成 CLI 登录检查。 |
| 找不到 Codex | 检查 CLI 安装路径；自定义路径可给登录启动项配置 ANYBOT_CODEX。 |
| 后台未确认上线 | 查看打印出的日志及 launch-error.log，检查网络和登录状态。 |
| 目录归属无法验证 | 未知非空目录或残缺旧版配置会保留；先备份确认后处理，完整旧版可通过更新验证。 |
| 卸载拒绝目录 | 确认从安装目录运行，标记、配置和程序路径没有被移动或替换成链接，不扩大删除范围。 |

更多见 [问题排查](TESTING.md)。
