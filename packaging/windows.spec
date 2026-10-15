# A console entrypoint for setup/maintenance, plus an invisible background entrypoint.
from pathlib import Path

root = Path(SPECPATH).parent
a = Analysis([str(root / 'agent/entrypoint.py')], pathex=[str(root / 'agent')],
             binaries=[], datas=[], hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
background = EXE(pyz, a.scripts, [], exclude_binaries=True, name='codex-any-bot',
                 console=False, debug=False, strip=False, upx=False)
console = EXE(pyz, a.scripts, [], exclude_binaries=True, name='codex-any-bot-console',
              console=True, debug=False, strip=False, upx=False)
coll = COLLECT(background, console, a.binaries, a.datas, name='codex-any-bot', strip=False, upx=False)
