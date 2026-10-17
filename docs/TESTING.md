# 常见问题、检查与测试

[返回首页](../README.md) · [CF 部署](DEPLOY.md) · [Windows](WINDOWS.md) · [Mac](MACOS.md) · [TG 操作](TELEGRAM.md)

## 先判断问题发生在哪一步

| 现象 | 优先检查 |
| --- | --- |
| 部署命令找不到 Python、Node 或 Git | 只在部署电脑安装所需工具，安装后重开终端；版本要求见 CF 教程。 |
| Worker 上传成功，Bot 不回复 | 还要确认 Secrets 和 Webhook 配置成功；核对 Bot Token、用户 ID、聊天 ID。 |
| /healthz 正常但 /start 没反应 | 健康检查不验证机器人配置；检查用户/聊天是否被允许、Webhook 地址是否正确。 |
| Windows 粘贴安装命令后变量或路径报错 | 使用 CMD，避免在 PowerShell 提前展开生成命令中的变量。 |
| 安装下载 404 | CF 的 RELEASE_TAG 对应的正式 Release、各平台归档和安装脚本是否已发布。 |
| Token / ID 绑定失败 | 核对自己的 CF 地址、Bot Token 和数字 ID；云端必须先升级到 v0.2.0。旧版配对码仅作为兼容接口保留。 |
| 下载或 Webhook 注册报证书错误 | 检查系统时间和受信任证书；Mac 使用官方 Python 时按安装包说明完成证书安装，不关闭 HTTPS 校验。 |
| Already installed | 已有本机配置；更新用 TG 按钮，重新绑定先完整卸载。 |
| Codex 未登录 | 在同一系统用户下完成 CLI 登录；桌面端登录不能替代实际检查。 |
| 目录不存在 | 提供该电脑上存在的绝对路径，不使用文档示例用户名或相对路径。 |
| 安装目录归属不明或发现链接 | 安装器会拒绝接管未知文件，先备份并确认目录，勿绕过检查。 |
| 一直等待但没有“成功” | 只有明确完成事件算成功；可停止后检查本机 Codex 和账号状态。 |
| 会话被占用 | 在 Codex 桌面端释放该会话；不要强行删除写锁。 |
| 设备离线 | 检查电脑是否登录、休眠、断网，客户端日志和 CF 地址可达性。 |
| CF 更新后新命令指向占位地址 | 重新部署时必须传入真实 PUBLIC_BASE_URL，见 CF 教程。 |
| 更新按钮没有新版本 | 检查是否已经发布正式安装包；仅推送源码不够。 |
| 卸载报告未完成 | 检查被占用文件和云端联网情况。新版自动清理本机缓存及可确认的旧版暂存，云端失败会明确提示；手动下载的用户副本另行处理。 |

## 用户需要查看什么

先去 TG 点“更多设置 → 诊断”。需要本地检查时：

- [Windows：日志位置和状态命令](WINDOWS.md#5-打印日志路径查看日志和状态)
- [Mac：日志位置和状态命令](MACOS.md#5-打印日志位置查看日志和状态)

反馈问题时提供系统类型、失败步骤、时间和错误文字即可。不要公开发送 Bot Token、config.json 或完整设备凭据。

如果网络通过代理访问，要分别保证 GitHub 下载、CF HTTPS/WSS 和 Codex 服务可达。本程序不会自动修改系统代理；客户端连接可检查 HTTPS_PROXY、NO_PROXY 等环境设置。

## 简单验收：确认整条链路工作

自动测试不使用你的真实 Bot 或 Codex 账号。部署后可以这样检查：

1. 同一 Bot 添加一台 Windows 和一台 Mac，分别命名。
2. 每台选择一个适合测试的会话，设置不同的保持时长和发送间隔。
3. 先用较短保持时长检查：首次成功后计时，到期停止。
4. 运行中缩短保持时长到已超时，确认停止。
5. 在新建会话执行过程中停止，确认不会继续新增任务。
6. 关闭终端后，TG 仍可控制；重新登录系统后上线待命。
7. 验证切换机器、独立重命名、时间按钮即时更新，以及一条未来的定时任务。
8. 停止任务后测试更新，确认机器以新版本重新上线。
9. 不再使用的设备按系统教程卸载、检查本机目录，并移除 TG 绑定。

真实 Codex 执行可能使用账号用量。电脑无法在关机或休眠中执行检查，不要以休眠期间没响应作为正常在线控制的证明。

## 开发者检查

以下仅用于修改源码和开发验证。普通受控电脑无需运行这些命令。Python 3.11+、Node.js 22+ 为开发前提；进入的是本项目源码目录。

### Windows CMD

~~~bat
cd /d "%USERPROFILE%\Downloads\codex-any-bot"
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
.venv\Scripts\python.exe -m pytest -q
cd cloud
npm.cmd ci
npm.cmd run check
npm.cmd test
npx.cmd wrangler deploy --dry-run
~~~

### Mac 终端

~~~bash
cd "$HOME/Downloads/codex-any-bot"
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
cd cloud
npm ci
npm run check
npm test
npx wrangler deploy --dry-run
~~~

--dry-run 只检查打包，不将代码部署到你的 CF。正常部署步骤见 [CF 教程](DEPLOY.md)。

## 自动测试覆盖范围

客户端测试覆盖会话名称与 ID 一致性、删除确认和失败保留、独立分钟设置、首次成功起算、不重复续期、动态缩短、最早停止时间、发送间隔、失败立即重试、成功后间隔、断线宽限、命令去重和重启待命。子进程测试启动模拟 Codex 及其子进程，验证停止能清理进程树。

云端测试使用本地 Workers 测试环境中的 SQLite Durable Object 和 WebSocket，验证授权、配对码一次性消费、Telegram 更新去重、设备路由、参数隔离及定时行为。

回归测试覆盖网络发送阻塞时的本地到期、连续重连失败、旧连接迟到事件、重新绑定的状态隔离、TG 回执/通知失败，以及认证期间设备被移除。v0.2.0 还检查 Token 不落盘、交互输入、独立设备凭据和关联记录删除。

发布构建会在 Windows x64 / ARM64、Mac Intel / Apple Silicon 上执行真实安装器：用本地发行包模拟更新，检查打印路径、缓存清理和完整本机卸载，同时验证其他文件未被删除。该测试关闭实际登录启动注册，不接触真实 Bot 账号；实际系统登录和真实网络仍需使用者验收。

这些检查不替代真实账号、真实网络和实际登录启动环境的验收。开发依赖通过 cloud/package-lock.json 固定，使用 npm ci 安装。

目录选择器测试覆盖：本机目录读取、只列单层文件夹、分页、中文与空格、空目录、盘符入口、无权限及无效路径；云端检查机器路由、长路径短令牌、选择不启动任务、新建模式明确启动、旧按钮失效和切换机器后的迟到回执。
