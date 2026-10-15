"""Run real platform installers against local release fixtures, then verify full local uninstall.

All state stays in .local; autostart registration and launch are disabled for this test.
No actual Telegram or Cloudflare account is used. Unreachable cloud cleanup is reported.
"""
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
from anybot import __version__


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run(args, env, expected_success=True):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, **options)
    print(result.stdout)
    if (result.returncode == 0) != expected_success:
        print(result.stderr)
        raise RuntimeError(f"Installer command failed ({result.returncode})")
    return result.stdout


def main():
    (ROOT / ".local").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="installer-test-", dir=ROOT / ".local") as directory:
        base = Path(directory).resolve()
        root = base / "codex-any-bot"
        root.mkdir()
        legacy = base / "legacy-temp"
        legacy.mkdir()
        owned = legacy / ("codex-any-bot-" + "a" * 32)
        owned.mkdir()
        (owned / "codex-any-bot-windows-x64.zip").write_bytes(b"identified old cache")
        sentinel = legacy / "unrelated.txt"
        sentinel.write_text("must remain", encoding="utf-8")
        (root / "config.json").write_text(json.dumps({"device_id": "test", "token": "fake-device-token",
            "server": "https://127.0.0.1:9", "cwd": str(base)}), encoding="utf-8")
        arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
        name = f"codex-any-bot-windows-{arch}.zip" if sys.platform == "win32" else f"codex-any-bot-macos-{arch}.tar.gz"
        archive = ROOT / "dist" / name
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest = base / "manifest.json"
        manifest.write_text(json.dumps({"version": "v" + __version__, "files": {name: {"sha256": digest}},
            "checksums": {name.replace(".", "_"): digest}}), encoding="utf-8")
        env = {**os.environ, "ANYBOT_DATA_DIR": str(root), "ANYBOT_LEGACY_TEMP_DIR": str(legacy),
               "ANYBOT_FIXTURE_MANIFEST": str(manifest), "ANYBOT_FIXTURE_ARCHIVE": str(archive)}
        failed_parent = base / "failed"
        failed_parent.mkdir()
        failed_root = failed_parent / "codex-any-bot"
        failed_env = {**env, "ANYBOT_DATA_DIR": str(failed_root), "ANYBOT_FIXTURE_FAIL": "1"}
        if sys.platform == "win32":
            driver = base / "install-test.ps1"
            driver.write_text("""$ErrorActionPreference = 'Stop'
function Invoke-RestMethod { param($Uri) if ($env:ANYBOT_FIXTURE_FAIL) { throw 'Simulated download failure' }; Get-Content -LiteralPath $env:ANYBOT_FIXTURE_MANIFEST -Raw | ConvertFrom-Json }
function Invoke-WebRequest { param($Uri, $OutFile, [switch]$UseBasicParsing) Copy-Item -LiteralPath $env:ANYBOT_FIXTURE_ARCHIVE -Destination $OutFile }
""" + "& " + ps_quote(ROOT / "install/install.ps1") + " -Update -NoAutoStart -NoLaunch\n", encoding="utf-8")
            command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)]
            run(command, failed_env, expected_success=False)
            assert not failed_root.exists(), "Failed download left a fresh installation directory"
            output = run(command, env)
        else:
            bin_dir = base / "bin"
            bin_dir.mkdir()
            curl = bin_dir / "curl"
            curl.write_text("#!" + sys.executable + "\n" + """import os, shutil, sys
if os.environ.get('ANYBOT_FIXTURE_FAIL'): raise SystemExit(22)
source = os.environ['ANYBOT_FIXTURE_MANIFEST'] if any(v.endswith('manifest.json') for v in sys.argv) else os.environ['ANYBOT_FIXTURE_ARCHIVE']
destination = sys.argv[sys.argv.index('-o') + 1]
shutil.copyfile(source, destination)
""", encoding="utf-8")
            curl.chmod(0o755)
            env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
            failed_env["PATH"] = env["PATH"]
            command = ["bash", str(ROOT / "install/install.sh"), "--update", "--no-autostart", "--no-launch"]
            run(command, failed_env, expected_success=False)
            assert not failed_root.exists(), "Failed download left a fresh installation directory"
            output = run(command, env)
        assert "Log:" in output and "Uninstall:" in output
        assert list((root / "cache").iterdir()) == [], "Installer left staging files"
        pointer = json.loads((root / "current.json").read_text(encoding="utf-8-sig"))
        assert pointer["version"] == "v" + __version__
        assert Path(pointer["executable"]).is_file()
        if sys.platform == "win32":
            assert Path(pointer["console_executable"]).is_file()
            assert __version__ in run([pointer["console_executable"], "--version"], env)
            output = run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(root / "uninstall.ps1"), "-Purge"], env)
        else:
            assert __version__ in run([pointer["executable"], "--version"], env)
            output = run(["bash", str(root / "uninstall.sh"), "--purge"], env)
        assert not root.exists(), "Uninstaller left application files"
        assert not owned.exists(), "Identified old cache remains"
        assert sentinel.read_text() == "must remain", "Uninstaller touched unrelated data"
        assert "Cloud binding could not be removed" in output or sys.platform == "darwin"
        print("PASS: real install/update, printed paths, staging cleanup, full local uninstall and unrelated-file protection.")


if __name__ == "__main__":
    main()
