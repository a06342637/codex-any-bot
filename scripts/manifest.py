import argparse
import hashlib
import json
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("directory", type=Path)
parser.add_argument("--version", required=True)
args = parser.parse_args()
if not re.fullmatch(r"v\d+\.\d+\.\d+", args.version):
    raise SystemExit("Invalid version")
files = {}
for path in sorted(args.directory.iterdir()):
    if path.is_file() and path.name != "manifest.json":
        files[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}
manifest = {"version": args.version, "protocol": 1, "files": files,
            "checksums": {name.replace(".", "_"): data["sha256"] for name, data in files.items()}}
(args.directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
