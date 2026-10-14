# Windows 接入与后台运行

提供 Windows x64 和 ARM64 原生安装包。安装包包含 Python 运行环境；需要你预先安装并登录 Codex CLI。`codex login status` 应成功；Codex 桌面端的登录状态不一定等于 CLI 登录状态。

## 接入

1. 在 TG Bot 点“添加机器”。
2. 在要绑定的电脑上打开 CMD 或 PowerShell，进入希望默认使用的项目目录。
3. 粘贴 TG 给出的 Windows 命令。十分钟内有效，只能绑定一台机器。
4. 显示安装成功后关闭窗口，之后通过 TG 操作。

客户端下载固定 Release 的归档，校验 SHA-256 后安装到 `%LOCALAPPDATA%\codex-any-bot\versions`。配对只使用一次性码，本机不保存 Bot Token。

后台启动任务名为 `codex-any-bot`，在当前用户登录后运行，权限为当前用户。它不会让电脑自动登录、阻止休眠或在退出登录后维持任务。电脑需要能访问 Worker HTTPS/WSS、GitHub 下载地址，以及 Codex 所需服务。

## 本地配置与诊断

- 数据目录：`%LOCALAPPDATA%\codex-any-bot`
- `config.json`：设备凭据，勿分享。
- `state.sqlite`：参数、命令去重和最近状态。
- `agent.log`：轮换日志，不记录完整模型输出或 Bot Token。
- `current.json` / `previous.json`：当前和上一版本路径。

若 Codex 不在常见位置，可以配置用户环境变量 `ANYBOT_CODEX` 为原生可执行文件的绝对路径，再重启客户端。优先使用原生 `codex.exe`，不通过 shell 拼接执行命令。

在任务管理器或任务计划程序中可识别本项目的客户端。调试源码时：

```powershell
python -m pip install -e .
python -m anybot diagnose
python -m anybot status
```

TG“诊断”检查版本和 CLI 登录状态。启动任务时还会验证工作目录是否存在；会话写锁错误需要先在桌面端释放对应会话，不会强行删锁。

## 更新与卸载

TG 点“机器设置 → 更新客户端”：下载并校验最新正式版，停止旧执行，切换新版本后待命，不继续旧任务。失败时优先查看本地日志和 `previous.json`。

卸载并保留配置：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\codex-any-bot\uninstall.ps1"
```

彻底删除本项目数据，在命令末尾加 `-Purge`。卸载只处理本项目专属目录、进程和登录任务，不删除 Codex 的会话或配置。最后在 TG 移除该机器卡片。
