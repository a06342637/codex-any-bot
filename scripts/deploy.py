"""Interactive deployment. Secrets go to Wrangler stdin, never into tracked files."""
import getpass
import json
import re
import secrets
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "cloud"


def main():
    npx = shutil.which("npx.cmd" if sys.platform == "win32" else "npx")
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not npm or not npx:
        raise SystemExit("Install Node.js 22+ first.")
    print("部署到你自己的 Cloudflare 账号；需要 Workers 免费方案、一个 Telegram Bot 和你的 Telegram ID。")
    url = input("Worker HTTPS 地址（如 https://codex-any-bot.xxx.workers.dev）：").strip().rstrip("/")
    if not re.fullmatch(r"https://[a-zA-Z0-9.-]+", url):
        raise SystemExit("Invalid HTTPS origin")
    token = getpass.getpass("Bot Token（不显示、不写入文件）：").strip()
    user = input("允许操作的 Telegram 用户 ID：").strip()
    chat = input("聊天 ID（私聊一般等于用户 ID）：").strip() or user
    if not re.fullmatch(r"\d+", user) or not re.fullmatch(r"-?\d+", chat) or not token:
        raise SystemExit("Invalid IDs or token")
    secret = secrets.token_hex(32)
    subprocess.run([npm, "ci"], cwd=CLOUD, check=True)
    subprocess.run([npx, "wrangler", "login"], cwd=CLOUD, check=True)
    subprocess.run([npx, "wrangler", "deploy", "--var", "PUBLIC_BASE_URL:" + url], cwd=CLOUD, check=True)
    payload = json.dumps({"BOT_TOKEN": token, "ALLOWED_USER_ID": user, "CHAT_ID": chat, "WEBHOOK_SECRET": secret})
    subprocess.run([npx, "wrangler", "secret", "bulk"], cwd=CLOUD, input=payload, text=True, check=True)
    body = json.dumps({"url": url + "/telegram/webhook", "secret_token": secret,
                       "allowed_updates": ["message", "callback_query"], "drop_pending_updates": False}).encode()
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/setWebhook", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        if not result.get("ok"):
            raise RuntimeError("setWebhook failed")
    except Exception:
        raise SystemExit("Webhook 设置失败。Token 未输出；请检查网络和 Bot Token 后重新运行。")
    # Save only the non-secret public address so subsequent deployments retain it.
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    (local / "deployment.json").write_text(json.dumps({"public_base_url": url}), encoding="utf-8")
    print("部署成功。向 Bot 发送 /start，然后点击 添加机器。")
    print("后续部署请继续传入 --var PUBLIC_BASE_URL:" + url)


if __name__ == "__main__":
    main()
