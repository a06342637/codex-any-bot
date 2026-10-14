"""Build a standalone client on the target operating system."""
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
windows = sys.platform == "win32"
arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
args = [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "--onedir", "--name", "codex-any-bot", "--paths", "agent"]
if windows:
    args.append("--noconsole")
args.append("agent/entrypoint.py")
subprocess.run(args, check=True)
folder = ROOT / "dist/codex-any-bot"
for name in (["uninstall.ps1"] if windows else ["uninstall.sh"]):
    shutil.copy2(ROOT / "install" / name, folder / name)
output = ROOT / "dist" / (f"codex-any-bot-windows-{arch}.zip" if windows else f"codex-any-bot-macos-{arch}.tar.gz")
if windows:
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in folder.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(folder))
else:
    with tarfile.open(output, "w:gz") as archive:
        for path in folder.iterdir():
            archive.add(path, arcname=path.name)
print(output)
