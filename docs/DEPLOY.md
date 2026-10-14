# 部署自己的 TG 控制中心

需要：一个 Cloudflare 账号（Workers 免费方案即可起步）、一个通过 BotFather 创建的 Telegram Bot、你的 Telegram 用户 ID。运行部署脚本的电脑需有 Node.js 22+、Python 3.11+。部署完成后，这台电脑无需保持在线。

## 一键部署向导

在项目目录运行：

```powershell
python scripts/deploy.py
```

按提示输入 Worker 公网地址、Bot Token、用户 ID 和聊天 ID；私聊时聊天 ID 通常等于用户 ID。Bot Token 使用隐藏输入，脚本不会写入项目文件。向导安装依赖、打开 Cloudflare 登录、部署 Worker 和 SQLite Durable Object、上传 Secrets，最后注册 Telegram Webhook。

Worker 地址在 Cloudflare 控制台 **Workers & Pages** 中查看。首次先启用自己的 `workers.dev` 子域名；默认 Worker 名为 `codex-any-bot`，地址形如 `https://codex-any-bot.你的子域.workers.dev`。也可使用已配置的自定义域名。

部署前先在 TG 私聊 Bot 发送 `/start`。完成后再次发送 `/start`，点击“添加机器”。部署会切换这个 Bot 的消息接收方式，同 Bot 的旧版轮询脚本应先停止；不需要修改旧项目文件。

## 手动部署

```sh
cd cloud
npm ci
npx wrangler login
npx wrangler deploy --var PUBLIC_BASE_URL:https://codex-any-bot.你的子域.workers.dev
npx wrangler secret put BOT_TOKEN
npx wrangler secret put ALLOWED_USER_ID
npx wrangler secret put CHAT_ID
npx wrangler secret put WEBHOOK_SECRET
```

Webhook 注册使用 Telegram `setWebhook`，URL 为 `https://你的Worker地址/telegram/webhook`，`secret_token` 与 `WEBHOOK_SECRET` 相同。推荐使用向导完成注册，避免 Token 留在 shell 历史中。不要将 Token 放入 `wrangler.jsonc`，也不要提交 `.dev.vars`。

`PUBLIC_BASE_URL` 必须是实际 HTTPS 根地址，不带路径。`RELEASE_TAG` 指定已有 GitHub Release，如 `v0.1.0`；添加机器生成的命令使用这个固定版本。发布资产未生成前，安装命令会返回 404。

## 后续部署与回退

- 后续 `wrangler deploy` 必须仍传入真实 `--var PUBLIC_BASE_URL:...`，否则仓库中的占位地址会覆盖部署值。Secrets 无需重设。
- 发布新客户端后，将 `RELEASE_TAG` 更新为对应标签并部署。客户端“更新”使用 GitHub 最新正式 Release。
- Worker 可在 Cloudflare 控制台回滚到上一部署版本。SQLite 数据不随代码回滚删除；第一版只增加表和字段，不执行破坏性迁移。
- 客户端保留旧版本目录与 `previous.json`。Windows 可以把登录任务的程序改回记录的旧 executable；Mac 把 LaunchAgent 的 ProgramArguments 第一项改回旧 executable 后重新加载。先停止客户端，操作方法见各系统文档。
- 不自动升级 Cloudflare 付费方案。超免费额度或平台故障会导致连接不可用，客户端仍独立检查已知截止时间。

## 验证

访问 `/healthz` 应返回 `{"ok":true,"protocol":1}`。这只验证 Worker 可达，不验证 Bot 配置；实际用 `/start` 验证 Telegram 路由。

绑定后先配置 1 分钟保持时长和 1 分钟发送间隔，手动启动一个可测试的会话，观察首次成功、截止时间、自动停止。再使用第二台机器验证独立控制。真实模型执行会使用该机器的 Codex 账户用量。

## 云端持久化

一个 SQLite Durable Object 管理这个 Bot 的全部设备。保存设备凭据哈希、名称、参数、命令确认、定时任务和最新状态；不上传完整 Codex 会话历史或模型正文。命令和 Telegram 更新去重记录保留七天，配对码十分钟有效。建议小规模个人机器使用，规模增长后先查看 Cloudflare 配额。
