# Cloudflare 完整部署教程

[返回首页](../README.md) · [Windows 接入](WINDOWS.md) · [Mac 接入](MACOS.md) · [TG 操作](TELEGRAM.md)

适用于当前 **v0.2.4 的 CF 部署方式**。先完成本页，再在各台电脑安装客户端。首次部署选一台 Windows 或 Mac 操作即可，不必每台都部署。

## 1. CF 负责什么

CF 保存机器名称、运行参数和定时任务，接收 Telegram 指令，再通过加密连接发送给对应电脑。Codex 在电脑上运行，不在 CF 上运行。

~~~text
Bot A ↔ CF 上的 codex-any-bot 服务 ↔ 电脑 A、电脑 B
~~~

Bot Token、用户 ID 先在**部署向导**中配置到自己的 CF 服务。每台电脑首次安装时输入相同 Token 和 ID 做绑定校验，客户端不保存 Bot Token。TG“添加机器”提供已预填 CF 地址的命令；通用安装命令则会先询问自己的 CF 地址。电脑不需要登录 CF。

## 2. 准备账号与软件

| 项目 | 需要准备什么 |
| --- | --- |
| Cloudflare | [注册或登录](https://dash.cloudflare.com/)，完成邮箱验证，启用 Workers。 |
| Telegram Bot | 已有机器人的 Token，或通过官方 [BotFather](https://t.me/BotFather)创建机器人。 |
| Telegram 用户 ID | 允许控制设备的人的数字 ID，不是 @用户名，也不是机器人的 ID。 |
| 部署电脑 | Windows 或 Mac，Python 3.11+、Node.js 22+；用 Git 下载项目时还需 Git。 |

软件下载：[Python](https://www.python.org/downloads/) · [Node.js](https://nodejs.org/en/download) · [Git](https://git-scm.com/downloads)

选择对应系统的安装包；安装后重新打开命令窗口，让 PATH 生效。Windows 安装 Python 时启用加入 PATH 的选项。

CF 可以先用 Workers 免费方案，不必购买域名或服务器。本项目使用的 SQLite Durable Object 支持免费方案；额度用尽时请求可能失败，本项目不会自动升级付费。[官方额度说明](https://developers.cloudflare.com/durable-objects/platform/pricing/)

## 3. 准备 Bot Token 和用户 ID

### 已有机器人

在 Telegram 打开官方 **@BotFather**，发送 /mybots，选择你的机器人，进入 API Token 页面取得 Token。继续使用已有 Bot 即可。

### 还没有机器人

向 @BotFather 发送 /newbot，按提示设置显示名称和机器人用户名，保存返回的 Token。用户名格式按 BotFather 的提示填写。

### 查询自己的数字 ID

如果还不知道，可以使用查询 ID 的工具，例如第三方 [@userinfobot](https://t.me/userinfobot)，发送 /start 查看自己的数字 ID。它只用于查 ID，**不要把 Bot Token 发给它或发到公开聊天里**。

第一次建议使用你与 Bot 的**私聊**：用户 ID 填自己的数字 ID，聊天 ID 直接回车，默认使用相同 ID。群聊 ID 不等于个人 ID，本教程先按私聊完成接入。

最后打开你自己的 Bot，发送一次 /start。此时尚未部署程序，不回复是正常的。

## 4. 确定 Cloudflare 服务地址

1. 登录 [Cloudflare 控制台](https://dash.cloudflare.com/)。
2. 进入 **Workers & Pages**，完成首次启用提示。无需添加自己购买的网站域名。
3. 找到 **Your subdomain / 你的子域名**，设置或记下账号的 workers.dev 子域名。

假设账号子域名是 mydevices123.workers.dev，本项目的 Worker 名称为 codex-any-bot，完整地址就是：

~~~text
https://codex-any-bot.mydevices123.workers.dev
~~~

mydevices123 是示例，必须替换成你自己的子域名。地址格式是：

~~~text
https://codex-any-bot.你的子域名.workers.dev
~~~

后面输入的是 **HTTPS 根地址**，不要添加 /telegram/webhook、/v1/connect 或其他路径。

向导会创建 Worker 和关联存储，不需要在网页里手写代码或手动建数据库。如果账号已有同名 Worker，先确认它就是本项目，避免覆盖其他服务。UI 名称随控制台版本可能变化，以 [workers.dev 官方说明](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)为准。

保持这个地址能被 Telegram 和电脑直接访问。不要额外启用需要浏览器登录的访问拦截，否则 Webhook 和后台客户端无法按当前方式接入；程序本身会验证 Webhook 密钥、用户 ID 和设备凭据。

## 5. 下载项目并运行部署向导

Windows 和 Mac **任选一种**。这里的仓库只需下载到部署电脑；客户端安装命令由部署后的 Bot 生成。

### Windows：使用 CMD

开始菜单搜索 **CMD / 命令提示符**，打开后检查依赖：

~~~bat
python --version
node --version
git --version
~~~

首次下载，逐行运行：

~~~bat
cd /d "%USERPROFILE%\Downloads"
git clone https://github.com/a06342637/codex-any-bot.git
cd codex-any-bot
python scripts\deploy.py
~~~

如果已有本项目目录，不要重复克隆。例如当前项目位于 C:\Users\adminuser\Downloads\codex-any-bot，可直接运行：

~~~bat
cd /d "C:\Users\adminuser\Downloads\codex-any-bot"
python scripts\deploy.py
~~~

python 找不到但已安装 Python 启动器时，可改用 py -3，并确认版本至少为 3.11。

### Mac：使用终端

打开“终端”，检查依赖：

~~~bash
python3 --version
node --version
git --version
~~~

首次下载，逐行运行：

~~~bash
cd "$HOME/Downloads"
git clone https://github.com/a06342637/codex-any-bot.git
cd codex-any-bot
python3 scripts/deploy.py
~~~

已有项目时进入实际目录，直接运行最后一条命令，不必重复克隆。

## 6. 按向导填写四项信息

| 提示 | 应填写什么 |
| --- | --- |
| Worker HTTPS 地址 | 第 4 步确定的真实根地址。 |
| Bot Token | BotFather 提供的 Token；输入时不显示字符是正常的。 |
| 允许操作的 Telegram 用户 ID | 你的数字用户 ID。 |
| 聊天 ID | 私聊时直接回车，默认与上面的用户 ID 一致。 |

接下来程序会：

1. 安装项目所需的部署工具。
2. 打开浏览器，通过 Cloudflare 官方页面登录并授权 Wrangler。
3. 创建/更新 Worker 和 SQLite Durable Object 存储。
4. 将 Bot Token、用户 ID、聊天 ID 和随机 Webhook 密钥上传为 CF Secrets。
5. 注册 Telegram Webhook，连接 Bot 与这个 Worker。

**不需要另外手动生成 Cloudflare API Token。** 浏览器里确认的是 Cloudflare 登录授权；不要将 Bot Token 填进账号密码框。

Token 不写进仓库文件。成功后只在本机项目的 .local/deployment.json 保存非秘密的服务地址，便于以后查看。

如同一个 Bot 仍有旧程序轮询接收指令，部署前先停止它们。向导会切换消息接收方式，并丢弃切换前未处理的 Telegram 更新，避免执行旧指令；不需要删除或修改原项目目录。

## 7. 检查部署结果

终端应显示：

~~~text
部署成功。向 Bot 发送 /start，然后点击 添加机器。
~~~

在浏览器访问你的服务地址加 /healthz：

~~~text
https://codex-any-bot.你的子域名.workers.dev/healthz
~~~

正常返回：

~~~json
{"ok":true,"protocol":1}
~~~

这只证明 Worker 可访问。**还要回到自己的 Bot 发送 /start，确认出现“我的机器”和“添加机器”等按钮**，才说明机器人配置接通了。

如果健康检查正常而 Bot 不回复，检查：

- Token 是否对应你正在聊天的 Bot。
- 用户 ID 是否是自己的数字 ID，聊天 ID 是否正确。
- 向导是否完成 Webhook 注册，而不只是上传了 Worker。
- 地址有没有浏览器登录拦截或不正确的域名。

配置有误可修正后重新运行向导。普通代码更新不需要设备重新配对，但不要随意改成另一个 Bot 或删除云端存储。

## 8. 添加 Windows 和 Mac

接下来按系统继续：

- [Windows 完整教程：在 CMD 执行接入命令](WINDOWS.md)
- [Mac 完整教程：在终端执行接入命令](MACOS.md)

在同一个 Bot 点“添加机器”，获取已预填 CF 地址的 Windows / Mac 命令；同一命令可在多台电脑使用。运行后输入本 Bot Token 和自己的数字 ID，绑定成功即启动后台客户端并打印日志、目录和卸载命令。电脑上线先待命，部署电脑完成后可以关闭。

## 9. 更新：电脑端与云端分别处理

### 电脑端：TG 一键更新

发布新的正式 Release 后，在 TG 打开机器卡片，点 **机器管理 → 选择机器 → 更新程序**。电脑需要在线；客户端会校验并下载新版、停止旧任务，更新后上线待命。

不需要到电脑重新输入命令，也不要求受控电脑为本程序安装 Git、Python 或 Node.js。

### 云端：在部署电脑执行一次

TG 的更新按钮不会更新 CF。从 v0.1.x 升级到 v0.2.0 时，必须先更新云端，以启用 Token + ID 绑定和自动移除设备接口，再在 TG 更新客户端。已有设备凭据继续有效，客户端更新不重新询问信息。

将下面的 YOUR-SUBDOMAIN 换成真实子域名；自定义域名则填写实际根地址。项目有未提交修改时先处理，不要强制覆盖。

Windows CMD：

~~~bat
cd /d "%USERPROFILE%\Downloads\codex-any-bot"
git pull --ff-only
cd cloud
npm.cmd ci
npx.cmd wrangler deploy --var "PUBLIC_BASE_URL:https://codex-any-bot.YOUR-SUBDOMAIN.workers.dev"
~~~

Mac 终端：

~~~bash
cd "$HOME/Downloads/codex-any-bot"
git pull --ff-only
cd cloud
npm ci
npx wrangler deploy --var "PUBLIC_BASE_URL:https://codex-any-bot.YOUR-SUBDOMAIN.workers.dev"
~~~

CF 登录过期时，在同一目录先执行 npx.cmd wrangler login（Windows）或 npx wrangler login（Mac），再部署。

**每次都要传入真实 PUBLIC_BASE_URL。** 仓库配置使用占位地址，不带参数可能把云端地址改回占位值。正常代码部署保留 Secrets，无需重输 Bot Token。新设备安装命令使用 RELEASE_TAG 指定的已发布版本，当前为 v0.2.4。

云端部署可能让客户端短暂重连，客户端会核对最新状态。维护前建议先在 TG 停止需要维护的任务。

## 10. 停用与数据清理

只卸载某台电脑：按 [Windows](WINDOWS.md#卸载与清理) / [Mac](MACOS.md#卸载与清理)教程运行完整卸载。新版自动清理本机程序、日志、缓存和启动项，并尝试移除本设备的云端绑定与关联状态；网络不可用时会报告云端待清理，之后再从 TG 移除。其他电脑不受影响。

整个系统不再使用：先停止并卸载所有客户端，再到 CF 控制台删除本项目的 Worker，并核对关联 Durable Object 命名空间/存储是否也已删除。**删除客户端或删除 Worker 代码，不等于自动清空所有云端数据。** 按控制台的资源关联和删除提示操作，不要删除其他项目的资源。

不再使用的 Bot Token 可在 BotFather 撤销。不再需要的部署源码副本、下载文件另行清理；它们与客户端安装目录是不同位置。

## 11. 官方资料

- [Telegram Bot API 消息接收](https://core.telegram.org/bots/api#getting-updates)
- [Cloudflare workers.dev 地址](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)
- [Cloudflare Secrets](https://developers.cloudflare.com/workers/configuration/secrets/)
- [Cloudflare 额度与计费](https://developers.cloudflare.com/durable-objects/platform/pricing/)
- [本项目常见问题](TESTING.md)
