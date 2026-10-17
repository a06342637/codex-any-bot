# 协议与任务规则

## 通信

Telegram 只配置一个 Webhook。Worker 验证 Webhook 密钥，随后校验操作者用户 ID 和聊天 ID。SQLite Durable Object 统一分发。客户端仅主动建立 WSS 连接，无监听端口。

- `POST /v1/enroll`：交互输入的 Bot Token、允许用户 ID、机器名称、系统和默认目录；验证后返回设备 ID 与独立 Token。继续兼容旧版一次性码，不在本地保存输入的 Bot Token。
- `POST /v1/unenroll`：用设备凭据移除自身绑定及关联命令、定时、选择缓存；不能删除其他设备。
- `GET /v1/connect`：WebSocket Upgrade，`Authorization: Bearer <设备Token>` 和 `X-Device-ID` 放在请求头，不放 URL。
- `POST /telegram/webhook`：仅 Telegram Webhook 入口。
- `GET /healthz`：无敏感信息的存活检查。

协议版本为 `1`。命令包含 `id / device_id / version / action / payload / expires_at`。动作包括 `start`、`stop`、`settings`、`deadline`、`sessions`、`diagnose`、`restart`、`update`、`revoke`。设备回传 `hello`、`status`、`ack`；服务端先用 `reconcile` 同步状态。

立即命令六十秒过期。停止意图和参数会持久化，离线后重连仍可同步。启动不在离线时排队。命令 ID 持久化认领后才执行；崩溃后已认领指令不重放，遇到不确定结果应查看状态再手动发新命令，避免重复新建会话。

## 会话与时钟

通过 `codex app-server` 的初始化握手及 `thread/list` 读取本机会话；不直接修改 Codex 数据文件。执行采用 `codex exec [resume] --json --skip-git-repo-check`，提示词从 stdin 输入，工作目录通过进程参数指定，不经过 shell 插值。

仅 `turn.completed` 加正常退出算成功；首次成功设置 `first_success_at`。保持截止时间是 `first_success_at + hold_minutes × 60`，再与指定停止时间取最早值。后续轮次、失败和重连不会续期。发送间隔只从成功的轮次结束计算。可重试的失败或会话占用在上一轮结束后立即重试；认证、权限、归档和无法确定新会话等情况仍暂停。

同机仅一个执行进程树。停止或到期设置取消信号，Windows Job Object / macOS 进程组清理所属子进程。客户端每约 0.2 秒检查取消和截止时间，模型响应没有固定时长保证。系统时钟应保持准确；电脑睡眠期间无法运行检查，醒来后先检查截止时间。

客户端断线超过六十秒不启动新轮次，但继续监控当前任务的截止时间；重连先同步停止意图和参数。客户端进程重启后只上线待命。更新或重启不会自动恢复旧任务。

## 持久化与隔离

设备名称不是身份键，修改名称或 IP 不会创建新设备。云端只存设备 Token 的 SHA-256；客户端本地配置保存自己的 Token。按机器保存时长、间隔、提示词、目录和选定会话。记录最新状态及必要错误分类，不上传完整模型输出。

Windows 包同时提供交互命令行入口和无窗口后台入口。安装/更新暂存位于本机程序目录的 cache，结束时清理；卸载器核对 ownership.json 与绝对路径后清理本机。旧版临时文件只清理可确认归属的项目，不盲删系统临时目录。

新项目使用独立目录、启动项和仓库。参考项目 `C:\Users\adminuser\Downloads\an` 只读，项目中没有对它的运行时依赖。

会话元数据包含 thread_id 和 thread_name。任务保留自己的会话快照，面板另外显示当前选择，迟到的旧任务事件不能覆盖新选择。删除会话使用 Codex thread/delete；确认令牌单次有效，删除期间禁止启动和切换，只有匹配的成功回执才清理选择。

目录浏览通过 directories 指令在目标客户端读取单层文件夹，每页 8 项，不读取文件内容。浏览请求和选择按钮绑定当前机器与浏览标识；切页或切换机器后旧结果不再更新面板。Telegram 回调只保存短令牌，完整路径保存在带过期时间的云端记录中。普通目录选择只保存 cwd，新建模式明确选择后才发送 start。
