"""Read one level of folders on the controlled computer, without opening files."""
import os
import sys
from pathlib import Path


PAGE_SIZE = 8


def drive_roots() -> list[str]:
    if sys.platform != "win32":
        return ["/"]
    import ctypes
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [f"{chr(65 + index)}:\\" for index in range(26) if mask & (1 << index)]


def list_directories(cwd: str, path: str | None = None, offset: int = 0, location: str | None = None) -> dict:
    if type(offset) is not int or offset < 0:
        raise ValueError("目录页码无效，请重新打开")
    if location not in (None, "home", "roots"):
        raise ValueError("目录入口无效")
    if path is not None and (not isinstance(path, str) or not path or len(path) > 4096):
        raise ValueError("请输入有效的绝对目录路径")
    if location == "roots":
        entries = [{"name": root, "path": root} for root in drive_roots()]
        current, parent = None, None
    else:
        selected = str(Path.home()) if location == "home" else path
        if selected is None:
            configured = Path(cwd).expanduser() if cwd else None
            selected = str(configured) if configured and configured.is_absolute() and configured.is_dir() else str(Path.home())
        directory = Path(selected).expanduser()
        if not directory.is_absolute():
            raise ValueError("请输入绝对目录路径")
        try:
            directory = directory.resolve(strict=True)
            entries = []
            with os.scandir(directory) as children:
                for entry in children:
                    try:
                        if entry.is_dir():
                            entries.append({"name": entry.name, "path": str(directory / entry.name)})
                    except OSError:
                        continue
        except PermissionError:
            raise ValueError("没有权限读取此目录，请选择其他目录") from None
        except (OSError, RuntimeError):
            raise ValueError("目录不存在或暂时无法读取，请返回上级或选择其他目录") from None
        entries.sort(key=lambda item: (item["name"].casefold(), item["name"]))
        current = str(directory)
        parent = str(directory.parent) if directory.parent != directory else None
    # If folders disappeared between page requests, return the final available page.
    offset = min(offset, max(0, (len(entries) - 1) // PAGE_SIZE * PAGE_SIZE))
    end = min(offset + PAGE_SIZE, len(entries))
    return {"path": current, "parent": parent, "entries": entries[offset:end],
            "offset": offset, "previous_offset": max(0, offset - PAGE_SIZE) if offset else None,
            "next_offset": end if end < len(entries) else None, "total": len(entries),
            "location": "roots" if location == "roots" else None}
