# macOS 接入与后台运行

提供 Apple Silicon 和 Intel 安装包，包含 Python 运行环境。需要本机可用、已登录的 Codex CLI：`codex login status` 应成功。

## 接入

在 TG 点击“添加机器”，在 Mac 终端进入希望使用的工作目录，然后粘贴 Mac 命令。安装器按 CPU 类型选择固定版本归档并校验 SHA-256。绑定成功后可以关闭终端。

客户端装在 `~/Library/Application Support/codex-any-bot/versions`，登录启动配置位于 `~/Library/LaunchAgents/com.codex-any-bot.agent.plist`。这是当前用户的 LaunchAgent，用户登录后启动；休眠、关机或退出登录时不保证运行。

## 设置与诊断

本项目数据均保存在 `~/Library/Application Support/codex-any-bot`，不修改 `~/.codex-squeeze.json` 或原项目文件。`config.json` 包含设备凭据，勿分享。

优先检测 PATH、`~/.local/bin/codex`、Homebrew 的常用目录和 `/Applications/Codex.app/Contents/Resources/codex`。找不到时可安装 Codex CLI；若自定义路径，给 LaunchAgent 配置 `ANYBOT_CODEX` 环境变量后重新加载。

源码诊断：

```sh
python3 -m pip install -e .
python3 -m anybot diagnose
python3 -m anybot status
```

TG“诊断”可查看版本和登录状态。`agent.log` 是客户端日志，`launch-error.log` 是 LaunchAgent 启动错误。客户端遵守本机 Codex 的配置，不自动绕过权限审批。

## 更新与卸载

TG“更新客户端”会校验最新正式版安装器和归档，停止旧任务，切换新版本后待命。旧版本与 `previous.json` 保留，可用于回退。

卸载并保留配置：

```sh
bash "$HOME/Library/Application Support/codex-any-bot/uninstall.sh"
```

彻底删除本项目数据：

```sh
bash "$HOME/Library/Application Support/codex-any-bot/uninstall.sh" --purge
```

卸载只处理本项目自己的 LaunchAgent、目录和客户端，不删除 Codex 会话。最后在 TG 移除机器。
